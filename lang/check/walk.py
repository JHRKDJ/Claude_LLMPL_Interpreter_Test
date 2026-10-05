"""Body walker for the static checker: statements and expressions with types and
effects. Mixed into `Checker` (typecheck.py)."""
from __future__ import annotations

from typing import Optional

from .. import typesys as T
from ..diagnostics import Label
from ..runtime.builtins.registry import METHODS, MODULES, PRELUDE, PROPS, STATICS
from ..runtime.core_types import ALL_CORE_TYPES
from ..runtime.values import TypeValue
from ..syntax import ast as A
from .decls import FnSig, TypeInfo
from .exhaustive import check_match
from .types import DYN, consistent, is_mutable_type, join, kind_of_type, receiver_bindings, sig_type, unify

AGG = "core.AggregateException"
DEADLINE = "core.DeadlineExceeded"
CHCLOSED = "core.ChannelClosed"
CORE_CASES = {"Some", "None", "Ok", "Err"}


def short(q: str) -> str:
    return q.rsplit(".", 1)[-1] if not q.startswith("$") else q[1:]


class WalkMixin:
    # ------------------------------------------------------------------ module bodies
    def check_module_bodies(self, mname: str, mod: A.Module) -> None:
        from .typecheck import FnState, Scope
        self.cur_module = mname
        for d in mod.decls:
            if isinstance(d, A.FnDecl):
                sig = self.modules[mname][d.name][1]
                self.check_fn(d, sig, None)
            elif isinstance(d, (A.RecordDecl, A.EnumDecl)):
                ti = self.types[f"{mname}.{d.name}"]
                for m in d.methods:
                    self.check_fn(m, ti.methods[m.name], ti)
                if isinstance(d, A.RecordDecl):
                    from .contracts_check import check_contract_expr
                    for inv in d.invariants:
                        sc = Scope()
                        for fname, fty in ti.fields.items():
                            sc.vars[fname] = (fty, "field", None)
                        sc.vars["self"] = (ti.ty, "param", None)
                        self.fn_stack.append(FnState(None, d, False, "contract", ti))
                        try:
                            self.with_collector(lambda: self.expr(inv, sc))
                        finally:
                            self.fn_stack.pop()
                        check_contract_expr(self, inv, "invariant", mname)
            elif isinstance(d, A.ConstDecl):
                sc = Scope()
                self.fn_stack.append(FnState(None, d, False, "const"))
                try:
                    t = self.with_collector(lambda: self.expr(d.value, sc))[0]
                finally:
                    self.fn_stack.pop()
                ent = self.modules[mname].get(d.name)
                if ent is not None and ent[1] is None:
                    self.modules[mname][d.name] = ("const", t)
                if is_mutable_type(t):
                    self.legal("S.MODULE.MUTABLE_GLOBAL", f"module constant `{d.name}` would hold a mutable {t}",
                               d.value.span, label="this value is mutable",
                               help="module-level state must be frozen (V3 5.2); create mutable state in `main` "
                                    "and pass it explicitly to the code that needs it")
                if d.type is not None:
                    want = self.ty(d.type, mname)
                    if not consistent(t, want, self.satisfies):
                        self.oblig("S.TYPE.STATIC_MISMATCH", f"constant `{d.name}` is {t}, annotation says {want}",
                                   d.value.span, expected=str(want), found=str(t))
            elif isinstance(d, A.TestDecl):
                sc = Scope()
                self.fn_stack.append(FnState(None, d, True, "test"))
                try:
                    self.with_collector(lambda: self.block(d.body, sc))
                finally:
                    self.fn_stack.pop()

    def with_collector(self, fn):
        from .typecheck import Collector
        c = Collector()
        self.eff_stack.append(c)
        try:
            r = fn()
        finally:
            self.eff_stack.pop()
        return r, c

    def raise_eff(self, names, unknown, span) -> None:
        if self.eff_stack:
            self.eff_stack[-1].add(names, unknown, span)

    # ------------------------------------------------------------------ functions
    def check_fn(self, d: A.FnDecl, sig: FnSig, owner: Optional[TypeInfo]) -> None:
        from .typecheck import FnState, Scope
        from .contracts_check import check_contract_expr
        sc = Scope()
        if d.has_self and owner is not None:
            sc.vars["self"] = (owner.ty, "param", d.params[0].span)
        for (name, t, _, borrow), p in zip(sig.params, [p for p in d.params if not p.is_self]):
            sc.vars[name] = (t, "borrowparam" if borrow else "param", p.span)
            if p.type is not None:
                sc.origins[name] = p.type.span
        st = FnState(sig, d, d.is_async, "fn", owner)
        self.fn_stack.append(st)
        try:
            for kind, clauses in (("requires", d.requires), ("ensures", d.ensures)):
                for c in clauses:
                    csc = Scope(sc)
                    if kind == "ensures":
                        csc.vars["result"] = (sig.ret if sig.ret_written else DYN, "result", c.span)
                    cst = FnState(sig, d, False, "contract", owner)
                    self.fn_stack.append(cst)
                    try:
                        t, _ = self.with_collector(lambda c=c, csc=csc: self.expr(c, csc))
                    finally:
                        self.fn_stack.pop()
                    if self.report:
                        check_contract_expr(self, c, kind, self.cur_module)
                        if not consistent(t, T.BOOL):
                            self.oblig("S.TYPE.STATIC_MISMATCH", f"{kind} clause must be a Bool, found {t}", c.span)
            if d.body is None:
                return
            d.body.ann["value_discarded"] = True  # function bodies return only via `return`
            _, coll = self.with_collector(lambda: self.block(d.body, sc))
        finally:
            self.fn_stack.pop()
        names = frozenset(coll.names)
        if sig.effect is None:
            sig.inferred = names
            sig.inferred_unknown = coll.unknown
            d.ann["effect"] = None if coll.unknown else frozenset(n for n in names if not n.startswith("$"))
        if self.report:
            self.check_escaping(d, sig, coll)
            if d.is_resource:
                self.check_yield_count(d)
            if d.is_async:
                self.check_cancel_points(d)

    def check_escaping(self, d, sig: FnSig, coll) -> None:
        declared = sig.effect
        if declared is None:
            if coll.names:
                first = sorted(coll.names)[0]
                listing = ", ".join(sorted(short(n) for n in coll.names))
                self.oblig("S.EFFECT.UNDECLARED_THROWS",
                           f"`{d.name}` may let {listing} escape but declares no `throws` clause",
                           coll.names[first] or d.span,
                           secondary=[Label(d.name_span or d.span, f"`{d.name}` declared here")],
                           help=f"add `throws {listing}` to `{d.name}`, or handle the error locally")
            return
        allow_vars = any(n.startswith("$") for n in declared)
        for n, site in coll.names.items():
            if n in declared:
                continue
            if n.startswith("$") and n in declared:
                continue
            if allow_vars and n.startswith("$"):
                continue
            self.oblig("S.EFFECT.UNDECLARED_THROWS",
                       f"{short(n)} may escape `{d.name}`, but its throws clause does not declare it",
                       site or d.span, secondary=[Label(d.name_span or d.span, f"`{d.name}` declared here")],
                       help=f"add `{short(n)}` to the throws clause or handle it with `try ... catch {short(n)} => ...`")

    def check_yield_count(self, d: A.FnDecl) -> None:
        from .yieldflow import provider_exit_counts
        counts = provider_exit_counts(d.body)
        if counts != {1}:
            found = ("no" if counts <= {0} else "two or more" if counts <= {2}
                     else "a path-dependent number of")
            self.oblig("S.RESOURCE.YIELD_COUNT",
                       f"provider `{d.name}` must yield exactly once on every path that completes normally "
                       f"(found {found} yield(s))", d.name_span or d.span,
                       help="acquire, `yield` the resource once, then release; signal acquisition failure by throwing")

    def check_cancel_points(self, d: A.FnDecl) -> None:
        for n in A.walk(d.body):
            if isinstance(n, A.WhileStmt) or (isinstance(n, A.ForStmt) and not n.is_await):
                body_nodes = list(A.walk(n.body)) + list(A.walk(n.cond if isinstance(n, A.WhileStmt) else n.iterable))
                has_point = any(isinstance(x, (A.Await, A.Parallel, A.Within)) or
                                (isinstance(x, A.Select) and x.mode != "now") or  # select now never waits
                                (isinstance(x, A.Call) and isinstance(x.callee, A.Field) and x.callee.name == "check"
                                 and isinstance(x.callee.obj, A.Name) and x.callee.obj.name == "cancel")
                                for x in body_nodes)
                is_forever = isinstance(n, A.WhileStmt) and isinstance(n.cond, A.Literal) and n.cond.value is True
                if not has_point and (is_forever or self.verified):
                    self.advise("W.CANCEL.NO_CANCELLATION_POINT",
                                "async loop has no reachable cancellation point (await, cancel.check(), channel "
                                "operation or select)", n.span,
                                help="call `cancel.check()` between chunks of CPU-bound work (V3 7.10.2)")

    # ------------------------------------------------------------------ statements
    def block(self, b: A.Block, scope, new_scope: bool = True) -> T.Ty:
        from .typecheck import Scope, Collector
        sc = Scope(scope) if new_scope else scope
        result = T.UNIT
        defer_throw = 0
        defer_effects = []
        body_coll = Collector()
        self.eff_stack.append(body_coll)
        try:
            for st in b.stmts:
                if isinstance(st, A.DeferStmt):
                    _, dc = self.with_collector(lambda st=st: (self.block(st.body, sc) if isinstance(st.body, A.Block)
                                                               else self.expr(st.body, sc)))
                    if not dc.empty:
                        defer_throw += 1
                        defer_effects.append((list(dc.names), dc.unknown, st.span))
                    result = T.UNIT
                    continue
                if isinstance(st, A.ExprStmt):
                    if isinstance(st.expr, A.Select) and (st is not b.stmts[-1] or b.ann.get("value_discarded")):
                        st.expr.ann["_value_unused"] = True
                    result = self.expr(st.expr, sc)
                else:
                    self.stmt(st, sc)
                    # control leaves the block: its value is never produced (BUG-0010)
                    result = T.NEVER if isinstance(st, (A.ReturnStmt, A.BreakStmt, A.ContinueStmt,
                                                        A.ThrowStmt)) else T.UNIT
        finally:
            self.eff_stack.pop()
        # V3 5.6: a cleanup failure after normal completion is thrown as is; only a body
        # failure (or another cleanup failure) plus a cleanup failure aggregates (BUG-0032)
        body_can_throw = bool(body_coll.names) or body_coll.unknown
        for names, unknown, span in defer_effects:
            body_coll.add(names, unknown, span)
        if defer_throw and (defer_throw > 1 or body_can_throw):
            body_coll.add([AGG], False, b.span)
        for n, s in body_coll.names.items():
            self.raise_eff([n], False, s)
        if body_coll.unknown:
            self.raise_eff([], True, body_coll.unknown_site or b.span)
        return result

    def stmt(self, st, sc) -> None:
        c = st.__class__
        fs = self.fn_stack[-1] if self.fn_stack else None
        if c is A.LetStmt:
            t = self.expr(st.value, sc) if st.value is not None else None
            self.check_parallel_value(st.value)
            ann = self.ty(st.type, self.cur_module, self.tparams()) if st.type is not None else None
            if t is not None and ann is not None and not consistent(t, ann, self.satisfies):
                self.mismatch(st.value.span, ann, t, "binding annotation", st.type.span)
            if t is not None and isinstance(t, T.TBorrow):
                self.oblig("S.RESOURCE.ESCAPE", "a resource cannot be bound with `let`", st.span,
                           help="use the `use` binding directly; pass it to helpers as a `borrow` parameter")
            if st.value is not None and isinstance(st.value, A.Lambda):
                self.check_lambda_escape(st.value, "bound to a variable")
            if st.destructure:
                items = t.items if isinstance(t, T.TTuple) else None
                if t is not None and t is not DYN and not isinstance(t, (T.TTuple, T.TVar)) and t is not T.NEVER:
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"cannot destructure {t} into {len(st.names)} names: it is "
                               f"not a tuple", st.value.span,
                               help="unwrap the Option first (e.g. `match e { Some((a, b)) => ... }`)"
                               if isinstance(t, T.TCon) and t.name == "Option" else None)
                elif items is not None and len(items) != len(st.names):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"tuple has {len(items)} elements, {len(st.names)} names "
                               f"given", st.value.span)
                for i, (name, span) in enumerate(st.names):
                    it = items[i] if items is not None and i < len(items) else DYN
                    sc.vars[name] = (it, "let", span)
            else:
                name, span = st.names[0]
                sc.vars[name] = (ann if ann is not None else (t if t is not None else DYN), "let", span)
                if st.type is not None:
                    sc.origins[name] = st.type.span
                else:
                    o = self.origin_of(st.value, sc) if st.value is not None else None
                    if o is not None:
                        sc.origins[name] = o
            return
        if c is A.AssignStmt:
            vt = self.expr(st.value, sc)
            self.check_parallel_value(st.value)
            tgt = st.target
            if isinstance(tgt, A.Name):
                ent = sc.get(tgt.name)
                if ent is not None:
                    par = self.enclosing_parallel()
                    if par is not None and contains_task(vt) and ent[2] is not None and \
                            ent[2].file is par.span.file and ent[2].start < par.span.start:
                        self.legal("S.TASK.HANDLE_ESCAPE",
                                   f"task handle assigned to `{tgt.name}`, which outlives the `parallel` block that "
                                   f"owns the task", st.span, secondary=[Label(par.span, "owning task group")],
                                   help="await the handle (or select on it) inside the block and assign the result")
                    if isinstance(vt, T.TBorrow):
                        self.oblig("S.RESOURCE.ESCAPE", "a resource cannot be assigned to an ordinary binding",
                                   st.span)
                    want = ent[0]
                    if st.op == "=" and want is not DYN and ent[1] in ("let", "param") and \
                            not consistent(vt, want, self.satisfies) and want is not None:
                        decl_ann = None
                        self.mismatch(st.value.span, want, vt, "binding type", decl_ann)
            elif isinstance(tgt, A.Field):
                ot = self.expr(tgt.obj, sc)
                self.check_field_assign(tgt, ot, vt, st)
            elif isinstance(tgt, A.Index):
                ot = self.expr(tgt.obj, sc)
                for i in tgt.indices:
                    self.expr(i, sc)
                if isinstance(ot, T.TCon) and ot.name in ("List", "Map", "Set"):
                    self.oblig("S.TYPE.FROZEN_MUTATION", f"cannot assign into a frozen {ot.name}", tgt.span,
                               help="use a Mutable collection or build an updated copy")
            return
        if c is A.ReturnStmt:
            if st.value is not None:
                t = self.expr(st.value, sc)
                self.check_parallel_value(st.value)
                par = self.enclosing_parallel()
                if par is not None and contains_task(t):
                    self.legal("S.TASK.HANDLE_ESCAPE", "a task handle cannot be returned out of the `parallel` block "
                               "that owns the task", st.value.span, secondary=[Label(par.span, "owning task group")],
                               help="return the awaited result instead")
                if isinstance(t, T.TBorrow):
                    self.oblig("S.RESOURCE.ESCAPE", "a resource borrow cannot be returned", st.value.span)
                if isinstance(st.value, A.Lambda):
                    self.check_lambda_escape(st.value, "returned")
                if fs is not None and fs.sig is not None and fs.sig.ret_written and fs.kind == "fn":
                    want = fs.sig.ret
                    if not consistent(t, want, self.satisfies):
                        self.mismatch(st.value.span, want, t, "return type", fs.decl.ret.span if fs.decl.ret else None)
            elif fs is not None and fs.sig is not None and fs.sig.ret_written and fs.kind == "fn" and \
                    fs.sig.ret not in (T.UNIT, DYN):
                self.oblig("S.TYPE.STATIC_MISMATCH", f"`return` without a value in a function returning {fs.sig.ret}",
                           st.span)
            return
        if c is A.ThrowStmt:
            t = self.expr(st.value, sc)
            if isinstance(t, T.TNominal):
                ti = self.types.get(t.qualname)
                if ti is not None and not ti.is_error:
                    self.legal("S.EFFECT.NOT_AN_ERROR", f"{ti.name} is not a declared error type and cannot be thrown",
                               st.value.span, help=f"declare it with `error {ti.name} {{ ... }}`")
                    return
                self.raise_eff([t.qualname], False, st.span)
            elif t is DYN:
                self.raise_eff([], True, st.span)
            else:
                self.legal("S.EFFECT.NOT_AN_ERROR", f"a {t} value cannot be thrown", st.value.span)
            return
        if c is A.AssertStmt:
            t = self.expr(st.cond, sc)
            if not consistent(t, T.BOOL):
                self.oblig("S.TYPE.STATIC_MISMATCH", f"assert condition must be Bool, found {t}", st.cond.span)
            if st.message is not None:
                self.expr(st.message, sc)
            return
        if c is A.WhileStmt:
            from .typecheck import Scope
            body_sc = Scope(sc)
            self.cond(st.cond, sc, body_sc)
            fs.loop_depth += 1 if fs else 0
            try:
                st.body.ann["value_discarded"] = True
                self.block(st.body, body_sc, new_scope=False)
            finally:
                if fs:
                    fs.loop_depth -= 1
            return
        if c is A.ForStmt:
            from .typecheck import Scope
            it = self.expr(st.iterable, sc)
            elem = DYN
            if isinstance(it, T.TCon):
                if it.name in ("List", "MutableList", "Set", "MutableSet"):
                    elem = it.args[0]
                elif it.name in ("Map", "MutableMap"):
                    self.oblig("S.TYPE.STATIC_MISMATCH", "maps are not directly iterable", st.iterable.span,
                               help="iterate `.keys()`, `.values()` or `.entries()`")
                elif it.name == "ReceivePort":
                    elem = it.args[0]
                    if not st.is_await:
                        self.legal("S.ASYNC.MISSING_AWAIT", "iterating a ReceivePort waits for messages: write "
                                   "`for await x in port`", st.span)
            elif it == T.RANGE:
                elem = T.INT
            elif it in (T.STR, T.INT, T.FLOAT, T.BOOL):
                self.oblig("S.TYPE.STATIC_MISMATCH", f"{it} is not iterable", st.iterable.span,
                           help="iterate `.chars()` for strings" if it == T.STR else None)
            if st.is_await:
                self.raise_eff([], False, st.span)
                if fs:
                    fs.has_cancel_point = True
            origin = self.origin_of(st.iterable, sc)
            if origin is not None and needs_rt_check(elem):
                st.ann["rt_check"] = (elem, origin)
            body_sc = Scope(sc)
            self.with_pattern_origin(origin, lambda: self.bind_pattern(st.pattern, elem, body_sc))
            if fs:
                fs.loop_depth += 1
            try:
                st.body.ann["value_discarded"] = True
                st.body.ann["value_discarded"] = True
                self.block(st.body, body_sc, new_scope=False)
            finally:
                if fs:
                    fs.loop_depth -= 1
            return
        if c is A.OnAbandonStmt:
            self.check_on_abandon(st, sc)
            return
        if c in (A.BreakStmt, A.ContinueStmt, A.NonlocalStmt):
            return
        if c is A.ExprStmt:
            self.expr(st.expr, sc)

    def tparams(self) -> frozenset:
        out = set()
        for fs in self.fn_stack:
            d = fs.decl
            if d is not None:
                out |= set(getattr(d, "type_params", []) or [])
            if fs.owner is not None:
                out |= set(fs.owner.type_params)
        return frozenset(out)

    def check_on_abandon(self, st: A.OnAbandonStmt, sc) -> None:
        call = st.call
        ok = isinstance(call, A.Call) and isinstance(call.callee, A.Field) and not call.args
        if ok:
            rt = self.expr(call.callee.obj, sc)
            inner = rt.inner if isinstance(rt, T.TBorrow) else rt
            k = kind_of_type(inner)
            b = METHODS.get(k, {}).get(call.callee.name) if k else None
            ok = b is not None and b.abandon_safe
        if not ok:
            self.legal("S.RESOURCE.ON_ABANDON_RESTRICTED",
                       "`onAbandon` accepts only a built-in abandonment-safe release primitive call (e.g. "
                       "`onAbandon file.close()`)", st.span,
                       help="abandonment-safe release may only close/release/revoke/roll back; it never runs user code "
                            "(V3 5.5.11)")

    def check_field_assign(self, tgt: A.Field, ot: T.Ty, vt: T.Ty, st) -> None:
        if isinstance(vt, T.TBorrow):  # BUG-0030
            self.oblig("S.RESOURCE.ESCAPE", f"a resource borrow cannot be stored in field `{tgt.name}`", st.span)
            return
        inner = ot.inner if isinstance(ot, T.TBorrow) else ot
        if isinstance(inner, T.TNominal):
            ti = self.types.get(inner.qualname)
            if ti is None:
                return
            if ti.kind in ("record", "error"):
                self.oblig("S.TYPE.FROZEN_MUTATION", f"cannot assign field `{tgt.name}` of frozen record {ti.name}",
                           tgt.span, help=f"create an updated value with `with {{ {tgt.name}: ... }}`")
                return
            if tgt.name not in ti.fields:
                self.unknown_member(tgt, ti.name, list(ti.fields))
                return
            want = ti.fields[tgt.name]
            if not consistent(vt, want, self.satisfies):
                self.mismatch(st.value.span, want, vt, f"field `{tgt.name}`", ti.field_spans.get(tgt.name))
            if tgt.name in ti.invariant_fields:
                fs = self.current_fn()
                in_own = fs is not None and fs.owner is ti and isinstance(tgt.obj, A.Name) and tgt.obj.name == "self"
                if not in_own:
                    self.legal("S.CONTRACT.INVARIANT_FIELD_WRITE",
                               f"field `{tgt.name}` participates in an invariant of {ti.name}; assign it only inside "
                               f"{ti.name}'s methods (on `self`)", tgt.span,
                               help=f"add a method to {ti.name} that performs the update")
                elif fs is not None and fs.decl is not None and fs.decl.is_async:
                    pass

    def current_fn(self):
        for fs in reversed(self.fn_stack):
            if fs.kind in ("fn", "test", "contract", "const"):
                return fs
        return None

    # ------------------------------------------------------------------ helpers
    def mismatch(self, span, want, got, what: str, annot_span=None) -> None:
        sec = [Label(annot_span, f"{what} declared here")] if annot_span is not None else []
        self.oblig("S.TYPE.STATIC_MISMATCH", f"expected {want} for {what}, found {got}", span,
                   label=f"this is {got}", expected=str(want), found=str(got), secondary=sec,
                   help=self.mismatch_help(want, got))

    @staticmethod
    def mismatch_help(want, got) -> Optional[str]:
        if isinstance(want, T.TCon) and want.name == "Option" and consistent(got, want.args[0]):
            return "wrap the value: `Some(x)` (there is no implicit conversion to an Option)"
        if {str(want), str(got)} == {"Int", "Float"}:
            return "convert explicitly with `toFloat()` / `toInt()`"
        return None

    def check_parallel_value(self, v) -> None:
        if isinstance(v, A.Parallel) and v.ann.get("_value_has_task"):
            last = v.body.stmts[-1] if v.body.stmts else v.body
            self.legal("S.TASK.HANDLE_ESCAPE", "the `parallel` block's value contains a task handle, which cannot "
                       "outlive the block that owns the task", last.span, secondary=[Label(v.span, "owning task group")],
                       help="await the handle inside the block and produce its result")

    def enclosing_parallel(self):
        """The innermost `parallel` node lexically enclosing the current point *in the
        current function* (a lambda body inside a group is a different function)."""
        stack = getattr(self, "_parallel_stack", None)
        if not stack:
            return None
        top = stack[-1]
        return top if top.ann.get("_fn_depth") == len(self.fn_stack) else None

    def unknown_member(self, node, tname: str, members, for_call: bool = False) -> None:
        close = difflib.get_close_matches(node.name, members, n=3, cutoff=0.5)
        self.oblig("S.TYPE.UNKNOWN_METHOD" if for_call else "S.TYPE.UNKNOWN_FIELD",
                   f"{tname} has no {'method' if for_call else 'field or method'} `{node.name}`",
                   node.name_span or node.span,
                   help=("did you mean " + ", ".join(f"`{c}`" for c in close) + "?") if close else None)

    def check_lambda_escape(self, lam: A.Lambda, how: str) -> None:
        for b in lam.ann.get("capture_bindings", []) or []:
            if b.kind == "use" or (b.kind == "param" and isinstance(getattr(b.node, "type", None), A.TypeExpr)
                                   and getattr(b.node, "borrow", False)):
                self.oblig("S.RESOURCE.ESCAPE",
                           f"closure capturing resource `{b.name}` is {how} and may outlive the resource scope",
                           lam.span, help="keep closures over resources local to the call that uses them")
                return


import difflib  # noqa: E402  (used by unknown_member)


def _ends_abruptly(b) -> bool:
    if b is None or not isinstance(b, A.Block) or not b.stmts:
        return False
    last = b.stmts[-1]
    return isinstance(last, (A.ReturnStmt, A.ThrowStmt))


def contains_task(t) -> bool:
    if isinstance(t, T.TFn):
        return t.captures_task  # a closure capturing a handle carries it (BUG-0035)
    if isinstance(t, T.TCon):
        return t.name == "Task" or any(contains_task(a) for a in t.args)
    if isinstance(t, T.TTuple):
        return any(contains_task(a) for a in t.items)
    return False


def needs_rt_check(t) -> bool:
    """A transient check is only useful for a known, non-generic static type."""
    from .types import ErrSet
    if t is DYN or isinstance(t, (T.TVar, ErrSet)) or t is T.NEVER:
        return False
    if isinstance(t, T.TCon):
        return True
    return isinstance(t, (T.TPrim, T.TNominal, T.TTuple, T.TFn))
