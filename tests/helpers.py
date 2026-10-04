"""Shared helpers: run language source through the real toolchain pipeline."""
from __future__ import annotations

import io
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lang.diagnostics.render_text import render_all
from lang.runtime.interp import RunOptions
from lang.tooling.driver import load_and_check, run_program


@dataclass
class Run:
    stdout: str
    exit_code: Optional[int]
    outcome: Optional[str]
    diags: list = field(default_factory=list)  # runtime failure diagnostics
    check: list = field(default_factory=list)  # static diagnostics
    warnings: list = field(default_factory=list)
    value: object = None

    @property
    def codes(self) -> list[str]:
        return [d.stable_code for d in self.diags]

    @property
    def check_codes(self) -> list[str]:
        return [d.stable_code for d in self.check]

    @property
    def check_errors(self) -> list[str]:
        return [d.stable_code for d in self.check if d.severity == "error"]

    @property
    def check_warnings(self) -> list[str]:
        return [d.stable_code for d in self.check if d.severity == "warning"]

    @property
    def lines(self) -> list[str]:
        return self.stdout.splitlines()

    def text(self) -> str:
        return render_all(self.check + self.diags)

    @property
    def diag(self):
        return self.diags[0]


def run(src: str, mode: str = "draft", clock: str = "virtual", schedule: str = "fifo", seed: Optional[int] = None,
        argv=None, files: Optional[dict] = None, entry: str = "main.lang") -> Run:
    d = Path(tempfile.mkdtemp(prefix="langtest-"))
    for name, text in (files or {}).items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    path = d / entry
    path.write_text(src)
    out = io.StringIO()
    err = io.StringIO()
    opts = RunOptions(mode=mode, clock=clock, schedule=schedule, seed=seed, stdout=out, stderr=err,
                      argv=list(argv or []))
    co, r = run_program(path, opts)
    if r is None:
        return Run(out.getvalue(), None, None, [], co.diagnostics)
    return Run(out.getvalue(), r.exit_code, r.outcome, r.diagnostics, co.diagnostics, r.warnings, r.value)


def check(src: str, mode: str = "verified", files: Optional[dict] = None) -> Run:
    d = Path(tempfile.mkdtemp(prefix="langcheck-"))
    for name, text in (files or {}).items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    path = d / "main.lang"
    path.write_text(src)
    co = load_and_check(path, mode)
    return Run("", None, None, [], co.diagnostics)


def ok(src: str, **kw) -> Run:
    r = run(src, **kw)
    assert r.exit_code == 0 and not [c for c in r.check if c.severity == "error"], r.text()
    return r


def run_unchecked(src: str, mode: str = "draft", clock: str = "virtual", schedule: str = "fifo",
                  seed: Optional[int] = None) -> Run:
    """Execute parsed source *without* the static checker, to exercise the runtime's own
    defence-in-depth checks for rules the checker normally rejects first."""
    from lang.modules.loader import load_program
    from lang.runtime.interp import Interpreter
    d = Path(tempfile.mkdtemp(prefix="langraw-"))
    path = d / "main.lang"
    path.write_text(src)
    prog = load_program(path)
    assert prog.parse_ok, render_all(list(prog.all_diagnostics()))
    out = io.StringIO()
    opts = RunOptions(mode=mode, clock=clock, schedule=schedule, seed=seed, stdout=out, stderr=io.StringIO())
    r = Interpreter(prog, opts).run_main()
    return Run(out.getvalue(), r.exit_code, r.outcome, r.diagnostics, [], r.warnings, r.value)
