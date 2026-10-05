"""Channel selection (V3 5.14, 7.12, 8.13-8.17; SPEC-019).

Arbitration: scan enabled branches starting at the site's fairness cursor (per lexical
select site *per function activation*); the first ready branch commits atomically and
the cursor moves past it. `select priority` always scans in source order. Under
`--schedule=random` the scan start is chosen by the seeded RNG. If nothing is ready,
the task registers on every enabled alternative and blocks (a cancellation point);
a channel peer may commit directly into one branch (claim), other events (closure,
task completion, deadline) wake the task to re-scan. Losing branches have no effect.
"""
from __future__ import annotations

from ...syntax import ast as A
from ..builtins.common import want_int
from ..builtins.registry import prelude
from ..channels import Channel, ReceivePort, SendPort, Waiter
from ..core_types import RECEIVE_SELECTION, RECEIVED, TASK_SELECTION, err, ok
from ..equality import type_name
from ..signals import Fault, Thrown
from ..tasks import Wait, wake
from ..values import Duration, FrozenList, FrozenRecord, Instant, MutableList, UNIT, VariantValue
from .conc import TaskHandle
from .core import Env


class SelectState:
    __slots__ = ("task", "done", "chosen", "payload", "seq", "unregs")

    def __init__(self, task):
        self.task = task
        self.done = False
        self.chosen = None
        self.payload = None
        self.seq = None
        self.unregs: list = []

    def claim(self, branch: int, payload, seq) -> None:
        self.done = True
        self.chosen = branch
        self.payload = payload
        self.seq = seq
        wake(self.task, "selected")

    def recheck(self) -> None:
        if not self.done and self.task.wait is not None and self.task.wait.kind == "select":
            wake(self.task, "recheck")

    def unregister_all(self) -> None:
        for f in self.unregs:
            f()
        self.unregs.clear()


class Branch:
    __slots__ = ("index", "node", "kind", "enabled", "port", "value", "handle", "deadline", "binding", "guard")

    def __init__(self, index, node, kind):
        self.index = index
        self.node = node
        self.kind = kind
        self.enabled = True
        self.port = None
        self.value = None
        self.handle = None
        self.deadline = None
        self.binding = None
        self.guard = None


class SelectMixin:
    # ------------------------------------------------------------------ setup
    def setup_branches(self, node: A.Select, env: Env) -> list[Branch]:
        out = []
        now = self.sched.now()
        for i, br in enumerate(node.branches):
            b = Branch(i, br, br.kind)
            b.binding = br.binding
            if br.guard is not None:
                if br.guard in ("true", "false"):
                    g = br.guard == "true"
                else:
                    g = self.eval(A.Name(span=br.guard_span, name=br.guard), env)
                if type(g) is not bool:
                    raise self.abandon("A.TYPE.NON_BOOL_CONDITION", f"select guard `{br.guard}` must be a Bool, found "
                                       f"{type_name(g)}", br.guard_span, env)
                b.guard = g
                b.enabled = g
            if br.kind in ("receive", "closed"):
                p = self.eval(br.target, env)
                if type(p) is not ReceivePort:
                    raise self.abandon("A.TYPE.OPERAND_MISMATCH",
                                       f"`{br.kind}` branch needs a ReceivePort, found {type_name(p)}", br.target.span,
                                       env)
                b.port = p
            elif br.kind == "send":
                b.value = self.eval(br.value, env)
                p = self.eval(br.target, env)
                if type(p) is not SendPort:
                    raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`send` branch needs a SendPort, found {type_name(p)}",
                                       br.target.span, env)
                b.port = p
                if b.enabled:
                    try:
                        self.check_message(p.channel, b.value, br.span)
                    except Fault as f:
                        raise self.abandon_fault(f, br.span, env)
            elif br.kind == "task":
                h = self.eval(br.target, env)
                if type(h) is not TaskHandle:
                    raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`task` branch needs a task handle, found "
                                       f"{type_name(h)}", br.target.span, env)
                b.handle = h
            elif br.kind == "at":
                d = self.eval(br.target, env)
                if type(d) is not Instant:
                    raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`at` needs an Instant deadline, found {type_name(d)}",
                                       br.target.span, env, help="use `after <Duration>` for a relative timeout")
                b.deadline = d.nanos
            elif br.kind == "after":
                d = self.eval(br.target, env)
                if type(d) is not Duration:
                    raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`after` needs a Duration, found {type_name(d)}",
                                       br.target.span, env)
                b.deadline = now + d.nanos
            out.append(b)
        return out

    # ------------------------------------------------------------------ readiness
    def branch_ready(self, b: Branch, closed_ports: set) -> bool:
        k = b.kind
        if k == "receive":
            ch = b.port.channel
            if ch.buffer or ch.first_alive(ch.send_waiters) is not None:
                return True
            return ch.no_more_sends() and b.port.id not in closed_ports
        if k == "closed":
            ch = b.port.channel
            return not ch.buffer and ch.first_alive(ch.send_waiters) is None and ch.no_more_sends()
        if k == "dreceive":
            ch = b.port.channel
            return bool(ch.buffer) or ch.first_alive(ch.send_waiters) is not None or ch.no_more_sends()
        if k == "send":
            ch = b.port.channel
            if ch.cannot_send():
                return True
            if ch.first_alive(ch.recv_waiters) is not None:
                return True
            return ch.capacity != 0 and ch.has_space()
        if k == "task":
            return b.handle.task.done
        if k in ("at", "after"):
            return self.sched.now() >= b.deadline
        return False

    def commit_branch(self, b: Branch, node, env):
        """Commit the chosen ready branch; returns the payload for its handler."""
        task = self.sched.current
        k = b.kind
        if k == "dreceive":
            ch = b.port.channel
            if not ch.buffer and ch.first_alive(ch.send_waiters) is None and ch.no_more_sends():
                return _CLOSED
            k = "receive"
        if k == "receive":
            ch = b.port.channel
            self.check_holder(b.port, task, b.node.span)
            if ch.buffer:
                return self.take_buffered(ch, task, b.port)
            sw = ch.first_alive(ch.send_waiters)
            if sw is not None:
                v, seq, ports = self.take_from_sender(ch, sw, task)
                ch.record("receive", task.path, b.port.id, seq)
                self.adopt_ports(task, ports)
                return v
            raise self.closed_error(ch, "receive", b.port, "ControllerClosed" if ch.closed else "NoSenders",
                                    b.node.span)
        if k == "closed":
            return UNIT
        if k == "send":
            ch = b.port.channel
            self.check_holder(b.port, task, b.node.span)
            reason = ch.cannot_send()
            if reason:
                raise self.closed_error(ch, "send", b.port, reason, b.node.span)
            w = ch.first_alive(ch.recv_waiters)
            if w is not None:
                self.commit_to_receiver(ch, w, b.value, task, b.port)
            else:
                self.commit_to_buffer(ch, b.value, task, b.port)
            return UNIT
        if k == "task":
            child = b.handle.task
            if b.handle.group.closed:
                raise self.abandon("A.TASK.HANDLE_OUTSIDE_SCOPE", f"task {child.path} selected after its parallel "
                                   "block ended", b.node.span, env)
            out = child.outcome
            if out.kind == "ok":
                return ok(out.value)
            if out.kind == "threw":
                child.origin.observed = True
                prov = out.thrown.prov.copy()
                prov.chain.append(b.node.span)
                return err(out.thrown.error, prov)
            return self.deliver_outcome(child, b.node.span, env)
        return UNIT

    # ------------------------------------------------------------------ main
    def eval_Select(self, node: A.Select, env: Env):
        task = self.sched.current
        frame = task.frames[-1]
        if node.mode != "now" and not frame.is_async:
            raise self.abandon("A.ASYNC.SYNC_CONTEXT", "blocking `select` may only appear in async functions",
                               node.span, env, help="use `select now { ... none ready => ... }` for a non-blocking check")
        branches = self.setup_branches(node, env)
        none_branch = next((b for b in branches if b.kind == "none"), None)
        if (node.mode == "now") != (none_branch is not None):
            raise self.abandon("A.RUNTIME.INVALID_ARGUMENT",
                               "`none ready` is required in `select now` and not allowed elsewhere", node.span, env)
        real = [b for b in branches if b.kind != "none"]
        closed_ports = {b.port.id for b in real if b.kind == "closed" and b.enabled}
        if frame.select_cursors is None:
            frame.select_cursors = {}
        site = frame.select_cursors.setdefault(node.id, [0, 0])
        return self.run_selection(node, real, none_branch, closed_ports, site, env, node.mode)

    def run_selection(self, node, real, none_branch, closed_ports, site, env, mode, handler=None):
        task = self.sched.current
        n = len(real)
        site[1] += 1
        invocation = site[1]
        while True:
            if mode == "priority":
                order = list(range(n))
                start = 0
            else:
                start = site[0] % n if n else 0
                if self.sched.schedule == "random" and n > 1:
                    start = self.sched.rng.randrange(n)
                order = [(start + k) % n for k in range(n)]
            ready = [i for i in range(n) if real[i].enabled and self.branch_ready(real[i], closed_ports)]
            pick = next((i for i in order if i in ready), None)
            if pick is not None:
                b = real[pick]
                self.record_select(node, invocation, real, ready, start, b, mode)
                payload = self.commit_branch(b, node, env)
                if b.port is not None and b.port.channel.events and task.select_ring:
                    # the committed message's sequence number (V3 7.12.14; BUG-0039)
                    task.select_ring[-1]["seq"] = b.port.channel.events[-1].get("seq")
                if mode != "priority":
                    site[0] = (pick + 1) % n
                return (handler or self.run_branch_handler)(b, payload, env)
            if mode == "now":
                self.record_select(node, invocation, real, ready, start, None, mode)
                return (handler or self.run_branch_handler)(none_branch, None, env)
            enabled = [b for b in real if b.enabled]
            if not enabled:
                raise self.abandon("A.CONCURRENCY.DEADLOCK", "select has no enabled branch and would wait forever",
                                   node.span, env, help="ensure at least one guard is true, or add a deadline branch")
            self.check_cancel(node.span)
            st = SelectState(task)
            self.register_select(st, real, task)
            watched = frozenset(b.handle.task for b in enabled if b.kind == "task")
            self.block(Wait("select", f"selecting at {node.span.describe()} over {len(enabled)} branch(es)", True,
                            st.unregister_all, watched, node.span))
            if st.done:
                b = real[st.chosen]
                self.record_select(node, invocation, real, [st.chosen], start, b, mode, seq=st.seq)
                if mode != "priority":
                    site[0] = (st.chosen + 1) % n
                return (handler or self.run_branch_handler)(b, st.payload, env)

    def register_select(self, st: SelectState, real, task) -> None:
        for b in real:
            if not b.enabled:
                continue
            k = b.kind
            if k in ("receive", "dreceive"):
                ch = b.port.channel
                w = Waiter(task, "recv", b.port, select=st, branch=b.index)
                ch.recv_waiters.append(w)
                st.unregs.append(lambda ch=ch, w=w: _remove(ch.recv_waiters, w))
                ch.watchers.append(st)
                st.unregs.append(lambda ch=ch: _remove(ch.watchers, st))
            elif k == "closed":
                ch = b.port.channel
                ch.watchers.append(st)  # closure/endpoint loss reaches watchers via recheck_waiters
                st.unregs.append(lambda ch=ch: _remove(ch.watchers, st))
            elif k == "send":
                ch = b.port.channel
                w = Waiter(task, "send", b.port, b.value, select=st, branch=b.index)
                ch.send_waiters.append(w)
                st.unregs.append(lambda ch=ch, w=w: _remove(ch.send_waiters, w))
                ch.watchers.append(st)
                st.unregs.append(lambda ch=ch: _remove(ch.watchers, st))
            elif k == "task":
                child = b.handle.task
                if child.done:
                    continue
                child.watchers.append(st)
                st.unregs.append(lambda child=child: _remove(child.watchers, st))
            elif k in ("at", "after"):
                timer = self.sched.add_timer(b.deadline, st.recheck)
                st.unregs.append(lambda timer=timer: setattr(timer, "cancelled", True))

    def run_branch_handler(self, b: Branch, payload, env):
        benv = env
        if b.binding is not None:
            benv = Env(env)
            benv.vars[b.binding] = payload
        body = b.node.body
        if body.__class__ is A.Block:
            return self.exec_block(body, benv)
        return self.eval(body, benv)

    def record_select(self, node, invocation, real, ready, start, chosen, mode, seq=None) -> None:
        task = self.sched.current
        ev = {
            "site": node.span.describe() if hasattr(node, "span") and node.span is not None else str(node),
            "invocation": invocation,
            "mode": mode,
            "enabled": [b.index for b in real if b.enabled],
            "disabled": [b.index for b in real if not b.enabled],
            "ready": list(ready),
            "cursor": start,
            "chosen": chosen.index if chosen is not None else None,
            "chosen_kind": chosen.kind if chosen is not None else "none",
            "channels": sorted({b.port.channel.id for b in real if b.port is not None}),
        }
        if seq is not None:
            ev["seq"] = seq
        deadlines = [b.deadline for b in real if b.deadline is not None]
        if deadlines:
            ev["deadline_remaining_ns"] = min(deadlines) - self.sched.now()
        if self.sched.schedule == "random":
            ev["seed"] = self.sched.seed
        task.select_ring.append(ev)


def _remove(lst, item) -> None:
    try:
        lst.remove(item)
    except ValueError:
        pass


class _SiteNode:
    def __init__(self, span):
        self.span = span


_CLOSED = object()


def _dynamic_site(interp, span):
    frame = interp.sched.current.frames[-1]
    if frame.select_cursors is None:
        frame.select_cursors = {}
    return frame.select_cursors.setdefault(("dyn", span.start if span else 0), [0, 0])


@prelude("selectReceive", 1, sig="async fn(List[ReceivePort[T]]) -> ReceiveSelection", is_async=True)
def _select_receive(interp, args, span):
    ports = args[0]
    if type(ports) not in (FrozenList, MutableList) or not ports.items:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "selectReceive expects a non-empty List of ReceivePorts")
    real = []
    for i, p in enumerate(ports.items):
        if type(p) is not ReceivePort:
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"selectReceive element {i} is {type_name(p)}, not a ReceivePort")
        b = Branch(i, _SiteNode(span), "dreceive")
        b.port = p
        real.append(b)

    def handler(b, payload, env):
        if payload is _CLOSED:
            ch = b.port.channel
            outcome = VariantValue(RECEIVED.cases["Closed"], ("ControllerClosed" if ch.closed else "NoSenders",))
        else:
            outcome = VariantValue(RECEIVED.cases["Message"], (payload,))
        return FrozenRecord(RECEIVE_SELECTION, (b.index, outcome))
    return interp.run_selection(_SiteNode(span), real, None, set(), _dynamic_site(interp, span), None, "normal",
                                handler)


@prelude("selectTask", 1, sig="async fn(List[Task[T, E]]) -> TaskSelection", is_async=True)
def _select_task(interp, args, span):
    handles = args[0]
    if type(handles) not in (FrozenList, MutableList) or not handles.items:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "selectTask expects a non-empty List of task handles")
    real = []
    for i, h in enumerate(handles.items):
        if type(h) is not TaskHandle:
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"selectTask element {i} is {type_name(h)}, not a task handle")
        b = Branch(i, _SiteNode(span), "task")
        b.handle = h
        real.append(b)

    def handler(b, payload, env):
        return FrozenRecord(TASK_SELECTION, (b.index, payload))
    return interp.run_selection(_SiteNode(span), real, None, set(), _dynamic_site(interp, span), None, "normal",
                                handler)
