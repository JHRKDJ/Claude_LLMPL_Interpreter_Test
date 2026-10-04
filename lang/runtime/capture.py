"""Bounded, cycle-safe, side-effect-free, secret-aware value representation for
diagnostics (V3 7.13.4, 8.20).

Never calls user code. Limits depth, item count, string length and total size, and
reports truncation/redaction explicitly. Fields declared `sensitive` and names that
look like credentials are redacted.
"""
from __future__ import annotations

import re

from .equality import float_repr, quote_str, duration_repr
from .values import (UNIT, Closure, Duration, FrozenList, FrozenMap, FrozenRecord, FrozenSet, Instant, MutableList,
                     MutableMap, MutableRecord, MutableSet, RangeValue, TupleValue, UnitType, VariantValue,
                     BoundMethod, Builtin, BuiltinBound, TypeValue, UNINIT, Uninit)

SECRET_NAME = re.compile(r"(pass(word|wd|phrase)?|secret|token|api_?key|credential|auth|private_?key|session)",
                         re.IGNORECASE)
SECRET_VALUE = re.compile(r"^(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|xox[bp]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{10,}\.)")

MAX_DEPTH = 3
MAX_ITEMS = 8
MAX_STR = 80
MAX_TOTAL = 600


class Budget:
    __slots__ = ("left", "truncated", "redacted")

    def __init__(self, total: int = MAX_TOTAL):
        self.left = total
        self.truncated = False
        self.redacted = False


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME.search(name))


def safe_repr(v, budget: Budget | None = None, depth: int = 0, seen=None, name: str | None = None) -> str:
    if budget is None:
        budget = Budget()
    if seen is None:
        seen = set()
    if name is not None and is_secret_name(name) and v is not None and not isinstance(v, (bool, UnitType)):
        budget.redacted = True
        return "<redacted>"
    out = _repr(v, budget, depth, seen)
    budget.left -= len(out)
    return out


def _repr(v, budget: Budget, depth: int, seen) -> str:
    if budget.left <= 0:
        budget.truncated = True
        return "…"
    t = type(v)
    if t is bool:
        return "true" if v else "false"
    if t is int:
        s = str(v)
        if len(s) > MAX_STR:
            budget.truncated = True
            return s[:20] + f"…({len(s)} digits)"
        return s
    if t is float:
        return float_repr(v)
    if t is str:
        if SECRET_VALUE.match(v):
            budget.redacted = True
            return "<redacted>"
        if len(v) > MAX_STR:
            budget.truncated = True
            return quote_str(v[:MAX_STR]) + f"…({len(v)} chars)"
        return quote_str(v)
    if t is UnitType:
        return "()"
    if t is Uninit:
        return "<uninitialised>"
    if depth >= MAX_DEPTH:
        budget.truncated = True
        return _summary(v)
    if t in (FrozenRecord, MutableRecord):
        if t is MutableRecord:
            if v.id in seen:
                return f"<cycle {v.rtype.name}#{v.id}>"
            seen.add(v.id)
        parts = []
        for f, x in zip(v.rtype.fields, v.values):
            if f.sensitive or is_secret_name(f.name):
                budget.redacted = True
                parts.append(f"{f.name}: <redacted>")
            else:
                parts.append(f"{f.name}: {_repr(x, budget, depth + 1, seen)}")
            if len(parts) >= MAX_ITEMS:
                budget.truncated = True
                parts.append("…")
                break
        return f"{v.rtype.name}(" + ", ".join(parts) + ")"
    if t is VariantValue:
        case = v.case
        core = case.etype.qualname in ("core.Option", "core.Result")
        name = case.name if core else f"{case.etype.name}.{case.name}"
        if case.fields is None:
            return name
        inner = ", ".join(_repr(x, budget, depth + 1, seen) for x in v.values[:MAX_ITEMS])
        return f"{name}({inner})"
    if t in (FrozenList, MutableList, TupleValue):
        items = v.items
        if t is MutableList:
            if v.id in seen:
                return "<cycle MutableList>"
            seen.add(v.id)
        shown = [_repr(x, budget, depth + 1, seen) for x in list(items)[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            budget.truncated = True
            shown.append(f"… {len(items) - MAX_ITEMS} more (length {len(items)})")
        if t is TupleValue:
            return "(" + ", ".join(shown) + ")"
        return ("MutableList" if t is MutableList else "") + "[" + ", ".join(shown) + "]"
    if t in (FrozenMap, MutableMap):
        if t is MutableMap:
            if v.id in seen:
                return "<cycle MutableMap>"
            seen.add(v.id)
        entries = list(v.data.values())
        shown = []
        for k, x in entries[:MAX_ITEMS]:
            ks = _repr(k, budget, depth + 1, seen)
            if type(k) is str and is_secret_name(k):
                budget.redacted = True
                shown.append(f"{ks}: <redacted>")
            else:
                shown.append(f"{ks}: {_repr(x, budget, depth + 1, seen)}")
        if len(entries) > MAX_ITEMS:
            budget.truncated = True
            shown.append(f"… {len(entries) - MAX_ITEMS} more (size {len(entries)})")
        return ("MutableMap" if t is MutableMap else "") + "{" + ", ".join(shown) + "}"
    if t in (FrozenSet, MutableSet):
        items = list(v.data.values())
        shown = [_repr(x, budget, depth + 1, seen) for x in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            budget.truncated = True
            shown.append(f"… {len(items) - MAX_ITEMS} more")
        return ("MutableSet" if t is MutableSet else "Set") + "{" + ", ".join(shown) + "}"
    if t is RangeValue:
        return f"{v.lo}..{'=' if v.inclusive else ''}{v.hi}"
    if t is Duration:
        return duration_repr(v.nanos)
    if t is Instant:
        return f"Instant({duration_repr(v.nanos)})"
    if t is Closure:
        return f"<fn {v.name}>"
    if t in (BoundMethod, Builtin, BuiltinBound, TypeValue):
        return f"<{type(v).__name__.lower()}>"
    d = getattr(v, "lang_display", None)
    if d is not None:
        return d()
    return f"<{type(v).__name__}>"


def _summary(v) -> str:
    t = type(v)
    if t in (FrozenList, MutableList, TupleValue):
        return f"<{t.__name__} length {len(v.items)}>"
    if t in (FrozenMap, MutableMap, FrozenSet, MutableSet):
        return f"<{t.__name__} size {len(v.data)}>"
    if t in (FrozenRecord, MutableRecord):
        return f"<{v.rtype.name}>"
    if t is VariantValue:
        return f"<{v.case.qualname}>"
    return "…"
