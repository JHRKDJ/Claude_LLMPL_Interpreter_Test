"""Channel operations in the evaluator (V3 5.13, 7.11, 8.12; SPEC-018; AMB-006).

Commit protocol for a send (blocking or select branch):
  1. classify the message (reject non-sendables) — no copy yet;
  2. reserve: a waiting receiver (FIFO) or buffer space;
  3. copy the mutable graph once, privately;
  4. commit atomically with the next sequence number.
Cancellation before commit sends/consumes nothing; once committed, the operation
completes and any pending cancellation is delivered at the next point.
"""
from __future__ import annotations

from ...diagnostics import Diagnostic, Label, code
from ..builtins.registry import method, static
from ..channels import Broadcast, Channel, PublishPort, ReceivePort, SendPort, Waiter
from ..core_types import CHANNEL_CLOSED, TRY_RECEIVE, TRY_SEND, make_error
from ..equality import type_name
from ..frozen import is_frozen
from ..isolation import PORTS_EXIST, Transfer
from ..signals import Fault, Thrown
from ..tasks import Wait, wake
from ..values import UNIT, TypeValue, VariantValue

UNBOUNDED_ADVISORY = 10000


class ChannelMixin:
    def init_channels(self) -> None:
        pass

    # ------------------------------------------------------------------ holders
    def adopt_ports(self, task, ports) -> None:
        for p in ports:
            p.holders.add(task)
            task.held_ports.add(p)

    def release_task_ports(self, task) -> None:
        for p in list(task.held_ports):
            self.release_port(p, task)

    def hold_in_transit(self, ch, ports) -> None:
        """Ports inside a buffered message are held by the carrying channel until a
        receiver takes the message (BUG-0034)."""
        for p in ports:
            p.holders.add(ch)

    def end_transit(self, ch, ports) -> None:
        for p in ports:
            p.holders.discard(ch)

    def drop_undeliverable(self, ch) -> None:
        """The carrying channel can no longer deliver its buffer: release in-transit holds."""
        for _seq, _v, _path, ports in list(ch.buffer):
            for p in ports:
                if ch in p.holders:
                    p.holders.discard(ch)
                    if not p.holders:
                        self._endpoint_lost(p, None)

    def release_port(self, port, task) -> None:
        port.holders.discard(task)
        task.held_ports.discard(port)
        if not port.holders:
            self._endpoint_lost(port, task)

    def _endpoint_lost(self, port, task) -> None:
        ch = port.channel
        if isinstance(ch, Channel):
            ch.record("endpoint-lost", task.path if task is not None else "<in transit>", port.id,
                      note=type(port).__name__)
            if type(port).__name__ == "ReceivePort" and ch.receivers_lost() and ch.buffer:
                self.drop_undeliverable(ch)
            self.recheck_waiters(ch)
        elif isinstance(ch, Broadcast):
            self.recheck_broadcast(ch)

    def recheck_waiters(self, ch: Channel) -> None:
        for q in (ch.send_waiters, ch.recv_waiters):
            for w in list(q):
                if w.alive() and w.task.wait is not None:
                    if w.select is not None:
                        w.select.recheck()
                    else:
                        wake(w.task, "recheck")
        for st in list(ch.watchers):
            st.recheck()

    def check_holder(self, port, task, span) -> None:
        if task not in port.holders:
            raise Fault("A.CHANNEL.PORT_RELEASED",
                        f"{type(port).__name__}#{port.id} is not held by task {task.path} (released or never received)",
                        help="ports are held by the task that created them or received them as task arguments/"
                             "captures/messages; `release()` ends a task's holding")

    # ------------------------------------------------------------------ creation
    def new_channel(self, capacity, tv, span) -> Channel:
        elem = None
        desc = "Dyn"
        if tv is not None and tv.args:
            elem = self.type_value_to_ty(tv.args[0]) if isinstance(tv.args[0], TypeValue) else None
            desc = str(elem) if elem is not None else "Dyn"
        t = self.sched.current
        ch = Channel(capacity, elem, span, desc, t.path if t else "?")
        ch.record("create", t.path if t else "?", note=f"capacity {capacity}")
        return ch

    def make_port(self, ch, cls):
        p = cls(ch)
        PORTS_EXIST[0] = True
        if isinstance(ch, Channel):
            (ch.send_ports if cls is SendPort else ch.recv_ports).append(p)
        task = self.sched.current
        self.adopt_ports(task, [p])
        return p

    # ------------------------------------------------------------------ errors
    def closed_error(self, ch, op: str, port, reason: str, span) -> Thrown:
        err = make_error(CHANNEL_CLOSED, channelId=ch.id, operation=op, reason=reason,
                         portId=port.id if port is not None else 0)
        prov = self.new_provenance(span)
        prov.context.append(("channelCreatedAt", ch.created_at.describe() if ch.created_at else "?"))
        prov.context.append(("messageType", ch.type_desc))
        ch.record(f"{op}-failed", self.sched.current.path, port.id if port else None, note=reason)
        return Thrown(err, prov)

    def check_message(self, ch, value, span):
        if getattr(ch, "elem_type", None) is not None and not self.registry.check(ch.elem_type, value):
            raise Fault("A.TYPE.DYNAMIC_MISMATCH",
                        f"Channel#{ch.id} carries {ch.type_desc}, but a {type_name(value)} was sent",
                        expected=ch.type_desc, found=type_name(value))
        Transfer("channel message", copy=False).value(value, "message")

    def copy_message(self, value):
        tr = Transfer("channel message")
        v = tr.root(value, "message")
        return v, tr

    # ------------------------------------------------------------------ commit helpers
    def commit_to_receiver(self, ch: Channel, w: Waiter, value, sender, port):
        v, tr = self.copy_message(value)
        seq = ch.next_seq()
        ch.record("send", sender.path, port.id if port else None, seq, note=f"delivered to {w.task.path}")
        self.adopt_ports(w.task, tr.ports)
        w.committed = True
        w.result = v
        w.seq = seq
        try:
            ch.recv_waiters.remove(w)
        except ValueError:
            pass
        if w.select is not None:
            w.select.claim(w.branch, v, seq)
        else:
            wake(w.task, "committed")

    def commit_to_buffer(self, ch: Channel, value, sender, port):
        v, tr = self.copy_message(value)
        seq = ch.next_seq()
        ch.buffer.append((seq, v, sender.path, tr.ports))
        self.hold_in_transit(ch, tr.ports)
        ch.record("send", sender.path, port.id if port else None, seq, note="buffered")
        n = len(ch.buffer)
        if n > ch.peak:
            ch.peak = n
            if ch.capacity is None and n >= UNBOUNDED_ADVISORY and not ch.growth_warned:
                ch.growth_warned = True
                d = Diagnostic(code("W.CHANNEL.UNBOUNDED_GROWTH"),
                               f"unbounded Channel#{ch.id} holds {n} queued messages and is growing",
                               severity="warning", primary=Label(ch.created_at, "channel created here"))
                d.help.append("use a buffered channel for backpressure, or consume faster")
                self.runtime_warnings.append(d)
        for st in list(ch.watchers):
            st.recheck()

    def take_from_sender(self, ch: Channel, sw: Waiter, receiver):
        v, tr = self.copy_message(sw.value)
        seq = ch.next_seq()
        ch.record("send", sw.task.path, sw.port.id, seq, note=f"rendezvous with {receiver.path}")
        sw.committed = True
        sw.seq = seq
        try:
            ch.send_waiters.remove(sw)
        except ValueError:
            pass
        if sw.select is not None:
            sw.select.claim(sw.branch, None, seq)
        else:
            wake(sw.task, "committed")
        return v, seq, tr.ports

    def refill_from_waiting_sender(self, ch: Channel):
        if ch.capacity == 0:
            return
        sw = ch.first_alive(ch.send_waiters)
        if sw is not None and ch.has_space():
            v, tr = self.copy_message(sw.value)
            seq = ch.next_seq()
            ch.buffer.append((seq, v, sw.task.path, tr.ports))
            self.hold_in_transit(ch, tr.ports)
            ch.record("send", sw.task.path, sw.port.id, seq, note="buffered after wait")
            sw.committed = True
            sw.seq = seq
            ch.send_waiters.popleft()
            if sw.select is not None:
                sw.select.claim(sw.branch, None, seq)
            else:
                wake(sw.task, "committed")

    # ------------------------------------------------------------------ send
    def channel_send(self, port, value, span):
        task = self.sched.current
        ch = port.channel
        self.check_holder(port, task, span)
        self.check_message(ch, value, span)
        while True:
            reason = ch.cannot_send()
            if reason:
                raise self.closed_error(ch, "send", port, reason, span)
            w = ch.first_alive(ch.recv_waiters)
            if w is not None:
                self.commit_to_receiver(ch, w, value, task, port)
                return UNIT
            if ch.has_space() and ch.capacity != 0:
                self.commit_to_buffer(ch, value, task, port)
                return UNIT
            self.check_cancel(span)
            sw = Waiter(task, "send", port, value)
            ch.send_waiters.append(sw)

            def unregister(sw=sw, ch=ch):
                try:
                    ch.send_waiters.remove(sw)
                except ValueError:
                    pass
            self.block(Wait("channel", f"sending on Channel#{ch.id} ({self.cap_desc(ch)})", True, unregister, ch,
                            span))
            if sw.committed:
                return UNIT
            unregister()

    def cap_desc(self, ch) -> str:
        return "rendezvous" if ch.capacity == 0 else ("unbounded" if ch.capacity is None else f"buffered {ch.capacity}")

    def channel_try_send(self, port, value, span):
        task = self.sched.current
        ch = port.channel
        self.check_holder(port, task, span)
        self.check_message(ch, value, span)
        reason = ch.cannot_send()
        if reason:
            ch.record("trySend-closed", task.path, port.id, note=reason)
            return VariantValue(TRY_SEND.cases["Closed"], (reason,))
        w = ch.first_alive(ch.recv_waiters)
        if w is not None:
            self.commit_to_receiver(ch, w, value, task, port)
            return TRY_SEND.nullary("Sent")
        if ch.has_space() and ch.capacity != 0:
            self.commit_to_buffer(ch, value, task, port)
            return TRY_SEND.nullary("Sent")
        return TRY_SEND.nullary("WouldBlock")

    # ------------------------------------------------------------------ receive
    def take_buffered(self, ch: Channel, task, port):
        seq, v, spath, ports = ch.buffer.popleft()
        ch.record("receive", task.path, port.id if port else None, seq)
        self.adopt_ports(task, ports)
        self.end_transit(ch, ports)
        self.refill_from_waiting_sender(ch)
        bc = getattr(ch, "broadcast", None)
        if bc is not None:
            self.recheck_broadcast(bc)
        return v

    def channel_receive(self, port, span, env=None, closed_ok: bool = False):
        task = self.sched.current
        ch = port.channel
        self.check_holder(port, task, span)
        while True:
            if ch.buffer:
                return True, self.take_buffered(ch, task, port)
            sw = ch.first_alive(ch.send_waiters)
            if sw is not None:
                v, seq, ports = self.take_from_sender(ch, sw, task)
                ch.record("receive", task.path, port.id, seq)
                self.adopt_ports(task, ports)
                return True, v
            if ch.no_more_sends():
                if closed_ok:
                    return False, None
                raise self.closed_error(ch, "receive", port, "ControllerClosed" if ch.closed else "NoSenders", span)
            self.check_cancel(span)
            rw = Waiter(task, "recv", port)
            ch.recv_waiters.append(rw)

            def unregister(rw=rw, ch=ch):
                try:
                    ch.recv_waiters.remove(rw)
                except ValueError:
                    pass
            self.block(Wait("channel", f"receiving on Channel#{ch.id} ({self.cap_desc(ch)})", True, unregister, ch,
                            span))
            if rw.committed:
                ch.record("receive", task.path, port.id, rw.seq)
                return True, rw.result
            unregister()

    def channel_try_receive(self, port, span):
        task = self.sched.current
        ch = port.channel
        self.check_holder(port, task, span)
        if ch.buffer:
            return VariantValue(TRY_RECEIVE.cases["Message"], (self.take_buffered(ch, task, port),))
        sw = ch.first_alive(ch.send_waiters)
        if sw is not None:
            v, seq, ports = self.take_from_sender(ch, sw, task)
            self.adopt_ports(task, ports)
            return VariantValue(TRY_RECEIVE.cases["Message"], (v,))
        if ch.no_more_sends():
            return VariantValue(TRY_RECEIVE.cases["Closed"], ("ControllerClosed" if ch.closed else "NoSenders",))
        return TRY_RECEIVE.nullary("WouldBlock")

    def channel_close(self, ch: Channel, span) -> None:
        if ch.closed:
            return
        ch.closed = True
        ch.record("close", self.sched.current.path)
        self.recheck_waiters(ch)

    # ------------------------------------------------------------------ broadcast
    def broadcast_subscribe(self, bc: Broadcast, span):
        if bc.closed:
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", "cannot subscribe to a closed broadcast")
        sub = Channel(bc.capacity, bc.elem_type, span, bc.type_desc, self.sched.current.path)
        sub.broadcast = bc
        bc.subscribers.append(sub)
        return self.make_port(sub, ReceivePort)

    def live_subscribers(self, bc: Broadcast):
        return [s for s in bc.subscribers if not s.receivers_lost() and not s.closed]

    def broadcast_send(self, port: PublishPort, value, span):
        task = self.sched.current
        bc = port.channel
        self.check_holder(port, task, span)
        if not is_frozen(value):
            raise Fault("A.CHANNEL.BROADCAST_MUTABLE",
                        f"broadcast messages must be transitively frozen; found mutable {type_name(value)}",
                        help="freeze the message (`.freeze()`) or send a frozen projection")
        if bc.elem_type is not None and not self.registry.check(bc.elem_type, value):
            raise Fault("A.TYPE.DYNAMIC_MISMATCH", f"Broadcast#{bc.id} carries {bc.type_desc}, found {type_name(value)}")
        Transfer("broadcast message", copy=False).value(value, "message")
        while True:
            if bc.closed:
                raise self.closed_error(bc, "publish", port, "ControllerClosed", span)
            subs = self.live_subscribers(bc)
            if all(s.has_space() or s.first_alive(s.recv_waiters) is not None for s in subs):
                bc.seq += 1
                bc.events.append({"op": "publish", "task": task.path, "seq": bc.seq, "subscribers": len(subs)})
                for s in subs:
                    w = s.first_alive(s.recv_waiters)
                    if w is not None:
                        self.commit_to_receiver(s, w, value, task, None)
                    else:
                        s.buffer.append((s.next_seq(), value, task.path, []))
                        for st in list(s.watchers):
                            st.recheck()
                return UNIT
            self.check_cancel(span)
            entry = [task]
            bc.waiting_publishers.append(entry)

            def unregister(entry=entry, bc=bc):
                try:
                    bc.waiting_publishers.remove(entry)
                except ValueError:
                    pass
            self.block(Wait("channel", f"publishing on Broadcast#{bc.id} (a subscriber is full)", True, unregister,
                            None, span))
            unregister()

    def recheck_broadcast(self, bc: Broadcast) -> None:
        for entry in list(bc.waiting_publishers):
            t = entry[0]
            if t.wait is not None:
                wake(t, "recheck")

    def broadcast_close(self, bc: Broadcast) -> None:
        if bc.closed:
            return
        bc.closed = True
        for s in bc.subscribers:
            self.channel_close(s, None)
        self.recheck_broadcast(bc)


# ====================================================================== builtins
def _cap(v):
    if type(v) is not int or v < 1:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "buffered capacity must be a positive Int",
                    help="use `Channel[T].rendezvous()` for capacity 0, or `.unbounded()`")
    return v


@static("Channel", "rendezvous", 0, sig="fn() -> Channel[T]")
def _ch_rendezvous(interp, args, span, tv=None):
    return interp.new_channel(0, tv, span)


@static("Channel", "buffered", 1, sig="fn(Int) -> Channel[T]")
def _ch_buffered(interp, args, span, tv=None):
    return interp.new_channel(_cap(args[0]), tv, span)


@static("Channel", "unbounded", 0, sig="fn() -> Channel[T]")
def _ch_unbounded(interp, args, span, tv=None):
    return interp.new_channel(None, tv, span)


@method("Channel", "sender", 0, sig="fn() -> SendPort[T]")
def _ch_sender(interp, recv, args, span):
    return interp.make_port(recv, SendPort)


@method("Channel", "receiver", 0, sig="fn() -> ReceivePort[T]")
def _ch_receiver(interp, recv, args, span):
    return interp.make_port(recv, ReceivePort)


@method("Channel", "close", 0, sig="fn() -> Unit")
def _ch_close(interp, recv, args, span):
    interp.channel_close(recv, span)
    return UNIT


@method("Channel", "isClosed", 0, sig="fn() -> Bool")
def _ch_is_closed(interp, recv, args, span):
    return recv.closed


@method("SendPort", "send", 1, sig="async fn(T) -> Unit throws ChannelClosed", is_async=True,
        effect=frozenset({"core.ChannelClosed"}))
def _send(interp, recv, args, span):
    return interp.channel_send(recv, args[0], span)


@method("SendPort", "trySend", 1, sig="fn(T) -> TrySend")
def _try_send(interp, recv, args, span):
    return interp.channel_try_send(recv, args[0], span)


@method(["SendPort", "ReceivePort", "PublishPort"], "release", 0, sig="fn() -> Unit")
def _release(interp, recv, args, span):
    interp.release_port(recv, interp.sched.current)
    return UNIT


@method("ReceivePort", "receive", 0, sig="async fn() -> T throws ChannelClosed", is_async=True,
        effect=frozenset({"core.ChannelClosed"}))
def _receive(interp, recv, args, span):
    got, v = interp.channel_receive(recv, span)
    return v


@method("ReceivePort", "tryReceive", 0, sig="fn() -> TryReceive[T]")
def _try_receive(interp, recv, args, span):
    return interp.channel_try_receive(recv, span)


@static("Broadcast", "buffered", 1, sig="fn(Int) -> Broadcast[T]")
def _bc_new(interp, args, span, tv=None):
    elem = None
    desc = "Dyn"
    if tv is not None and tv.args and isinstance(tv.args[0], TypeValue):
        elem = interp.type_value_to_ty(tv.args[0])
        desc = str(elem)
    return Broadcast(_cap(args[0]), elem, span, desc)


@method("Broadcast", "subscribe", 0, sig="fn() -> ReceivePort[T]")
def _bc_subscribe(interp, recv, args, span):
    return interp.broadcast_subscribe(recv, span)


@method("Broadcast", "publisher", 0, sig="fn() -> PublishPort[T]")
def _bc_publisher(interp, recv, args, span):
    p = PublishPort(recv)
    PORTS_EXIST[0] = True
    recv.publishers.append(p)
    interp.adopt_ports(interp.sched.current, [p])
    return p


@method("Broadcast", "close", 0, sig="fn() -> Unit")
def _bc_close(interp, recv, args, span):
    interp.broadcast_close(recv)
    return UNIT


@method("PublishPort", "send", 1, sig="async fn(T) -> Unit throws ChannelClosed", is_async=True,
        effect=frozenset({"core.ChannelClosed"}))
def _bc_send(interp, recv, args, span):
    return interp.broadcast_send(recv, args[0], span)
