"""Declaration tables for static checking: signatures, record/enum/protocol info."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import typesys as T
from ..runtime.core_types import ALL_CORE_TYPES, CATEGORIES, OPTION, RESULT
from ..syntax import ast as A


@dataclass
class FnSig:
    name: str
    params: list  # (name, Ty, has_default, borrow)
    ret: T.Ty
    effect: Optional[frozenset]  # error qualnames / "$E" vars, or None if not written
    is_async: bool = False
    is_resource: bool = False
    yields: Optional[T.Ty] = None
    type_params: list = field(default_factory=list)
    decl: object = None
    owner: Optional[str] = None
    has_self: bool = False
    builtin: bool = False
    variadic: bool = False
    inferred: Optional[frozenset] = None  # inferred effect for unannotated functions
    inferred_unknown: bool = False
    ret_written: bool = False

    def effect_for_callers(self):
        """(names, unknown) visible to callers."""
        if self.effect is not None:
            return self.effect, False
        if self.inferred is not None:
            return self.inferred, self.inferred_unknown
        return frozenset(), False

    def as_fn_type(self) -> T.TFn:
        names, unknown = self.effect_for_callers()
        eff = None if unknown else T.Effect(_effect_items(names))
        return T.TFn([p[1] for p in self.params], self.ret, eff, self.is_async)


def _effect_items(names):
    out = []
    for n in names:
        if n.startswith("$"):
            out.append(T.TVar(n[1:]))
        else:
            out.append(T.TNominal(n, "error"))
    return out


@dataclass
class TypeInfo:
    qualname: str
    name: str
    kind: str  # record mrecord error enum errorenum protocol
    decl: object = None
    fields: dict = field(default_factory=dict)  # name -> Ty
    field_spans: dict = field(default_factory=dict)
    cases: dict = field(default_factory=dict)  # name -> list[(name, Ty)] | None
    methods: dict = field(default_factory=dict)  # name -> FnSig
    type_params: list = field(default_factory=list)
    categories: tuple = ()
    invariant_fields: frozenset = frozenset()
    module: str = ""

    @property
    def ty(self) -> T.TNominal:
        return T.TNominal(self.qualname, self.kind)

    @property
    def is_error(self) -> bool:
        return self.kind in ("error", "errorenum")


def core_type_infos() -> dict[str, TypeInfo]:
    """TypeInfos for runtime-defined core records/enums (Option/Result excluded:
    they are constructor types TCon)."""
    from ..runtime.values import EnumType, RecordType
    out = {}
    for name, t in ALL_CORE_TYPES.items():
        if t is OPTION or t is RESULT:
            continue
        if isinstance(t, RecordType):
            kind = "error" if t.is_error else "record"
            ti = TypeInfo(t.qualname, name, kind, categories=tuple(f"core.{c}" for c in t.categories), module="core")
            for f in t.fields:
                ti.fields[f.name] = f.type if f.type is not None else T.DYN
        else:
            kind = "errorenum" if t.is_error else "enum"
            ti = TypeInfo(t.qualname, name, kind, module="core", type_params=list(t.type_params))
            for cname, ci in t.cases.items():
                ti.cases[cname] = None if ci.fields is None else [(f.name, f.type or T.DYN) for f in ci.fields]
        out[t.qualname] = ti
    return out


CORE_CATEGORY_QUALS = {name: f"core.{name}" for name in CATEGORIES}
