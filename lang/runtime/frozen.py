"""Transitive frozenness of runtime values (V3 5.1.1-3).

Frozen records and frozen collections only ever contain frozen values (enforced at
construction), so checking them is O(1). Variants and tuples may contain mutable
values (they are then not value-like), so they are checked by recursion over their
(small, immutable) payloads. Closures are frozen when every capture is effectively
constant and holds a frozen value.
"""
from __future__ import annotations

from .values import (UNIT, Borrow, BoundMethod, Builtin, BuiltinBound, Closure, Duration, FrozenList, FrozenMap,
                     FrozenRecord, FrozenSet, Instant, ModuleValue, MutableList, MutableMap, MutableRecord,
                     MutableSet, Namespace, RangeValue, TupleValue, TypeValue, UnitType, VariantValue)

_ALWAYS = (bool, int, float, str, UnitType, FrozenRecord, FrozenList, FrozenMap, FrozenSet, Duration, Instant,
           RangeValue, TypeValue, Builtin, ModuleValue, Namespace)


def is_frozen(v) -> bool:
    t = type(v)
    if t in _ALWAYS:
        return True
    if t is VariantValue or t is TupleValue:
        items = v.values if t is VariantValue else v.items
        return all(is_frozen(x) for x in items)
    if t is Closure:
        return closure_is_frozen(v)
    if t is BuiltinBound:
        return is_frozen(v.receiver)
    if t is BoundMethod:
        return is_frozen(v.receiver)
    if t in (MutableRecord, MutableList, MutableMap, MutableSet, Borrow):
        return False
    f = getattr(v, "lang_frozen", None)
    if f is not None:
        return f() if callable(f) else bool(f)
    return False


def closure_is_frozen(c: Closure) -> bool:
    caps = c.decl.ann.get("captures") if hasattr(c.decl, "ann") else None
    if caps is None:
        return c.env is None or c.env.kind in ("module", "prelude")
    for name, reassigned in caps:
        if reassigned:
            return False
        e = c.env.find(name) if c.env is not None else None
        if e is None:
            continue
        if e.kind in ("module", "prelude"):
            continue
        if not is_frozen(e.vars[name]):
            return False
    return True


def captures_borrow(v) -> bool:
    """True for a closure that captures a resource borrow (it is borrow-like and must
    not outlive the scope; V3 5.5.5, BUG-0029)."""
    if type(v) is not Closure:
        return False
    caps = v.decl.ann.get("captures") if hasattr(v.decl, "ann") else None
    if not caps or v.env is None:
        return False
    for name, _ in caps:
        e = v.env.find(name)
        if e is not None and type(e.vars.get(name)) is Borrow:
            return True
    return False
