"""Option and Result methods (V3 5.4, 5.7, 7.3.4, 7.7.8; SPEC-012).

`Result.orThrow()` is the explicit Err -> exception conversion; it throws the Err's
error value with its stored provenance extended by the conversion site. `context`
attaches bounded explicit context to an Err's provenance (V3 7.7.8).
"""
from __future__ import annotations

from ..capture import Budget, safe_repr
from ..core_types import ERR_CASE, NONE, OK_CASE, OPTION, RESULT, SOME_CASE, err, ok, some
from ..equality import type_name
from ..signals import ErrorProvenance, Fault, Thrown
from ..values import VariantValue
from .common import want_bool, want_str
from .registry import method

MAX_CONTEXT = 16


def _is_some(v):
    return v.case is SOME_CASE


@method("Option", "isSome", 0, sig="fn() -> Bool", contract_safe=True)
def _is_some_m(interp, recv, args, span):
    return recv.case is SOME_CASE


@method("Option", "isNone", 0, sig="fn() -> Bool", contract_safe=True)
def _is_none_m(interp, recv, args, span):
    return recv.case is not SOME_CASE


@method("Option", "unwrap", 0, sig="fn() -> T")
def _unwrap(interp, recv, args, span):
    if recv.case is SOME_CASE:
        return recv.values[0]
    raise Fault("A.OPTION.UNWRAP_NONE", "unwrap() called on None",
                help="match on the Option, or use `unwrapOr(default)`")


@method("Option", "expect", 1, sig="fn(Str) -> T")
def _expect(interp, recv, args, span):
    if recv.case is SOME_CASE:
        return recv.values[0]
    raise Fault("A.OPTION.UNWRAP_NONE", f"expect() failed on None: {want_str(args[0], 'message')}")


@method("Option", "unwrapOr", 1, sig="fn(T) -> T", contract_safe=True)
def _unwrap_or(interp, recv, args, span):
    return recv.values[0] if recv.case is SOME_CASE else args[0]


@method("Option", "unwrapOrElse", 1, sig="fn(fn() -> T throws E) -> T throws E")
def _unwrap_or_else(interp, recv, args, span):
    return recv.values[0] if recv.case is SOME_CASE else interp.call_value(args[0], [], None, span)


@method("Option", "map", 1, sig="fn(fn(T) -> U throws E) -> U? throws E")
def _opt_map(interp, recv, args, span):
    if recv.case is SOME_CASE:
        return some(interp.call_value(args[0], [recv.values[0]], None, span))
    return NONE


@method("Option", "flatMap", 1, sig="fn(fn(T) -> U? throws E) -> U? throws E")
def _opt_flat_map(interp, recv, args, span):
    if recv.case is SOME_CASE:
        r = interp.call_value(args[0], [recv.values[0]], None, span)
        if not (type(r) is VariantValue and r.case.etype is OPTION):
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"flatMap callback must return an Option, found {type_name(r)}")
        return r
    return NONE


@method("Option", "filter", 1, sig="fn(fn(T) -> Bool throws E) -> T? throws E")
def _opt_filter(interp, recv, args, span):
    if recv.case is SOME_CASE and want_bool(interp.call_value(args[0], [recv.values[0]], None, span)):
        return recv
    return NONE


@method("Option", "or", 1, sig="fn(T?) -> T?", contract_safe=True)
def _opt_or(interp, recv, args, span):
    return recv if recv.case is SOME_CASE else args[0]


@method("Option", "okOr", 1, sig="fn(E) -> Result[T, E]")
def _ok_or(interp, recv, args, span):
    if recv.case is SOME_CASE:
        return ok(recv.values[0])
    return err(args[0], interp.new_provenance(span))


# ---------------------------------------------------------------- Result
@method("Result", "isOk", 0, sig="fn() -> Bool", contract_safe=True)
def _is_ok(interp, recv, args, span):
    return recv.case is OK_CASE


@method("Result", "isErr", 0, sig="fn() -> Bool", contract_safe=True)
def _is_err(interp, recv, args, span):
    return recv.case is ERR_CASE


@method("Result", "unwrap", 0, sig="fn() -> T")
def _r_unwrap(interp, recv, args, span):
    if recv.case is OK_CASE:
        return recv.values[0]
    raise Fault("A.RESULT.UNWRAP_ERR", f"unwrap() called on Err({safe_repr(recv.values[0], Budget(200))})",
                help="match on the Result, use `unwrapOr`, or convert with `try r.orThrow()`")


@method("Result", "unwrapOr", 1, sig="fn(T) -> T", contract_safe=True)
def _r_unwrap_or(interp, recv, args, span):
    return recv.values[0] if recv.case is OK_CASE else args[0]


@method("Result", "ok", 0, sig="fn() -> T?", contract_safe=True)
def _r_ok(interp, recv, args, span):
    return some(recv.values[0]) if recv.case is OK_CASE else NONE


@method("Result", "err", 0, sig="fn() -> E?", contract_safe=True)
def _r_err(interp, recv, args, span):
    return some(recv.values[0]) if recv.case is ERR_CASE else NONE


@method("Result", "map", 1, sig="fn(fn(T) -> U throws X) -> Result[U, E] throws X")
def _r_map(interp, recv, args, span):
    if recv.case is OK_CASE:
        return ok(interp.call_value(args[0], [recv.values[0]], None, span))
    return recv


@method("Result", "mapErr", 1, sig="fn(fn(E) -> F throws X) -> Result[T, F] throws X")
def _r_map_err(interp, recv, args, span):
    if recv.case is ERR_CASE:
        prov = recv.prov.copy() if recv.prov else interp.new_provenance(span)
        return err(interp.call_value(args[0], [recv.values[0]], None, span), prov)
    return recv


@method("Result", "orThrow", 0, sig="fn() -> T throws E")
def _or_throw(interp, recv, args, span):
    if recv.case is OK_CASE:
        return recv.values[0]
    prov = recv.prov.copy() if recv.prov is not None else interp.new_provenance(span)
    prov.chain.append(span)
    interp.check_throwable(recv.values[0], span)
    raise Thrown(recv.values[0], prov)


@method("Result", "context", 2, sig="fn(Str, Dyn) -> Result[T, E]")
def _context(interp, recv, args, span):
    if recv.case is OK_CASE:
        return recv
    key = want_str(args[0], "context key")
    prov = recv.prov.copy() if recv.prov is not None else interp.new_provenance(span)
    if len(prov.context) < MAX_CONTEXT:
        prov.context.append((key, safe_repr(args[1], Budget(200), name=key)))
    return VariantValue(ERR_CASE, recv.values, prov)
