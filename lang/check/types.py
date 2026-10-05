"""Static type utilities: consistency, unification, builtin signatures."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from .. import typesys as T
from ..source import SourceFile
from ..syntax.lexer import Lexer
from ..syntax.parser import ParseError, Parser

DYN = T.DYN
UNKNOWN_EFFECT = None  # effect value meaning "cannot be determined statically"

# Generic parameter names of builtin receiver kinds (used to read builtin method sigs)
KIND_PARAMS = {
    "List": ["T"], "MutableList": ["T"], "Set": ["T"], "MutableSet": ["T"], "Map": ["K", "V"],
    "MutableMap": ["K", "V"], "Option": ["T"], "Result": ["T", "E"], "Channel": ["T"], "SendPort": ["T"],
    "ReceivePort": ["T"], "Broadcast": ["T"], "PublishPort": ["T"], "Task": ["T", "E"],
}


def kind_of_type(t: T.Ty) -> Optional[str]:
    """Builtin method-table kind for a static type (mirrors runtime kind_of)."""
    if isinstance(t, T.TPrim):
        return {"Int": "Int", "Float": "Float", "Str": "Str", "Bool": "Bool", "Duration": "Duration",
                "Instant": "Instant", "Range": "Range", "Unit": "Unit"}.get(t.name)
    if isinstance(t, T.TCon):
        if t.name in ("TaskGroupReport",):
            return None
        return t.name
    if isinstance(t, T.TTuple):
        return "Tuple"
    if isinstance(t, T.TNominal) and t.qualname == "core.AggregateException":
        return "AggregateException"
    return None


@lru_cache(maxsize=None)
def parse_sig(sig: str):
    """Parse a builtin signature string (`fn(T) -> U throws E`, `async fn() -> T`,
    `fn(Str) yields File throws ...`) into a syntactic FnType (cached)."""
    text = sig.replace(" yields ", " -> ")
    variadic = "..." in text
    text = text.replace("...", "")
    sf = SourceFile("<sig>", text)
    lx = Lexer(sf)
    toks = lx.tokenize()
    p = Parser(sf, toks)
    p.nl = [True]
    try:
        t = p.parse_type()
    except ParseError:
        return None, variadic
    return t, variadic


def sig_type(sig: Optional[str], bindings: dict, resolve) -> tuple[Optional[T.TFn], bool]:
    """Instantiate a builtin signature with receiver bindings (e.g. T -> Int).
    Unbound single-letter names are generic variables."""
    if not sig:
        return None, False
    texpr, variadic = parse_sig(sig)
    if texpr is None:
        return None, variadic
    names = set()
    _collect_names(texpr, names)
    tparams = frozenset(n for n in names if (len(n) <= 2 and n[:1].isupper() and n not in T.PRIMS))
    tparams = tparams | frozenset({"Self"})
    try:
        ty = T.from_expr(texpr, resolve, tparams)
    except T.TypeConversionError:
        return None, variadic
    subst = dict(bindings)
    ty = T.substitute(ty, subst)
    return (ty if isinstance(ty, T.TFn) else None), variadic


def _collect_names(t, out: set) -> None:
    from ..syntax import ast as A
    if isinstance(t, A.TypeName):
        if len(t.path) == 1:
            out.add(t.path[0])
        for a in t.args:
            _collect_names(a, out)
    elif isinstance(t, A.OptionalType):
        _collect_names(t.inner, out)
    elif isinstance(t, A.TupleType):
        for i in t.items:
            _collect_names(i, out)
    elif isinstance(t, A.FnType):
        for p in t.params:
            _collect_names(p, out)
        if t.ret is not None:
            _collect_names(t.ret, out)
        for e in t.throws or []:
            _collect_names(e, out)


def receiver_bindings(t: T.Ty) -> dict:
    k = kind_of_type(t)
    out: dict = {"Self": t}
    if isinstance(t, T.TCon) and k in KIND_PARAMS:
        for name, arg in zip(KIND_PARAMS[k], t.args):
            out[name] = arg
    return out


# ------------------------------------------------------------------ consistency
class Conformance:
    """Static structural protocol conformance (mirrors rtypes.method_conforms)."""

    def __init__(self, satisfies_fn):
        self.satisfies_fn = satisfies_fn


class ErrSet(T.Ty):
    """Static error set of a task handle with several possible error types (the `E`
    of `Task[T, E]` when it is a finite union). Gradual: consistent with any type."""

    __slots__ = ("names",)

    def __init__(self, names):
        self.names = frozenset(names)

    def __eq__(self, other):
        return isinstance(other, ErrSet) and self.names == other.names

    def __hash__(self):
        return hash(("errset", self.names))

    def __str__(self):
        return " | ".join(sorted(n.rsplit(".", 1)[-1] for n in self.names))


def task_error_type(names, unknown: bool, types: dict) -> T.Ty:
    """The `E` of a spawned task from the effect collected for its body."""
    if unknown:
        return DYN
    concrete = [n for n in names if not n.startswith("$")]
    if not concrete:
        return T.NEVER if not names else DYN
    if len(concrete) == 1 and len(names) == 1 and concrete[0] in types:
        return types[concrete[0]].ty
    return ErrSet(names)


def task_error_names(et: T.Ty):
    """(names, unknown) a task's error component may throw when awaited."""
    if et is DYN:
        return set(), True
    if et is T.NEVER:
        return set(), False
    if isinstance(et, ErrSet):
        return set(et.names), False
    if isinstance(et, T.TNominal):
        return {et.qualname}, False
    if isinstance(et, T.TVar):
        return {"$" + et.name}, False
    return set(), True


def _is_report(t) -> bool:
    return (isinstance(t, T.TCon) and t.name == "TaskGroupReport") or \
        (isinstance(t, T.TNominal) and t.qualname == "core.TaskGroupReport")


def consistent(src: T.Ty, dst: T.Ty, satisfies=None) -> bool:
    """Is a value of static type `src` acceptable where `dst` is expected?"""
    if src is DYN or dst is DYN or src == dst:
        return True
    if isinstance(src, ErrSet) or isinstance(dst, ErrSet):
        return True
    if isinstance(src, T.TVar) or isinstance(dst, T.TVar):
        return True
    if src is T.NEVER:
        return True
    if _is_report(src) and _is_report(dst):  # `TaskGroupReport` annotation vs collect result (BUG-0039)
        return True
    if isinstance(dst, T.TBorrow):
        return consistent(src.inner if isinstance(src, T.TBorrow) else src, dst.inner, satisfies)
    if isinstance(src, T.TBorrow):
        return consistent(src.inner, dst, satisfies)
    if isinstance(dst, T.TNominal) and dst.kind == "protocol":
        if isinstance(src, T.TNominal) and src.kind == "protocol":
            return src.qualname == dst.qualname
        if satisfies is not None:
            r = satisfies(src, dst)
            return r is None or r is True
        return True
    if isinstance(src, T.TNominal) and isinstance(dst, T.TNominal):
        if src.qualname != dst.qualname:
            return False
        if src.args and dst.args:
            return all(consistent(a, b, satisfies) for a, b in zip(src.args, dst.args))
        return True
    if isinstance(src, T.TCon) and isinstance(dst, T.TCon):
        if src.name != dst.name or len(src.args) != len(dst.args):
            return False
        return all(consistent(a, b, satisfies) for a, b in zip(src.args, dst.args))
    if isinstance(src, T.TTuple) and isinstance(dst, T.TTuple):
        return len(src.items) == len(dst.items) and all(
            consistent(a, b, satisfies) for a, b in zip(src.items, dst.items))
    if isinstance(src, T.TFn) and isinstance(dst, T.TFn):
        if len(src.params) != len(dst.params) or src.is_async != dst.is_async:
            return False
        if not all(consistent(b, a, satisfies) for a, b in zip(src.params, dst.params)):
            return False
        if not consistent(src.ret, dst.ret, satisfies) and dst.ret != T.UNIT:
            return False
        return effect_within(src.effect, dst.effect)
    return False


def effect_within(have: Optional[T.Effect], allowed: Optional[T.Effect]) -> bool:
    if have is None or allowed is None:
        return True
    if any(isinstance(i, T.TVar) for i in allowed.items):
        return True
    names = {i.qualname for i in allowed.items if isinstance(i, T.TNominal)}
    return all((not isinstance(i, T.TNominal)) or i.qualname in names for i in have.items)


def join(a: T.Ty, b: T.Ty) -> T.Ty:
    """Least common static type of two branches (Dyn when they disagree)."""
    if a == b:
        return a
    if a is T.NEVER:
        return b
    if b is T.NEVER:
        return a
    if a is DYN or b is DYN:
        return DYN
    if isinstance(a, T.TCon) and isinstance(b, T.TCon) and a.name == b.name and len(a.args) == len(b.args):
        return T.TCon(a.name, tuple(join(x, y) for x, y in zip(a.args, b.args)))
    return DYN


def unify(param: T.Ty, arg: T.Ty, subst: dict) -> None:
    """First-order matching of a generic parameter type against an argument type."""
    if isinstance(param, T.TVar):
        if param.name not in subst or subst[param.name] is DYN:
            if arg is not DYN:
                subst[param.name] = arg
        return
    if isinstance(param, T.TCon) and isinstance(arg, T.TCon) and param.name == arg.name:
        for p, a in zip(param.args, arg.args):
            unify(p, a, subst)
    elif isinstance(param, T.TTuple) and isinstance(arg, T.TTuple):
        for p, a in zip(param.items, arg.items):
            unify(p, a, subst)
    elif isinstance(param, T.TFn) and isinstance(arg, T.TFn):
        for p, a in zip(param.params, arg.params):
            unify(p, a, subst)
        unify(param.ret, arg.ret, subst)
        if param.effect is not None:
            for item in param.effect.items:
                if isinstance(item, T.TVar):
                    if arg.effect is None:
                        subst[item.name] = None
                    else:
                        prev = subst.get(item.name)
                        if isinstance(prev, T.Effect):
                            subst[item.name] = prev.union(arg.effect)
                        elif prev is None and item.name in subst:
                            pass
                        else:
                            subst[item.name] = arg.effect
    elif isinstance(param, T.TNominal) and isinstance(arg, T.TNominal) and param.qualname == arg.qualname:
        for p, a in zip(param.args, arg.args):
            unify(p, a, subst)
    elif isinstance(param, T.TBorrow):
        unify(param.inner, arg.inner if isinstance(arg, T.TBorrow) else arg, subst)


def unfrozen_closure(t: T.Ty) -> Optional[str]:
    """Why a function value is not frozen (it captures mutable or reassigned state),
    so it cannot be stored in a frozen value (V3 5.1.3, BUG-0050); None otherwise."""
    if isinstance(t, T.TFn) and t.unsendable:
        return t.unsendable
    return None


def is_mutable_type(t: T.Ty) -> Optional[bool]:
    if isinstance(t, T.TCon):
        return t.name in T.MUTABLE_CONS
    if isinstance(t, T.TNominal):
        return t.kind == "mrecord"
    if t is DYN:
        return None
    return False
