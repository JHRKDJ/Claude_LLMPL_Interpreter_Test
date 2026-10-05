"""std.regex: regular expressions over Str (V3 6.14 standard library).

Patterns use Python `re` syntax: this is a documented leakage boundary of the
reference implementation (IMPL-007). Positions are code-point indices, like every
Str index. Matching is full-string for `matches` and leftmost-first elsewhere.
An invalid pattern throws the recoverable `PatternError` (category Data).
Replacement templates refer to groups as `$0`..`$9`; `$$` is a literal `$`.
"""
from __future__ import annotations

import re
from functools import lru_cache

from ..core_types import NONE, PATTERN_ERROR, REGEX_MATCH, make_error, some
from ..signals import Thrown
from ..values import FrozenList
from .common import want_str
from .registry import module_fn

_EFFECT = frozenset({"core.PatternError"})
_TEMPLATE = re.compile(r"\$(\$|\d)")


@lru_cache(maxsize=256)
def _compile_cached(pattern: str):
    return re.compile(pattern)


def _compile(interp, pattern, span):
    pattern = want_str(pattern, "pattern")
    try:
        return _compile_cached(pattern)
    except re.error as e:
        err = make_error(PATTERN_ERROR, pattern=pattern, message=e.msg, position=e.pos or 0)
        raise Thrown(err, interp.new_provenance(span))


def _match_value(m):
    groups = FrozenList(tuple(NONE if g is None else some(g) for g in m.groups()))
    return make_error(REGEX_MATCH, text=m.group(0), start=m.start(), end=m.end(), groups=groups)


@module_fn("std.regex", "matches", 2, sig="fn(Str, Str) -> Bool throws PatternError", effect=_EFFECT)
def _matches(interp, args, span):
    rx = _compile(interp, args[0], span)
    return rx.fullmatch(want_str(args[1], "text")) is not None


@module_fn("std.regex", "find", 2, sig="fn(Str, Str) -> RegexMatch? throws PatternError", effect=_EFFECT)
def _find(interp, args, span):
    rx = _compile(interp, args[0], span)
    m = rx.search(want_str(args[1], "text"))
    return NONE if m is None else some(_match_value(m))


@module_fn("std.regex", "findAll", 2, sig="fn(Str, Str) -> List[RegexMatch] throws PatternError", effect=_EFFECT)
def _find_all(interp, args, span):
    rx = _compile(interp, args[0], span)
    return FrozenList(tuple(_match_value(m) for m in rx.finditer(want_str(args[1], "text"))))


@module_fn("std.regex", "replace", 3, sig="fn(Str, Str, Str) -> Str throws PatternError", effect=_EFFECT)
def _replace(interp, args, span):
    rx = _compile(interp, args[0], span)
    template = want_str(args[2], "replacement")
    text = want_str(args[1], "text")

    def sub(m):
        def one(t):
            tok = t.group(1)
            if tok == "$":
                return "$"
            n = int(tok)
            if n > (rx.groups or 0):
                return t.group(0)
            return m.group(n) or ""
        return _TEMPLATE.sub(one, template)
    return rx.sub(sub, text)


@module_fn("std.regex", "split", 2, sig="fn(Str, Str) -> List[Str] throws PatternError", effect=_EFFECT)
def _split(interp, args, span):
    rx = _compile(interp, args[0], span)
    text = want_str(args[1], "text")
    out, pos = [], 0
    for m in rx.finditer(text):
        if m.end() == m.start() and m.start() in (0, len(text)):
            continue
        out.append(text[pos:m.start()])
        pos = m.end()
    out.append(text[pos:])
    return FrozenList(tuple(out))


@module_fn("std.regex", "escape", 1, sig="fn(Str) -> Str")
def _escape(interp, args, span):
    return re.escape(want_str(args[0], "text"))
