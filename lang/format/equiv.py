"""Structural AST equivalence ignoring source positions (formatter safety net)."""
from __future__ import annotations

import dataclasses

from ..source import Span
from ..syntax import ast as A

# `own_line`: moving a trailing comment onto its own line is canonicalisation, not a
# change (comment text and order are still compared; BUG-0040)
IGNORED = {"span", "id", "ann", "name_span", "end_span", "guard_span", "own_line"}


def _norm(x):
    # `-(3)` and `-3` denote the same literal (the parser folds adjacent `-<number>`)
    if isinstance(x, A.Unary) and x.op == "-" and isinstance(x.operand, A.Literal) and \
            x.operand.kind in ("int", "float"):
        return A.Literal(span=x.span, value=-x.operand.value, kind=x.operand.kind)
    return x


def ast_equal(a, b, path: str = "") -> str | None:
    """None if equivalent, else a description of the first difference."""
    a, b = _norm(a), _norm(b)
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and type(a) is not bool and type(b) is not bool:
            return None if a == b else f"{path}: {a!r} != {b!r}"
        return f"{path}: {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, Span):
        return None
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            r = ast_equal(x, y, f"{path}[{i}]")
            if r:
                return r
        return None
    if dataclasses.is_dataclass(a):
        if isinstance(a, A.If) and a.ann.get("block_expr") != b.ann.get("block_expr"):
            return f"{path}: block expression vs if"
        for f in dataclasses.fields(a):
            if f.name in IGNORED:
                continue
            r = ast_equal(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}")
            if r:
                return r
        return None
    if a != b:
        return f"{path}: {a!r} != {b!r}"
    return None
