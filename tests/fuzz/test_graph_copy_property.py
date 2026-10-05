"""Property test for task-boundary graph copy (V3 5.11, 7.10.10; TEST-FUZZ-004):
for random mutable graphs with sharing and cycles, the copy is isomorphic to the
source (aliases and cycles preserved), shares every frozen leaf, and contains no
mutable node of the source graph (no alias back)."""
import random

import pytest

from lang.runtime.equality import hash_key
from lang.runtime.isolation import Transfer
from lang.runtime.values import FrozenList, MutableList, MutableMap


def random_graph(rng: random.Random):
    nodes = []
    for _ in range(rng.randrange(1, 12)):
        nodes.append(MutableList([]) if rng.random() < 0.6 else MutableMap({}))
    leaves = [1, "s", 2.5, True, FrozenList((1, "x")), FrozenList(())]
    for n in nodes:
        for j in range(rng.randrange(0, 5)):
            child = rng.choice(nodes) if rng.random() < 0.5 else rng.choice(leaves)
            if isinstance(n, MutableList):
                n.items.append(child)
            else:
                k = rng.choice([j, f"k{j}"])
                n.data[hash_key(k)] = (k, child)
    return nodes[0], nodes


def edges(n):
    if isinstance(n, MutableList):
        return list(n.items)
    return [v for _, v in n.data.values()]


def is_mutable(v):
    return isinstance(v, (MutableList, MutableMap))


@pytest.mark.parametrize("seed", range(150))
def test_graph_copy_is_isomorphic_and_disjoint(seed):
    rng = random.Random(seed)
    root, nodes = random_graph(rng)
    copy = Transfer("property").value(root, "root")
    mapping = {}
    stack = [(root, copy)]
    while stack:
        s, d = stack.pop()
        if id(s) in mapping:
            assert mapping[id(s)] is d, "alias structure not preserved"
            continue
        assert type(s) is type(d) and d is not s
        mapping[id(s)] = d
        se, de = edges(s), edges(d)
        assert len(se) == len(de)
        if isinstance(s, MutableMap):
            assert [k for k, _ in s.data.values()] == [k for k, _ in d.data.values()]  # order kept
        for a, b in zip(se, de):
            if is_mutable(a):
                stack.append((a, b))
            else:
                assert a is b  # frozen values are shared, not copied
    reachable_src = {id(n) for n in nodes if id(n) in mapping}
    copied = list(mapping.values())
    assert not any(id(c) in reachable_src for c in copied), "copy aliases the source graph"
    assert len({id(c) for c in copied}) == len(mapping)  # one copy per source node


def test_mutating_the_copy_never_changes_the_source():
    rng = random.Random(7)
    root, _ = random_graph(rng)
    root.items.append(root) if isinstance(root, MutableList) else None
    before = repr([type(x).__name__ for x in edges(root)])
    c = Transfer("property").value(root, "root")
    if isinstance(c, MutableList):
        c.items.clear()
    else:
        c.data.clear()
    assert repr([type(x).__name__ for x in edges(root)]) == before
