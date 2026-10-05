"""Evaluator core: environments, frames, dispatch, abandonment diagnostics, task bodies.

The Interpreter class is assembled from mixins (exprs, stmts, calls, patterns,
concurrency, resources, link) so each semantic area lives in its own file.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

from ...diagnostics import (ChannelProvenance, Diagnostic, Frame as DFrame, Label, Note, ResourceProvenance,
                            TaskProvenance, code)
from ...syntax import ast as A
from ..capture import Budget, safe_repr
from ..equality import type_name
from ..signals import Abandoned, Cancelled, Fault, HardTermination, Signal, Thrown
from ..tasks import Outcome, Task
from ..values import UNINIT

sys.setrecursionlimit(200000)

MAX_CALL_DEPTH = 2500


class Env:
    __slots__ = ("vars", "parent", "consts", "types", "kind")

    def __init__(self, parent: Optional["Env"] = None, kind: str = "block"):
        self.vars: dict[str, Any] = {}
        self.parent = parent
        self.consts: Optional[set] = None
        self.types: Optional[dict] = None
        self.kind = kind  # block | fn | module | prelude

    def define(self, name: str, value, const: bool = False, ty=None) -> None:
        self.vars[name] = value
        if const:
            if self.consts is None:
                self.consts = set()
            self.consts.add(name)
        if ty is not None:
            if self.types is None:
                self.types = {}
            self.types[name] = ty

    def find(self, name: str) -> Optional["Env"]:
        e = self
        while e is not None:
            if name in e.vars:
                return e
            e = e.parent
        return None


class Frame:
    __slots__ = ("name", "decl", "call_span", "env", "cur_env", "is_async", "groups", "select_cursors",
                 "closure", "provider_state", "snapshots", "self_value", "contract_mode")

    def __init__(self, name: str, decl, call_span, env: Env, is_async: bool, closure=None):
        self.name = name
        self.decl = decl
        self.call_span = call_span
        self.env = env
        self.cur_env = env
        self.is_async = is_async
        self.groups: list = []
        self.select_cursors: Optional[dict] = None
        self.closure = closure
        self.provider_state = None
        self.snapshots: Optional[dict] = None
        self.self_value = None
        self.contract_mode = False


class InterpCore:
    """Shared machinery used by all evaluator mixins."""

    # set up by Interpreter.__init__
    sched = None
    registry = None
    options = None

    # ------------------------------------------------------------ task access
    @property
    def task(self) -> Task:
        return self.sched.current

    @property
    def frame(self) -> Frame:
        return self.sched.current.frames[-1]

    # ------------------------------------------------------------ dispatch
    def eval(self, node, env: Env):
        try:
            return self._ev[node.__class__](node, env)
        except Fault as f:
            raise self.abandon_fault(f, node.span, env) from None

    # ------------------------------------------------------------ diagnostics
    def capture_frames(self, env: Optional[Env] = None, innermost_span=None) -> list[DFrame]:
        task = self.sched.current
        if task is None:
            return []
        out: list[DFrame] = []
        frames = list(task.frames)
        loc = innermost_span
        for i in range(len(frames) - 1, -1, -1):
            fr = frames[i]
            fenv = env if (i == len(frames) - 1 and env is not None) else fr.cur_env
            locs, trunc = self._locals(fenv)
            out.append(DFrame(fr.name, loc, locs, trunc))
            loc = fr.call_span
        return out

    def _locals(self, env: Optional[Env]) -> tuple[dict, bool]:
        out: dict[str, str] = {}
        truncated = False
        e = env
        budget = Budget(900)
        while e is not None and e.kind in ("block", "fn"):
            for k, v in e.vars.items():
                if k in out or k.startswith("$"):
                    continue
                if len(out) >= 12:
                    truncated = True
                    break
                out[k] = safe_repr(v, budget, name=k)
            if e.kind == "fn":
                break
            e = e.parent
        if budget.truncated:
            truncated = True
        return out, truncated

    def task_provenance(self) -> Optional[TaskProvenance]:
        t = self.sched.current
        if t is None:
            return None
        g = t.group
        return TaskProvenance(t.path, g.site if g else None, g.mode if g else None,
                              self.sched.seed if self.sched.schedule == "random" else None)

    def make_diag(self, stable: str, message: str, span, env: Optional[Env] = None, label: str = "",
                  help: Optional[str] = None, notes=None, expected=None, found=None, secondary=None,
                  values=None, frames: bool = True) -> Diagnostic:
        d = Diagnostic(code(stable), message, primary=Label(span, label) if span is not None else None)
        if help:
            d.help.append(help)
        for n in notes or []:
            d.notes.append(n if isinstance(n, Note) else Note(str(n)))
        d.expected = expected
        d.found = found
        for s in secondary or []:
            d.secondary.append(s)
        if values:
            d.values.update(values)
        if frames:
            d.frames = self.capture_frames(env, span)
            if any(f.locals_truncated for f in d.frames):
                d.truncated = True
        d.task = self.task_provenance()
        t = self.sched.current
        if t is not None and t.select_ring:
            d.select_events = list(t.select_ring)
        if self.sched.schedule == "random" and self.sched.decisions:
            d.extra["schedule_decisions"] = list(self.sched.decisions)
        return d

    def abandon(self, stable: str, message: str, span, env: Optional[Env] = None, **kw) -> Abandoned:
        return Abandoned(self.make_diag(stable, message, span, env, **kw))

    def abandon_fault(self, f: Fault, span, env: Optional[Env]) -> Abandoned:
        d = self.make_diag(f.stable, f.message, span, env, help=f.help, notes=f.notes, expected=f.expected,
                           found=f.found, secondary=f.secondary, values=f.values)
        d.extra.update(f.extra)
        return Abandoned(d)

    # ------------------------------------------------------------ cancellation points
    def check_cancel(self, span=None) -> None:
        t = self.sched.current
        if t.cancel_pending():
            raise Cancelled("cancellation delivered", span)

    # ------------------------------------------------------------ task bodies
    def run_task_body(self, task: Task, body) -> None:
        """Runs on the task's own thread. Records the terminal outcome."""
        try:
            value = body()
            task.outcome = Outcome("ok", value=value)
        except Thrown as t:
            task.outcome = Outcome("threw", thrown=t)
        except Cancelled as c:
            task.outcome = Outcome("cancelled", reason=(task.pending_scope().reason if task.pending_scope() else c.reason))
        except Abandoned as a:
            task.outcome = Outcome("abandoned", diagnostic=a.diagnostic)
        except HardTermination as h:
            task.outcome = Outcome("abandoned", diagnostic=h.diagnostic)
            self.hard_termination = h.diagnostic
        except RecursionError:
            d = self.make_diag("A.RUNTIME.STACK_OVERFLOW", "maximum recursion depth exceeded", None, frames=False)
            task.outcome = Outcome("abandoned", diagnostic=d)
        except MemoryError:
            d = self.make_diag("A.RUNTIME.MEMORY", "memory exhausted", None, frames=False)
            task.outcome = Outcome("abandoned", diagnostic=d)
        except Signal as s:  # Return/Break/Continue escaping a task body: interpreter defect
            d = self.make_diag("H.RUNTIME.INTERNAL_ERROR", f"control signal {type(s).__name__} escaped a task",
                               None, frames=False)
            task.outcome = Outcome("abandoned", diagnostic=d)
            self.hard_termination = d
        except Exception as e:  # interpreter defect
            import traceback
            d = Diagnostic(code("H.RUNTIME.INTERNAL_ERROR"), f"internal interpreter error: {type(e).__name__}: {e}")
            d.notes.append(Note(traceback.format_exc()[-4000:]))
            d.task = TaskProvenance(task.path)
            task.outcome = Outcome("abandoned", diagnostic=d)
            self.hard_termination = d
        finally:
            task.done = True
            task.frames.clear()
            self.on_task_finished(task)

    def on_task_finished(self, task: Task) -> None:
        release = getattr(self, "release_task_ports", None)
        if release is not None:
            release(task)
        if task.group is not None:
            task.group.on_child_done(task)

    # ------------------------------------------------------------ misc helpers
    def require_bool(self, v, span, what: str, env: Optional[Env] = None) -> bool:
        if type(v) is not bool:
            raise self.abandon("A.TYPE.NON_BOOL_CONDITION",
                               f"{what} must be a Bool, found {type_name(v)} (there is no truthiness)",
                               span, env, expected="Bool", found=type_name(v),
                               help="compare explicitly, e.g. `xs.isEmpty()`, `x != 0`, `opt is Some`")
        return v

    def resource_provenance(self, state, phase=None, exit_class=None) -> ResourceProvenance:
        return ResourceProvenance(state.provider_name, state.acquired_at, state.scope_span, phase, exit_class)

    def channel_provenance(self, ch, operation, port_id=None, reason=None) -> ChannelProvenance:
        return ChannelProvenance(ch.id, operation, ch.created_at, port_id, reason, ch.type_desc,
                                 None, list(ch.events))
