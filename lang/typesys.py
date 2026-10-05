"""Type terms shared by the static checker and the runtime transient checks.

Types are immutable value objects. Nominal types are identified by qualified name
(`module.Name`) so that this module does not depend on runtime classes.
"""
from __future__ import annotations

from typing import Callable, Optional

from .syntax import ast as A


class Ty:
    __slots__ = ()

    def __eq__(self, other):  # structural
        return type(self) is type(other) and self._key() == other._key()

    def __hash__(self):
        return hash((type(self).__name__, self._key()))

    def _key(self):
        return ()

    def __repr__(self) -> str:
        return f"Ty({self})"


class TPrim(Ty):
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def _key(self):
        return self.name

    def __str__(self) -> str:
        return self.name


DYN = TPrim("Dyn")
INT = TPrim("Int")
FLOAT = TPrim("Float")
BOOL = TPrim("Bool")
STR = TPrim("Str")
UNIT = TPrim("Unit")
NEVER = TPrim("Never")
DURATION = TPrim("Duration")
INSTANT = TPrim("Instant")
RANGE = TPrim("Range")
PRIMS = {t.name: t for t in (DYN, INT, FLOAT, BOOL, STR, UNIT, NEVER, DURATION, INSTANT, RANGE)}


class TCon(Ty):
    """Built-in generic constructor application, e.g. List[Int]."""

    __slots__ = ("name", "args")

    def __init__(self, name: str, args: tuple = ()):
        self.name = name
        self.args = tuple(args)

    def _key(self):
        return (self.name, self.args)

    def __str__(self) -> str:
        if self.name == "Option" and self.args:
            inner = str(self.args[0])
            return f"{inner}?" if not isinstance(self.args[0], TFn) else f"({inner})?"
        if not self.args:
            return self.name
        return f"{self.name}[{', '.join(str(a) for a in self.args)}]"


CON_ARITY = {
    "List": 1, "Set": 1, "Map": 2, "MutableList": 1, "MutableSet": 1, "MutableMap": 2,
    "Option": 1, "Result": 2, "Task": 2, "Channel": 1, "SendPort": 1, "ReceivePort": 1,
    "Broadcast": 1, "TaskGroupReport": 2, "TaskOutcome": 2, "File": 0, "Dir": 0, "PublishPort": 1,
}
FROZEN_CONS = {"List", "Set", "Map", "Option", "Result", "SendPort", "ReceivePort"}
MUTABLE_CONS = {"MutableList", "MutableSet", "MutableMap"}


class TTuple(Ty):
    __slots__ = ("items",)

    def __init__(self, items):
        self.items = tuple(items)

    def _key(self):
        return self.items

    def __str__(self) -> str:
        return "(" + ", ".join(str(i) for i in self.items) + ")"


class Effect:
    """A finite error set (nominal error types and effect variables)."""

    __slots__ = ("items",)

    def __init__(self, items=()):
        self.items = frozenset(items)

    def union(self, other: "Effect") -> "Effect":
        return Effect(self.items | other.items)

    def __eq__(self, other):
        return isinstance(other, Effect) and self.items == other.items

    def __hash__(self):
        return hash(self.items)

    def __bool__(self):
        return bool(self.items)

    def names(self) -> list[str]:
        return sorted(str(i) for i in self.items)

    def __str__(self) -> str:
        return " | ".join(self.names()) if self.items else "nothing"


EMPTY_EFFECT = Effect()


class TFn(Ty):
    __slots__ = ("params", "ret", "effect", "is_async")

    def __init__(self, params, ret: Ty, effect: Optional[Effect], is_async: bool = False):
        self.params = tuple(params)
        self.ret = ret
        self.effect = effect  # None => unknown (Dyn effect)
        self.is_async = is_async

    def _key(self):
        return (self.params, self.ret, self.effect, self.is_async)

    def __str__(self) -> str:
        s = ("async " if self.is_async else "") + "fn(" + ", ".join(str(p) for p in self.params) + ")"
        if self.ret != UNIT:
            s += f" -> {self.ret}"
        if self.effect is None:
            s += " throws ?"
        elif self.effect:
            s += f" throws {self.effect}"
        return s


class TNominal(Ty):
    """User or core nominal type: record, enum, error, error enum, protocol."""

    __slots__ = ("qualname", "kind", "args")

    def __init__(self, qualname: str, kind: str, args=()):
        self.qualname = qualname
        self.kind = kind  # record mrecord error enum errorenum protocol
        self.args = tuple(args)

    def _key(self):
        return (self.qualname, self.args)

    @property
    def short(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]

    def __str__(self) -> str:
        if self.args:
            return f"{self.short}[{', '.join(str(a) for a in self.args)}]"
        return self.short


class TVar(Ty):
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def _key(self):
        return self.name

    def __str__(self) -> str:
        return self.name


class TBorrow(Ty):
    __slots__ = ("inner",)

    def __init__(self, inner: Ty):
        self.inner = inner

    def _key(self):
        return self.inner

    def __str__(self) -> str:
        return f"borrow {self.inner}"


def option(t: Ty) -> TCon:
    return TCon("Option", (t,))


Resolver = Callable[[list[str], A.TypeExpr], Optional[Ty]]


class TypeConversionError(Exception):
    def __init__(self, message: str, node: A.TypeExpr, stable: str = "S.NAME.NOT_A_TYPE", help: str = ""):
        super().__init__(message)
        self.message = message
        self.node = node
        self.stable = stable
        self.help = help


def from_expr(t: Optional[A.TypeExpr], resolve: Resolver, type_params: frozenset = frozenset()) -> Ty:
    """Convert a syntactic type to a term. `resolve(path, node)` maps a user name to a
    TNominal (or None if unknown -> TypeConversionError)."""
    if t is None:
        return DYN
    if isinstance(t, A.OptionalType):
        return option(from_expr(t.inner, resolve, type_params))
    if isinstance(t, A.TupleType):
        return TTuple(from_expr(i, resolve, type_params) for i in t.items)
    if isinstance(t, A.BorrowType):
        return TBorrow(from_expr(t.inner, resolve, type_params))
    if isinstance(t, A.FnType):
        params = [from_expr(p, resolve, type_params) for p in t.params]
        ret = from_expr(t.ret, resolve, type_params) if t.ret is not None else UNIT
        eff = Effect(from_expr(e, resolve, type_params) for e in t.throws) if t.throws else EMPTY_EFFECT
        return TFn(params, ret, eff, t.is_async)
    if isinstance(t, A.TypeName):
        args = [from_expr(a, resolve, type_params) for a in t.args]
        if len(t.path) == 1:
            n = t.path[0]
            if n in type_params:
                if args:
                    raise TypeConversionError(f"type parameter {n} takes no arguments", t, "S.TYPE.GENERIC_ARITY")
                return TVar(n)
            if n in PRIMS:
                if args:
                    raise TypeConversionError(f"{n} takes no type arguments", t, "S.TYPE.GENERIC_ARITY")
                return PRIMS[n]
            if n in CON_ARITY:
                want = CON_ARITY[n]
                if args and len(args) != want:
                    raise TypeConversionError(f"{n} expects {want} type argument(s), got {len(args)}", t,
                                              "S.TYPE.GENERIC_ARITY")
                if not args:
                    args = [DYN] * want
                return TCon(n, tuple(args))
        r = resolve(t.path, t)
        if r is None:
            hint = ""
            lower = t.path[-1].lower()
            for cand in list(PRIMS) + list(CON_ARITY):
                if cand.lower() == lower:
                    hint = f"did you mean `{cand}`?"
            raise TypeConversionError(f"unknown type `{'.'.join(t.path)}`", t, "S.NAME.NOT_A_TYPE", hint)
        if isinstance(r, TNominal) and args:
            return TNominal(r.qualname, r.kind, tuple(args))
        return r
    raise TypeConversionError("unsupported type syntax", t)


def is_frozen_type(t: Ty, frozen_nominal: Callable[[TNominal], bool]) -> Optional[bool]:
    """True if values of t are transitively frozen; False if certainly not; None if unknown."""
    if t is DYN or isinstance(t, TVar):
        return None
    if isinstance(t, TPrim):
        return True
    if isinstance(t, TCon):
        if t.name in MUTABLE_CONS or t.name in ("Channel", "Task", "Broadcast"):
            return False
        if t.name in ("SendPort", "ReceivePort"):
            return True
        res = True
        for a in t.args:
            r = is_frozen_type(a, frozen_nominal)
            if r is False:
                return False
            if r is None:
                res = None
        return res
    if isinstance(t, TTuple):
        res = True
        for a in t.items:
            r = is_frozen_type(a, frozen_nominal)
            if r is False:
                return False
            if r is None:
                res = None
        return res
    if isinstance(t, TFn):
        return None
    if isinstance(t, TNominal):
        if t.kind == "protocol":
            return None
        return frozen_nominal(t)
    if isinstance(t, TBorrow):
        return False
    return None


def substitute(t: Ty, subst: dict) -> Ty:
    """Replace type variables bound to types; error-set variables bound to effects are
    replaced inside function-type effects only (BUG-0013)."""
    if isinstance(t, TVar):
        r = subst.get(t.name, t)
        return r if isinstance(r, Ty) else t
    if isinstance(t, TCon):
        return TCon(t.name, tuple(substitute(a, subst) for a in t.args))
    if isinstance(t, TTuple):
        return TTuple(substitute(a, subst) for a in t.items)
    if isinstance(t, TFn):
        eff = None if t.effect is None else substitute_effect(t.effect, subst)
        return TFn([substitute(p, subst) for p in t.params], substitute(t.ret, subst), eff, t.is_async)
    if isinstance(t, TNominal) and t.args:
        return TNominal(t.qualname, t.kind, tuple(substitute(a, subst) for a in t.args))
    if isinstance(t, TBorrow):
        return TBorrow(substitute(t.inner, subst))
    return t


def substitute_effect(e: Effect, subst: dict) -> Optional[Effect]:
    out = set()
    for item in e.items:
        if isinstance(item, TVar) and item.name in subst:
            rep = subst[item.name]
            if isinstance(rep, Effect):
                out |= rep.items
            elif rep is None:
                return None
            else:
                out.add(rep)
        else:
            out.add(item)
    return Effect(out)
