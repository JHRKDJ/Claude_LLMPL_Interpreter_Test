"""Str methods (V3 7.3.3: immutable Unicode, code-point indexing, no implicit
normalisation). No Python negative indexing or truthiness leaks."""
from __future__ import annotations

import unicodedata

from ..core_types import NONE, some
from ..signals import Fault
from ..values import FrozenList
from .common import want_int, want_str
from .registry import method, prop


@prop("Str", "length", "Int")
def _len(interp, recv):
    return len(recv)


@method("Str", "isEmpty", 0, sig="fn() -> Bool", contract_safe=True)
def _empty(interp, recv, args, span):
    return len(recv) == 0


@method("Str", "contains", 1, sig="fn(Str) -> Bool", contract_safe=True)
def _contains(interp, recv, args, span):
    return want_str(args[0]) in recv


@method("Str", "startsWith", 1, sig="fn(Str) -> Bool", contract_safe=True)
def _sw(interp, recv, args, span):
    return recv.startswith(want_str(args[0]))


@method("Str", "endsWith", 1, sig="fn(Str) -> Bool", contract_safe=True)
def _ew(interp, recv, args, span):
    return recv.endswith(want_str(args[0]))


@method("Str", "indexOf", 1, sig="fn(Str) -> Int?", contract_safe=True)
def _index_of(interp, recv, args, span):
    i = recv.find(want_str(args[0]))
    return NONE if i < 0 else some(i)


@method("Str", "split", 1, sig="fn(Str) -> List[Str]")
def _split(interp, recv, args, span):
    sep = want_str(args[0], "separator")
    if sep == "":
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "split separator must not be empty", help="use `.chars()`")
    return FrozenList(tuple(recv.split(sep)))


@method("Str", "splitWhitespace", 0, sig="fn() -> List[Str]")
def _split_ws(interp, recv, args, span):
    return FrozenList(tuple(recv.split()))


@method("Str", "lines", 0, sig="fn() -> List[Str]")
def _lines(interp, recv, args, span):
    return FrozenList(tuple(recv.splitlines()))


@method("Str", "trim", 0, sig="fn() -> Str")
def _trim(interp, recv, args, span):
    return recv.strip()


@method("Str", "trimStart", 0, sig="fn() -> Str")
def _trim_s(interp, recv, args, span):
    return recv.lstrip()


@method("Str", "trimEnd", 0, sig="fn() -> Str")
def _trim_e(interp, recv, args, span):
    return recv.rstrip()


@method("Str", "toUpper", 0, sig="fn() -> Str")
def _upper(interp, recv, args, span):
    return recv.upper()


@method("Str", "toLower", 0, sig="fn() -> Str")
def _lower(interp, recv, args, span):
    return recv.lower()


@method("Str", "replace", 2, sig="fn(Str, Str) -> Str")
def _replace(interp, recv, args, span):
    return recv.replace(want_str(args[0]), want_str(args[1]))


@method("Str", "chars", 0, sig="fn() -> List[Str]")
def _chars(interp, recv, args, span):
    return FrozenList(tuple(recv))


@method("Str", "slice", 2, sig="fn(Int, Int) -> Str")
def _slice(interp, recv, args, span):
    a, b = want_int(args[0], "start"), want_int(args[1], "end")
    if not (0 <= a <= b <= len(recv)):
        raise Fault("A.INDEX.OUT_OF_RANGE", f"slice({a}, {b}) is out of range for Str of length {len(recv)}",
                    help="requires 0 <= start <= end <= length (code points)")
    return recv[a:b]


@method("Str", "charAt", 1, sig="fn(Int) -> Str?", contract_safe=True)
def _char_at(interp, recv, args, span):
    i = want_int(args[0], "index")
    return some(recv[i]) if 0 <= i < len(recv) else NONE


@method("Str", "repeat", 1, sig="fn(Int) -> Str")
def _repeat(interp, recv, args, span):
    n = want_int(args[0], "count")
    if n < 0:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "repeat count must be non-negative")
    return recv * n


@method("Str", "toInt", 0, sig="fn() -> Int?")
def _to_int(interp, recv, args, span):
    s = recv.strip()
    if not s or not (s.lstrip("+-").isdigit()) or s.count("-") + s.count("+") > 1:
        return NONE
    if not s.lstrip("+-").isascii():
        return NONE
    return some(int(s))


@method("Str", "toFloat", 0, sig="fn() -> Float?")
def _to_float(interp, recv, args, span):
    s = recv.strip()
    import re
    if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s):
        return NONE
    return some(float(s))


@method("Str", "padStart", 2, sig="fn(Int, Str) -> Str")
def _pad_start(interp, recv, args, span):
    n = want_int(args[0], "width")
    ch = want_str(args[1], "fill")
    if len(ch) != 1:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "fill must be a single character")
    return recv.rjust(n, ch)


@method("Str", "padEnd", 2, sig="fn(Int, Str) -> Str")
def _pad_end(interp, recv, args, span):
    n = want_int(args[0], "width")
    ch = want_str(args[1], "fill")
    if len(ch) != 1:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "fill must be a single character")
    return recv.ljust(n, ch)


@method("Str", "normalized", 1, sig="fn(Str) -> Str")
def _normalized(interp, recv, args, span):
    form = want_str(args[0], "form")
    if form not in ("NFC", "NFD", "NFKC", "NFKD"):
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "normalization form must be NFC, NFD, NFKC or NFKD")
    return unicodedata.normalize(form, recv)


@method("Str", "codePoint", 0, sig="fn() -> Int")
def _code_point(interp, recv, args, span):
    if len(recv) != 1:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "codePoint() requires a single-character Str")
    return ord(recv)


@method("Str", "toStr", 0, sig="fn() -> Str", contract_safe=True)
def _to_str(interp, recv, args, span):
    return recv


@method("Str", "compareTo", 1, sig="fn(Str) -> Int", contract_safe=True)
def _cmp(interp, recv, args, span):
    o = want_str(args[0])
    return -1 if recv < o else (1 if recv > o else 0)
