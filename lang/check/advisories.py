"""Heuristic advisories that need only declarations and syntax (never blocking).

- W.INVARIANT.ACROSS_AWAIT (V3 8.8): inside a method of an invariant-bearing mutable
  record, an invariant-relevant field of `self` is assigned and a later cancellation
  point follows in the same method. Every cancellation point is a potential exit, so
  the invariant may be observed broken; the runtime re-checks it on a cancelled exit
  and abandons if it does not hold.
- W.STATE.PASS_THROUGH (V3 3.1 mutable-state horizon): a parameter of mutable type
  is never read or mutated by the function itself, only forwarded to other calls,
  so the state's horizon is wider than the code that needs it.
"""
from __future__ import annotations

from .. import typesys as T
from ..diagnostics import Label
from ..syntax import ast as A
from .types import is_mutable_type

CANCEL_NODES = (A.Await, A.Within, A.Parallel)


def is_cancel_point(n) -> bool:
    if isinstance(n, CANCEL_NODES):
        return True
    if isinstance(n, A.Select):
        return n.mode != "now"
    if isinstance(n, A.ForStmt) and getattr(n, "is_await", False):
        return True
    if isinstance(n, A.Call) and isinstance(n.callee, A.Field) and n.callee.name == "check" and \
            isinstance(n.callee.obj, A.Name) and n.callee.obj.name == "cancel":
        return True
    return False


def run_advisories(chk, mods) -> None:
    for mname, ms in mods:
        chk.cur_module = mname
        for d in ms.ast.decls:
            if isinstance(d, A.RecordDecl):
                ti = chk.types.get(f"{mname}.{d.name}")
                for m in d.methods:
                    if d.mutable and d.invariants and m.has_self and ti is not None:
                        invariant_across_await(chk, m, ti.invariant_fields, d.name)
                    pass_through(chk, m, ti.methods.get(m.name) if ti is not None else None)
            elif isinstance(d, A.EnumDecl):
                ti = chk.types.get(f"{mname}.{d.name}")
                for m in d.methods:
                    pass_through(chk, m, ti.methods.get(m.name) if ti is not None else None)
            elif isinstance(d, A.FnDecl):
                ent = chk.modules.get(mname, {}).get(d.name)
                pass_through(chk, d, ent[1] if ent is not None and ent[0] == "fn" else None)


def invariant_across_await(chk, m: A.FnDecl, fields, rname: str) -> None:
    if m.body is None or not fields:
        return
    nodes = sorted((n for n in A.walk(m.body) if isinstance(n, A.Node) and n.span is not None),
                   key=lambda n: n.span.start)
    mutation = None
    for n in nodes:
        if isinstance(n, A.Lambda):
            continue
        if mutation is None and isinstance(n, A.AssignStmt) and isinstance(n.target, A.Field) and \
                isinstance(n.target.obj, A.Name) and n.target.obj.name == "self" and n.target.name in fields:
            mutation = n
            continue
        if mutation is not None and is_cancel_point(n) and n.span.start > mutation.span.end:
            chk.advise("W.INVARIANT.ACROSS_AWAIT",
                       f"`{m.name}` mutates invariant field `{mutation.target.name}` of {rname} before this "
                       f"cancellation point; cancellation here exits with the invariant possibly broken", n.span,
                       secondary=[Label(mutation.span, "invariant-relevant mutation")],
                       help="compute before mutating, mutate after the await, or restore the invariant before "
                            "suspending (V3 8.8)")
            return


def pass_through(chk, d: A.FnDecl, sig) -> None:
    if d.body is None or sig is None:
        return
    for p, (pname, pty, _, borrow) in zip([p for p in d.params if not p.is_self], sig.params):
        if borrow or not is_mutable_type(pty) or isinstance(pty, T.TBorrow):
            continue
        uses = [n for n in A.walk(d.body) if isinstance(n, A.Name) and n.name == pname]
        if not uses:
            continue
        forwarded = set()
        for n in A.walk(d.body):
            if isinstance(n, A.Call):
                for a in n.args:
                    if isinstance(a.value, A.Name) and a.value.name == pname:
                        forwarded.add(id(a.value))
            elif isinstance(n, A.Spawn) and n.call is not None:
                for a in n.call.args:
                    if isinstance(a.value, A.Name) and a.value.name == pname:
                        forwarded.add(id(a.value))
        if forwarded and all(id(u) in forwarded for u in uses):
            chk.advise("W.STATE.PASS_THROUGH",
                       f"mutable parameter `{pname}` ({pty}) is only forwarded by `{d.name}`, never used by it",
                       p.span, help="pass the mutable state only to the code that uses it, or pass a narrower "
                                    "component (V3 3.1 mutable-state horizon)")
