"""Prelude functions available without import."""
from __future__ import annotations

from ..equality import compare, display, type_name
from ..signals import Fault
from ..values import UNIT
from .common import want_str
from .registry import prelude


@prelude("print", 0, 10**9, sig="fn(Dyn...) -> Unit")
def _print(interp, args, span):
    interp.write_out(" ".join(display(a) for a in args) + "\n")
    return UNIT


@prelude("eprint", 0, 10**9, sig="fn(Dyn...) -> Unit")
def _eprint(interp, args, span):
    interp.write_err(" ".join(display(a) for a in args) + "\n")
    return UNIT


@prelude("min", 2, sig="fn(T, T) -> T", contract_safe=True)
def _min(interp, args, span):
    a, b = args
    return b if compare(b, a) < 0 else a


@prelude("max", 2, sig="fn(T, T) -> T", contract_safe=True)
def _max(interp, args, span):
    a, b = args
    return b if compare(b, a) > 0 else a


@prelude("typeName", 1, sig="fn(Dyn) -> Str", contract_safe=True)
def _type_name(interp, args, span):
    return type_name(args[0])


@prelude("unreachable", 0, 1, sig="fn(Str) -> Never")
def _unreachable(interp, args, span):
    msg = want_str(args[0], "message") if args else "reached code marked unreachable"
    raise Fault("A.RUNTIME.UNREACHABLE", msg)
