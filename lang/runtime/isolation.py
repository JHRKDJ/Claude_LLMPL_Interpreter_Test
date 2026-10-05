"""Task-boundary sendability and graph copy (V3 5.11, 7.6.6, 7.10.10, 8.2).

Every value crossing a task boundary (spawn arguments, block captures, task results,
channel messages) is classified *before* the child starts or the message commits:

  primitive / Str / frozen record / frozen collection / frozen variant -> share
  mutable record / mutable collection (and variants/tuples containing them) -> graph copy
  closure with only sendable, effectively-constant captures -> share
  closure with mutable captures -> reject
  resource borrow / resource handle -> reject
  send/receive port -> share (frozen capability; receiving task becomes a holder)
  channel controller, task handle, interpreter capability -> reject

The graph copy preserves cycles and aliasing inside the copied graph and never
produces an alias back into the source graph. No user hooks run (V3 7.10.10).
"""
from __future__ import annotations

from .equality import type_name
from .frozen import is_frozen, closure_is_frozen
from .signals import Fault
from .values import (Borrow, BoundMethod, Builtin, BuiltinBound, Closure, FrozenList, FrozenMap, FrozenRecord,
                     FrozenSet, ModuleValue, MutableList, MutableMap, MutableRecord, MutableSet, Namespace,
                     ResourceHandle, TupleValue, TypeValue, UnitType, VariantValue, Duration, Instant, RangeValue)

_SCALARS = (bool, int, float, str, UnitType, Duration, Instant, RangeValue, TypeValue, Builtin)


class Transfer:
    """One boundary crossing. Collects ports found and the copy size (for advisories)."""

    def __init__(self, what: str, copy: bool = True):
        self.what = what
        self.copy = copy  # False: classify only (reject non-sendables, find ports), no copying
        self.ports: list = []
        self.copied = 0
        self.memo: dict = {}
        self.roots: list = []  # (root description, elements copied) for advisories

    def root(self, v, path: str):
        """Transfer one root value (an argument, capture, result or message)."""
        before = self.copied
        out = self.value(v, path)
        self.roots.append((path, self.copied - before))
        return out

    def reject(self, v, why: str, path: str):
        raise Fault("A.TASK.NOT_SENDABLE",
                    f"{self.what}: {type_name(v)} at {path} cannot cross a task boundary ({why})",
                    help=_REJECT_HELP.get(why, "pass a frozen value or an explicit argument instead"),
                    extra={"path": path, "reason": why})

    def value(self, v, path: str = "value"):
        t = type(v)
        if t in _SCALARS:
            return v
        if t is FrozenRecord:
            self._scan_frozen(v.values, path)
            return v
        if t is FrozenList:
            self._scan_frozen(v.items, path)
            return v
        if t is FrozenMap:
            self._scan_frozen([x for _, x in v.data.values()], path)
            return v
        if t is FrozenSet:
            return v
        if t is VariantValue:
            if is_frozen(v):
                self._scan_frozen(v.values, path)
                return v
            key = id(v)
            if key in self.memo:
                return self.memo[key]
            new = VariantValue(v.case, tuple(self.value(x, f"{path}.{f.name if v.case.fields else i}")
                                             for i, (x, f) in enumerate(zip(v.values, v.case.fields or [None] * len(v.values)))),
                               v.prov)
            self.memo[key] = new
            return new
        if t is TupleValue:
            if is_frozen(v):
                self._scan_frozen(v.items, path)
                return v
            return TupleValue(tuple(self.value(x, f"{path}.{i}") for i, x in enumerate(v.items)))
        if not self.copy and t in (MutableRecord, MutableList, MutableMap, MutableSet):
            key = id(v)
            if key in self.memo:
                return v
            self.memo[key] = v
            if t is MutableRecord:
                for f, x in zip(v.rtype.fields, v.values):
                    self.value(x, f"{path}.{f.name}")
            elif t is MutableList:
                for i, x in enumerate(v.items):
                    self.value(x, f"{path}[{i}]")
            elif t is MutableMap:
                for k, x in v.data.values():
                    self.value(x, f"{path}[{k!r}]")
            return v
        if t is MutableRecord:
            key = id(v)
            if key in self.memo:
                return self.memo[key]
            new = MutableRecord(v.rtype, [None] * len(v.values))
            self.memo[key] = new
            self.copied += 1
            for i, (f, x) in enumerate(zip(v.rtype.fields, v.values)):
                new.values[i] = self.value(x, f"{path}.{f.name}")
            return new
        if t is MutableList:
            key = id(v)
            if key in self.memo:
                return self.memo[key]
            new = MutableList([], v.elem_type)
            self.memo[key] = new
            self.copied += len(v.items) + 1
            new.items = [self.value(x, f"{path}[{i}]") for i, x in enumerate(v.items)]
            return new
        if t is MutableMap:
            key = id(v)
            if key in self.memo:
                return self.memo[key]
            new = MutableMap({}, v.key_type, v.value_type)
            self.memo[key] = new
            self.copied += len(v.data) + 1
            for hk, (k, x) in v.data.items():
                new.data[hk] = (k, self.value(x, f"{path}[{k!r}]"))
            return new
        if t is MutableSet:
            key = id(v)
            if key in self.memo:
                return self.memo[key]
            new = MutableSet(dict(v.data), v.elem_type)
            self.memo[key] = new
            self.copied += len(v.data) + 1
            return new
        if t is Closure:
            if closure_is_frozen(v):
                caps = v.decl.ann.get("captures") if hasattr(v.decl, "ann") else None
                if caps and v.env is not None:
                    vals = []
                    for name, _ in caps:
                        e = v.env.find(name)
                        if e is not None and e.kind not in ("module", "prelude"):
                            vals.append(e.vars[name])
                    self._scan_frozen(vals, f"{path}.<captures>")
                return v
            self.reject(v, "closure with mutable captures", path)
        if t is BoundMethod:
            if not is_frozen(v.receiver):  # a bound method closes over its receiver (BUG-0037)
                self.reject(v, "bound method of a mutable value", path)
            self._scan_frozen([v.receiver], f"{path}.<receiver>")
            return v
        if t is BuiltinBound:
            recv = self.value(v.receiver, f"{path}.<receiver>")
            return BuiltinBound(recv, v.builtin)
        if t is Borrow:
            self.reject(v, "resource borrow", path)
        if isinstance(v, ResourceHandle):
            self.reject(v, "resource", path)
        if t is ModuleValue or t is Namespace:
            return v
        policy = getattr(t, "lang_sendable", None)
        if policy == "share":
            if getattr(t, "is_port", False):
                self.ports.append(v)
            return v
        if policy == "reject":
            self.reject(v, getattr(t, "lang_reject_reason", "runtime capability"), path)
        self.reject(v, "runtime capability", path)

    def _scan_frozen(self, items, path):
        """Frozen graphs are shared; they are traversed to find embedded ports and to
        reject embedded capabilities such as task handles (BUG-0021)."""
        if not PORTS_EXIST[0]:
            return
        stack = list(items)
        seen = 0
        while stack and seen < 100000:
            x = stack.pop()
            seen += 1
            t = type(x)
            if getattr(t, "is_port", False):
                self.ports.append(x)
            elif getattr(t, "lang_sendable", None) == "reject":
                self.reject(x, getattr(t, "lang_reject_reason", "runtime capability"), path)
            elif t is FrozenRecord or t is VariantValue:
                stack.extend(x.values)
            elif t is FrozenList or t is TupleValue:
                stack.extend(x.items)
            elif t is FrozenMap:
                stack.extend(val for _, val in x.data.values())


# True once any port or task handle exists, i.e. once frozen graphs may embed one.
PORTS_EXIST = [False]

_REJECT_HELP = {
    "closure with mutable captures": "pass the needed data as explicit task arguments (mutable values are copied), "
                                     "or capture only frozen, never-reassigned bindings",
    "resource borrow": "resources cannot leave their scope or task; open the resource inside the child task",
    "resource": "resources cannot cross task boundaries; open the resource inside the child task",
    "channel controller": "pass a send or receive port (`ch.sender()` / `ch.receiver()`) instead of the controller",
    "task handle": "task handles stay within their structured scope; communicate results through return values",
}
