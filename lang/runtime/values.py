"""Runtime value representations.

Python primitives are used for Int (int), Float (float), Bool (bool) and Str (str);
every other language value is an instance of a class below. Python semantics never
leak through: equality, hashing, ordering and display are implemented explicitly in
equality.py (e.g. 1 == 1.0 is not silently true, True is not an Int).
"""
from __future__ import annotations

import itertools
from typing import Any, Optional

_ids = itertools.count(1)


class UnitType:
    __slots__ = ()
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = object.__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "()"


UNIT = UnitType()


class Uninit:
    """Marker for an uninitialised binding (V3 5.4: a binding state, not a value)."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<uninitialised>"


UNINIT = Uninit()


# ----------------------------------------------------------------------------- types
class FieldInfo:
    __slots__ = ("name", "type", "type_expr", "default", "sensitive", "index", "span")

    def __init__(self, name, type, type_expr, default, sensitive, index, span):
        self.name = name
        self.type = type  # typesys term or None (Dyn)
        self.type_expr = type_expr
        self.default = default  # AST expr or None
        self.sensitive = sensitive
        self.index = index
        self.span = span


class RecordType:
    """A declared `record`, `mutable record` or `error` type."""

    def __init__(self, name: str, qualname: str, decl, mutable: bool, kind: str = "record",
                 category: Optional[str] = None):
        self.name = name
        self.qualname = qualname
        self.decl = decl
        self.mutable = mutable
        self.kind = kind  # record | error
        self.categories: tuple[str, ...] = (category,) if category else ()
        self.fields: list[FieldInfo] = []
        self.field_index: dict[str, int] = {}
        self.methods: dict[str, Any] = {}
        self.invariants: list = []  # AST exprs
        self.invariant_fields: frozenset[str] = frozenset()
        self.type_params: list[str] = []
        self.module = None
        self.id = next(_ids)
        self.protocol_contracts: dict[str, list] = {}  # method -> [(protocol, FnDecl)]

    @property
    def is_error(self) -> bool:
        return self.kind == "error"

    def __repr__(self) -> str:
        return f"<type {self.qualname}>"


class CaseInfo:
    __slots__ = ("name", "fields", "field_index", "index", "etype", "span", "_nullary")

    def __init__(self, name, fields, index, etype, span):
        self.name = name
        self.fields = fields  # list[FieldInfo] or None (no payload)
        self.field_index = {f.name: i for i, f in enumerate(fields or [])}
        self.index = index
        self.etype = etype
        self.span = span
        self._nullary = None

    @property
    def qualname(self) -> str:
        return f"{self.etype.name}.{self.name}"


class EnumType:
    def __init__(self, name: str, qualname: str, decl, is_error: bool = False, category: Optional[str] = None):
        self.name = name
        self.qualname = qualname
        self.decl = decl
        self.is_error = is_error
        self.categories: tuple[str, ...] = (category,) if category else ()
        self.cases: dict[str, CaseInfo] = {}
        self.methods: dict[str, Any] = {}
        self.type_params: list[str] = []
        self.module = None
        self.id = next(_ids)
        self.protocol_contracts: dict[str, list] = {}
        self.mutable = False

    def nullary(self, case: str) -> "VariantValue":
        ci = self.cases[case]
        if ci._nullary is None:
            ci._nullary = VariantValue(ci, ())
        return ci._nullary

    def __repr__(self) -> str:
        return f"<enum {self.qualname}>"


class ProtocolType:
    def __init__(self, name: str, qualname: str, decl):
        self.name = name
        self.qualname = qualname
        self.decl = decl
        self.methods: dict[str, Any] = {}  # name -> FnDecl (signature + contracts)
        self.module = None
        self.id = next(_ids)

    def __repr__(self) -> str:
        return f"<protocol {self.qualname}>"


class CategoryType:
    def __init__(self, name: str, qualname: str):
        self.name = name
        self.qualname = qualname

    def __repr__(self) -> str:
        return f"<category {self.qualname}>"


# ----------------------------------------------------------------------------- data
class FrozenRecord:
    __slots__ = ("rtype", "values", "_hash")

    def __init__(self, rtype: RecordType, values: tuple):
        self.rtype = rtype
        self.values = values
        self._hash = None

    def get(self, name: str):
        return self.values[self.rtype.field_index[name]]

    def __repr__(self) -> str:
        return f"<{self.rtype.name} {self.values}>"


class MutableRecord:
    __slots__ = ("rtype", "values", "op_depth", "id", "owner_task")

    def __init__(self, rtype: RecordType, values: list, owner_task=None):
        self.rtype = rtype
        self.values = values
        self.op_depth = 0  # >0 while one of its methods is executing (invariant rule)
        self.id = next(_ids)
        self.owner_task = owner_task

    def get(self, name: str):
        return self.values[self.rtype.field_index[name]]

    def __repr__(self) -> str:
        return f"<mutable {self.rtype.name}#{self.id}>"


class VariantValue:
    """Value of a closed variant (enum, Option, Result, error enum). Frozen."""

    __slots__ = ("case", "values", "prov", "_hash")

    def __init__(self, case: CaseInfo, values: tuple, prov=None):
        self.case = case
        self.values = values
        self.prov = prov  # Err provenance (does not affect equality)
        self._hash = None

    @property
    def etype(self) -> EnumType:
        return self.case.etype

    def __repr__(self) -> str:
        return f"<{self.case.qualname} {self.values}>"


class TupleValue:
    __slots__ = ("items", "_hash")

    def __init__(self, items: tuple):
        self.items = items
        self._hash = None


class FrozenList:
    __slots__ = ("items", "_hash")

    def __init__(self, items: tuple):
        self.items = items
        self._hash = None


class MutableList:
    __slots__ = ("items", "version", "id", "elem_type")

    def __init__(self, items: list, elem_type=None):
        self.items = items
        self.version = 0
        self.id = next(_ids)
        self.elem_type = elem_type


class FrozenMap:
    """Insertion-ordered frozen map. `data` maps typed key -> (key, value)."""

    __slots__ = ("data", "_hash")

    def __init__(self, data: dict):
        self.data = data
        self._hash = None


class MutableMap:
    __slots__ = ("data", "version", "id", "key_type", "value_type")

    def __init__(self, data: dict, key_type=None, value_type=None):
        self.data = data
        self.version = 0
        self.id = next(_ids)
        self.key_type = key_type
        self.value_type = value_type


class FrozenSet:
    __slots__ = ("data", "_hash")

    def __init__(self, data: dict):
        self.data = data  # typed key -> element
        self._hash = None


class MutableSet:
    __slots__ = ("data", "version", "id", "elem_type")

    def __init__(self, data: dict, elem_type=None):
        self.data = data
        self.version = 0
        self.id = next(_ids)
        self.elem_type = elem_type


class RangeValue:
    __slots__ = ("lo", "hi", "inclusive")

    def __init__(self, lo: int, hi: int, inclusive: bool):
        self.lo = lo
        self.hi = hi
        self.inclusive = inclusive

    def as_range(self) -> range:
        return range(self.lo, self.hi + 1 if self.inclusive else self.hi)


class Duration:
    __slots__ = ("nanos",)

    def __init__(self, nanos: int):
        self.nanos = int(nanos)


class Instant:
    __slots__ = ("nanos",)

    def __init__(self, nanos: int):
        self.nanos = int(nanos)


# ----------------------------------------------------------------------------- callables
class Closure:
    """A user function or lambda closed over its defining environment."""

    __slots__ = ("decl", "env", "name", "owner", "module", "is_async", "is_resource", "effect",
                 "captures_mutable", "id", "params_info", "ret_type", "throws_types", "is_lambda",
                 "type_params")

    def __init__(self, decl, env, name: str, module, owner=None, is_lambda: bool = False):
        self.decl = decl
        self.env = env
        self.name = name
        self.owner = owner  # RecordType/EnumType for methods
        self.module = module
        self.is_async = getattr(decl, "is_async", False)
        self.is_resource = getattr(decl, "is_resource", False)
        self.effect = None  # frozenset of error qualnames, or None = unannotated/unknown
        self.captures_mutable = None
        self.id = next(_ids)
        self.params_info = None
        self.ret_type = None
        self.throws_types = None
        self.is_lambda = is_lambda
        self.type_params = list(getattr(decl, "type_params", []) or [])

    def __repr__(self) -> str:
        return f"<fn {self.name}>"


class BoundMethod:
    __slots__ = ("receiver", "func")

    def __init__(self, receiver, func):
        self.receiver = receiver
        self.func = func


class Builtin:
    """Native function. `impl(interp, args, kwargs, span)` -> value."""

    __slots__ = ("name", "impl", "is_async", "effect", "min_args", "max_args", "abandon_safe", "doc",
                 "is_provider", "pass_receiver", "sig", "kind", "contract_safe")

    def __init__(self, name, impl, is_async=False, effect=frozenset(), min_args=0, max_args=None,
                 abandon_safe=False, doc="", is_provider=False, sig=None, kind=None, contract_safe=False):
        self.name = name
        self.impl = impl
        self.is_async = is_async
        self.effect = effect  # frozenset of error qualnames; None => forwards callback effects
        self.min_args = min_args
        self.max_args = max_args
        self.abandon_safe = abandon_safe
        self.doc = doc
        self.is_provider = is_provider
        self.sig = sig  # textual signature used by the static checker
        self.kind = kind  # receiver kind for methods
        self.contract_safe = contract_safe  # total, read-only: allowed in contracts

    def __repr__(self) -> str:
        return f"<builtin {self.name}>"


class BuiltinBound:
    __slots__ = ("receiver", "builtin")

    def __init__(self, receiver, builtin: Builtin):
        self.receiver = receiver
        self.builtin = builtin


class TypeValue:
    """A type used as a value: constructor / namespace for associated functions."""

    __slots__ = ("kind", "target", "args", "name")

    def __init__(self, kind: str, target, args=(), name: str = ""):
        self.kind = kind  # record enum case protocol builtin category
        self.target = target
        self.args = tuple(args)
        self.name = name

    def __repr__(self) -> str:
        return f"<type {self.name}>"


class ModuleValue:
    __slots__ = ("name", "namespace", "module")

    def __init__(self, name: str, namespace: dict, module=None):
        self.name = name
        self.namespace = namespace
        self.module = module


class Namespace:
    """Builtin namespace object such as `time` or `cancel`."""

    __slots__ = ("name", "members")

    def __init__(self, name: str, members: dict):
        self.name = name
        self.members = members


def is_identity_bearing(v) -> bool:
    return isinstance(v, (MutableRecord, MutableList, MutableMap, MutableSet))


# ----------------------------------------------------------------------------- resources
class ResourceState:
    """Shared liveness record for one resource scope's yielded value."""

    __slots__ = ("active", "task", "scope_span", "acquired_at", "name", "provider_name")

    def __init__(self, task, scope_span, acquired_at, name: str, provider_name: str):
        self.active = True
        self.task = task
        self.scope_span = scope_span
        self.acquired_at = acquired_at
        self.name = name
        self.provider_name = provider_name


class Borrow:
    """A scoped borrow of a resource-owning value (V3 5.5.7-8, 7.9.4).

    Every `use` binding and every borrow passed to helpers is a Borrow. The target is
    only reachable through the borrow, which dies when the owning scope exits.
    """

    __slots__ = ("target", "state")

    def __init__(self, target, state: ResourceState):
        self.target = target
        self.state = state

    def lang_type_name(self) -> str:
        from .equality import type_name
        return f"borrow {type_name(self.target)}"

    def lang_display(self) -> str:
        return f"<borrow of {self.state.provider_name} resource>"


class ResourceHandle:
    """Base class for native resource handles (files, temp dirs, ...)."""

    resource_kind = "Resource"

    def lang_type_name(self) -> str:
        return self.resource_kind

    def lang_display(self) -> str:
        return f"<{self.resource_kind}>"
