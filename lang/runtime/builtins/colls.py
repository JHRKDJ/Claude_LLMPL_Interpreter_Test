"""Frozen and mutable collections (V3 5.1, 7.3.2; SPEC-008).

Frozen List/Map/Set are persistent in observable behaviour: every update returns a
new value (implemented by copying; unobservable). Mutable collections are
identity-bearing and carry a version counter so that iteration can detect
modification. Indexing never uses Python's negative-index semantics.
"""
from __future__ import annotations

import functools

from ..core_types import NONE, some, OPTION
from ..equality import compare, hash_key, lang_eq, type_name, display
from ..frozen import is_frozen
from ..signals import Fault
from ..values import (FrozenList, FrozenMap, FrozenSet, MutableList, MutableMap, MutableSet, RangeValue,
                      TupleValue, UNIT, TypeValue)
from .common import index_check, no_borrow, want_bool, want_frozen_element, want_int, want_str
from .registry import method, prop, static

LISTS = ["List", "MutableList"]
MAPS = ["Map", "MutableMap"]
SETS = ["Set", "MutableSet"]


def flist(items) -> FrozenList:
    items = tuple(items)
    for x in items:
        want_frozen_element(x, "List")
    return FrozenList(items)


def fmap(pairs) -> FrozenMap:
    data = {}
    for k, v in pairs:
        want_frozen_element(k, "Map key")
        want_frozen_element(v, "Map")
        data[hash_key(k)] = (k, v)
    return FrozenMap(data)


def fset(items) -> FrozenSet:
    data = {}
    for x in items:
        want_frozen_element(x, "Set")
        data[hash_key(x)] = x
    return FrozenSet(data)


def touch(c) -> None:
    c.version += 1


def _call(interp, f, args, span):
    return interp.call_value(f, list(args), None, span)


def _sorted(interp, items, span, key=None):
    if key is None:
        return sorted(items, key=functools.cmp_to_key(compare))
    keyed = [(_call(interp, key, [x], span), x) for x in items]
    keyed.sort(key=functools.cmp_to_key(lambda a, b: compare(a[0], b[0])))
    return [x for _, x in keyed]


def same_kind(recv, items):
    """Transforms return a collection of the receiver's kind: List -> List (frozen,
    elements must be frozen), MutableList -> a fresh MutableList."""
    if type(recv) is MutableList:
        items = list(items)
        for x in items:
            no_borrow(x, "collection")
        return MutableList(items)
    return flist(items)


# ============================================================================ List & MutableList
@prop(LISTS, "length", "Int")
def _len(interp, recv):
    return len(recv.items)


@method(LISTS, "isEmpty", 0, sig="fn() -> Bool", contract_safe=True)
def _is_empty(interp, recv, args, span):
    return len(recv.items) == 0



def lookup_key(data, k):
    """hash_key(k) for a map/set lookup. Int and Float keys are distinct, and comparing
    an Int with a Float abandons (SPEC-010), so looking up `1.0` where `1` is a key (or
    vice versa) abandons instead of silently missing (BUG-0046)."""
    hk = hash_key(k)
    if hk in data:
        return hk
    twin = None
    if type(k) is float and k == k and k not in (float("inf"), float("-inf")) and k.is_integer():
        twin = hash_key(int(k))
    elif type(k) is int:
        try:
            twin = hash_key(float(k))
        except OverflowError:
            twin = None
    if twin is not None and twin in data:
        raise Fault("A.TYPE.OPERAND_MISMATCH",
                    f"cannot look up {type_name(k)} key {k!r} among {('Float' if type(k) is int else 'Int')} keys "
                    f"(no implicit numeric coercion)", help="convert explicitly with toFloat()/toInt()")
    return hk

@method(LISTS, "get", 1, sig="fn(Int) -> T?", contract_safe=True)
def _get(interp, recv, args, span):
    i = want_int(args[0], "index")
    if 0 <= i < len(recv.items):
        return some(recv.items[i])
    return NONE


@method(LISTS, "first", 0, sig="fn() -> T?", contract_safe=True)
def _first(interp, recv, args, span):
    return some(recv.items[0]) if recv.items else NONE


@method(LISTS, "last", 0, sig="fn() -> T?", contract_safe=True)
def _last(interp, recv, args, span):
    return some(recv.items[-1]) if recv.items else NONE


@method(LISTS, "contains", 1, sig="fn(T) -> Bool", contract_safe=True)
def _contains(interp, recv, args, span):
    x = args[0]
    return any(lang_eq(x, y) for y in recv.items)


@method(LISTS, "indexOf", 1, sig="fn(T) -> Int?", contract_safe=True)
def _index_of(interp, recv, args, span):
    for i, y in enumerate(recv.items):
        if lang_eq(args[0], y):
            return some(i)
    return NONE


@method(LISTS, "count", 1, sig="fn(fn(T) -> Bool throws E) -> Int throws E", contract_safe=True)
def _count(interp, recv, args, span):
    return sum(1 for x in list(recv.items) if want_bool(_call(interp, args[0], [x], span)))


@method(LISTS, "any", 1, sig="fn(fn(T) -> Bool throws E) -> Bool throws E", contract_safe=True)
def _any(interp, recv, args, span):
    for x in list(recv.items):
        if want_bool(_call(interp, args[0], [x], span)):
            return True
    return False


@method(LISTS, "all", 1, sig="fn(fn(T) -> Bool throws E) -> Bool throws E", contract_safe=True)
def _all(interp, recv, args, span):
    for x in list(recv.items):
        if not want_bool(_call(interp, args[0], [x], span)):
            return False
    return True


@method(LISTS, "find", 1, sig="fn(fn(T) -> Bool throws E) -> T? throws E")
def _find(interp, recv, args, span):
    for x in list(recv.items):
        if want_bool(_call(interp, args[0], [x], span)):
            return some(x)
    return NONE


@method(LISTS, "findIndex", 1, sig="fn(fn(T) -> Bool throws E) -> Int? throws E")
def _find_index(interp, recv, args, span):
    for i, x in enumerate(list(recv.items)):
        if want_bool(_call(interp, args[0], [x], span)):
            return some(i)
    return NONE


@method(LISTS, "map", 1, sig="fn(fn(T) -> U throws E) -> List[U] throws E")
def _map(interp, recv, args, span):
    return same_kind(recv, [_call(interp, args[0], [x], span) for x in list(recv.items)])


@method(LISTS, "flatMap", 1, sig="fn(fn(T) -> List[U] throws E) -> List[U] throws E")
def _flat_map(interp, recv, args, span):
    out = []
    for x in list(recv.items):
        r = _call(interp, args[0], [x], span)
        if type(r) not in (FrozenList, MutableList):
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"flatMap callback must return a List, found {type_name(r)}")
        out.extend(r.items)
    return same_kind(recv, out)


@method(LISTS, "filter", 1, sig="fn(fn(T) -> Bool throws E) -> List[T] throws E")
def _filter(interp, recv, args, span):
    return same_kind(recv, [x for x in list(recv.items) if want_bool(_call(interp, args[0], [x], span))])


@method(LISTS, "fold", 2, sig="fn(U, fn(U, T) -> U throws E) -> U throws E")
def _fold(interp, recv, args, span):
    acc = args[0]
    for x in list(recv.items):
        acc = _call(interp, args[1], [acc, x], span)
    return acc


@method(LISTS, "forEach", 1, sig="fn(fn(T) -> Unit throws E) -> Unit throws E")
def _for_each(interp, recv, args, span):
    for x in list(recv.items):
        _call(interp, args[0], [x], span)
    return UNIT


@method(LISTS, "sum", 0, sig="fn() -> T", contract_safe=True)
def _sum(interp, recv, args, span):
    items = recv.items
    if not items:
        return 0
    t = type(items[0])
    if t not in (int, float) or any(type(x) is not t for x in items):
        raise Fault("A.TYPE.OPERAND_MISMATCH", "sum() requires all Int or all Float elements")
    return sum(items) if t is int else float(sum(items))


@method(LISTS, "min", 0, sig="fn() -> T?", contract_safe=True)
def _min(interp, recv, args, span):
    if not recv.items:
        return NONE
    best = recv.items[0]
    for x in recv.items[1:]:
        if compare(x, best) < 0:
            best = x
    return some(best)


@method(LISTS, "max", 0, sig="fn() -> T?", contract_safe=True)
def _max(interp, recv, args, span):
    if not recv.items:
        return NONE
    best = recv.items[0]
    for x in recv.items[1:]:
        if compare(x, best) > 0:
            best = x
    return some(best)


@method(LISTS, "minBy", 1, sig="fn(fn(T) -> U throws E) -> T? throws E")
def _min_by(interp, recv, args, span):
    if not recv.items:
        return NONE
    items = _sorted(interp, list(recv.items), span, args[0])
    return some(items[0])


@method(LISTS, "maxBy", 1, sig="fn(fn(T) -> U throws E) -> T? throws E")
def _max_by(interp, recv, args, span):
    if not recv.items:
        return NONE
    keyed = [(_call(interp, args[0], [x], span), x) for x in recv.items]
    best = keyed[0]
    for k in keyed[1:]:
        if compare(k[0], best[0]) > 0:
            best = k
    return some(best[1])


@method(LISTS, "sorted", 0, sig="fn() -> List[T]")
def _sorted_m(interp, recv, args, span):
    return same_kind(recv, _sorted(interp, list(recv.items), span))


@method(LISTS, "sortedBy", 1, sig="fn(fn(T) -> U throws E) -> List[T] throws E")
def _sorted_by(interp, recv, args, span):
    return same_kind(recv, _sorted(interp, list(recv.items), span, args[0]))


@method(LISTS, "isSorted", 0, sig="fn() -> Bool", contract_safe=True)
def _is_sorted(interp, recv, args, span):
    xs = recv.items
    return all(compare(xs[i], xs[i + 1]) <= 0 for i in range(len(xs) - 1))


@method(LISTS, "reversed", 0, sig="fn() -> List[T]")
def _reversed(interp, recv, args, span):
    return same_kind(recv, reversed(recv.items))


@method(LISTS, "appended", 1, sig="fn(T) -> List[T]")
def _appended(interp, recv, args, span):
    return same_kind(recv, tuple(recv.items) + (args[0],))


@method(LISTS, "prepended", 1, sig="fn(T) -> List[T]")
def _prepended(interp, recv, args, span):
    return same_kind(recv, (args[0],) + tuple(recv.items))


@method(LISTS, "concat", 1, sig="fn(List[T]) -> List[T]")
def _concat(interp, recv, args, span):
    o = args[0]
    if type(o) not in (FrozenList, MutableList):
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"concat expects a List, found {type_name(o)}")
    return same_kind(recv, tuple(recv.items) + tuple(o.items))


@method(LISTS, "slice", 2, sig="fn(Int, Int) -> List[T]")
def _slice(interp, recv, args, span):
    n = len(recv.items)
    a, b = want_int(args[0], "start"), want_int(args[1], "end")
    if not (0 <= a <= b <= n):
        raise Fault("A.INDEX.OUT_OF_RANGE", f"slice({a}, {b}) is out of range for length {n}",
                    help="requires 0 <= start <= end <= length")
    return same_kind(recv, recv.items[a:b])


@method(LISTS, "take", 1, sig="fn(Int) -> List[T]")
def _take(interp, recv, args, span):
    k = want_int(args[0], "count")
    if k < 0:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "take() count must be non-negative")
    return same_kind(recv, recv.items[:k])


@method(LISTS, "drop", 1, sig="fn(Int) -> List[T]")
def _drop(interp, recv, args, span):
    k = want_int(args[0], "count")
    if k < 0:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "drop() count must be non-negative")
    return same_kind(recv, recv.items[k:])


@method(LISTS, "replaced", 2, sig="fn(Int, T) -> List[T]")
def _replaced(interp, recv, args, span):
    i = index_check(args[0], len(recv.items))
    items = list(recv.items)
    items[i] = args[1]
    return same_kind(recv, items)


@method(LISTS, "inserted", 2, sig="fn(Int, T) -> List[T]")
def _inserted(interp, recv, args, span):
    i = want_int(args[0], "index")
    if not 0 <= i <= len(recv.items):
        raise Fault("A.INDEX.OUT_OF_RANGE", f"insert position {i} out of range for length {len(recv.items)}")
    items = list(recv.items)
    items.insert(i, args[1])
    return same_kind(recv, items)


@method(LISTS, "removedAt", 1, sig="fn(Int) -> List[T]")
def _removed_at(interp, recv, args, span):
    i = index_check(args[0], len(recv.items))
    items = list(recv.items)
    del items[i]
    return same_kind(recv, items)


@method(LISTS, "distinct", 0, sig="fn() -> List[T]")
def _distinct(interp, recv, args, span):
    seen = set()
    out = []
    for x in recv.items:
        k = hash_key(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return same_kind(recv, out)


@method(LISTS, "zip", 1, sig="fn(List[U]) -> List[(T, U)]")
def _zip(interp, recv, args, span):
    o = args[0]
    if type(o) not in (FrozenList, MutableList):
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"zip expects a List, found {type_name(o)}")
    return same_kind(recv, [TupleValue((a, b)) for a, b in zip(recv.items, o.items)])


@method(LISTS, "enumerate", 0, sig="fn() -> List[(Int, T)]")
def _enumerate(interp, recv, args, span):
    return same_kind(recv, [TupleValue((i, x)) for i, x in enumerate(recv.items)])


@method(LISTS, "join", 1, sig="fn(Str) -> Str")
def _join(interp, recv, args, span):
    sep = want_str(args[0], "separator")
    parts = []
    for x in recv.items:
        if type(x) is not str:
            raise Fault("A.TYPE.OPERAND_MISMATCH", f"join() requires a List of Str, found element {type_name(x)}",
                        help="map elements to strings first, e.g. `xs.map(fn(x) => \"{x}\").join(\", \")`")
        parts.append(x)
    return sep.join(parts)


@method(LISTS, "groupBy", 1, sig="fn(fn(T) -> K throws E) -> Map[K, List[T]] throws E")
def _group_by(interp, recv, args, span):
    groups: dict = {}
    for x in list(recv.items):
        k = _call(interp, args[0], [x], span)
        hk = hash_key(k)
        if hk not in groups:
            groups[hk] = (k, [])
        groups[hk][1].append(x)
    return fmap((k, flist(v)) for k, v in groups.values())


@method(LISTS, "toSet", 0, sig="fn() -> Set[T]")
def _to_set(interp, recv, args, span):
    return fset(recv.items)


@method(LISTS, "toList", 0, sig="fn() -> List[T]")
def _to_list(interp, recv, args, span):
    return recv if type(recv) is FrozenList else flist(recv.items)


@method(LISTS, "freeze", 0, sig="fn() -> List[T]")
def _freeze(interp, recv, args, span):
    if type(recv) is FrozenList:
        return recv
    return FrozenList(tuple(deep_freeze(x) for x in recv.items))


@method(LISTS, "mutableCopy", 0, sig="fn() -> MutableList[T]")
def _mcopy(interp, recv, args, span):
    return MutableList(list(recv.items))


# ---- MutableList only
def _check_elem(recv, x):
    no_borrow(x, "collection")
    if recv.elem_type is not None:
        pass  # element annotation checked by typed call sites (transient)
    return x


@method("MutableList", "push", 1, sig="fn(T) -> Unit")
def _push(interp, recv, args, span):
    recv.items.append(interp.check_elem_write(recv, _check_elem(recv, args[0]), span))
    touch(recv)
    return UNIT


@method("MutableList", "pop", 0, sig="fn() -> T?")
def _pop(interp, recv, args, span):
    if not recv.items:
        return NONE
    touch(recv)
    return some(recv.items.pop())


@method("MutableList", "insert", 2, sig="fn(Int, T) -> Unit")
def _insert(interp, recv, args, span):
    i = want_int(args[0], "index")
    if not 0 <= i <= len(recv.items):
        raise Fault("A.INDEX.OUT_OF_RANGE", f"insert position {i} out of range for length {len(recv.items)}")
    recv.items.insert(i, interp.check_elem_write(recv, _check_elem(recv, args[1]), span))
    touch(recv)
    return UNIT


@method("MutableList", "removeAt", 1, sig="fn(Int) -> T")
def _remove_at(interp, recv, args, span):
    i = index_check(args[0], len(recv.items))
    touch(recv)
    return recv.items.pop(i)


@method("MutableList", "remove", 1, sig="fn(T) -> Bool")
def _remove(interp, recv, args, span):
    for i, y in enumerate(recv.items):
        if lang_eq(args[0], y):
            del recv.items[i]
            touch(recv)
            return True
    return False


@method("MutableList", "set", 2, sig="fn(Int, T) -> Unit")
def _set(interp, recv, args, span):
    i = index_check(args[0], len(recv.items))
    recv.items[i] = interp.check_elem_write(recv, _check_elem(recv, args[1]), span)
    touch(recv)
    return UNIT


@method("MutableList", "clear", 0, sig="fn() -> Unit")
def _clear(interp, recv, args, span):
    recv.items.clear()
    touch(recv)
    return UNIT


@method("MutableList", "extend", 1, sig="fn(List[T]) -> Unit")
def _extend(interp, recv, args, span):
    o = args[0]
    if type(o) not in (FrozenList, MutableList):
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"extend expects a List, found {type_name(o)}")
    for x in list(o.items):
        recv.items.append(interp.check_elem_write(recv, _check_elem(recv, x), span))
    touch(recv)
    return UNIT


@method("MutableList", "sort", 0, sig="fn() -> Unit")
def _sort(interp, recv, args, span):
    recv.items[:] = _sorted(interp, list(recv.items), span)
    touch(recv)
    return UNIT


@method("MutableList", "sortBy", 1, sig="fn(fn(T) -> U throws E) -> Unit throws E")
def _sort_by(interp, recv, args, span):
    recv.items[:] = _sorted(interp, list(recv.items), span, args[0])
    touch(recv)
    return UNIT


@method("MutableList", "reverse", 0, sig="fn() -> Unit")
def _reverse(interp, recv, args, span):
    recv.items.reverse()
    touch(recv)
    return UNIT


# ============================================================================ Map & MutableMap
@prop(MAPS, "length", "Int")
def _map_len(interp, recv):
    return len(recv.data)


@method(MAPS, "isEmpty", 0, sig="fn() -> Bool", contract_safe=True)
def _map_empty(interp, recv, args, span):
    return not recv.data


@method(MAPS, "get", 1, sig="fn(K) -> V?", contract_safe=True)
def _map_get(interp, recv, args, span):
    e = recv.data.get(lookup_key(recv.data, args[0]))
    return NONE if e is None else some(e[1])


@method(MAPS, "getOrDefault", 2, sig="fn(K, V) -> V", contract_safe=True)
def _map_get_default(interp, recv, args, span):
    e = recv.data.get(lookup_key(recv.data, args[0]))
    return args[1] if e is None else e[1]


@method(MAPS, "containsKey", 1, sig="fn(K) -> Bool", contract_safe=True)
def _map_contains(interp, recv, args, span):
    return lookup_key(recv.data, args[0]) in recv.data


@method(MAPS, "keys", 0, sig="fn() -> List[K]", contract_safe=True)
def _map_keys(interp, recv, args, span):
    return FrozenList(tuple(k for k, _ in recv.data.values()))


@method(MAPS, "values", 0, sig="fn() -> List[V]", contract_safe=True)
def _map_values(interp, recv, args, span):
    vals = tuple(v for _, v in recv.data.values())
    if type(recv) is MutableMap:
        return MutableList(list(vals))
    return FrozenList(vals)


@method(MAPS, "entries", 0, sig="fn() -> List[(K, V)]")
def _map_entries(interp, recv, args, span):
    ents = tuple(TupleValue((k, v)) for k, v in recv.data.values())
    if type(recv) is MutableMap:
        return MutableList(list(ents))
    return FrozenList(ents)


@method(MAPS, "inserted", 2, sig="fn(K, V) -> Map[K, V]")
def _map_inserted(interp, recv, args, span):
    want_frozen_element(args[0], "Map key")
    want_frozen_element(args[1], "Map")
    data = dict(recv.data)
    data[hash_key(args[0])] = (args[0], args[1])
    return FrozenMap(data)


@method(MAPS, "removed", 1, sig="fn(K) -> Map[K, V]")
def _map_removed(interp, recv, args, span):
    data = dict(recv.data)
    data.pop(hash_key(args[0]), None)
    return FrozenMap(data)


@method(MAPS, "merged", 1, sig="fn(Map[K, V]) -> Map[K, V]")
def _map_merged(interp, recv, args, span):
    o = args[0]
    if type(o) not in (FrozenMap, MutableMap):
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"merged expects a Map, found {type_name(o)}")
    data = dict(recv.data)
    for k, e in o.data.items():
        want_frozen_element(e[1], "Map")
        data[k] = e
    return FrozenMap(data)


@method(MAPS, "mapValues", 1, sig="fn(fn(V) -> U throws E) -> Map[K, U] throws E")
def _map_map_values(interp, recv, args, span):
    return fmap((k, _call(interp, args[0], [v], span)) for k, v in list(recv.data.values()))


@method(MAPS, "filter", 1, sig="fn(fn(K, V) -> Bool throws E) -> Map[K, V] throws E")
def _map_filter(interp, recv, args, span):
    return fmap((k, v) for k, v in list(recv.data.values()) if want_bool(_call(interp, args[0], [k, v], span)))


@method(MAPS, "freeze", 0, sig="fn() -> Map[K, V]")
def _map_freeze(interp, recv, args, span):
    if type(recv) is FrozenMap:
        return recv
    return FrozenMap({hk: (k, deep_freeze(v)) for hk, (k, v) in recv.data.items()})


@method(MAPS, "mutableCopy", 0, sig="fn() -> MutableMap[K, V]")
def _map_mcopy(interp, recv, args, span):
    return MutableMap(dict(recv.data))


@method("MutableMap", "set", 2, sig="fn(K, V) -> Unit")
def _mmap_set(interp, recv, args, span):
    want_frozen_element(args[0], "Map key")
    no_borrow(args[1], "collection")
    recv.data[hash_key(args[0])] = (args[0], args[1])
    touch(recv)
    return UNIT


@method("MutableMap", "remove", 1, sig="fn(K) -> V?")
def _mmap_remove(interp, recv, args, span):
    e = recv.data.pop(lookup_key(recv.data, args[0]), None)
    if e is None:
        return NONE
    touch(recv)
    return some(e[1])


@method("MutableMap", "clear", 0, sig="fn() -> Unit")
def _mmap_clear(interp, recv, args, span):
    recv.data.clear()
    touch(recv)
    return UNIT


@method("MutableMap", "getOrInsert", 2, sig="fn(K, V) -> V")
def _mmap_get_or_insert(interp, recv, args, span):
    hk = hash_key(args[0])
    e = recv.data.get(hk)
    if e is None:
        want_frozen_element(args[0], "Map key")
        no_borrow(args[1], "collection")
        recv.data[hk] = (args[0], args[1])
        touch(recv)
        return args[1]
    return e[1]


# ============================================================================ Set & MutableSet
@prop(SETS, "length", "Int")
def _set_len(interp, recv):
    return len(recv.data)


@method(SETS, "isEmpty", 0, sig="fn() -> Bool", contract_safe=True)
def _set_empty(interp, recv, args, span):
    return not recv.data


@method(SETS, "contains", 1, sig="fn(T) -> Bool", contract_safe=True)
def _set_contains(interp, recv, args, span):
    return lookup_key(recv.data, args[0]) in recv.data


@method(SETS, "toList", 0, sig="fn() -> List[T]")
def _set_to_list(interp, recv, args, span):
    return FrozenList(tuple(recv.data.values()))


@method(SETS, "inserted", 1, sig="fn(T) -> Set[T]")
def _set_inserted(interp, recv, args, span):
    want_frozen_element(args[0], "Set")
    d = dict(recv.data)
    d[hash_key(args[0])] = args[0]
    return FrozenSet(d)


@method(SETS, "removed", 1, sig="fn(T) -> Set[T]")
def _set_removed(interp, recv, args, span):
    d = dict(recv.data)
    d.pop(hash_key(args[0]), None)
    return FrozenSet(d)


def _other_set(o):
    if type(o) not in (FrozenSet, MutableSet):
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"expected a Set, found {type_name(o)}")
    return o


@method(SETS, "union", 1, sig="fn(Set[T]) -> Set[T]")
def _set_union(interp, recv, args, span):
    d = dict(recv.data)
    d.update(_other_set(args[0]).data)
    return FrozenSet(d)


@method(SETS, "intersection", 1, sig="fn(Set[T]) -> Set[T]")
def _set_inter(interp, recv, args, span):
    o = _other_set(args[0]).data
    return FrozenSet({k: v for k, v in recv.data.items() if k in o})


@method(SETS, "difference", 1, sig="fn(Set[T]) -> Set[T]")
def _set_diff(interp, recv, args, span):
    o = _other_set(args[0]).data
    return FrozenSet({k: v for k, v in recv.data.items() if k not in o})


@method(SETS, "isSubsetOf", 1, sig="fn(Set[T]) -> Bool", contract_safe=True)
def _set_subset(interp, recv, args, span):
    o = _other_set(args[0]).data
    return all(k in o for k in recv.data)


@method(SETS, "freeze", 0, sig="fn() -> Set[T]")
def _set_freeze(interp, recv, args, span):
    return recv if type(recv) is FrozenSet else FrozenSet(dict(recv.data))


@method(SETS, "mutableCopy", 0, sig="fn() -> MutableSet[T]")
def _set_mcopy(interp, recv, args, span):
    return MutableSet(dict(recv.data))


@method("MutableSet", "add", 1, sig="fn(T) -> Bool")
def _mset_add(interp, recv, args, span):
    want_frozen_element(args[0], "Set")
    hk = hash_key(args[0])
    if hk in recv.data:
        return False
    recv.data[hk] = args[0]
    touch(recv)
    return True


@method("MutableSet", "remove", 1, sig="fn(T) -> Bool")
def _mset_remove(interp, recv, args, span):
    if recv.data.pop(lookup_key(recv.data, args[0]), None) is None:
        return False
    touch(recv)
    return True


@method("MutableSet", "clear", 0, sig="fn() -> Unit")
def _mset_clear(interp, recv, args, span):
    recv.data.clear()
    touch(recv)
    return UNIT


# ============================================================================ Tuple & Range
@prop("Tuple", "length", "Int")
def _tuple_len(interp, recv):
    return len(recv.items)


@prop("Range", "length", "Int")
def _range_len(interp, recv):
    return len(recv.as_range())


@method("Range", "toList", 0, sig="fn() -> List[Int]")
def _range_list(interp, recv, args, span):
    return FrozenList(tuple(recv.as_range()))


@method("Range", "contains", 1, sig="fn(Int) -> Bool", contract_safe=True)
def _range_contains(interp, recv, args, span):
    x = args[0]
    return type(x) is int and x in recv.as_range()


@method("Range", "map", 1, sig="fn(fn(Int) -> U throws E) -> List[U] throws E")
def _range_map(interp, recv, args, span):
    return flist([_call(interp, args[0], [x], span) for x in recv.as_range()])


@method("Range", "all", 1, sig="fn(fn(Int) -> Bool throws E) -> Bool throws E", contract_safe=True)
def _range_all(interp, recv, args, span):
    return all(want_bool(_call(interp, args[0], [x], span)) for x in recv.as_range())


@method("Range", "any", 1, sig="fn(fn(Int) -> Bool throws E) -> Bool throws E", contract_safe=True)
def _range_any(interp, recv, args, span):
    return any(want_bool(_call(interp, args[0], [x], span)) for x in recv.as_range())


# ============================================================================ constructors
@static("List", "of", 0, 10**9, sig="fn(T...) -> List[T]")
def _list_of(interp, args, span, tv=None):
    return flist(args)


@static("List", "repeat", 2, sig="fn(T, Int) -> List[T]")
def _list_repeat(interp, args, span, tv=None):
    n = want_int(args[1], "count")
    if n < 0:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "repeat count must be non-negative")
    return flist([args[0]] * n)


@static("List", "empty", 0, sig="fn() -> List[T]")
def _list_empty(interp, args, span, tv=None):
    return FrozenList(())


@static("Set", "of", 0, 10**9, sig="fn(T...) -> Set[T]")
def _set_of(interp, args, span, tv=None):
    return fset(args)


@static("Set", "empty", 0, sig="fn() -> Set[T]")
def _set_empty_s(interp, args, span, tv=None):
    return FrozenSet({})


@static("Map", "empty", 0, sig="fn() -> Map[K, V]")
def _map_empty_s(interp, args, span, tv=None):
    return FrozenMap({})


@static("MutableList", "of", 0, 10**9, sig="fn(T...) -> MutableList[T]")
def _mlist_of(interp, args, span, tv=None):
    for x in args:
        no_borrow(x, "collection")
    return MutableList(list(args))


@static("MutableSet", "of", 0, 10**9, sig="fn(T...) -> MutableSet[T]")
def _mset_of(interp, args, span, tv=None):
    d = {}
    for x in args:
        want_frozen_element(x, "Set")
        d[hash_key(x)] = x
    return MutableSet(d)


def deep_freeze(v):
    """Snapshot conversion used by `.freeze()`: mutable records/collections reachable
    from the receiver become frozen copies (V3 5.1.7: later mutation cannot change
    the frozen value)."""
    from ..values import MutableRecord, FrozenRecord, VariantValue
    t = type(v)
    if t is MutableList:
        return FrozenList(tuple(deep_freeze(x) for x in v.items))
    if t is MutableMap:
        return FrozenMap({hk: (k, deep_freeze(x)) for hk, (k, x) in v.data.items()})
    if t is MutableSet:
        return FrozenSet(dict(v.data))
    if t is MutableRecord:
        raise Fault("A.TYPE.FROZEN_MUTATION",
                    f"cannot freeze a mutable record ({v.rtype.name}) into a frozen collection",
                    help="convert it to a frozen record explicitly (e.g. a `snapshot()` method)")
    if t is VariantValue:
        return VariantValue(v.case, tuple(deep_freeze(x) for x in v.values), v.prov)
    if t is TupleValue:
        return TupleValue(tuple(deep_freeze(x) for x in v.items))
    return v
