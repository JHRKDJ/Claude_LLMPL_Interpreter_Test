"""Transient runtime type checks and protocol shape checks (V3 5.3, 7.5.2, 7.6.2-3).

`check(ty, v)` is *shallow* (transient semantics): it checks the outer constructor,
and one level into Option/Result/tuples (O(1) and bounded), but never traverses
collections. Nested contents are checked later at the typed use that relies on them.
Concrete record annotations are nominal; protocol annotations check the complete
immediate shape (methods, arities, async-ness, effects, no added preconditions).
"""
from __future__ import annotations

from typing import Optional

from .. import typesys as T
from .core_types import OPTION, RESULT
from .equality import type_name
from .values import (UNIT, Borrow, BoundMethod, Builtin, BuiltinBound, Closure, Duration, EnumType, FrozenList,
                     FrozenMap, FrozenRecord, FrozenSet, Instant, MutableList, MutableMap, MutableRecord, MutableSet,
                     ProtocolType, RangeValue, RecordType, TupleValue, TypeValue, UnitType, VariantValue)


def lang_kind(v) -> Optional[str]:
    return getattr(type(v), "lang_kind", None)


class TypeRegistry:
    """Maps nominal qualnames to runtime type objects; caches protocol conformance."""

    def __init__(self):
        self.nominals: dict[str, object] = {}
        self.protocols: dict[str, ProtocolType] = {}
        self._conf: dict[tuple, Optional[str]] = {}
        self.builtin_method_table = None  # set by interpreter: fn(value) -> dict[name, Builtin]

    def register(self, qualname: str, t) -> None:
        self.nominals[qualname] = t
        if isinstance(t, ProtocolType):
            self.protocols[qualname] = t

    # ------------------------------------------------------------ shallow check
    def check(self, ty: T.Ty, v) -> bool:
        if ty is T.DYN:
            return True
        tv = type(v)
        if tv is Borrow and not isinstance(ty, T.TBorrow):
            # a borrow satisfies the annotation of the borrowed value (non-escaping use)
            return self.check(ty, v.target)
        if isinstance(ty, T.TPrim):
            n = ty.name
            if n == "Int":
                return tv is int
            if n == "Float":
                return tv is float
            if n == "Bool":
                return tv is bool
            if n == "Str":
                return tv is str
            if n == "Unit":
                return tv is UnitType
            if n == "Duration":
                return tv is Duration
            if n == "Instant":
                return tv is Instant
            if n == "Range":
                return tv is RangeValue
            if n == "Never":
                return False
            return True
        if isinstance(ty, T.TCon):
            n = ty.name
            if n == "List":
                return tv is FrozenList
            if n == "MutableList":
                return tv is MutableList
            if n == "Map":
                return tv is FrozenMap
            if n == "MutableMap":
                return tv is MutableMap
            if n == "Set":
                return tv is FrozenSet
            if n == "MutableSet":
                return tv is MutableSet
            if n == "Option":
                if tv is not VariantValue or v.case.etype is not OPTION:
                    return False
                if v.case.name == "Some":
                    return self.check(ty.args[0], v.values[0])
                return True
            if n == "Result":
                if tv is not VariantValue or v.case.etype is not RESULT:
                    return False
                if v.case.name == "Ok":
                    return self.check(ty.args[0], v.values[0])
                return self.check(ty.args[1], v.values[0]) if not _is_effect_var(ty.args[1]) else True
            if n in ("TaskOutcome",):
                return tv is VariantValue and v.case.etype.qualname == "core.TaskOutcome"
            if n == "TaskGroupReport":
                return tv is FrozenRecord and v.rtype.qualname == "core.TaskGroupReport"
            return lang_kind(v) == n
        if isinstance(ty, T.TTuple):
            if tv is not TupleValue or len(v.items) != len(ty.items):
                return False
            return all(self.check(t, x) for t, x in zip(ty.items, v.items))
        if isinstance(ty, T.TFn):
            return self.check_callable(ty, v) is None
        if isinstance(ty, T.TNominal):
            if ty.kind == "protocol":
                return self.protocol_shape(ty.qualname, v) is None
            if tv is FrozenRecord or tv is MutableRecord:
                return v.rtype.qualname == ty.qualname
            if tv is VariantValue:
                return v.case.etype.qualname == ty.qualname
            return False
        if isinstance(ty, T.TVar):
            return True
        if isinstance(ty, T.TBorrow):
            return tv is Borrow and self.check(ty.inner, v.target)
        return True

    # ------------------------------------------------------------ callables
    def check_callable(self, ty: T.TFn, v) -> Optional[str]:
        tv = type(v)
        if tv is Closure:
            params = [p for p in v.decl.params if not p.is_self]
            required = [p for p in params if p.default is None]
            if not (len(required) <= len(ty.params) <= len(params)):
                return f"expects {len(params)} parameter(s), annotation requires {len(ty.params)}"
            if v.is_async != ty.is_async:
                return "async-ness differs from the annotation"
            if ty.effect is not None and v.effect is not None:
                extra = effect_excess(v.effect, ty.effect)
                if extra:
                    return f"may throw {', '.join(sorted(extra))}, outside the annotated throws set"
            return None
        if tv is BoundMethod:
            f = v.func
            params = [p for p in f.decl.params if not p.is_self]
            if len(params) != len(ty.params):
                return f"expects {len(params)} parameter(s), annotation requires {len(ty.params)}"
            if ty.effect is not None and f.effect is not None:
                extra = effect_excess(f.effect, ty.effect)
                if extra:
                    return f"may throw {', '.join(sorted(extra))}, outside the annotated throws set"
            return None
        if tv in (Builtin, BuiltinBound):
            b = v if tv is Builtin else v.builtin
            if ty.effect is not None and b.effect is not None:
                extra = effect_excess(frozenset(b.effect), ty.effect)
                if extra:
                    return f"may throw {', '.join(sorted(extra))}, outside the annotated throws set"
            return None
        if tv is TypeValue:
            return None
        return f"{type_name(v)} is not callable"

    # ------------------------------------------------------------ protocols
    def protocol_shape(self, qualname: str, v) -> Optional[str]:
        """None if v satisfies the protocol's immediate shape, else a reason."""
        proto = self.protocols.get(qualname)
        if proto is None:
            return None
        if type(v) is Borrow:
            v = v.target
        key_t = runtime_type_key(v)
        key = (key_t, qualname)
        if key in self._conf:
            return self._conf[key]
        reason = self._shape(proto, v)
        if key_t is not None:
            self._conf[key] = reason
        return reason

    def _shape(self, proto: ProtocolType, v) -> Optional[str]:
        methods = self.methods_of(v)
        for name, pdecl in proto.methods.items():
            m = methods.get(name)
            if m is None:
                return f"missing method `{name}`"
            reason = method_conforms(pdecl, m)
            if reason:
                return f"method `{name}` {reason}"
        return None

    def methods_of(self, v) -> dict:
        tv = type(v)
        if tv in (FrozenRecord, MutableRecord):
            return v.rtype.methods
        if tv is VariantValue:
            return v.case.etype.methods
        if self.builtin_method_table is not None:
            return self.builtin_method_table(v) or {}
        return {}


def runtime_type_key(v):
    tv = type(v)
    if tv in (FrozenRecord, MutableRecord):
        return ("rec", v.rtype.id)
    if tv is VariantValue:
        return ("enum", v.case.etype.id)
    if tv in (int, float, str, bool):
        return ("prim", tv.__name__)
    return ("py", tv.__name__)


def _is_effect_var(t) -> bool:
    return isinstance(t, T.TVar)


def effect_excess(have, allowed: T.Effect) -> set[str]:
    """Error qualnames in `have` not covered by `allowed` (effect variables cover nothing
    specific at runtime: they are treated as permissive)."""
    allowed_names = set()
    for item in allowed.items:
        if isinstance(item, T.TVar):
            return set()
        if isinstance(item, T.TNominal):
            allowed_names.add(item.qualname)
    out = set()
    for h in have:
        if h not in allowed_names:
            out.add(h.rsplit(".", 1)[-1])
    return out


def method_conforms(pdecl, m) -> Optional[str]:
    """Compare a protocol method signature with an implementation (closure or builtin)."""
    p_params = [p for p in pdecl.params if not p.is_self]
    if type(m) is Closure:
        d = m.decl
        i_params = [p for p in d.params if not p.is_self]
        if len(i_params) != len(p_params):
            return f"takes {len(i_params)} parameter(s) but the protocol requires {len(p_params)}"
        if bool(d.is_async) != bool(pdecl.is_async):
            return "differs in async-ness from the protocol"
        if d.requires:
            return "adds a `requires` precondition (implementations cannot strengthen protocol preconditions)"
        p_eff = getattr(pdecl, "_effect_names", None)
        if m.effect is not None and p_eff is not None:
            extra = {e for e in m.effect if e not in p_eff}
            if extra:
                return f"may throw {', '.join(sorted(x.rsplit('.', 1)[-1] for x in extra))}, which the protocol does not declare"
        return None
    if type(m) is Builtin:
        return None
    return "is not a method"
