"""std.json: parse to dynamic frozen values; deterministic stringify.

JSON object -> frozen Map[Str, Dyn] (key order preserved), array -> List[Dyn],
integral number -> Int, other number -> Float, string -> Str, true/false -> Bool,
null -> None. Malformed input throws the recoverable `JsonError` (category Data).
"""
from __future__ import annotations

import json
import math

from ..core_types import JSON_ERROR, NONE, OPTION, make_error
from ..equality import hash_key, type_name
from ..signals import Fault, Thrown
from ..values import (FrozenList, FrozenMap, FrozenRecord, MutableList, MutableMap, MutableRecord, TupleValue,
                      VariantValue, FrozenSet, MutableSet)
from .common import want_int, want_str
from .registry import module_fn


def _to_value(x):
    if x is None:
        return NONE
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return x
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return FrozenList(tuple(_to_value(i) for i in x))
    if isinstance(x, dict):
        return FrozenMap({hash_key(k): (k, _to_value(v)) for k, v in x.items()})
    raise Fault("A.RUNTIME.UNREACHABLE", "unexpected JSON value")


@module_fn("std.json", "parse", 1, sig="fn(Str) -> Dyn throws JsonError", effect=frozenset({"core.JsonError"}))
def _parse(interp, args, span):
    text = want_str(args[0], "text")

    def bad_const(name):
        raise ValueError(f"invalid constant {name}")
    try:
        data = json.loads(text, parse_constant=bad_const)
    except json.JSONDecodeError as e:
        err = make_error(JSON_ERROR, message=e.msg, line=e.lineno, column=e.colno)
        raise Thrown(err, interp.new_provenance(span))
    except ValueError as e:
        err = make_error(JSON_ERROR, message=str(e), line=0, column=0)
        raise Thrown(err, interp.new_provenance(span))
    except RecursionError:
        err = make_error(JSON_ERROR, message="nesting too deep", line=0, column=0)
        raise Thrown(err, interp.new_provenance(span))
    return _to_value(data)


def _to_py(v, depth=0):
    if depth > 200:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "value nesting too deep for JSON")
    t = type(v)
    if t is bool or t is int or t is str:
        return v
    if t is float:
        if not math.isfinite(v):
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", "JSON cannot represent NaN or Infinity")
        return v
    if t in (FrozenList, MutableList, TupleValue):
        return [_to_py(x, depth + 1) for x in v.items]
    if t in (FrozenSet, MutableSet):
        return [_to_py(x, depth + 1) for x in v.data.values()]
    if t in (FrozenMap, MutableMap):
        out = {}
        for k, x in v.data.values():
            if type(k) is not str:
                raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"JSON object keys must be Str, found {type_name(k)}")
            out[k] = _to_py(x, depth + 1)
        return out
    if t in (FrozenRecord, MutableRecord):
        return {f.name: _to_py(x, depth + 1) for f, x in zip(v.rtype.fields, v.values)}
    if t is VariantValue:
        if v.case.etype is OPTION:
            return None if v.case.name == "None" else _to_py(v.values[0], depth + 1)
        if v.case.fields is None:
            return v.case.name
        raise Fault("A.RUNTIME.INVALID_ARGUMENT",
                    f"cannot serialise variant {v.case.qualname} with payload to JSON; convert it explicitly")
    raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"cannot serialise {type_name(v)} to JSON")


@module_fn("std.json", "stringify", 1, 2, sig="fn(Dyn, Int) -> Str")
def _stringify(interp, args, span):
    data = _to_py(args[0])
    indent = None
    if len(args) > 1:
        indent = want_int(args[1], "indent")
        if indent < 0:
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", "indent must be non-negative")
    if indent is None:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return json.dumps(data, ensure_ascii=False, indent=indent, allow_nan=False)
