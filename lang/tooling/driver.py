"""Load -> check -> run pipeline shared by the CLI, tests and the REPL."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..modules.loader import ProgramSource, load_program
from ..runtime.interp import Interpreter, RunOptions, RunResult


@dataclass
class CheckOutcome:
    program: ProgramSource
    diagnostics: list = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)


def check_program(prog: ProgramSource, mode: str) -> CheckOutcome:
    diags = list(prog.all_diagnostics())
    if not prog.parse_ok:
        return CheckOutcome(prog, diags)
    try:
        from ..check import check as run_checker
    except ImportError:
        return CheckOutcome(prog, diags)
    diags.extend(run_checker(prog, mode))
    return CheckOutcome(prog, diags)


def load_and_check(path: str | Path, mode: Optional[str] = None, text: Optional[str] = None) -> CheckOutcome:
    prog = load_program(path, text=text)
    m = mode or prog.project.mode
    return check_program(prog, m)


def run_program(path: str | Path, options: Optional[RunOptions] = None, text: Optional[str] = None
                ) -> tuple[CheckOutcome, Optional[RunResult]]:
    options = options or RunOptions()
    co = load_and_check(path, options.mode, text)
    if co.blocking:
        return co, None
    interp = Interpreter(co.program, options)
    return co, interp.run_main()
