"""Static analysis: name resolution, gradual type checking, effects, exhaustiveness,
resources, concurrency rules, contracts, and the draft/verified severity policy.

`check(program, mode)` returns diagnostics. In draft mode verified-only obligations
are warnings (non-blocking); legality rules are errors in both modes (V3 5.15).
"""
from __future__ import annotations

from .resolve import resolve_program


def check(program, mode: str = "draft") -> list:
    diags = resolve_program(program, mode)
    from .typecheck import typecheck_program
    diags.extend(typecheck_program(program, mode, diags))
    return diags
