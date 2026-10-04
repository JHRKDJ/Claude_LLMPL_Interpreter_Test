"""Channel data structures (V3 5.13, 7.11; SPEC-018; AMB-006).

Pure data + bookkeeping; blocking behaviour lives in interp/chan.py.

- `Channel` (the controller) owns the buffer, the FIFO waiter queues, the commit
  sequence counter, the endpoint registry and a bounded diagnostic event ring that
  program code cannot read.
- `SendPort` / `ReceivePort` are frozen, sendable capabilities. Each task that
  holds a port (created it, or received it across a task boundary) is a holder;
  holdings end at task termination or `port.release()`. An endpoint side is *lost*
  once at least one port of that side existed and none has a holder left.
"""
from __future__ import annotations

import itertools
from collections import deque
from typing import Optional

_chan_ids = itertools.count(1)
_port_ids = itertools.count(1)


class Waiter:
    """A task waiting to send or receive on one channel (possibly inside a select)."""

    __slots__ = ("task", "kind", "port", "value", "select", "branch", "committed", "result", "seq")

    def __init__(self, task, kind: str, port, value=None, select=None, branch: int = -1):
        self.task = task
        self.kind = kind  # send | recv
        self.port = port
        self.value = value  # classified (not yet copied) message for senders
        self.select = select  # SelectState or None
        self.branch = branch
        self.committed = False
        self.result = None
        self.seq = None

    def alive(self) -> bool:
        if self.committed:
            return False
        if self.select is not None and self.select.done:
            return False
        return True


class Channel:
    lang_kind = "Channel"
    lang_sendable = "reject"
    lang_reject_reason = "channel controller"

    def __init__(self, capacity: Optional[int], elem_type, created_at, type_desc: str, created_by: str):
        self.id = next(_chan_ids)
        self.capacity = capacity  # 0 rendezvous, n buffered, None unbounded
        self.elem_type = elem_type
        self.created_at = created_at
        self.type_desc = type_desc
        self.created_by = created_by
        self.buffer: deque = deque()  # (seq, value, sender_path)
        self.closed = False
        self.send_waiters: deque = deque()
        self.recv_waiters: deque = deque()
        self.seq = 0
        self.send_ports: list = []
        self.recv_ports: list = []
        self.events: deque = deque(maxlen=32)
        self.peak = 0
        self.growth_warned = False
        self.watchers: list = []  # select states / tasks to re-check on state change

    # ------------------------------------------------------------ endpoints
    def senders_lost(self) -> bool:
        return bool(self.send_ports) and not any(p.holders for p in self.send_ports)

    def receivers_lost(self) -> bool:
        return bool(self.recv_ports) and not any(p.holders for p in self.recv_ports)

    def no_more_sends(self) -> bool:
        return self.closed or self.senders_lost()

    def cannot_send(self) -> Optional[str]:
        if self.closed:
            return "ControllerClosed"
        if self.receivers_lost():
            return "NoReceivers"
        return None

    def has_space(self) -> bool:
        return self.capacity is None or len(self.buffer) < self.capacity

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def record(self, op: str, task_path: str, port_id=None, seq=None, note: str = "") -> None:
        ev = {"op": op, "task": task_path}
        if port_id is not None:
            ev["port"] = port_id
        if seq is not None:
            ev["seq"] = seq
        if note:
            ev["note"] = note
        self.events.append(ev)

    def first_alive(self, q: deque) -> Optional[Waiter]:
        while q:
            w = q[0]
            if w.alive():
                return w
            q.popleft()
        return None

    def lang_display(self) -> str:
        cap = "rendezvous" if self.capacity == 0 else ("unbounded" if self.capacity is None else f"buffered({self.capacity})")
        return f"<Channel#{self.id} {cap}{' closed' if self.closed else ''}>"


class _Port:
    lang_sendable = "share"
    is_port = True

    __slots__ = ("id", "channel", "holders")

    def __init__(self, channel: Channel):
        self.id = next(_port_ids)
        self.channel = channel
        self.holders: set = set()

    def lang_frozen(self) -> bool:
        return True

    def lang_eq(self, other) -> bool:
        return self is other

    def lang_hash_key(self):
        return ("port", self.id)


class SendPort(_Port):
    lang_kind = "SendPort"
    __slots__ = ()

    def lang_display(self) -> str:
        return f"<SendPort#{self.id} of Channel#{self.channel.id}>"


class ReceivePort(_Port):
    lang_kind = "ReceivePort"
    __slots__ = ()

    def lang_display(self) -> str:
        return f"<ReceivePort#{self.id} of Channel#{self.channel.id}>"


class Broadcast:
    """Broadcast abstraction (V3 5.13.3): every subscriber receives every message
    published after it subscribed; messages must be transitively frozen."""

    lang_kind = "Broadcast"
    lang_sendable = "reject"
    lang_reject_reason = "channel controller"

    def __init__(self, capacity: int, elem_type, created_at, type_desc: str):
        self.id = next(_chan_ids)
        self.capacity = capacity
        self.elem_type = elem_type
        self.created_at = created_at
        self.type_desc = type_desc
        self.subscribers: list[Channel] = []
        self.closed = False
        self.waiting_publishers: deque = deque()
        self.publishers: list = []
        self.events: deque = deque(maxlen=32)
        self.seq = 0

    def lang_display(self) -> str:
        return f"<Broadcast#{self.id}>"


class PublishPort(_Port):
    lang_kind = "PublishPort"
    __slots__ = ()

    def lang_display(self) -> str:
        return f"<PublishPort#{self.id}>"
