"""Black-box harness: runs the oracle and LocalFlow (through the interpreter CLI) as
separate processes and returns only externally observable results."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parents[1]
FIXTURES = APP / "fixtures"


@dataclass
class Observed:
    exit: int
    stdout: str
    report: object
    files: dict  # path -> exact bytes of every regular file except report.json
    tree: list  # (path, "dir" | "file", permission bits) of every entry, report.json included
    layout: object  # report.json text with message values masked (key order, indentation)


def strip_messages(x):
    if isinstance(x, dict):
        return {k: strip_messages(v) for k, v in x.items() if k != "message"}
    if isinstance(x, list):
        return [strip_messages(v) for v in x]
    return x


def snapshot(outdir: Path) -> dict:
    """Exact bytes: no newline translation or decoding, so CRLF and encoding
    differences are observable (final review harness finding)."""
    files = {}
    if outdir.exists():
        for p in sorted(outdir.rglob("*")):
            if p.is_file() and p.relative_to(outdir) != Path("report.json"):
                files[str(p.relative_to(outdir))] = p.read_bytes()
    return files


def tree(outdir: Path) -> list:
    """Every directory and file left behind (empty leftovers included) with its mode."""
    out = []
    if outdir.exists():
        for p in sorted(outdir.rglob("*")):
            out.append((str(p.relative_to(outdir)), "dir" if p.is_dir() else "file",
                        stat.S_IMODE(p.stat().st_mode)))
    return out


_MESSAGE = re.compile(r'^(\s*"message": )"(?:[^"\\]|\\.)*"', re.M)


def layout(outdir: Path):
    rep = outdir / "report.json"
    if not rep.exists():
        return None
    return _MESSAGE.sub(r'\1"…"', rep.read_bytes().decode("utf-8", "replace"))


def observe(cmd, outdir: Path, timeout=600) -> Observed:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    # bytes, decoded without newline translation, so stdout is compared exactly
    p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=str(ROOT))
    out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    rep_path = outdir / "report.json"
    report = json.loads(rep_path.read_bytes()) if rep_path.exists() else None
    return Observed(p.returncode, out, report, snapshot(outdir), tree(outdir), layout(outdir)), err


def run_oracle(fixture: Path, outdir: Path) -> Observed:
    obs, _ = observe([sys.executable, str(APP / "reference_model" / "localflow_ref.py"), str(fixture), str(outdir)],
                     outdir)
    return obs


def run_localflow(fixture: Path, outdir: Path, schedule_args=()):
    return observe([sys.executable, "-m", "lang", "run", "--clock=virtual", "--quiet-warnings", *schedule_args,
                    str(APP / "src" / "main.lang"), str(fixture), str(outdir)], outdir)
