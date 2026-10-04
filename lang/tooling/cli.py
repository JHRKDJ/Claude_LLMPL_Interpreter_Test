"""Command-line interface (V3 7.14.2; working command family `lang run/check/format/repl/test`).

Exit status: 0 success; 1 unhandled recoverable error; 2 static errors (program not
run / check failed); 3 abandonment; 4 hard termination or interpreter defect;
130 cancelled by interrupt; a value returned by `main() -> Int` is used verbatim.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Optional

from ..diagnostics.render_json import render_json, to_dict
from ..diagnostics.render_text import render, render_all, summary_line


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--mode", choices=["draft", "verified"], default=None,
                   help="acceptance mode (default: from lang.toml, else draft)")
    p.add_argument("--release", action="store_true", help="release build: requires verified acceptance")
    p.add_argument("--json", action="store_true", help="machine-readable diagnostics on stdout/stderr")
    p.add_argument("--quiet", action="store_true", help="one line per diagnostic")
    p.add_argument("--deep", action="store_true", help="deep diagnostics (all frames, event histories)")


def _add_runtime(p: argparse.ArgumentParser, clock_default: Optional[str] = "real") -> None:
    p.add_argument("--clock", choices=["real", "virtual"], default=clock_default,
                   help="time source (default: real for run/repl, virtual for test)")
    p.add_argument("--schedule", choices=["fifo", "random"], default="fifo")
    p.add_argument("--seed", type=int, default=None)


def _render(diags, args, stream=sys.stderr, **extra) -> None:
    if not diags and not extra:
        return
    if args.json:
        stream.write(render_json(diags, **extra) + "\n")
        return
    mode = "quiet" if args.quiet else ("deep" if args.deep else "default")
    for d in diags:
        stream.write(render(d, mode) + "\n\n")


def _mode(args, project_mode: str) -> str:
    if args.release:
        return "verified"
    return args.mode or project_mode


def cmd_check(args) -> int:
    from ..tooling.driver import check_program
    from ..modules.loader import load_program
    status = 0
    all_diags = []
    for path in args.paths:
        prog = load_program(path)
        mode = _mode(args, prog.project.mode)
        co = check_program(prog, mode)
        all_diags.extend(co.diagnostics)
        if args.fix:
            from .fixes import apply_import_fixes
            changed = apply_import_fixes(co.diagnostics, write=not args.diff, stream=sys.stdout)
            if changed and not args.json:
                sys.stderr.write(f"applied {changed} import fix(es)\n")
        if co.blocking:
            status = 2
    if args.json:
        sys.stdout.write(render_json(all_diags, ok=status == 0) + "\n")
    else:
        _render(all_diags, args)
        sys.stderr.write(summary_line(all_diags) + "\n")
    return status


def cmd_run(args) -> int:
    from ..modules.loader import load_program
    from ..runtime.interp import Interpreter, RunOptions
    from ..tooling.driver import check_program
    prog = load_program(args.path)
    mode = _mode(args, prog.project.mode)
    co = check_program(prog, mode)
    warnings = [d for d in co.diagnostics if d.severity != "error"]
    if co.blocking:
        _render(co.diagnostics, args)
        if not args.json:
            sys.stderr.write(summary_line(co.diagnostics) + " — program not run\n")
        return 2
    if warnings and not args.quiet_warnings:
        _render(warnings, args)
    opts = RunOptions(mode=mode, clock=args.clock, schedule=args.schedule, seed=args.seed, argv=args.args,
                      deep=args.deep)
    interp = Interpreter(co.program, opts)
    _install_interrupt(interp)
    res = interp.run_main()
    diags = list(res.diagnostics) + list(res.warnings)
    if args.json:
        if diags or res.exit_code != 0:
            sys.stderr.write(render_json(diags, outcome=res.outcome, exit_code=res.exit_code) + "\n")
    else:
        _render(diags, args)
    return res.exit_code


def _install_interrupt(interp) -> None:
    """First SIGINT: cooperative cancellation of the root task. Second: hard termination."""
    state = {"count": 0}

    def handler(signum, frame):
        state["count"] += 1
        sched = interp.sched
        root = sched.all_tasks[0] if sched.all_tasks else None
        if state["count"] == 1 and root is not None:
            from ..runtime.tasks import cancel_scope
            cancel_scope(root.root_scope, "external interrupt")
        else:
            sys.stderr.write("hard termination requested (second interrupt); no cleanup guarantees\n")
            import os
            os._exit(4)
    try:
        signal.signal(signal.SIGINT, handler)
    except ValueError:
        pass


def cmd_format(args) -> int:
    from ..format import format_source
    status = 0
    for path in args.paths:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        try:
            out = format_source(text, str(p))
        except ValueError as e:
            sys.stderr.write(f"{p}: cannot format: {e}\n")
            status = 2
            continue
        if args.check:
            if out != text:
                sys.stderr.write(f"{p}: not canonically formatted\n")
                status = 1
        elif args.diff:
            import difflib
            sys.stdout.writelines(difflib.unified_diff(text.splitlines(True), out.splitlines(True), str(p), str(p)))
        elif out != text:
            p.write_text(out, encoding="utf-8")
    return status


def cmd_test(args) -> int:
    from .testrunner import run_tests
    return run_tests(args)


def cmd_repl(args) -> int:
    from .repl import repl_main
    return repl_main(args)


def cmd_lock(args) -> int:
    from ..modules.project import load_project, write_lock
    proj = load_project(Path(args.path))
    if proj.manifest_path is None:
        sys.stderr.write("no lang.toml found\n")
        return 2
    sys.stdout.write(write_lock(proj))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lang", description="LLM-native language toolchain (V3 reference)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="check (per mode) and run a program")
    p.add_argument("path")
    p.add_argument("args", nargs="*", help="arguments passed to main(args: List[Str])")
    _add_common(p)
    _add_runtime(p)
    p.add_argument("--quiet-warnings", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("check", help="static checks (draft or verified)")
    p.add_argument("paths", nargs="+")
    _add_common(p)
    p.add_argument("--fix", action="store_true", help="apply unambiguous known-import insertions (visible edits)")
    p.add_argument("--diff", action="store_true", help="with --fix: print the patch instead of writing files")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("format", help="canonical formatter")
    p.add_argument("paths", nargs="+")
    p.add_argument("--check", action="store_true", help="exit 1 if a file is not canonically formatted")
    p.add_argument("--diff", action="store_true", help="print a unified diff instead of rewriting")
    p.set_defaults(fn=cmd_format)
    p = sub.add_parser("test", help="run `test \"...\" { }` blocks")
    p.add_argument("paths", nargs="+")
    _add_common(p)
    _add_runtime(p, clock_default=None)
    p.add_argument("--filter", default=None, help="run only tests whose name contains this text")
    p.add_argument("--repeat", type=int, default=1, help="with --schedule=random: runs per test (seeds seed..)")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("repl", help="interactive session with runtime module loading")
    _add_common(p)
    _add_runtime(p)
    p.set_defaults(fn=cmd_repl)
    p = sub.add_parser("lock", help="(re)write lang.lock from lang.toml dependencies")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(fn=cmd_lock)
    args = ap.parse_args(argv)
    if getattr(args, "release", False) and getattr(args, "mode", None) == "draft":
        sys.stderr.write("error[S.MODE.RELEASE_REQUIRES_VERIFIED]: release builds require verified acceptance\n")
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
