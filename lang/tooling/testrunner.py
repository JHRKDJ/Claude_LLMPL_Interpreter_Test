"""`lang test`: run `test "name" { ... }` blocks (V3 7.14.2, 7.14.5).

Each test runs in a fresh interpreter (fresh module constants, fresh scheduler), so
tests cannot observe each other. A test passes when its body completes normally;
an unhandled recoverable error, an abandonment (including a failed `assert`), a
cancellation or hard termination is a failure.

Schedule stress (V3 7.14.5): `--schedule=random` perturbs task scheduling, select
tie-breaking and competing receivers with a recorded seed. When no seed is given one
is drawn and printed; `--repeat N` runs every test with seeds seed, seed+1, ...
Every failure under random scheduling carries a W.TEST.SEED diagnostic with the
command that reproduces it, plus the recent selection events already attached to
the failure diagnostic.

Tests use the virtual clock unless `--clock=real` is given (deterministic timing).
"""
from __future__ import annotations

import io
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..diagnostics import Diagnostic, Note, code
from ..diagnostics.render_json import to_dict
from ..diagnostics.render_text import render


@dataclass
class TestResult:
    file: str
    name: str
    passed: bool
    outcome: str
    seed: Optional[int]
    stdout: str = ""
    diagnostics: list = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class TestReport:
    results: list = field(default_factory=list)
    static: list = field(default_factory=list)  # (file, diagnostics) that blocked a file
    seed: Optional[int] = None

    @property
    def failed(self) -> list:
        return [r for r in self.results if not r.passed]

    @property
    def exit_code(self) -> int:
        if self.static:
            return 2
        return 1 if self.failed else 0


def collect_files(paths) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*.lang")):
                if not any(part.startswith(".") for part in f.relative_to(p).parts):
                    out.append(f)
        else:
            out.append(p)
    return out


def _tests_of(module_ast):
    from ..syntax import ast as A
    return [d for d in module_ast.decls if isinstance(d, A.TestDecl)]


def run_test_files(paths, mode: Optional[str] = None, schedule: str = "fifo",
                   seed: Optional[int] = None, clock: str = "virtual", name_filter: Optional[str] = None,
                   repeat: int = 1) -> TestReport:
    from ..modules.loader import load_program
    from ..runtime.interp import Interpreter, RunOptions
    from .driver import check_program
    if schedule == "random" and seed is None:
        seed = int(time.time() * 1000) % 1_000_000_007
    report = TestReport(seed=seed if schedule == "random" else None)
    for f in collect_files(paths):
        prog = load_program(f)
        m = mode or prog.project.mode
        co = check_program(prog, m)
        if co.blocking:
            report.static.append((str(f), co.diagnostics))
            continue
        entry = co.program.modules.get(co.program.entry)
        if entry is None or entry.ast is None:
            continue
        for t in _tests_of(entry.ast):
            if name_filter and name_filter not in t.name:
                continue
            for k in range(max(1, repeat)):
                s = (seed + k) if schedule == "random" else None
                out = io.StringIO()
                opts = RunOptions(mode=m, clock=clock, schedule=schedule, seed=s, stdout=out, stderr=io.StringIO())
                start = time.perf_counter()
                interp = Interpreter(co.program, opts)
                res = interp.run_test(co.program.entry, t)
                diags = list(res.diagnostics)
                passed = res.outcome == "ok"
                if not passed and schedule == "random":
                    diags.append(_seed_diag(f, t.name, s, m))
                report.results.append(TestResult(str(f), t.name, passed, res.outcome, s, out.getvalue(), diags,
                                                 (time.perf_counter() - start) * 1000))
                if not passed:
                    break  # further seeds of a failing test add no information
    return report


def _seed_diag(f, name: str, seed: int, mode: str) -> Diagnostic:
    d = Diagnostic(code("W.TEST.SEED"), f"test \"{name}\" failed under randomised scheduling with seed {seed}",
                   severity="warning")
    d.help.append(f"reproduce: lang test {f} --mode={mode} --schedule=random --seed={seed} --filter \"{name}\"")
    d.notes.append(Note("the failure depends on task/select ordering only if it passes under --schedule=fifo; "
                        "user logic must not rely on scheduling order (V3 7.14.5)"))
    d.extra["seed"] = seed
    return d


def run_tests(args) -> int:
    clock = getattr(args, "clock", None) or "virtual"
    report = run_test_files(args.paths, getattr(args, "mode", None), args.schedule, args.seed, clock,
                            getattr(args, "filter", None), getattr(args, "repeat", 1))
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps({
            "ok": report.exit_code == 0,
            "seed": report.seed,
            "static": [{"file": f, "diagnostics": [to_dict(d) for d in ds]} for f, ds in report.static],
            "results": [{"file": r.file, "name": r.name, "passed": r.passed, "outcome": r.outcome, "seed": r.seed,
                         "duration_ms": round(r.duration_ms, 2), "stdout": r.stdout,
                         "diagnostics": [to_dict(d) for d in r.diagnostics]} for r in report.results],
        }, indent=2) + "\n")
        return report.exit_code
    mode = "quiet" if getattr(args, "quiet", False) else ("deep" if getattr(args, "deep", False) else "default")
    if report.seed is not None:
        sys.stdout.write(f"schedule: random, seed {report.seed}\n")
    for f, ds in report.static:
        for d in ds:
            if d.severity == "error":
                sys.stderr.write(render(d, mode) + "\n\n")
        sys.stdout.write(f"ERROR {f}: static errors, tests not run\n")
    for r in report.results:
        tag = "PASS" if r.passed else "FAIL"
        seed = f" [seed {r.seed}]" if r.seed is not None else ""
        sys.stdout.write(f"{tag} {r.file} :: {r.name}{seed}\n")
        if not r.passed:
            if r.stdout:
                sys.stdout.write("".join("    | " + ln + "\n" for ln in r.stdout.splitlines()))
            for d in r.diagnostics:
                sys.stderr.write(render(d, mode) + "\n\n")
    passed = sum(1 for r in report.results if r.passed)
    sys.stdout.write(f"{passed} passed, {len(report.failed)} failed"
                     + (f", {len(report.static)} file(s) with static errors" if report.static else "") + "\n")
    return report.exit_code
