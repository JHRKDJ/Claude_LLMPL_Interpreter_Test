"""Static rules for `select` (V3 5.14, 7.12, 8.13-8.17; SPEC-019)."""
from __future__ import annotations

from .. import typesys as T
from ..syntax import ast as A
from .types import DYN, consistent

PURE_NODES = (A.Name, A.Literal, A.Field, A.Binary, A.Unary, A.TupleLit, A.ListLit, A.MapLit, A.StringLit, A.Range)


def is_pure_setup(e) -> bool:
    """Branch setup may use endpoints, handles, precomputed values, deadlines and
    restricted pure expressions; effectful construction (calls, awaits...) is prohibited."""
    for n in A.walk(e):
        if isinstance(n, A.InterpPart):
            continue
        if not isinstance(n, PURE_NODES):
            return False
    return True


class SelectCheckMixin:
    def x_Select(self, e: A.Select, sc):
        from .typecheck import Scope
        fs = self.fn_stack[-1] if self.fn_stack else None
        if fs is not None and e.mode != "now":
            fs.has_cancel_point = True
        has_none = any(b.kind == "none" for b in e.branches)
        if e.mode == "now" and not has_none:
            self.legal("S.SELECT.NONE_READY_PLACEMENT", "`select now` requires a `none ready` branch", e.span)
        if e.mode != "now" and has_none:
            nb = next(b for b in e.branches if b.kind == "none")
            self.legal("S.SELECT.NONE_READY_PLACEMENT", "blocking `select` has no default branch; `none ready` "
                       "belongs to `select now`", nb.span,
                       help="use `select now { ... none ready => ... }` for a non-blocking check")
        closed_targets = {b.target.span.text for b in e.branches if b.kind == "closed" and b.target is not None}
        result = T.NEVER
        in_loop = fs is not None and fs.loop_depth > 0
        throws_closed = False
        for b in e.branches:
            bsc = Scope(sc)
            for x in (b.target, b.value):
                if x is not None and not is_pure_setup(x):
                    self.legal("S.SELECT.IMPURE_SETUP", "select branch setup must be a precomputed value (no calls, "
                               "awaits or other effects)", x.span,
                               help="compute it before the select: `let v = ...` then `send v to port`")
            if b.guard is not None and b.guard not in ("true", "false"):
                ent = sc.get(b.guard)
                gt = ent[0] if ent is not None else self.global_type(b.guard)
                if not consistent(gt, T.BOOL):
                    self.legal("S.SELECT.INVALID_GUARD", f"select guard `{b.guard}` must be a Bool, found {gt}",
                               b.guard_span)
            k = b.kind
            if k in ("receive", "closed"):
                pt = self.expr(b.target, sc)
                elem = DYN
                if isinstance(pt, T.TCon) and pt.name == "ReceivePort":
                    elem = pt.args[0]
                elif pt is not DYN:
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"`{k}` branch needs a ReceivePort, found {pt}", b.target.span)
                if k == "receive":
                    if b.target.span.text not in closed_targets:
                        throws_closed = True
                    if b.binding:
                        bsc.vars[b.binding] = (elem, "pattern", b.span)
                if k == "closed" and in_loop and not _exits(b.body):
                    self.advise("W.SELECT.CLOSED_LOOP",
                                "closed branch inside a loop neither exits nor changes eligibility; a closed channel "
                                "stays ready and will win repeatedly", b.span,
                                help="break/return in the closed branch, or use a guard to disable the branch")
            elif k == "send":
                vt = self.expr(b.value, sc)
                pt = self.expr(b.target, sc)
                if isinstance(pt, T.TCon) and pt.name == "SendPort":
                    if not consistent(vt, pt.args[0], self.satisfies):
                        self.oblig("S.TYPE.STATIC_MISMATCH", f"cannot send {vt} on SendPort[{pt.args[0]}]",
                                   b.value.span)
                elif pt is not DYN:
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"`send` branch needs a SendPort, found {pt}", b.target.span)
                self.check_sendable(vt, b.value, "select send")
                throws_closed = True
            elif k == "task":
                ht = self.expr(b.target, sc)
                rt = T.TCon("Result", (DYN, DYN))
                if isinstance(ht, T.TCon) and ht.name == "Task":
                    rt = T.TCon("Result", (ht.args[0], ht.args[1]))
                elif ht is not DYN:
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"`task` branch needs a task handle, found {ht}",
                               b.target.span)
                if b.binding:
                    bsc.vars[b.binding] = (rt, "pattern", b.span)
            elif k == "at":
                dt = self.expr(b.target, sc)
                if dt not in (T.INSTANT, DYN):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"`at` needs an Instant, found {dt}", b.target.span,
                               help="use `after <Duration>` for a relative timeout")
            elif k == "after":
                dt = self.expr(b.target, sc)
                if dt not in (T.DURATION, DYN):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"`after` needs a Duration, found {dt}", b.target.span)
                if in_loop:
                    self.advise("W.SELECT.DEADLINE_RESET",
                                "relative `after` inside a loop computes a fresh deadline on every iteration and may "
                                "postpone the timeout indefinitely", b.span,
                                help="compute `let deadline = time.now() + d` before the loop and use `at deadline`")
            bt = self.block(b.body, bsc, new_scope=False) if isinstance(b.body, A.Block) else self.expr(b.body, bsc)
            result = _join(result, bt)
        if e.mode == "priority" and in_loop:
            self.advise("W.SELECT.STARVATION", "`select priority` in a loop may starve later branches", e.span,
                        help="use the default rotating select unless strict priority is intended")
        if e.mode == "now" and in_loop and fs is not None:
            loop_has_point = getattr(fs, "has_cancel_point", False)
            if not loop_has_point:
                self.advise("W.SELECT.BUSY_POLL", "`select now` repeated in a loop without any suspension point is a "
                            "busy poll", e.span, help="use a blocking `select` (with a deadline if needed)")
        if throws_closed:
            self.raise_eff(["core.ChannelClosed"], False, e.span)
        return DYN if result is T.NEVER else result


def _join(a, b):
    from .types import join
    return join(a, b)


def _exits(body) -> bool:
    for n in A.walk(body):
        if isinstance(n, (A.BreakStmt, A.ReturnStmt, A.ThrowStmt)):
            return True
    return False
