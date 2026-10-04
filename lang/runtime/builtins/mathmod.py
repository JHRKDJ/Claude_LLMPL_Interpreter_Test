"""std.math: Float helpers (IEEE semantics; see SPEC-010 NaN policy)."""
from __future__ import annotations

import math

from ..signals import Fault
from .common import want_float
from .registry import MODULES, module_fn

MODULES.setdefault("std.math", {})
MODULES["std.math"]["pi"] = math.pi
MODULES["std.math"]["e"] = math.e
MODULES["std.math"]["infinity"] = math.inf
MODULES["std.math"]["nan"] = math.nan


def _unary(name, fn, domain=None):
    def impl(interp, args, span):
        x = want_float(args[0], f"math.{name} argument")
        if domain is not None and not domain(x):
            return math.nan
        try:
            return fn(x)
        except OverflowError:
            return math.inf
    module_fn("std.math", name, 1, sig="fn(Float) -> Float")(impl)


_unary("sqrt", math.sqrt, lambda x: x >= 0)
_unary("ln", math.log, lambda x: x > 0)
_unary("log10", math.log10, lambda x: x > 0)
_unary("log2", math.log2, lambda x: x > 0)
_unary("exp", math.exp)
_unary("sin", math.sin, math.isfinite)
_unary("cos", math.cos, math.isfinite)
_unary("tan", math.tan, math.isfinite)
_unary("atan", math.atan)
_unary("abs", abs)


@module_fn("std.math", "pow", 2, sig="fn(Float, Float) -> Float")
def _pow(interp, args, span):
    a = want_float(args[0], "base")
    b = want_float(args[1], "exponent")
    try:
        r = a ** b
    except (OverflowError, ZeroDivisionError):
        return math.inf
    return math.nan if isinstance(r, complex) else r


@module_fn("std.math", "atan2", 2, sig="fn(Float, Float) -> Float")
def _atan2(interp, args, span):
    return math.atan2(want_float(args[0]), want_float(args[1]))


@module_fn("std.math", "gcd", 2, sig="fn(Int, Int) -> Int")
def _gcd(interp, args, span):
    a, b = args
    if type(a) is not int or type(b) is not int:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "gcd expects Int arguments")
    return math.gcd(a, b)
