"""Black-box harness: runs the oracle and LocalFlow (through the interpreter CLI) as
separate processes and returns only externally observable results."""
from __future__ import annotations

import json
import os
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
    files: dict


def strip_messages(x):
    if isinstance(x, dict):
        return {k: strip_messages(v) for k, v in x.items() if k != "message"}
    if isinstance(x, list):
        return [strip_messages(v) for v in x]
    return x


def snapshot(outdir: Path) -> dict:
    files = {}
    if outdir.exists():
        for p in sorted(outdir.rglob("*")):
            if p.is_file() and p.name != "report.json":
                files[str(p.relative_to(outdir))] = p.read_text(encoding="utf-8")
    return files


def observe(cmd, outdir: Path, timeout=600) -> Observed:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=str(ROOT))
    rep_path = outdir / "report.json"
    report = json.loads(rep_path.read_text(encoding="utf-8")) if rep_path.exists() else None
    return Observed(p.returncode, p.stdout, report, snapshot(outdir)), p.stderr


def run_oracle(fixture: Path, outdir: Path) -> Observed:
    obs, _ = observe([sys.executable, str(APP / "reference_model" / "localflow_ref.py"), str(fixture), str(outdir)],
                     outdir)
    return obs


def run_localflow(fixture: Path, outdir: Path, schedule_args=()):
    return observe([sys.executable, "-m", "lang", "run", "--clock=virtual", "--quiet-warnings", *schedule_args,
                    str(APP / "src" / "main.lang"), str(fixture), str(outdir)], outdir)
