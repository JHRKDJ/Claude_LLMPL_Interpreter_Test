"""Structured concurrency in the evaluator: parallel groups, spawn, await, within,
sleep, cancellation checks (V3 5.12, 6.8, 7.10; SPEC-017; AMB-002/003/004)."""
from __future__ import annotations

from ...diagnostics import Diagnostic, Label, Note, TaskProvenance, code
from ...syntax import ast as A
from ..capture import Budget, safe_repr
from ..core_types import (ABANDONMENT_REPORT, DEADLINE_EXCEEDED, TASK_GROUP_REPORT, TASK_OUTCOME, make_error)
from ..equality import type_name
from ..frozen import is_frozen
from ..isolation import Transfer
from ..scheduler import Coro
from ..signals import Abandoned, Cancelled, Fault, HardTermination, Thrown
from ..tasks import CancelScope, Outcome, Task, TaskGroup, Wait, cancel_scope
from ..values import UNIT, Closure, Duration, FrozenList, FrozenRecord, Instant, VariantValue
from .core import Env, Frame


class TaskHandle:
    lang_kind = "Task"
    lang_sendable = "reject"
    lang_reject_reason = "task handle"

    __slots__ = ("task", "group")

    def __init__(self, task: Task, group: TaskGroup):
        self.task = task
        self.group = group

    def lang_display(self) -> str:
        return f"<task {self.task.path}>"


class ConcMixin:
    # ------------------------------------------------------------------ blocking
    def block(self, wait: Wait):
        task = self.sched.current
        if not task.frames[-1].is_async and wait.kind not in ("quiesce",):
            raise Fault("A.ASYNC.SYNC_CONTEXT", f"cannot suspend ({wait.detail}) inside a non-async function",
                        help="only async functions may suspend; mark the function `async fn`")
        task.wait = wait
        self.sched.block_current()
        kind, val = task.wake if task.wake is not None else ("value", None)
        task.wake = None
        task.wait = None
        if kind == "cancel":
            raise Cancelled("cancelled while waiting", wait.span)
        if kind == "abandon":
            raise Abandoned(val)
        return val

    # ------------------------------------------------------------------ await
    def eval_Await(self, node: A.Await, env: Env):
        e = node.expr
        if e.__class__ is A.Call:
            self.check_cancel(node.span)
            return self.eval_Call(e, env, awaited=True)
        v = self.eval(e, env)
        if type(v) is TaskHandle:
            return self.await_task(v, node.span, env)
        raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`await` needs an async call or a task handle, found "
                           f"{type_name(v)}", node.span, env)

    def await_task(self, h: TaskHandle, span, env):
        task = self.sched.current
        child = h.task
        if h.group.closed:
            raise self.abandon("A.TASK.HANDLE_OUTSIDE_SCOPE",
                               f"task {child.path} is awaited after its parallel block ended", span, env,
                               help="await task handles inside the parallel block that spawned them")
        self.check_cancel(span)
        if not child.done:
            child.awaiters.append(task)

            def unregister(child=child, task=task):
                if task in child.awaiters:
                    child.awaiters.remove(task)
            self.block(Wait("await", f"awaiting task {child.path}", True, unregister, child, span))
        return self.deliver_outcome(child, span, env)

    def deliver_outcome(self, child: Task, span, env):
        out = child.outcome
        if out.kind == "ok":
            return out.value
        if out.kind == "threw":
            t = out.thrown
            prov = t.prov.copy()
            prov.chain.append(span)
            return self._raise_child(t, prov, child)
        if out.kind == "abandoned":
            d = self.make_diag("A.TASK.AWAITED_ABANDONED",
                               f"awaited task {child.path} abandoned; its value is unavailable", span, env)
            d.causes.append(out.diagnostic)
            raise Abandoned(d)
        # cancelled
        if self.sched.current.cancel_pending():
            raise Cancelled("awaited task was cancelled", span)
        raise self.abandon("A.TASK.AWAITED_CANCELLED", f"awaited task {child.path} was cancelled ({out.reason})",
                           span, env)

    def _raise_child(self, t: Thrown, prov, child):
        raise Thrown(t.error, prov, origin=child.origin)

    # ------------------------------------------------------------------ parallel
    def eval_Parallel(self, node: A.Parallel, env: Env):
        task = self.sched.current
        frame = task.frames[-1]
        if not frame.is_async:
            raise self.abandon("A.ASYNC.SYNC_CONTEXT", "`parallel` blocks wait for their children and may only "
                               "appear in async functions", node.span, env)
        line, col = node.span.start_line_col
        group = TaskGroup(node.mode, node.span, task, f"parallel@{line}:{col}")
        if any(s.cancelled for s in task.scopes):
            group.scope.cancelled = True
            group.scope.reason = "enclosing scope already cancelled"
        task.scopes.append(group.scope)
        task.groups.append(group)
        frame.groups.append(group)
        body_exc = None
        value = UNIT
        try:
            value = self.exec_block(node.body, env)
        except (Thrown, Cancelled, Abandoned) as e:
            body_exc = e
        finally:
            frame.groups.pop()
        if body_exc is not None:
            reason = {Thrown: "group body threw", Cancelled: "group body cancelled",
                      Abandoned: "group body abandoned"}[type(body_exc)]
            group.trigger(reason) if not group.scope.cancelled else None
        self.wait_quiescence(group)
        task.scopes.remove(group.scope)
        task.groups.remove(group)
        group.closed = True
        return self.group_outcome(group, value, body_exc, node, env)

    def wait_quiescence(self, group: TaskGroup) -> None:
        while group.live > 0:
            group.exit_wait = True
            task = self.sched.current
            task.wait = Wait("quiesce", f"waiting for {group.live} child task(s) of {group.label} to finish",
                             False, None, group, group.site)
            self.sched.block_current()
            wk = task.wake
            task.wake = None
            task.wait = None
            if wk is not None and wk[0] == "abandon":
                raise Abandoned(wk[1])
        group.exit_wait = False

    def child_diag(self, c: Task) -> Diagnostic:
        out = c.outcome
        if out.kind == "abandoned":
            return out.diagnostic
        if out.kind == "threw":
            d = self.error_diag(out.thrown, "R.ERROR.UNHANDLED", f"task {c.path} threw")
            d.task = TaskProvenance(c.path, c.group.site if c.group else None, c.group.mode if c.group else None)
            return d
        if out.kind == "cancelled":
            d = Diagnostic(code("C.TASK.CANCELLED"), f"task {c.path} was cancelled ({out.reason})",
                           severity="info")
            d.task = TaskProvenance(c.path)
            return d
        d = Diagnostic(code("I.RUNTIME.REPORT"), f"task {c.path} succeeded", severity="info")
        d.task = TaskProvenance(c.path)
        return d

    def group_outcome(self, group: TaskGroup, value, body_exc, node, env):
        task = self.sched.current
        children = group.children
        mode = group.mode
        outer_cancel = any(s.cancelled for s in task.scopes)
        if isinstance(body_exc, Abandoned):
            for c in children:
                if c.outcome.kind != "ok":
                    body_exc.diagnostic.children.append(self.child_diag(c))
            raise body_exc
        abandoned = [c for c in children if c.outcome.kind == "abandoned"]
        if abandoned and mode != "collect":
            first = abandoned[0]
            d = self.make_diag("A.TASK.GROUP_FAILURE",
                               f"{mode} task group abandoned: child task {first.path} abandoned"
                               + (f" (and {len(abandoned) - 1} more)" if len(abandoned) > 1 else ""),
                               group.site, env, label="task group")
            d.notes.append(Note("child abandonment dominates ordinary group outcomes; other outcomes observed "
                                "before quiescence are listed below (TaskGroupFailure)"))
            if outer_cancel:
                d.notes.append(Note("external cancellation was also pending"))
            for c in children:
                d.children.append(self.child_diag(c))
            d.extra["task_group_failure"] = self.group_tree(group)
            raise Abandoned(d)
        if mode == "failfast":
            failures = []
            body_thrown = body_exc if isinstance(body_exc, Thrown) else None
            for c in children:
                if c.outcome.kind == "threw" and not c.origin.observed:
                    failures.append(("task", (c.path, c.outcome.thrown)))
            if body_thrown is not None:
                if not any(f[1][1].error is body_thrown.error for f in failures):
                    path = body_thrown.origin.task.path if body_thrown.origin is not None else f"{task.path}/{group.label}/<body>"
                    failures.append(("task" if body_thrown.origin is not None else "body", (path, body_thrown)))
            if failures:
                raise self.aggregate_thrown(self._order(failures, children), group.site, cancel_pending=outer_cancel)
            if isinstance(body_exc, Cancelled):
                raise body_exc
            return value
        if mode == "collect":
            if isinstance(body_exc, Thrown):
                raise self.aggregate_thrown([("body", (f"{task.path}/{group.label}/<body>", body_exc))], group.site,
                                            cancel_pending=outer_cancel)
            if isinstance(body_exc, Cancelled):
                raise body_exc
            return self.build_report(group, env)
        # race / firstSuccess
        if isinstance(body_exc, Thrown):
            parts = [("body", (f"{task.path}/{group.label}/<body>", body_exc))]
            parts += [("task", (c.path, c.outcome.thrown)) for c in children if c.outcome.kind == "threw"]
            raise self.aggregate_thrown(parts, group.site, cancel_pending=outer_cancel)
        if not children:
            raise self.abandon("A.TASK.EMPTY_GROUP", f"`parallel {mode}` requires at least one spawned task",
                               group.site, env)
        if isinstance(body_exc, Cancelled) and outer_cancel:
            raise body_exc
        w = group.winner
        if mode == "race":
            if w is None:
                raise self.abandon("A.RUNTIME.UNREACHABLE", "race finished without a winner", group.site, env)
            if w.outcome.kind == "ok":
                return w.outcome.value
            if w.outcome.kind == "threw":
                parts = [("task", (w.path, w.outcome.thrown))]
                parts += [("task", (c.path, c.outcome.thrown)) for c in children
                          if c is not w and c.outcome.kind == "threw"]
                raise self.aggregate_thrown(self._order(parts, children), group.site, cancel_pending=outer_cancel)
            raise Cancelled("race winner was cancelled", group.site)
        # firstSuccess
        if w is not None and w.outcome.kind == "ok":
            return w.outcome.value
        threw = [("task", (c.path, c.outcome.thrown)) for c in children if c.outcome.kind == "threw"]
        if outer_cancel or any(c.outcome.kind == "cancelled" for c in children) and not threw:
            raise Cancelled("all firstSuccess children cancelled", group.site)
        raise self.aggregate_thrown(threw, group.site, cancel_pending=outer_cancel)

    def _order(self, failures, children):
        order = {c.path: i for i, c in enumerate(children)}
        return sorted(failures, key=lambda f: order.get(f[1][0], len(order)))

    def group_tree(self, group: TaskGroup) -> dict:
        return {"group": group.label, "mode": group.mode,
                "children": [{"path": c.path, "outcome": c.outcome.kind if c.outcome else "running"}
                             for c in group.children]}

    def build_report(self, group: TaskGroup, env):
        outcomes = []
        for c in group.children:
            out = c.outcome
            if out.kind == "ok":
                if not is_frozen(out.value):
                    raise self.abandon("A.TASK.NOT_SENDABLE",
                                       f"collect report: task {c.path} returned a mutable {type_name(out.value)}; "
                                       f"results stored in a TaskGroupReport must be frozen", group.site, env,
                                       help="return a frozen value (e.g. `.freeze()`) from the child task")
                outcomes.append(VariantValue(TASK_OUTCOME.cases["Succeeded"], (c.path, out.value)))
            elif out.kind == "threw":
                outcomes.append(VariantValue(TASK_OUTCOME.cases["ThrewException"], (c.path, out.thrown.error)))
            elif out.kind == "abandoned":
                d = out.diagnostic
                rep = FrozenRecord(ABANDONMENT_REPORT, (d.stable_code, d.message, c.path))
                outcomes.append(VariantValue(TASK_OUTCOME.cases["Abandoned"], (c.path, rep)))
            else:
                outcomes.append(VariantValue(TASK_OUTCOME.cases["Cancelled"], (c.path, out.reason or "cancelled")))
        return FrozenRecord(TASK_GROUP_REPORT, (FrozenList(tuple(outcomes)),))

    # ------------------------------------------------------------------ spawn
    def eval_Spawn(self, node: A.Spawn, env: Env):
        task = self.sched.current
        frame = task.frames[-1]
        if not frame.groups:
            raise self.abandon("A.TASK.SPAWN_OUTSIDE_GROUP", "`spawn` must appear inside a `parallel` block of the "
                               "same function", node.span, env)
        group = frame.groups[-1]
        tr = Transfer("spawn argument")
        if node.call is not None:
            call = node.call
            f = self.eval(call.callee, env)
            args, kwargs = self.eval_args(call, env)
            try:
                args = [tr.value(a, f"argument {i + 1}") for i, a in enumerate(args)]
                if kwargs:
                    kwargs = {k: tr.value(v, f"argument `{k}`") for k, v in kwargs.items()}
                tr2 = Transfer("spawned function")
                f = tr2.value(f, "callee")
                tr.ports.extend(tr2.ports)
            except Fault as flt:
                raise self.abandon_fault(flt, node.span, env)
            name = self.callee_name(call.callee, f)

            def body(f=f, args=args, kwargs=kwargs):
                return self.call_value(f, args, kwargs, node.span, awaited=True)
        else:
            caps = node.ann.get("captures", [])
            cenv = Env(self.module_env_of(env), kind="fn")
            tr.what = "spawned block capture"
            for cname, reassigned in caps:
                e = env.find(cname)
                if e is None or e.kind in ("module", "prelude"):
                    continue
                v = e.vars[cname]
                if reassigned:
                    raise self.abandon("A.TASK.NOT_SENDABLE",
                                       f"spawned block captures `{cname}`, a binding that is reassigned; captured "
                                       f"bindings must be effectively constant", node.span, env,
                                       help="pass the value as an explicit argument: `spawn work(value)`")
                if not is_frozen(v):
                    raise self.abandon("A.TASK.NOT_SENDABLE",
                                       f"spawned block captures mutable {type_name(v)} `{cname}`; closures with "
                                       f"mutable captures cannot cross task boundaries", node.span, env,
                                       help="pass it as an explicit task argument (it will be graph-copied): "
                                            "`spawn work(" + cname + ")`")
                try:
                    cenv.vars[cname] = tr.value(v, cname)
                except Fault as flt:
                    raise self.abandon_fault(flt, node.span, env)
            name = "block"

            def body(cenv=cenv):
                return self.exec_block(node.block, cenv)
        child = Task(self.sched, group.child_path(name), name, parent=task, group=group)
        if group.scope.cancelled or any(s.cancelled for s in task.scopes):
            child.root_scope.cancelled = True
            child.root_scope.reason = group.scope.reason or "parent scope cancelled"
        self.adopt_ports(child, tr.ports)
        group.children.append(child)
        group.live += 1
        mod = frame.closure.module if frame.closure is not None else None

        def run(child=child, body=body):
            entry = Frame(f"<task {child.path}>", None, node.span, None, True)
            child.frames.append(entry)
            self.run_task_body(child, lambda: self.finish_child_value(child, body()))
        child.coro = Coro(self.sched, run, child.path)
        self.sched.make_ready(child)
        if tr.copied > self.options.large_copy_threshold:
            self.large_copy_advisory(tr, node.span)
        del mod
        return TaskHandle(child, group)

    def finish_child_value(self, child: Task, value):
        tr = Transfer("task result")
        try:
            v = tr.value(value, "result")
        except Fault as flt:
            raise self.abandon_fault(flt, None, None)
        return v

    def callee_name(self, callee_node, f) -> str:
        if isinstance(callee_node, A.Name):
            return callee_node.name
        if isinstance(callee_node, A.Field):
            return callee_node.name
        return getattr(f, "name", "task")

    def module_env_of(self, env: Env) -> Env:
        e = env
        while e is not None and e.kind not in ("module", "prelude"):
            e = e.parent
        return e

    def large_copy_advisory(self, tr: Transfer, span) -> None:
        d = Diagnostic(code("W.TASK.LARGE_COPY"),
                       f"{tr.what}: implicit graph copy of about {tr.copied} element(s) at a task boundary",
                       severity="warning", primary=Label(span, "copied here"))
        d.help.append("freeze the data (frozen values are shared without copying) or pass a smaller projection")
        d.task = self.task_provenance()
        self.runtime_warnings.append(d)

    # ------------------------------------------------------------------ within / sleep / check
    def eval_Within(self, node: A.Within, env: Env):
        task = self.sched.current
        d = self.eval(node.deadline, env)
        now = self.sched.now()
        if type(d) is Duration:
            deadline = Instant(now + d.nanos)
        elif type(d) is Instant:
            deadline = d
        else:
            raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`within` expects an Instant or Duration, found "
                               f"{type_name(d)}", node.deadline.span, env)
        scope = CancelScope("within", task, span=node.span)
        scope.within_deadline = deadline
        scope.timer = self.sched.add_timer(deadline.nanos, lambda: cancel_scope(scope, "deadline exceeded"))
        task.scopes.append(scope)
        try:
            return self.exec_block(node.body, env)
        except Cancelled:
            if scope.cancelled and not any(s.cancelled for s in task.scopes if s is not scope):
                task.scopes.remove(scope)
                err = make_error(DEADLINE_EXCEEDED, deadline=deadline)
                raise Thrown(err, self.new_provenance(node.span)) from None
            raise
        finally:
            scope.timer.cancelled = True
            if scope in task.scopes:
                task.scopes.remove(scope)

    def sleep_for(self, nanos: int, span):
        task = self.sched.current
        self.check_cancel(span)
        if nanos <= 0:
            self.sched.yield_current()
            return UNIT
        timer = self.sched.add_timer(self.sched.now() + nanos, lambda: self._wake_timer(task, timer_ref))
        timer_ref = timer

        def unregister():
            timer.cancelled = True
        self.block(Wait("sleep", f"sleeping {nanos / 1e9:g}s", True, unregister, None, span))
        return UNIT

    def _wake_timer(self, task, timer):
        from ..tasks import wake
        if task.wait is not None and task.wait.kind == "sleep":
            wake(task, None)

    def exec_for_await(self, st: A.ForStmt, env: Env):
        port = self.eval(st.iterable, env)
        recv = getattr(port, "lang_kind", None)
        if recv != "ReceivePort":
            raise self.abandon("A.TYPE.NOT_ITERABLE", f"`for await` iterates a ReceivePort, found {type_name(port)}",
                               st.iterable.span, env)
        from ..signals import BreakSignal, ContinueSignal
        while True:
            got, value = self.channel_receive(port, st.iterable.span, env, closed_ok=True)
            if not got:
                return
            benv = Env(env)
            b: dict = {}
            if not self.match_pattern(st.pattern, value, b, env):
                raise self.abandon("A.MATCH.NO_ARM", "for-await pattern does not match message", st.pattern.span, env)
            benv.vars.update(b)
            try:
                self.exec_block(st.body, benv, scope=False)
            except BreakSignal:
                return
            except ContinueSignal:
                continue

    # ------------------------------------------------------------------ deadlock
    def handle_deadlock(self) -> bool:
        blocked = [t for t in self.sched.all_tasks if not t.done and t.wait is not None]
        leaves = [t for t in blocked if t.wait.kind in ("channel", "select", "sleep", "await")
                  and not (t.wait.kind == "await")]
        stuck_cleanup = [t for t in blocked if t.mask > 0]
        if not leaves:
            leaves = [t for t in blocked if t.wait.kind == "await"]
        if not leaves:
            if blocked:
                d = Diagnostic(code("H.RUNTIME.HARD_TERMINATION"),
                               "all tasks are waiting for each other to quiesce (interpreter inconsistency)")
                self.hard_termination = d
            return False
        summary = "; ".join(f"{t.path}: {t.wait.detail}" for t in blocked[:12])
        for t in leaves:
            d = Diagnostic(code("A.CONCURRENCY.DEADLOCK"),
                           f"deadlock: every task is blocked and no deadline can wake them; {t.path} is "
                           f"{t.wait.detail}", primary=Label(t.wait.span, "blocked here") if t.wait.span else None)
            d.notes.append(Note(f"blocked tasks: {summary}"))
            if stuck_cleanup:
                d.notes.append(Note("some tasks are blocked inside cleanup with cancellation masked "
                                    "(stuck cleanup): " + ", ".join(x.path for x in stuck_cleanup)))
            if t.wait.kind == "channel" and t.wait.target is not None:
                ch = t.wait.target
                d.channel = self.channel_provenance(ch, t.wait.detail)
            d.task = TaskProvenance(t.path, t.group.site if t.group else None, t.group.mode if t.group else None,
                                    self.sched.seed if self.sched.schedule == "random" else None)
            d.select_events = list(t.select_ring)
            w = t.wait
            if w.unregister is not None:
                w.unregister()
            t.wait = None
            t.wake = ("abandon", d)
            self.sched.make_ready(t)
        return True
