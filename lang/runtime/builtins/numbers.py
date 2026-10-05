"""Int / Float / Bool / Duration / Instant methods (V3 7.3.3; SPEC-010)."""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from ..core_types import NONE, some
from ..equality import float_repr
from ..signals import Fault
from ..values import Duration, Instant
from .common import want_float, want_int
from .registry import method, prop, static

NS = 1_000_000_000


# ---------------------------------------------------------------- Int
@method("Int", "toFloat", 0, sig="fn() -> Float", contract_safe=True)
def _i_to_float(interp, recv, args, span):
    try:
        return float(recv)
    except OverflowError:
        raise Fault("A.NUMERIC.INVALID_CONVERSION", "Int too large to convert to Float")


@method(["Int", "Float", "Bool"], "toStr", 0, sig="fn() -> Str", contract_safe=True)
def _to_str(interp, recv, args, span):
    from ..equality import float_repr, display
    return display(recv)


@method("Int", "abs", 0, sig="fn() -> Int", contract_safe=True)
def _i_abs(interp, recv, args, span):
    return abs(recv)


@method("Int", "div", 1, sig="fn(Int) -> Int", contract_safe=True)
def _i_div(interp, recv, args, span):
    b = want_int(args[0], "divisor")
    if b == 0:
        raise Fault("A.NUMERIC.DIVISION_BY_ZERO", "integer division by zero",
                    help="use `checkedDiv` for a checked alternative returning Int?")
    return recv // b


@method("Int", "checkedDiv", 1, sig="fn(Int) -> Int?", contract_safe=True)
def _i_checked_div(interp, recv, args, span):
    b = want_int(args[0], "divisor")
    return NONE if b == 0 else some(recv // b)


@method("Int", "rem", 1, sig="fn(Int) -> Int", contract_safe=True)
def _i_rem(interp, recv, args, span):
    b = want_int(args[0], "divisor")
    if b == 0:
        raise Fault("A.NUMERIC.DIVISION_BY_ZERO", "integer remainder by zero")
    return recv % b


@method("Int", "pow", 1, sig="fn(Int) -> Int", contract_safe=True)
def _i_pow(interp, recv, args, span):
    e = want_int(args[0], "exponent")
    if e < 0:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "negative exponent for Int.pow",
                    help="convert to Float for fractional powers")
    if e > 100_000:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "exponent too large")
    return recv ** e


@method(["Int", "Float"], "min", 1, sig="fn(Self) -> Self", contract_safe=True)
def _min(interp, recv, args, span):
    o = args[0]
    if type(o) is not type(recv):
        raise Fault("A.TYPE.OPERAND_MISMATCH", "min() requires two values of the same numeric type")
    return o if o < recv else recv


@method(["Int", "Float"], "max", 1, sig="fn(Self) -> Self", contract_safe=True)
def _max(interp, recv, args, span):
    o = args[0]
    if type(o) is not type(recv):
        raise Fault("A.TYPE.OPERAND_MISMATCH", "max() requires two values of the same numeric type")
    return o if o > recv else recv


@method(["Int", "Float"], "clamp", 2, sig="fn(Self, Self) -> Self", contract_safe=True)
def _clamp(interp, recv, args, span):
    lo, hi = args
    if type(lo) is not type(recv) or type(hi) is not type(recv):
        raise Fault("A.TYPE.OPERAND_MISMATCH", "clamp() bounds must match the receiver type")
    if lo > hi:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "clamp() requires lo <= hi")
    return max(lo, min(hi, recv))


@method("Int", "isEven", 0, sig="fn() -> Bool", contract_safe=True)
def _even(interp, recv, args, span):
    return recv % 2 == 0


for _unit, _mult in (("nanos", 1), ("micros", 1000), ("millis", 1_000_000), ("seconds", NS), ("minutes", 60 * NS),
                     ("hours", 3600 * NS)):
    def _mk(mult):
        def _p(interp, recv):
            return Duration(recv * mult)
        return _p
    prop("Int", _unit, "Duration")(_mk(_mult))


# ---------------------------------------------------------------- Float
def _to_int_checked(f: float, how: str) -> int:
    if f != f or f in (math.inf, -math.inf):
        raise Fault("A.NUMERIC.INVALID_CONVERSION", f"cannot convert {float_repr(f)} to Int ({how})",
                    help="check `isFinite()` first")
    return int(f)


def round_half_away(f: float, digits: int = 0) -> Decimal:
    """Round the exact binary value half away from zero (SPEC-010; BUG-0045)."""
    return Decimal(f).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


@method("Float", "toInt", 0, sig="fn() -> Int", contract_safe=True)
def _f_to_int(interp, recv, args, span):
    return _to_int_checked(math.trunc(recv) if math.isfinite(recv) else recv, "truncation")


@method("Float", "round", 0, sig="fn() -> Int", contract_safe=True)
def _f_round(interp, recv, args, span):
    if not math.isfinite(recv):
        _to_int_checked(recv, "round")
    return int(round_half_away(recv))


@method("Float", "floor", 0, sig="fn() -> Int", contract_safe=True)
def _f_floor(interp, recv, args, span):
    if not math.isfinite(recv):
        _to_int_checked(recv, "floor")
    return math.floor(recv)


@method("Float", "ceil", 0, sig="fn() -> Int", contract_safe=True)
def _f_ceil(interp, recv, args, span):
    if not math.isfinite(recv):
        _to_int_checked(recv, "ceil")
    return math.ceil(recv)


@method("Float", "roundTo", 1, sig="fn(Int) -> Float", contract_safe=True)
def _f_round_to(interp, recv, args, span):
    d = want_int(args[0], "digits")
    if not math.isfinite(recv):
        return recv
    return float(round_half_away(recv, d))


@method("Float", "abs", 0, sig="fn() -> Float", contract_safe=True)
def _f_abs(interp, recv, args, span):
    return abs(recv)


@method("Float", "sqrt", 0, sig="fn() -> Float", contract_safe=True)
def _f_sqrt(interp, recv, args, span):
    return math.sqrt(recv) if recv >= 0 else math.nan


@method("Float", "pow", 1, sig="fn(Float) -> Float", contract_safe=True)
def _f_pow(interp, recv, args, span):
    e = want_float(args[0], "exponent")
    try:
        r = recv ** e
    except (OverflowError, ZeroDivisionError):
        return math.inf
    if isinstance(r, complex):
        return math.nan
    return r


@method("Float", "isNaN", 0, sig="fn() -> Bool", contract_safe=True)
def _f_isnan(interp, recv, args, span):
    return recv != recv


@method("Float", "isFinite", 0, sig="fn() -> Bool", contract_safe=True)
def _f_isfinite(interp, recv, args, span):
    return math.isfinite(recv)


# ---------------------------------------------------------------- Duration / Instant
@prop("Duration", "nanos", "Int")
def _d_nanos(interp, recv):
    return recv.nanos


@prop("Duration", "millis", "Int")
def _d_millis(interp, recv):
    return recv.nanos // 1_000_000


@prop("Duration", "seconds", "Float")
def _d_seconds(interp, recv):
    return recv.nanos / NS


@prop("Instant", "nanos", "Int")
def _i_nanos(interp, recv):
    return recv.nanos


@method("Instant", "since", 1, sig="fn(Instant) -> Duration", contract_safe=True)
def _i_since(interp, recv, args, span):
    o = args[0]
    if type(o) is not Instant:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "since() expects an Instant")
    return Duration(recv.nanos - o.nanos)


for _unit, _mult in (("nanos", 1), ("micros", 1000), ("millis", 1_000_000), ("seconds", NS), ("minutes", 60 * NS),
                     ("hours", 3600 * NS)):
    def _mk_s(mult, unit):
        def _s(interp, args, span, tv=None):
            n = args[0]
            if type(n) is int:
                return Duration(n * mult)
            if type(n) is float:
                if not math.isfinite(n):
                    raise Fault("A.NUMERIC.INVALID_CONVERSION", f"Duration.{unit} requires a finite number")
                return Duration(round(n * mult))
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"Duration.{unit} expects Int or Float")
        return _s
    static("Duration", _unit, 1, sig="fn(Dyn) -> Duration")(_mk_s(_mult, _unit))


@static("Duration", "zero", 0, sig="fn() -> Duration")
def _d_zero(interp, args, span, tv=None):
    return Duration(0)
