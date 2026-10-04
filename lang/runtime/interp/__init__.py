"""The evaluator, assembled from per-concern mixins."""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from typing import Optional

from ...diagnostics import Diagnostic, Label, Note, TaskProvenance, code
from ...syntax import ast as A
from ..builtins.common import kind_of
from ..builtins.registry import METHODS, load_all
from ..capture import Budget, safe_repr
from ..equality import type_name
from ..rtypes import TypeRegistry
from ..scheduler import Coro, Scheduler
from ..signals import Thrown
from ..tasks import Task
from ..values import Closure, FrozenRecord, UNIT
from .calls import CallMixin
from .conc import ConcMixin
from .core import Env, Frame, InterpCore
from .exprs import ExprMixin
from .link import LinkMixin
from .patterns import PatternMixin
from .res import ResourceMixin
from .stmts import StmtMixin, make_stmt_dispatch
from .chan import ChannelMixin
from .selectx import SelectMixin

load_all()


@dataclass
class RunOptions:
    mode: str = "draft"
    clock: str = "real"
    schedule: str = "fifo"
    seed: Optional[int] = None
    stdout: object = None
    stderr: object = None
    argv: list = field(default_factory=list)
    large_copy_threshold: int = 10000
    deep: bool = False


@dataclass
class RunResult:
    exit_code: int
    outcome: str  # ok | threw | abandoned | cancelled | hard
    value: object = None
    diagnostics: list = field(default_factory=list)  # failure diagnostics
    warnings: list = field(default_factory=list)  # runtime advisories


class Interpreter(InterpCore, ExprMixin, StmtMixin, CallMixin, PatternMixin, ConcMixin, ResourceMixin, LinkMixin,
                  ChannelMixin, SelectMixin):
    def __init__(self, program, options: Optional[RunOptions] = None):
        self.options = options or RunOptions()
        o = self.options
        self.sched = Scheduler(o.clock, o.schedule, o.seed)
        self.registry = TypeRegistry()
        self.registry.builtin_method_table = lambda v: METHODS.get(kind_of(v))
        self.out = o.stdout if o.stdout is not None else sys.stdout
        self.err = o.stderr if o.stderr is not None else sys.stderr
        self.runtime_warnings: list = []
        self.hard_termination = None
        self._ev = {
            A.Literal: self.eval_Literal, A.StringLit: self.eval_StringLit, A.Name: self.eval_Name,
            A.ListLit: self.eval_ListLit, A.MapLit: self.eval_MapLit, A.TupleLit: self.eval_TupleLit,
            A.Unary: self.eval_Unary, A.Binary: self.eval_Binary, A.Range: self.eval_Range,
            A.Call: self.eval_Call, A.Index: self.eval_Index, A.Field: self.eval_Field,
            A.WithUpdate: self.eval_WithUpdate, A.Lambda: self.eval_Lambda, A.If: self.eval_If,
            A.Match: self.eval_Match, A.Is: self.eval_Is, A.As: self.eval_As, A.Try: self.eval_Try,
            A.Capture: self.eval_Capture, A.Propagate: self.eval_Propagate, A.Await: self.eval_Await,
            A.Yield: self.eval_Yield, A.Use: self.eval_Use, A.Parallel: self.eval_Parallel,
            A.Spawn: self.eval_Spawn, A.Within: self.eval_Within, A.Select: self.eval_Select,
        }
        self._stmt = make_stmt_dispatch(self)
        self.init_channels()
        self.link_program(program)
        self.sched.on_deadlock = self.handle_deadlock

    # ------------------------------------------------------------------ io
    def write_out(self, s: str) -> None:
        self.out.write(s)
        if hasattr(self.out, "flush"):
            self.out.flush()

    def write_err(self, s: str) -> None:
        self.err.write(s)

    # ------------------------------------------------------------------ running
    def entry_module(self):
        return self.modules[self.program.entry]

    def run_main(self) -> RunResult:
        mod = self.entry_module()
        main = mod.env.vars.get("main")
        if not isinstance(main, Closure):
            d = Diagnostic(code("S.MODULE.NO_MAIN"), f"module `{mod.name}` has no `fn main()`")
            return RunResult(2, "static", diagnostics=[d])
        args = []
        params = [p for p in main.decl.params]
        if params:
            from ..values import FrozenList
            args = [FrozenList(tuple(self.options.argv))]

        def body():
            self.init_consts()
            return self.call_value(main, args, None, main.decl.span, awaited=True)
        return self.run_root(body, "main")

    def run_root(self, body, path: str) -> RunResult:
        root = Task(self.sched, path, path)
        entry = Frame("<entry>", None, None, None, True)

        def run():
            root.frames.append(entry)
            self.run_task_body(root, body)
        root.coro = Coro(self.sched, run, path)
        self.sched.run(root)
        return self.result_for(root)

    def result_for(self, root: Task) -> RunResult:
        if self.hard_termination is not None:
            return RunResult(4, "hard", diagnostics=[self.hard_termination], warnings=self.runtime_warnings)
        out = root.outcome
        if out is None:
            d = Diagnostic(code("H.RUNTIME.HARD_TERMINATION"), "program stopped before the root task finished")
            return RunResult(4, "hard", diagnostics=[d], warnings=self.runtime_warnings)
        if out.kind == "ok":
            v = out.value
            code_ = v if type(v) is int else 0
            return RunResult(code_, "ok", value=v, warnings=self.runtime_warnings)
        if out.kind == "threw":
            d = self.error_diag(out.thrown, "R.ERROR.UNHANDLED", "unhandled recoverable error")
            return RunResult(1, "threw", diagnostics=[d], warnings=self.runtime_warnings)
        if out.kind == "abandoned":
            return RunResult(3, "abandoned", diagnostics=[out.diagnostic], warnings=self.runtime_warnings)
        d = Diagnostic(code("C.PROGRAM.INTERRUPTED"), f"program cancelled ({out.reason})")
        return RunResult(130, "cancelled", diagnostics=[d], warnings=self.runtime_warnings)

    # ------------------------------------------------------------------ error diagnostics
    def error_diag(self, t: Thrown, stable: str, headline: str) -> Diagnostic:
        """Diagnostic for a recoverable error that escaped (or is being reported)."""
        e = t.error
        prov = t.prov
        msg = f"{headline}: {safe_repr(e, Budget(300))}"
        d = Diagnostic(code(stable), msg, primary=Label(prov.created_at, f"{type_name(e)} raised here")
                       if prov.created_at is not None else None)
        d.propagation = list(prov.chain)
        if prov.task_path:
            d.task = TaskProvenance(prov.task_path)
        for k, v in prov.context:
            d.values[k] = v
        for s in prov.unmarked:
            d.notes.append(Note("propagated through a call without a `try` marker (draft mode; verified mode "
                                "requires the marker)", s))
        if prov.cancel_pending:
            d.notes.append(Note("external cancellation was also pending and is redelivered after this failure"))
        d.extra["error_type"] = type_name(e)
        if isinstance(e, FrozenRecord) and e.rtype.categories:
            d.extra["category"] = e.rtype.categories[0]
        for source, path, err, p in prov.parts:
            child = self.error_diag(Thrown(err, p), "R.TASK.AGGREGATE" if source in ("task", "body") else stable,
                                    f"{source} failure" + (f" in {path}" if path else ""))
            if path:
                child.task = TaskProvenance(path)
            child.extra["source"] = source
            d.children.append(child)
        return d

    # ------------------------------------------------------------------ tests
    def run_test(self, mod_name: str, test: A.TestDecl) -> RunResult:
        mrt = self.modules[mod_name]
        self.sched = Scheduler(self.options.clock, self.options.schedule, self.options.seed)
        self.sched.on_deadlock = self.handle_deadlock
        self.hard_termination = None

        def body():
            self.init_consts()
            entry = self.sched.current.frames[-1]
            fenv = Env(mrt.env, kind="fn")
            fr = Frame(f"test \"{test.name}\"", test, test.span, fenv, True)
            self.sched.current.frames.append(fr)
            try:
                self.exec_block(test.body, fenv, scope=False)
            finally:
                self.sched.current.frames.pop()
            del entry
            return UNIT
        return self.run_root(body, f"test:{test.name}")
