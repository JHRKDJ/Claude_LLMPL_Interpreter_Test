"""Path analysis of resource-provider yields (V3 5.5.3; BUG-0031).

Abstract interpretation over the number of `yield`s executed, capped at 2 (meaning
"two or more"). Each construct maps the set of counts reachable at its entry to the
sets reachable when it falls through, returns, breaks or continues; paths that throw
are acquisition/release failures and are dropped. The provider is correct when every
normally completing path (falling off the end or returning) has executed exactly one
yield.
"""
from __future__ import annotations

from ..syntax import ast as A

CAP = 2
EMPTY = frozenset()


class Flow:
    __slots__ = ("fall", "ret", "brk", "cont")

    def __init__(self, fall=EMPTY, ret=EMPTY, brk=EMPTY, cont=EMPTY):
        self.fall, self.ret, self.brk, self.cont = frozenset(fall), frozenset(ret), frozenset(brk), frozenset(cont)

    def merge(self, o: "Flow") -> "Flow":
        return Flow(self.fall | o.fall, self.ret | o.ret, self.brk | o.brk, self.cont | o.cont)


def _bump(s):
    return frozenset(min(CAP, n + 1) for n in s)


def provider_exit_counts(body: A.Block) -> frozenset:
    f = block(body, frozenset({0}))
    return f.fall | f.ret


def block(b: A.Block, s) -> Flow:
    return stmts(b.stmts, s)


def stmts(sts, s) -> Flow:
    out = Flow()
    cur = frozenset(s)
    for st in sts:
        if not cur:
            break
        f = stmt(st, cur)
        out = Flow(EMPTY, out.ret | f.ret, out.brk | f.brk, out.cont | f.cont)
        cur = f.fall
    return Flow(cur, out.ret, out.brk, out.cont)


def stmt(st, s) -> Flow:
    c = st.__class__
    if c is A.ReturnStmt:
        f = expr(st.value, s) if st.value is not None else Flow(s)
        return Flow(EMPTY, f.ret | f.fall, f.brk, f.cont)
    if c is A.ThrowStmt:
        f = expr(st.value, s)
        return Flow(EMPTY, f.ret, f.brk, f.cont)
    if c is A.BreakStmt:
        return Flow(EMPTY, EMPTY, s, EMPTY)
    if c is A.ContinueStmt:
        return Flow(EMPTY, EMPTY, EMPTY, s)
    if c is A.WhileStmt or c is A.ForStmt:
        return loop(st, s)
    if c is A.DeferStmt:
        return Flow(s)
    return children(st, s)


def loop(st, s) -> Flow:
    always_runs = st.__class__ is A.WhileStmt and isinstance(st.cond, A.Literal) and st.cond.value is True
    head = st.cond if st.__class__ is A.WhileStmt else st.iterable
    entry = expr(head, s).fall
    exits = EMPTY if always_runs else entry  # zero iterations
    ret = EMPTY
    seen = EMPTY
    frontier = entry
    while frontier - seen:
        seen = seen | frontier
        f = block(st.body, frontier)
        ret |= f.ret
        exits |= f.brk
        again = f.fall | f.cont
        if not always_runs:
            exits |= again
        frontier = again
    return Flow(exits, ret, EMPTY, EMPTY)


def expr(e, s) -> Flow:
    if e is None:
        return Flow(s)
    c = e.__class__
    if c is A.Lambda:
        return Flow(s)  # a yield inside a lambda is rejected separately
    if c is A.Yield:
        f = expr(e.value, s)
        return Flow(_bump(f.fall), f.ret, f.brk, f.cont)
    if c is A.If:
        f = expr(e.cond, s)
        then = block(e.then, f.fall)
        if e.else_ is None:
            other = Flow(f.fall)
        elif e.else_.__class__ is A.If:
            other = expr(e.else_, f.fall)
        else:
            other = block(e.else_, f.fall)
        return Flow(EMPTY, f.ret, f.brk, f.cont).merge(then).merge(other)
    if c is A.Match:
        f = expr(e.scrutinee, s)
        out = Flow(EMPTY, f.ret, f.brk, f.cont)
        for arm in e.arms:
            out = out.merge(block(arm.body, f.fall) if arm.body.__class__ is A.Block else expr(arm.body, f.fall))
        return out
    if c is A.Block:
        return block(e, s)
    return children(e, s)


def children(node, s) -> Flow:
    out = Flow()
    cur = frozenset(s)
    for ch in A.iter_children(node):
        if not cur:
            break
        if isinstance(ch, A.Block):
            f = block(ch, cur)
        elif isinstance(ch, A.Stmt):
            f = stmt(ch, cur)
        elif isinstance(ch, A.Expr):
            f = expr(ch, cur)
        else:
            continue
        out = Flow(EMPTY, out.ret | f.ret, out.brk | f.brk, out.cont | f.cont)
        cur = f.fall
    return Flow(cur, out.ret, out.brk, out.cont)
