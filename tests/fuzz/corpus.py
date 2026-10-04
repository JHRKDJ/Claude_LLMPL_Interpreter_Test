"""Corpus of real programs: every program literal in the test suite (and example
sources), for formatter and parser fuzzing."""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=None)
def program_corpus() -> tuple[str, ...]:
    from lang.syntax.parser import parse_text
    found: list[str] = []
    seen = set()
    for py in sorted((ROOT / "tests").rglob("test_*.py")):
        if "fuzz" in py.parts:
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "fn " in node.value:
                src = node.value
                for prefix in ("", "error Bad { }\n"):
                    cand = prefix + src
                    if cand in seen:
                        continue
                    if parse_text(cand).ok:
                        seen.add(cand)
                        found.append(cand)
                        break
    for p in sorted(ROOT.glob("examples/**/*.lang")):
        text = p.read_text()
        if text not in seen and parse_text(text).ok:
            seen.add(text)
            found.append(text)
    return tuple(found)
