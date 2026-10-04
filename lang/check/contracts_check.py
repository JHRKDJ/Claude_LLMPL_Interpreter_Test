"""Restricted contract-expression language and predicate rules (V3 5.10.3-5, 7.8.2).

Permitted: literals, names (parameters, fields, `self`, `result`, constants, enum
cases), field reads, arithmetic/comparison/Boolean operators, `is` patterns, `match`
and `if` expressions over permitted parts, collection literals, ranges, calls of
predicates, `old(...)` in ensures, and total read-only builtin queries (length,
contains, get, isEmpty, all/any/count with an inline lambda in the same subset...).
Prohibited: mutation, I/O, awaiting/spawning/select/resources, throwing/try/capture,
unsafe indexing (`xs[i]`; use `xs.get(i)`), allocation-heavy transforms, general
calls of functions or user methods, and recursion among predicates.
"""
from __future__ import annotations

from ..runtime.builtins.registry import METHODS, PRELUDE
from ..syntax import ast as A
from .types import kind_of_type


def check_contract_expr(chk, e, kind: str, mname: str) -> None:
    for n in A.walk(e):
        reason = _violation(chk, n, kind, mname)
        if reason:
            chk.legal("S.CONTRACT.RESTRICTED", f"not allowed in a {kind} clause: {reason}", n.span,
                      help="contracts use a restricted, total, effect-free subset; move complex logic into a "
                           "`predicate` or check it in the body")
            return


def _violation(chk, n, kind, mname):
    c = n.__class__
    if c in (A.Await, A.Spawn, A.Parallel, A.Select, A.Use, A.Within, A.Yield):
        return "concurrency/resource operations"
    if c in (A.Try, A.Capture, A.Propagate):
        return "error handling (contracts must be total)"
    if c is A.Index:
        return "unsafe indexing `xs[i]` (use `xs.get(i)`)"
    if c is A.Lambda:
        return None if n.ann.get("_contract_ok") else "closures outside quantifier calls"
    if c is A.If and n.then is not None:
        for b in (n.then, n.else_ if isinstance(n.else_, A.Block) else None):
            if b is not None and any(not isinstance(s, A.ExprStmt) for s in b.stmts):
                return "statements inside contract expressions"
    if c is A.Call:
        callee = n.callee
        if isinstance(callee, A.Name):
            if callee.name == "old":
                if kind not in ("ensures",):
                    return "`old` outside ensures"
                return None
            ent = chk.lookup_global(mname, callee.name)
            if ent is not None and ent[0] == "predicate":
                return None
            if callee.name in ("Some", "Ok", "Err"):
                return None
            if ent is not None and ent[0] == "prelude" and getattr(ent[1], "contract_safe", False):
                return None
            if ent is not None and ent[0] == "type":
                return None
            return f"call of `{callee.name}` (only predicates may be called)"
        if isinstance(callee, A.Field):
            name = callee.name
            # enum case / associated: Type.Case(...)
            if isinstance(callee.obj, A.Name):
                ent = chk.lookup_global(mname, callee.obj.name)
                if ent is not None and ent[0] == "type":
                    return None
            for k, table in METHODS.items():
                b = table.get(name)
                if b is not None and b.contract_safe:
                    for a in n.args:
                        if isinstance(a.value, A.Lambda) and not a.value.is_block:
                            a.value.ann["_contract_ok"] = True
                    return None
            return f"method call `.{name}(...)` (only total read-only queries are allowed)"
        return "general calls"
    return None


def check_predicate(chk, d: A.PredicateDecl, mname: str) -> None:
    body = d.body
    if body is None:
        return
    if len(body.stmts) != 1 or not isinstance(body.stmts[0], A.ExprStmt):
        chk.legal("S.CONTRACT.RESTRICTED", f"predicate `{d.name}` body must be a single Bool expression", d.span)
        return
    check_contract_expr(chk, body.stmts[0].expr, "predicate", mname)
    # recursion among predicates (direct or indirect)
    graph = _predicate_graph(chk, mname)
    if _reaches(graph, d.name, d.name):
        chk.legal("S.CONTRACT.RECURSIVE_PREDICATE", f"predicate `{d.name}` is recursive", d.span,
                  help="predicates must be non-recursive so contract evaluation is bounded")


def _predicate_graph(chk, mname):
    cache = getattr(chk, "_pred_graph", None)
    if cache is not None and mname in cache:
        return cache[mname]
    graph = {}
    ms = chk.program.modules.get(mname)
    for d in ms.ast.decls:
        if isinstance(d, A.PredicateDecl) and d.body is not None:
            calls = set()
            for n in A.walk(d.body):
                if isinstance(n, A.Call) and isinstance(n.callee, A.Name):
                    calls.add(n.callee.name)
            graph[d.name] = calls
    if cache is None:
        chk._pred_graph = {}
    chk._pred_graph[mname] = graph
    return graph


def _reaches(graph, start, target) -> bool:
    seen = set()
    stack = list(graph.get(start, ()))
    while stack:
        x = stack.pop()
        if x == target:
            return True
        if x in seen:
            continue
        seen.add(x)
        stack.extend(graph.get(x, ()))
    return False
