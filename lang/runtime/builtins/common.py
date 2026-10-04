"""Helpers shared by native builtins."""
from __future__ import annotations

from ..core_types import OPTION, RESULT
from ..equality import type_name
from ..frozen import is_frozen
from ..signals import Fault
from ..values import (Duration, FrozenList, FrozenMap, FrozenRecord, FrozenSet, Instant, MutableList, MutableMap,
                      MutableRecord, MutableSet, RangeValue, TupleValue, UnitType, VariantValue, Borrow)


def kind_of(v) -> str | None:
    t = type(v)
    if t is int:
        return "Int"
    if t is float:
        return "Float"
    if t is str:
        return "Str"
    if t is bool:
        return "Bool"
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
        return "Tuple"
    if t is RangeValue:
        return "Range"
    if t is Duration:
        return "Duration"
    if t is Instant:
        return "Instant"
    if t is UnitType:
        return "Unit"
    if t is VariantValue:
        et = v.case.etype
        if et is OPTION:
            return "Option"
        if et is RESULT:
            return "Result"
        return None
    if t is FrozenRecord:
        if v.rtype.qualname == "core.AggregateException":
            return "AggregateException"
        if v.rtype.qualname == "core.TaskGroupReport":
            return "TaskGroupReport"
        return None
    return getattr(t, "lang_kind", None)


def want_int(v, what: str = "argument") -> int:
    if type(v) is not int:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"{what} must be an Int, found {type_name(v)}",
                    expected="Int", found=type_name(v))
    return v


def want_float(v, what: str = "argument") -> float:
    if type(v) is not float:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"{what} must be a Float, found {type_name(v)}",
                    expected="Float", found=type_name(v),
                    help="convert explicitly with `toFloat()`" if type(v) is int else None)
    return v


def want_str(v, what: str = "argument") -> str:
    if type(v) is not str:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"{what} must be a Str, found {type_name(v)}",
                    expected="Str", found=type_name(v), help="use interpolation \"{x}\" to build strings")
    return v


def want_bool(v, what: str = "callback result") -> bool:
    if type(v) is not bool:
        raise Fault("A.TYPE.NON_BOOL_CONDITION", f"{what} must be a Bool, found {type_name(v)}",
                    expected="Bool", found=type_name(v))
    return v


def want_frozen_element(v, container: str):
    if type(v) is Borrow:
        raise Fault("A.RESOURCE.ESCAPE", f"a resource borrow cannot be stored in a {container}",
                    help="resources stay inside their `use` scope; store derived data instead")
    if not is_frozen(v):
        raise Fault("A.TYPE.FROZEN_MUTATION",
                    f"a frozen {container} may only contain frozen values, found mutable {type_name(v)}",
                    help="freeze the value first (`.freeze()`), or use a Mutable collection")
    return v


def no_borrow(v, container: str):
    if type(v) is Borrow:
        raise Fault("A.RESOURCE.ESCAPE", f"a resource borrow cannot be stored in a {container}",
                    help="resources stay inside their `use` scope; store derived data instead")
    return v


def index_check(i, n: int, what: str = "index") -> int:
    i = want_int(i, what)
    if i < 0 or i >= n:
        raise Fault("A.INDEX.OUT_OF_RANGE", f"{what} {i} is out of range for length {n}",
                    help="use `.get(i)` for a checked alternative returning an Option"
                         + ("; negative indices are not supported" if i < 0 else ""),
                    values={"index": str(i), "length": str(n)})
    return i


def check_arity(name: str, args: list, lo: int, hi: int | None) -> None:
    hi = lo if hi is None else hi
    if not (lo <= len(args) <= hi):
        want = str(lo) if lo == hi else f"{lo}..{hi}"
        raise Fault("A.TYPE.ARITY", f"`{name}` expects {want} argument(s), got {len(args)}")
