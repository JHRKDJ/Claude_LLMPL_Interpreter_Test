"""Language-level equality, hashing, ordering, type names and display.

None of these delegate to Python's `==`, `hash`, `<` or `repr` for language values:
Python would equate 1 and 1.0 and True and 1, and would call user-visible dunder
methods. These functions are total over runtime values and raise `Fault` for
operations the language rejects (mixed Int/Float comparison, unhashable keys, NaN keys).
"""
from __future__ import annotations

import math

from .signals import Fault
from .values import (UNIT, Builtin, BuiltinBound, BoundMethod, Closure, Duration, EnumType, FrozenList,
                     FrozenMap, FrozenRecord, FrozenSet, Instant, ModuleValue, MutableList, MutableMap,
                     MutableRecord, MutableSet, Namespace, RangeValue, RecordType, TupleValue, TypeValue,
                     UnitType, VariantValue)


# ----------------------------------------------------------------------------- type names
def type_name(v) -> str:
    t = type(v)
    if t is bool:
        return "Bool"
    if t is int:
        return "Int"
    if t is float:
        return "Float"
    if t is str:
        return "Str"
    if t is UnitType:
        return "Unit"
    if t is FrozenRecord or t is MutableRecord:
        return v.rtype.name
    if t is VariantValue:
        return v.case.etype.name
    if t is FrozenList:
        return "List"
    if t is MutableList:
        return "MutableList"
    if t is FrozenMap:
        return "Map"
    if t is MutableMap:
        return "MutableMap"
    if t is FrozenSet:
        return "Set"
    if t is MutableSet:
        return "MutableSet"
    if t is TupleValue:
        return "(" + ", ".join(type_name(x) for x in v.items) + ")"
    if t is RangeValue:
        return "Range"
    if t is Duration:
        return "Duration"
    if t is Instant:
        return "Instant"
    if t in (Closure, BoundMethod, Builtin, BuiltinBound):
        return "Function"
    if t is TypeValue:
        return "Type"
    if t is ModuleValue:
        return "Module"
    if t is Namespace:
        return "Namespace"
    name = getattr(v, "lang_type_name", None)
    if name:
        return name() if callable(name) else name
    return t.__name__


# ----------------------------------------------------------------------------- equality
_STRUCTURAL = (FrozenRecord, VariantValue, TupleValue, FrozenList, FrozenMap)


def lang_eq(a, b) -> bool:
    if a is b:
        t = type(a)
        if t is float:
            return a == a  # NaN != NaN (IEEE)
        if t not in _STRUCTURAL:
            return True
        # frozen values have no observable identity: compare structurally even when
        # both sides are the same object (a contained NaN makes them unequal; BUG-0020)
    ta, tb = type(a), type(b)
    if ta is not tb:
        if (ta is int and tb is float) or (ta is float and tb is int):
            raise Fault("A.TYPE.OPERAND_MISMATCH",
                        f"cannot compare Int with Float using == (no implicit numeric coercion)",
                        help="convert explicitly, e.g. `x.toFloat() == y` or `x == y.toInt()`")
        return False
    if ta in (int, str, bool, float):
        return a == b
    if ta is FrozenRecord:
        if a.rtype is not b.rtype:
            return False
        return _seq_eq(a.values, b.values)
    if ta is VariantValue:
        if a.case is not b.case:
            return False
        return _seq_eq(a.values, b.values)
    if ta is TupleValue or ta is FrozenList:
        return len(a.items) == len(b.items) and _seq_eq(a.items, b.items)
    if ta is FrozenMap:
        if len(a.data) != len(b.data):
            return False
        for k, (_, va) in a.data.items():
            other = b.data.get(k)
            if other is None or not lang_eq(va, other[1]):
                return False
        return True
    if ta is FrozenSet:
        return a.data.keys() == b.data.keys()
    if ta is Duration or ta is Instant:
        return a.nanos == b.nanos
    if ta is RangeValue:
        return (a.lo, a.hi, a.inclusive) == (b.lo, b.hi, b.inclusive)
    if ta is UnitType:
        return True
    if ta is BoundMethod:
        return a.func is b.func and lang_eq(a.receiver, b.receiver) if not _identity(a.receiver) else (
            a.func is b.func and a.receiver is b.receiver)
    eqfn = getattr(a, "lang_eq", None)
    if eqfn is not None:
        return eqfn(b)
    # identity-bearing values (mutable records/collections, closures, capabilities)
    return False


def _identity(v) -> bool:
    return isinstance(v, (MutableRecord, MutableList, MutableMap, MutableSet))


def _seq_eq(xs, ys) -> bool:
    for x, y in zip(xs, ys):
        if not lang_eq(x, y):
            return False
    return True


# ----------------------------------------------------------------------------- hashing
def hash_key(v):
    """Python-hashable key whose equality coincides with language equality."""
    t = type(v)
    if t is int:
        return ("i", v)
    if t is str:
        return ("s", v)
    if t is bool:
        return ("b", v)
    if t is float:
        if v != v:
            raise Fault("A.NUMERIC.NAN_KEY", "NaN cannot be used as a map key or set element",
                        help="check `x.isNaN()` before inserting")
        return ("f", v)
    if t is UnitType:
        return ("u",)
    if t is FrozenRecord:
        if v._hash is None:
            v._hash = ("r", v.rtype.id, tuple(hash_key(x) for x in v.values))
        return v._hash
    if t is VariantValue:
        if v._hash is None:
            v._hash = ("v", v.case.etype.id, v.case.index, tuple(hash_key(x) for x in v.values))
        return v._hash
    if t is TupleValue:
        if v._hash is None:
            v._hash = ("t", tuple(hash_key(x) for x in v.items))
        return v._hash
    if t is FrozenList:
        if v._hash is None:
            v._hash = ("l", tuple(hash_key(x) for x in v.items))
        return v._hash
    if t is FrozenMap:
        if v._hash is None:
            v._hash = ("m", frozenset((k, hash_key(val)) for k, (_, val) in v.data.items()))
        return v._hash
    if t is FrozenSet:
        if v._hash is None:
            v._hash = ("S", frozenset(v.data.keys()))
        return v._hash
    if t is Duration:
        return ("D", v.nanos)
    if t is Instant:
        return ("I", v.nanos)
    if t is RangeValue:
        return ("R", v.lo, v.hi, v.inclusive)
    hk = getattr(v, "lang_hash_key", None)
    if hk is not None:
        return hk()
    raise Fault("A.TYPE.UNHASHABLE",
                f"a {type_name(v)} value cannot be a map key or set element (keys must be frozen values)",
                help="use a frozen value (e.g. `.freeze()` or an identifier field) as the key")


# ----------------------------------------------------------------------------- ordering
def compare(a, b) -> int:
    ta, tb = type(a), type(b)
    if ta is not tb:
        raise Fault("A.TYPE.OPERAND_MISMATCH",
                    f"cannot order {type_name(a)} and {type_name(b)}",
                    help="ordering requires two values of the same type" +
                         ("; convert explicitly with toFloat()/toInt()" if {ta, tb} == {int, float} else ""))
    if ta is int or ta is float or ta is str:
        if ta is float and (a != a or b != b):
            raise Fault("A.TYPE.OPERAND_MISMATCH", "NaN has no ordering", help="check `isNaN()` first")
        return -1 if a < b else (1 if a > b else 0)
    if ta is Duration or ta is Instant:
        return -1 if a.nanos < b.nanos else (1 if a.nanos > b.nanos else 0)
    if ta is TupleValue or ta is FrozenList:
        for x, y in zip(a.items, b.items):
            c = compare(x, y)
            if c:
                return c
        return (len(a.items) > len(b.items)) - (len(a.items) < len(b.items))
    if ta is MutableList:
        for x, y in zip(a.items, b.items):
            c = compare(x, y)
            if c:
                return c
        return (len(a.items) > len(b.items)) - (len(a.items) < len(b.items))
    raise Fault("A.TYPE.OPERAND_MISMATCH", f"values of type {type_name(a)} are not ordered",
                help="sort with an explicit key, e.g. `xs.sortedBy(fn(x) => x.name)`")


# ----------------------------------------------------------------------------- display
def float_repr(f: float) -> str:
    if f != f:
        return "NaN"
    if f == math.inf:
        return "Infinity"
    if f == -math.inf:
        return "-Infinity"
    r = repr(f)
    return r


def duration_repr(nanos: int) -> str:
    if nanos % 1_000_000_000 == 0:
        return f"{nanos // 1_000_000_000}s"
    if nanos % 1_000_000 == 0:
        return f"{nanos // 1_000_000}ms"
    if nanos % 1000 == 0:
        return f"{nanos // 1000}us"
    return f"{nanos}ns"


def quote_str(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch in "{}":
            out.append("\\" + ch)
        elif ord(ch) < 32:
            out.append(f"\\u{{{ord(ch):x}}}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def display(v) -> str:
    """Program-facing text conversion (print, interpolation). Never calls user code."""
    if type(v) is str:
        return v
    return repr_value(v)


def repr_value(v, _seen=None) -> str:
    t = type(v)
    if t is bool:
        return "true" if v else "false"
    if t is int:
        return str(v)
    if t is float:
        return float_repr(v)
    if t is str:
        return quote_str(v)
    if t is UnitType:
        return "()"
    if _seen is None:
        _seen = set()
    if t is FrozenRecord:
        inner = ", ".join(f"{f.name}: {repr_value(x, _seen)}" for f, x in zip(v.rtype.fields, v.values))
        return f"{v.rtype.name}({inner})"
    if t is MutableRecord:
        if v.id in _seen:
            return f"<cycle {v.rtype.name}#{v.id}>"
        _seen.add(v.id)
        inner = ", ".join(f"{f.name}: {repr_value(x, _seen)}" for f, x in zip(v.rtype.fields, v.values))
        _seen.discard(v.id)
        return f"{v.rtype.name}({inner})"
    if t is VariantValue:
        case = v.case
        et = case.etype
        core = et.qualname in ("core.Option", "core.Result")
        name = case.name if core else f"{et.name}.{case.name}"
        if case.fields is None:
            return name
        if core:
            return f"{name}(" + ", ".join(repr_value(x, _seen) for x in v.values) + ")"
        return f"{name}(" + ", ".join(f"{f.name}: {repr_value(x, _seen)}" for f, x in zip(case.fields, v.values)) + ")"
    if t is TupleValue:
        if len(v.items) == 1:
            return "(" + repr_value(v.items[0], _seen) + ",)"
        return "(" + ", ".join(repr_value(x, _seen) for x in v.items) + ")"
    if t is FrozenList:
        return "[" + ", ".join(repr_value(x, _seen) for x in v.items) + "]"
    if t is MutableList:
        if v.id in _seen:
            return "<cycle MutableList>"
        _seen.add(v.id)
        s = "MutableList[" + ", ".join(repr_value(x, _seen) for x in v.items) + "]"
        _seen.discard(v.id)
        return s
    if t is FrozenMap:
        return "{" + ", ".join(f"{repr_value(k, _seen)}: {repr_value(x, _seen)}" for k, x in v.data.values()) + "}"
    if t is MutableMap:
        if v.id in _seen:
            return "<cycle MutableMap>"
        _seen.add(v.id)
        s = "MutableMap{" + ", ".join(f"{repr_value(k, _seen)}: {repr_value(x, _seen)}" for k, x in v.data.values()) + "}"
        _seen.discard(v.id)
        return s
    if t is FrozenSet:
        return "Set{" + ", ".join(repr_value(x, _seen) for x in v.data.values()) + "}"
    if t is MutableSet:
        return "MutableSet{" + ", ".join(repr_value(x, _seen) for x in v.data.values()) + "}"
    if t is RangeValue:
        return f"{v.lo}..{'=' if v.inclusive else ''}{v.hi}"
    if t is Duration:
        return duration_repr(v.nanos)
    if t is Instant:
        return f"Instant({duration_repr(v.nanos)})"
    if t is Closure:
        return f"<fn {v.name}>"
    if t is BoundMethod:
        return f"<method {v.func.name}>"
    if t is Builtin:
        return f"<builtin {v.name}>"
    if t is BuiltinBound:
        return f"<builtin {v.builtin.name}>"
    if t is TypeValue:
        return f"<type {v.name}>"
    if t is ModuleValue:
        return f"<module {v.name}>"
    if t is Namespace:
        return f"<namespace {v.name}>"
    if isinstance(v, (RecordType, EnumType)):
        return f"<type {v.name}>"
    d = getattr(v, "lang_display", None)
    if d is not None:
        return d()
    return f"<{type(v).__name__}>"
