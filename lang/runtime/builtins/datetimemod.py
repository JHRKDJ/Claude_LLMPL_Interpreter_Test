"""std.datetime: UTC calendar date-times (V3 6.14 standard library).

`DateTime` is a frozen record in UTC with millisecond precision; there are no time
zones beyond UTC offsets accepted on input (IMPL-007). `utcNow()` reads the host wall
clock and is therefore the one nondeterministic function here; scheduling and
deadlines always use the monotonic `time.now()` (`Instant`) instead.
Malformed input throws the recoverable `FormatError` (category Data).
"""
from __future__ import annotations

import datetime as _dt

from ..core_types import DATE_TIME, FORMAT_ERROR, make_error
from ..signals import Thrown
from ..values import FrozenRecord
from .common import want_int, want_str
from .registry import module_fn

_EFFECT = frozenset({"core.FormatError"})
_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _value(d: _dt.datetime) -> FrozenRecord:
    d = d.astimezone(_dt.timezone.utc)
    return make_error(DATE_TIME, year=d.year, month=d.month, day=d.day, hour=d.hour, minute=d.minute,
                      second=d.second, millis=d.microsecond // 1000)


def _py(v, interp, span) -> _dt.datetime:
    if type(v) is not FrozenRecord or v.rtype is not DATE_TIME:
        from ..signals import Fault
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "expected a DateTime")
    f = dict(zip((x.name for x in DATE_TIME.fields), v.values))
    try:
        return _dt.datetime(f["year"], f["month"], f["day"], f["hour"], f["minute"], f["second"],
                            f["millis"] * 1000, tzinfo=_dt.timezone.utc)
    except ValueError as e:
        from ..signals import Fault
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"invalid DateTime: {e}")


def _bad(interp, span, text, expected):
    raise Thrown(make_error(FORMAT_ERROR, input=text, expected=expected), interp.new_provenance(span))


@module_fn("std.datetime", "parseIso", 1, sig="fn(Str) -> DateTime throws FormatError", effect=_EFFECT)
def _parse_iso(interp, args, span):
    text = want_str(args[0], "text")
    try:
        d = _dt.datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError:
        _bad(interp, span, text, "ISO-8601 date or date-time, e.g. 2024-05-01T12:30:00Z")
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return _value(d)


@module_fn("std.datetime", "formatIso", 1, sig="fn(DateTime) -> Str")
def _format_iso(interp, args, span):
    d = _py(args[0], interp, span)
    s = d.strftime("%Y-%m-%dT%H:%M:%S")
    if d.microsecond:
        s += f".{d.microsecond // 1000:03d}"
    return s + "Z"


@module_fn("std.datetime", "date", 3, sig="fn(Int, Int, Int) -> DateTime throws FormatError", effect=_EFFECT)
def _date(interp, args, span):
    return _of(interp, list(args) + [0, 0, 0, 0], span)


@module_fn("std.datetime", "of", 7, sig="fn(Int, Int, Int, Int, Int, Int, Int) -> DateTime throws FormatError",
           effect=_EFFECT)
def _of(interp, args, span):
    parts = [want_int(a, "date-time component") for a in args]
    try:
        return _value(_dt.datetime(*parts[:6], parts[6] * 1000, tzinfo=_dt.timezone.utc))
    except ValueError as e:
        _bad(interp, span, "-".join(str(p) for p in parts), f"a valid calendar date-time ({e})")


@module_fn("std.datetime", "toEpochMillis", 1, sig="fn(DateTime) -> Int")
def _to_epoch(interp, args, span):
    d = _py(args[0], interp, span)
    delta = d - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


@module_fn("std.datetime", "fromEpochMillis", 1, sig="fn(Int) -> DateTime")
def _from_epoch(interp, args, span):
    ms = want_int(args[0], "epoch milliseconds")
    return _value(_EPOCH + _dt.timedelta(milliseconds=ms))


@module_fn("std.datetime", "addMillis", 2, sig="fn(DateTime, Int) -> DateTime")
def _add(interp, args, span):
    return _value(_py(args[0], interp, span) + _dt.timedelta(milliseconds=want_int(args[1], "milliseconds")))


@module_fn("std.datetime", "weekday", 1, sig="fn(DateTime) -> Str")
def _weekday(interp, args, span):
    return _WEEKDAYS[_py(args[0], interp, span).weekday()]


@module_fn("std.datetime", "utcNow", 0, sig="fn() -> DateTime")
def _utc_now(interp, args, span):
    return _value(_dt.datetime.now(_dt.timezone.utc))
