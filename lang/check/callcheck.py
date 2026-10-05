"""Calls, error handling, async/resource/concurrency constructs for the checker."""
from __future__ import annotations

from typing import Optional

from .. import typesys as T
from ..diagnostics import Label
from ..runtime.builtins.registry import METHODS, STATICS
from ..runtime.values import Builtin
from ..syntax import ast as A
from .decls import FnSig
from .expr import BuiltinRef, BuiltinTypeRef, CaseRef, ModRef, SigRef, TypeRef, opt
from .types import (DYN, consistent, is_mutable_type, join, kind_of_type, receiver_bindings, sig_type,
                    task_error_names, task_error_type, unify)
from .walk import AGG, CHCLOSED, DEADLINE, contains_task, needs_rt_check, short


class CallInfo:
    """Normalised view of a call target."""

    def __init__(self, kind, params=None, ret=DYN, effect_names=frozenset(), effect_unknown=False, is_async=False,
                 is_provider=False, name="?", sig: Optional[FnSig] = None, variadic=False, decl=None,
                 type_params=(), yields=None):
        self.kind = kind  # fn | builtin | ctor | case | dyn
        self.params = params  # list[(name, Ty, has_default, borrow)] or None (unchecked)
        self.ret = ret
        self.effect_names = effect_names
        self.effect_unknown = effect_unknown
        self.is_async = is_async
        self.is_provider = is_provider
        self.name = name
        self.sig = sig
        self.variadic = variadic
        self.decl = decl
        self.type_params = type_params
        self.yields = yields


def eff_names_from(eff: Optional[T.Effect]):
    if eff is None:
        return frozenset(), True
    out = set()
    for i in eff.items:
        if isinstance(i, T.TNominal):
            out.add(i.qualname)
        elif isinstance(i, T.TVar):
            out.add("$" + i.name)
    return frozenset(out), False


class CallMixin:
    # ------------------------------------------------------------------ call targets
    def call_target(self, e: A.Call, sc) -> tuple[CallInfo, Optional[T.Ty]]:
        callee = e.callee
        recv_ty = None
        if isinstance(callee, A.Field):
            ot = self.expr(callee.obj, sc)
            recv_ty = ot
            mt = self.member_type(ot, callee, sc, for_call=True)
            if ot is DYN or (isinstance(ot, T.TBorrow) and ot.inner is DYN):
                if callee.name not in ("check",):
                    self.verified_only("S.TYPE.DYNAMIC_CALL",
                                       f"method `{callee.name}` is called on a Dyn value; narrow it first "
                                       f"(e.g. `value as Map[Str, Dyn]`) so its effects are known", callee.span)
                return CallInfo("dyn", effect_unknown=True, name=callee.name), recv_ty
            return self.info_for(mt, callee.name, e), recv_ty
        ct = self.expr(callee, sc)
        if ct is DYN:
            self.verified_only("S.TYPE.DYNAMIC_CALL",
                               "a Dyn value is invoked; narrow it to a function type with a known throws effect "
                               "first (e.g. `let f: fn(Int) -> Int throws E = value as fn(Int) -> Int throws E`)",
                               callee.span)
            return CallInfo("dyn", effect_unknown=True), None
        name = callee.name if isinstance(callee, A.Name) else "callee"
        return self.info_for(ct, name, e), None

    def info_for(self, t, name, e) -> CallInfo:
        if isinstance(t, SigRef):
            s = t.sig
            names, unknown = s.effect_for_callers()
            params = s.params
            info = CallInfo("fn", params, s.ret, names, unknown, s.is_async, s.is_resource, s.name, s, decl=s.decl,
                            type_params=s.type_params, yields=s.yields)
            if t.self_ty is not None and getattr(t.self_ty, "args", None):
                ti = self.types.get(t.self_ty.qualname)
                if ti is not None and ti.type_params:
                    sub = dict(zip(ti.type_params, t.self_ty.args))
                    info.params = [(n, T.substitute(pt, sub), d, b) for n, pt, d, b in params]
                    info.ret = T.substitute(info.ret, sub)
            if not t.bound and s.has_self:
                info.params = [("self", DYN, False, False)] + list(info.params)
            return info
        if isinstance(t, BuiltinRef):
            b = t.b
            bindings = receiver_bindings(t.recv) if t.recv is not None and not isinstance(t.recv, BuiltinTypeRef) else {}
            if isinstance(t.recv, BuiltinTypeRef) and t.recv.args:
                from .types import KIND_PARAMS
                for pname, a in zip(KIND_PARAMS.get(t.recv.name, []), t.recv.args):
                    bindings[pname] = a
            ft, variadic = sig_type(b.sig, bindings, self.core_resolver)
            names = frozenset(b.effect or ())
            if ft is None:
                return CallInfo("builtin", None, DYN, names, False, b.is_async, b.is_provider, b.name,
                                variadic=variadic)
            fnames, unknown = eff_names_from(ft.effect)
            params = [(f"arg{i}", p, False, isinstance(p, T.TBorrow)) for i, p in enumerate(ft.params)]
            ret = ft.ret
            if isinstance(t.recv, BuiltinTypeRef) and b.name.endswith((".rendezvous", ".buffered", ".unbounded")):
                arg = t.recv.args[0] if t.recv.args else DYN
                ret = T.TCon(t.recv.name, (arg,))
            info = CallInfo("builtin", params, ret, names | fnames, False, b.is_async or ft.is_async, b.is_provider,
                            b.name, variadic=variadic)
            info.type_params = tuple(sorted({n for n in _tvars(ft)}))
            if b.is_provider:
                info.yields = ft.ret
            return info
        if isinstance(t, TypeRef):
            ti = t.info
            if ti.kind in ("record", "mrecord", "error"):
                sub = dict(zip(ti.type_params, t.args)) if t.args else {}
                params = [(fn, T.substitute(ft, sub) if sub else ft, self.field_has_default(ti, fn), False)
                          for fn, ft in ti.fields.items()]
                ret = T.TNominal(ti.qualname, ti.kind, tuple(t.args)) if t.args else ti.ty
                return CallInfo("ctor", params, ret, frozenset(), False, name=ti.name, decl=ti.decl)
            self.oblig("S.TYPE.NOT_CALLABLE", f"`{ti.name}` cannot be constructed directly"
                       + (f"; choose a case, e.g. `{ti.name}.{next(iter(ti.cases), 'Case')}(...)`" if ti.cases else ""),
                       e.callee.span)
            return CallInfo("dyn")
        if isinstance(t, CaseRef):
            if t.info is None:
                if t.case in ("Some", "Ok"):
                    return CallInfo("case", [("value", T.TVar("T"), False, False)],
                                    opt(T.TVar("T")) if t.case == "Some" else T.TCon("Result", (T.TVar("T"), DYN)),
                                    name=t.case, type_params=("T",))
                if t.case == "Err":
                    return CallInfo("case", [("error", T.TVar("E"), False, False)],
                                    T.TCon("Result", (DYN, T.TVar("E"))), name="Err", type_params=("E",))
                return CallInfo("dyn")
            fields = t.info.cases.get(t.case) or []
            return CallInfo("case", [(fn, ft, False, False) for fn, ft in fields], t.info.ty,
                            name=f"{t.info.name}.{t.case}", type_params=tuple(t.info.type_params))
        if isinstance(t, BuiltinTypeRef):
            if t.name in ("MutableList", "MutableMap", "MutableSet"):
                arity = T.CON_ARITY[t.name]
                args = list(t.args) + [DYN] * (arity - len(t.args))
                return CallInfo("ctor", [], T.TCon(t.name, tuple(args[:arity])), name=t.name)
            self.oblig("S.TYPE.NOT_CALLABLE", f"`{t.name}` cannot be called; use its associated constructors",
                       e.callee.span)
            return CallInfo("dyn")
        if isinstance(t, T.TFn):
            names, unknown = eff_names_from(t.effect)
            return CallInfo("fn", [(f"arg{i}", p, False, isinstance(p, T.TBorrow)) for i, p in enumerate(t.params)],
                            t.ret, names, unknown, t.is_async, name=name)
        if isinstance(t, (ModRef,)):
            self.oblig("S.TYPE.NOT_CALLABLE", f"module `{t.module}` is not callable", e.callee.span)
            return CallInfo("dyn")
        if isinstance(t, T.TBorrow) and isinstance(t.inner, T.TFn):
            return self.info_for(t.inner, name, e)  # calling a borrow-capturing closure (BUG-0029)
        if isinstance(t, T.TBorrow) or t is DYN:
            return CallInfo("dyn", effect_unknown=True)
        self.oblig("S.TYPE.NOT_CALLABLE", f"a value of type {t} is not callable", e.callee.span)
        return CallInfo("dyn")

    def field_has_default(self, ti, fname) -> bool:
        d = ti.decl
        if d is None:
            return False
        for f in getattr(d, "fields", []):
            if f.name == fname:
                return f.default is not None
        return False

    # ------------------------------------------------------------------ calls
    def x_Call(self, e: A.Call, sc, awaited: bool = False):
        callee = e.callee
        if isinstance(callee, A.Name) and callee.name == "old" and sc.get("old") is None:
            for a in e.args:
                t = self.expr(a.value, sc)
                if is_mutable_type(t):
                    self.legal("S.CONTRACT.OLD_NOT_SNAPSHOTTABLE",
                               f"old(...) would capture a mutable {t}; only primitive or frozen results can be "
                               f"snapshotted", e.span, help="snapshot a primitive or frozen projection, e.g. "
                                                            "old(account.balance)")
                return t
            return DYN
        info, recv_ty = self.call_target(e, sc)
        if info.sig is not None and info.kind in ("fn", "method"):
            e.ann["_sig"] = info.sig
        arg_types = []
        for a in e.args:
            at = self.expr(a.value, sc)
            arg_types.append((a, at))
        fs = self.fn_stack[-1] if self.fn_stack else None
        ret, eff_names, eff_unknown = self.check_args(e, info, arg_types)
        if self.report:
            self.annotate_typed_call(e, info, recv_ty, arg_types, sc)
        # async rules
        if info.is_async:
            if fs is not None and not fs.is_async and fs.kind not in ("contract",):
                self.legal("S.ASYNC.SYNC_CALLS_ASYNC",
                           f"`{info.name}` is async; a non-async function cannot call it (only async functions may "
                           f"suspend)", e.span, help="mark the enclosing function `async fn` and use `await`")
            elif not awaited:
                self.oblig("S.ASYNC.MISSING_AWAIT", f"call to async `{info.name}` without `await`", e.span,
                           help=f"write `await {e.span.text}`")
            if fs is not None:
                fs.has_cancel_point = True
        elif awaited and info.kind not in ("dyn",):
            self.oblig("S.ASYNC.AWAIT_NON_ASYNC", f"`await` applied to non-async `{info.name}`", e.span)
        if info.is_provider and not (fs is not None and fs.in_use_init):
            self.legal("S.RESOURCE.PROVIDER_OUTSIDE_USE",
                       f"`{info.name}` is a resource provider; call it only as a `use` initialiser", e.span,
                       help=f"write `use x = try {e.span.text} {{ ... }}`")
        # effects
        if eff_names or eff_unknown:
            marked = e.ann.get("marked", True)
            if not marked and eff_names and not getattr(self, "_spawn_call", False):
                self.oblig("S.EFFECT.MISSING_TRY",
                           f"`{info.name}` may throw {', '.join(sorted(short(n) for n in eff_names))}; mark the call "
                           f"with `try` or handle it", e.span, label="unmarked failure point",
                           help=f"write `try {'await ' if awaited and info.is_async else ''}{e.span.text}` to "
                                f"propagate, or `try ... catch ... => ...` to handle")
            self.raise_eff(eff_names, eff_unknown, e.span)
        if info.kind == "fn" and info.sig is not None and info.sig.decl is not None and \
                isinstance(info.sig.decl, A.FnDecl) and info.sig.decl.ret is None and info.sig.ret is DYN:
            return DYN
        return ret

    def check_args(self, e: A.Call, info: CallInfo, arg_types):
        if info.params is None or info.kind == "dyn":
            return info.ret, info.effect_names, info.effect_unknown
        params = info.params
        # a named function passed as a value is checked by its full function type
        arg_types = [(a, self.callable_type(t)) for a, t in arg_types]
        positional = [(a, t) for a, t in arg_types if a.name is None]
        named = {a.name: (a, t) for a, t in arg_types if a.name is not None}
        subst: dict = {}
        if info.variadic:
            elem = params[0][1] if params else DYN
            for a, t in positional:
                unify(elem, t, subst)
        else:
            if info.kind == "ctor" and len(params) == 1 and len(positional) == 1 and not named:
                named = {params[0][0]: positional[0]}
                positional = []
            elif info.kind == "ctor" and positional:
                self.oblig("S.TYPE.ARITY", f"{info.name} must be constructed with named fields", e.span,
                           help=f"e.g. {info.name}(" + ", ".join(f"{p[0]}: ..." for p in params[:3]) + ")")
                return info.ret, info.effect_names, info.effect_unknown
            if len(positional) > len(params):
                self.oblig("S.TYPE.ARITY", f"`{info.name}` takes {len(params)} argument(s), {len(positional)} given",
                           e.span, secondary=[Label(info.decl.span, "declared here")] if getattr(info.decl, "span", None) else None)
                return info.ret, info.effect_names, info.effect_unknown
            bound = {}
            for (pname, pty, has_def, borrow), (a, t) in zip(params, positional):
                bound[pname] = (a, t, pty, borrow)
            pnames = {p[0] for p in params}
            for n, (a, t) in named.items():
                if n not in pnames:
                    self.oblig("S.TYPE.ARITY" if info.kind != "ctor" else "S.TYPE.UNKNOWN_FIELD",
                               f"`{info.name}` has no {'field' if info.kind == 'ctor' else 'parameter'} named `{n}`",
                               a.span)
                    continue
                if n in bound:
                    self.oblig("S.TYPE.ARITY", f"argument `{n}` given twice", a.span)
                    continue
                pty = next(p for p in params if p[0] == n)
                bound[n] = (a, t, pty[1], pty[3])
            for pname, pty, has_def, borrow in params:
                if pname not in bound and not has_def:
                    stable = "S.TYPE.MISSING_FIELD" if info.kind == "ctor" else "S.TYPE.ARITY"
                    self.oblig(stable, f"`{info.name}` is missing {'field' if info.kind == 'ctor' else 'argument'} "
                               f"`{pname}`", e.span)
            for pname, (a, t, pty, borrow) in bound.items():
                unify(pty, t, subst)
            for pname, (a, t, pty, borrow) in bound.items():
                want = T.substitute(pty, {k: v for k, v in subst.items() if isinstance(v, T.Ty)})
                self.check_one_arg(info, pname, a, t, want, borrow)
        ret = info.ret
        eff_names = set(info.effect_names)
        eff_unknown = info.effect_unknown
        # effect variables bound by this call are substituted into a returned function
        # type too, e.g. `compose(f, g) -> fn(A) -> C throws E1 | E2` (BUG-0013)
        ret = T.substitute(ret, subst)
        # effect variables
        for n in list(eff_names):
            if n.startswith("$"):
                var = n[1:]
                if var in subst:
                    eff_names.discard(n)
                    v = subst[var]
                    if v is None:
                        eff_unknown = True
                    elif isinstance(v, T.Effect):
                        en, eu = eff_names_from(v)
                        eff_names |= en
                        eff_unknown = eff_unknown or eu
                    elif isinstance(v, T.TNominal):
                        eff_names.add(v.qualname)
                elif not self._in_generic_scope(var):
                    eff_names.discard(n)
        return ret, frozenset(eff_names), eff_unknown

    def annotate_typed_call(self, e: A.Call, info, recv_ty, arg_types, sc) -> None:
        """IMPL-004 for calls: when the callee's type comes from a written annotation —
        a method of an annotated mutable collection, or a value of annotated function
        type — record the transient checks the runtime must perform: arguments against
        the parameter types (writes before insertion), the result against the return
        type, and escaping errors against the written throws set (V3 5.3.7, 7.7.6;
        BUG-0024, BUG-0026)."""
        callee = e.callee
        positional = [(a, t) for a, t in arg_types if a.name is None]
        if info.kind == "builtin" and isinstance(callee, A.Field):
            rt = recv_ty.inner if isinstance(recv_ty, T.TBorrow) else recv_ty
            if not (isinstance(rt, T.TCon) and rt.name in ("MutableList", "MutableMap", "MutableSet")):
                return
            origin = self.origin_of(callee.obj, sc)
            if origin is None or not info.params:
                return
            checks = [(i, p[1]) for i, ((a, at), p) in enumerate(zip(positional, info.params))
                      if at is DYN and needs_rt_check(p[1]) and not isinstance(p[1], T.TFn)]
            if checks:
                e.ann["typed_call"] = (checks, None, None, origin)
            return
        if info.kind != "fn" or info.sig is not None:
            return
        ct = callee.ann.get("_sty")
        if isinstance(ct, T.TBorrow):
            ct = ct.inner
        if not isinstance(ct, T.TFn):
            return
        origin = self.origin_of(callee, sc)
        if origin is None:
            return
        checks = [(i, p) for i, ((a, at), p) in enumerate(zip(positional, ct.params)) if needs_rt_check(p)]
        ret = ct.ret if needs_rt_check(ct.ret) else None
        effect = None
        if ct.effect is not None:
            names, unknown = eff_names_from(ct.effect)
            if not unknown and not any(n.startswith("$") for n in names):
                effect = tuple(sorted(names))
        if checks or ret is not None or effect is not None:
            e.ann["typed_call"] = (checks, ret, effect, origin)

    def _in_generic_scope(self, var: str) -> bool:
        for fs in self.fn_stack:
            d = fs.decl
            if d is not None and var in (getattr(d, "type_params", []) or []):
                return True
        return False

    def check_one_arg(self, info, pname, a, t, want, borrow) -> None:
        if isinstance(t, T.TBorrow) and info.kind in ("ctor", "case"):
            # wrapping a borrow in a record or variant (e.g. `Some(c)`) stores it (BUG-0030)
            self.oblig("S.RESOURCE.ESCAPE", f"a resource borrow cannot be stored in `{info.name}`", a.span)
            return
        if isinstance(t, T.TBorrow) and not isinstance(want, T.TBorrow):
            if info.kind in ("ctor", "case"):
                self.oblig("S.RESOURCE.ESCAPE", f"a resource borrow cannot be stored in `{info.name}`", a.span)
                return
            if info.kind == "builtin" and info.name.split(".")[-1] in ("push", "set", "insert", "send", "of",
                                                                         "inserted", "appended", "add"):
                self.oblig("S.RESOURCE.ESCAPE", f"a resource borrow cannot be stored via `{info.name}`", a.span)
                return
            if info.kind == "fn" and (want is not DYN or self.verified):
                self.oblig("S.RESOURCE.BORROW_PARAM",
                           f"resource passed to parameter `{pname}` of `{info.name}`, which is not declared `borrow`",
                           a.span, help=f"declare the parameter as `{pname}: borrow {t.inner}`")
                return
        if isinstance(a.value, A.Lambda) and info.kind in ("ctor", "case"):
            self.check_lambda_escape(a.value, "stored in a value")
        if not consistent(t, want, self.satisfies):
            reason = None
            if isinstance(want, T.TNominal) and want.kind == "protocol":
                reason = self.conformance(t, want)
            msg = (f"argument `{pname}` of `{info.name}` expects {want}, found {t}" if not reason or reason is True
                   else f"argument `{pname}` of `{info.name}`: {t} does not satisfy {want}: {reason}")
            self.oblig("S.TYPE.STATIC_MISMATCH", msg, a.span, expected=str(want), found=str(t),
                       help=self.mismatch_help(want, t))

    # ------------------------------------------------------------------ errors
    def x_Try(self, e: A.Try, sc):
        t, coll = self.with_collector(lambda: self.expr(e.expr, sc))
        names = dict(coll.names)
        result = t
        handled_any = False
        cases_caught: dict[str, set] = {}
        from .typecheck import Scope
        for cl in e.catches:
            target = self.catch_target(cl)
            hsc = Scope(sc)
            bind_ty = DYN
            if target is not None:
                kind, val = target
                caught = [n for n in names if self.error_matches(n, kind, val)]
                reachable = caught or (kind == "case" and val[0] in names)
                if not reachable and not coll.unknown and self.report:
                    self.advise("S.EFFECT.CATCH_UNREACHABLE",
                                f"`catch {'.'.join(cl.path)}` can never run: the expression cannot throw it", cl.span)
                if kind == "case" and val[0] in names:
                    # catching every case of an error enum handles the whole type
                    got = cases_caught.setdefault(val[0], set())
                    got.add(val[1])
                    ti = self.types.get(val[0])
                    if ti is not None and ti.cases and got >= set(ti.cases):
                        caught = [val[0]]
                for n in caught:
                    names.pop(n, None)
                    handled_any = True
                if kind == "type":
                    bind_ty = T.TNominal(val, self.types[val].kind) if val in self.types else DYN
                elif kind == "case":
                    bind_ty = T.TNominal(val[0], self.types[val[0]].kind) if val[0] in self.types else DYN
            if cl.binding:
                hsc.vars[cl.binding] = (bind_ty, "catch", cl.span)
            ht = self.block(cl.handler, hsc, new_scope=False) if isinstance(cl.handler, A.Block) else self.expr(cl.handler, hsc)
            result = join(result, ht)
        if e.fallback is not None:
            concrete = [n for n in names if not n.startswith("$")]
            if coll.unknown or len(concrete) != 1 or len(names) != 1:
                what = ("an unknown set of errors" if coll.unknown else
                        ("no errors" if not names else ", ".join(sorted(short(n) for n in names))))
                self.legal("S.EFFECT.BROAD_FALLBACK",
                           f"unqualified `else` fallback is only allowed when exactly one concrete error type can be "
                           f"thrown; here: {what}", e.span,
                           help="name the handled errors: `try e catch ErrorType => fallback` (V3 5.7.5)")
            else:
                e.ann["fallback_qual"] = concrete[0]
                names.pop(concrete[0], None)
            ft = self.expr(e.fallback, sc)
            result = join(result, ft)
        if not e.catches and e.fallback is None and coll.empty and self.report:
            self.advise("W.EFFECT.USELESS_TRY", "`try` marks a failure point, but this expression cannot throw a "
                        "recoverable error", e.span, help="remove `try`; it should mark only real failure points")
        for n, s in names.items():
            self.raise_eff([n], False, s)
        if coll.unknown:
            self.raise_eff([], True, coll.unknown_site)
        return result

    def catch_target(self, cl: A.CatchClause):
        path = cl.path
        ent = self.lookup_global(self.cur_module, path[0])
        i = 1
        while ent is not None and ent[0] == "module" and i < len(path):
            ent = self.modules.get(ent[1], {}).get(path[i])
            i += 1
        if ent is None:
            return None
        if ent[0] == "category" or cl.is_category:
            if ent[0] != "category":
                self.legal("S.EFFECT.NOT_AN_ERROR", f"`{'.'.join(path)}` is not a category", cl.span)
                return None
            return ("category", ent[1])
        if ent[0] == "type":
            ti = ent[1]
            if not ti.is_error:
                self.legal("S.EFFECT.NOT_AN_ERROR", f"`{ti.name}` is not an error type and cannot be caught", cl.span)
                return None
            rest = path[i:]
            if rest:
                if rest[0] not in ti.cases:
                    self.legal("S.EFFECT.NOT_AN_ERROR", f"`{ti.name}` has no case `{rest[0]}`", cl.span)
                    return None
                return ("case", (ti.qualname, rest[0]))
            return ("type", ti.qualname)
        self.legal("S.EFFECT.NOT_AN_ERROR", f"`{'.'.join(path)}` is not an error type or category", cl.span)
        return None

    def error_matches(self, name: str, kind: str, val) -> bool:
        if kind == "type":
            return name == val
        if kind == "case":
            return False  # catching one case leaves the enum type possibly escaping
        ti = self.types.get(name)
        return ti is not None and val in ti.categories

    def x_Capture(self, e: A.Capture, sc):
        t, coll = self.with_collector(lambda: self.expr(e.expr, sc))
        errs = [n for n in coll.names if not n.startswith("$")]
        et = DYN
        if len(errs) == 1 and not coll.unknown:
            ti = self.types.get(errs[0])
            et = ti.ty if ti is not None else DYN
        return T.TCon("Result", (t, et))

    def x_Propagate(self, e: A.Propagate, sc):
        t = self.expr(e.expr, sc)
        fs = self.current_fn()
        if fs is not None and fs.kind == "fn" and fs.sig is not None and fs.sig.ret_written:
            r = fs.sig.ret
            if not (isinstance(r, T.TCon) and r.name == "Result") and r is not DYN:
                self.legal("S.EFFECT.PROPAGATE_CONTEXT",
                           f"`propagate` returns the Err from the enclosing function, but it returns {r}", e.span,
                           help="use `try r.orThrow()` to turn an Err into an exception")
        elif fs is not None and fs.kind == "fn" and self.verified and fs.sig is not None and not fs.sig.ret_written:
            self.verified_only("S.EFFECT.PROPAGATE_CONTEXT",
                               "`propagate` requires the enclosing function to declare a `Result` return type", e.span)
        if isinstance(t, T.TCon) and t.name == "Result":
            return t.args[0]
        if t is not DYN:
            self.oblig("S.TYPE.STATIC_MISMATCH", f"`propagate` expects a Result, found {t}", e.span)
        return DYN

    # ------------------------------------------------------------------ async
    def x_Await(self, e: A.Await, sc):
        fs = self.fn_stack[-1] if self.fn_stack else None
        if fs is not None:
            fs.has_cancel_point = True
        if isinstance(e.expr, A.Call):
            return self.x_Call(e.expr, sc, awaited=True)
        t = self.expr(e.expr, sc)
        if isinstance(t, T.TCon) and t.name == "Task":
            names, unknown = task_error_names(t.args[1] if len(t.args) > 1 else DYN)
            if names:
                if not e.ann.get("marked", True):
                    self.oblig("S.EFFECT.MISSING_TRY",
                               f"awaiting this task may throw {', '.join(sorted(short(n) for n in names))}; mark it "
                               f"with `try` or handle it", e.span, help=f"write `try {e.span.text}`")
                self.raise_eff(sorted(names), False, e.span)
            if unknown:
                self.raise_eff([], True, e.span)
            return t.args[0]
        if t is not DYN:
            self.oblig("S.ASYNC.AWAIT_NON_ASYNC", f"`await` needs an async call or a task handle, found {t}", e.span)
        return DYN

    def _await_marked(self, e) -> bool:
        return True

    # ------------------------------------------------------------------ resources
    def x_Yield(self, e: A.Yield, sc):
        t = self.expr(e.value, sc)
        fs = self.current_fn()
        if fs is not None and fs.sig is not None and fs.sig.yields is not None:
            want = fs.sig.yields
            tt = t.inner if isinstance(t, T.TBorrow) else t
            if not consistent(tt, want, self.satisfies):
                self.mismatch(e.value.span, want, tt, "yielded resource", fs.decl.yields.span if fs.decl.yields else None)
        return T.TNominal("core.ScopeExit", "enum")

    def x_Use(self, e: A.Use, sc):
        from .typecheck import Scope
        init = e.init
        inner = init.expr if isinstance(init, A.Try) else init
        inner = inner.expr if isinstance(inner, A.Await) else inner
        fs = self.fn_stack[-1] if self.fn_stack else None
        yt = DYN
        if not isinstance(inner, A.Call):
            self.legal("S.RESOURCE.PROVIDER_OUTSIDE_USE", "a `use` scope must be initialised by a resource provider call",
                       init.span)
            self.expr(init, sc)
        else:
            if fs is not None:
                fs.in_use_init = True
            try:
                info, _ = self.call_target(inner, sc)
            finally:
                if fs is not None:
                    fs.in_use_init = False
            if info.kind != "dyn" and not info.is_provider:
                self.legal("S.RESOURCE.PROVIDER_OUTSIDE_USE",
                           f"`{info.name}` is not a resource provider (declare it `resource fn ... yields T`)", inner.span)
            if fs is not None:
                fs.in_use_init = True
            try:
                pt, pcoll = self.with_collector(lambda: self.expr(init, sc))
            finally:
                if fs is not None:
                    fs.in_use_init = False
            yt = info.yields if info.yields is not None else DYN
            prov_eff = pcoll
        bsc = Scope(sc)
        bsc.vars[e.name] = (T.TBorrow(yt), "use", e.name_span or e.span)
        bt, bcoll = self.with_collector(lambda: self.block(e.body, bsc, new_scope=False))
        if isinstance(bt, T.TBorrow):
            self.oblig("S.RESOURCE.ESCAPE", "a `use` scope cannot produce its resource as its value", e.body.span)
        for n, s in bcoll.names.items():
            self.raise_eff([n], False, s)
        if bcoll.unknown:
            self.raise_eff([], True, bcoll.unknown_site)
        if isinstance(inner, A.Call):
            for n, s in prov_eff.names.items():
                self.raise_eff([n], False, s)
            if prov_eff.unknown:
                self.raise_eff([], True, prov_eff.unknown_site)
            if (prov_eff.names or prov_eff.unknown) and (bcoll.names or bcoll.unknown):
                self.raise_eff([AGG], False, e.span)
        if self.report:
            self.scope_width_advice(e)
        return bt

    def scope_width_advice(self, e: A.Use) -> None:
        stmts = e.body.stmts
        last = -1
        for i, st in enumerate(stmts):
            if any(isinstance(n, A.Name) and n.name == e.name for n in A.walk(st)):
                last = i
        tail = stmts[last + 1:]
        if last >= 0 and tail and any(isinstance(n, (A.Await, A.WhileStmt, A.ForStmt, A.Parallel, A.Select))
                                      for st in tail for n in A.walk(st)):
            self.advise("W.RESOURCE.SCOPE_TOO_WIDE",
                        f"resource `{e.name}` stays open after its last use, across waiting or long-running work",
                        tail[0].span, help="end the `use` scope after the last use and keep only derived data")

    # ------------------------------------------------------------------ concurrency
    def x_Parallel(self, e: A.Parallel, sc):
        if not hasattr(self, "_parallel_stack"):
            self._parallel_stack = []
        e.ann.pop("_child_types", None)
        e.ann["_fn_depth"] = len(self.fn_stack)
        self._parallel_stack.append(e)
        try:
            bt, coll = self.with_collector(lambda: self.block(e.body, sc))
        finally:
            self._parallel_stack.pop()
        fs = self.fn_stack[-1] if self.fn_stack else None
        if fs is not None:
            fs.has_cancel_point = True
        child_types = e.ann.get("_child_types", [])
        if e.mode == "failfast" and contains_task(bt):
            e.ann["_value_has_task"] = True  # reported where the value is bound/assigned/returned
        # collect mode reports child failures as data; only the body's own failure is thrown
        may_fail = not coll.empty or (e.mode != "collect" and e.ann.get("_child_may_fail", False))
        if may_fail:
            self.raise_eff([AGG], False, e.span)
        if e.mode == "collect":
            return T.TNominal("core.TaskGroupReport", "record")
        if e.mode in ("race", "firstSuccess"):
            t = T.NEVER
            for ct in child_types:
                t = join(t, ct)
            return DYN if t is T.NEVER else t
        return bt

    def x_Spawn(self, e: A.Spawn, sc):
        group = self._innermost_parallel_node(e)
        if e.call is not None:
            call = e.call
            self._spawn_call = True
            try:
                _, coll = self.with_collector(lambda: self.x_Call(call, sc, awaited=True))
            finally:
                self._spawn_call = False
            rt = self._spawn_ret(call, sc)
            saved = self.report
            self.report = False
            try:
                arg_tys = [self.with_collector(lambda a=a: self.expr(a.value, sc))[0] for a in call.args]
            finally:
                self.report = saved
            for a, at in zip(call.args, arg_tys):
                self.check_sendable(at, a.value, "spawn argument")
            if group is not None and (coll.names or coll.unknown):
                group.ann["_child_may_fail"] = True
            if group is not None:
                group.ann.setdefault("_child_types", []).append(rt)
            return T.TCon("Task", (rt, task_error_type(coll.names, coll.unknown, self.types)))
        from .typecheck import FnState, Scope
        bsc = Scope(sc)
        for name, reassigned in e.ann.get("captures", []):
            ent = sc.get(name)
            if ent is None:
                continue
            if reassigned:
                self.oblig("S.TASK.CAPTURE_MUTABLE", f"spawned block captures `{name}`, which is reassigned",
                           e.span, help=f"pass it as an explicit argument: `spawn work({name})`")
            elif is_mutable_type(ent[0]) or isinstance(ent[0], T.TBorrow):
                self.oblig("S.TASK.CAPTURE_MUTABLE" if not isinstance(ent[0], T.TBorrow) else "S.TASK.NOT_SENDABLE",
                           f"spawned block captures `{name}` of type {ent[0]}, which cannot be shared across tasks",
                           e.span, help="pass it as an explicit task argument (mutable values are graph-copied)")
        outer = self.fn_stack[-1] if self.fn_stack else None
        st = FnState(None, outer.decl if outer else None, True, "lambda", outer.owner if outer else None)
        self.fn_stack.append(st)
        try:
            bt, coll = self.with_collector(lambda: self.block(e.block, bsc, new_scope=False))
        finally:
            self.fn_stack.pop()
        if group is not None and (coll.names or coll.unknown):
            group.ann["_child_may_fail"] = True
        if group is not None:
            group.ann.setdefault("_child_types", []).append(bt)
        return T.TCon("Task", (bt, task_error_type(coll.names, coll.unknown, self.types)))

    def _spawn_ret(self, call, sc):
        saved = self.report
        self.report = False
        try:
            info, _ = self.call_target(call, sc)
        finally:
            self.report = saved
        return info.ret if info is not None else DYN

    def _innermost_parallel_node(self, e):
        return self._parallel_stack[-1] if getattr(self, "_parallel_stack", None) else None

    def check_sendable(self, t, node, what) -> None:
        if isinstance(t, T.TBorrow):
            self.oblig("S.TASK.NOT_SENDABLE", f"{what}: a resource borrow cannot cross a task boundary", node.span,
                       help="open the resource inside the child task, or pass derived data")
        elif isinstance(t, T.TCon) and t.name in ("Channel", "Broadcast"):
            self.oblig("S.TASK.NOT_SENDABLE", f"{what}: channel controllers cannot cross task boundaries", node.span,
                       help="pass `ch.sender()` / `ch.receiver()` ports instead")
        elif isinstance(t, T.TCon) and t.name == "Task":
            self.oblig("S.TASK.NOT_SENDABLE", f"{what}: task handles stay within their structured scope", node.span)
        elif isinstance(t, T.TCon) and t.name in ("File", "Dir"):
            self.oblig("S.TASK.NOT_SENDABLE", f"{what}: resources cannot cross task boundaries", node.span)
        if isinstance(node, A.Lambda):
            for name, reassigned in node.ann.get("captures", []):
                if reassigned:
                    self.oblig("S.TASK.CAPTURE_MUTABLE", f"{what}: closure captures reassigned binding `{name}`",
                               node.span)

    def x_Within(self, e: A.Within, sc):
        dt = self.expr(e.deadline, sc)
        if dt not in (T.DURATION, T.INSTANT, DYN):
            self.oblig("S.TYPE.STATIC_MISMATCH", f"`within` expects a Duration or Instant, found {dt}", e.deadline.span)
        fs = self.fn_stack[-1] if self.fn_stack else None
        if fs is not None:
            fs.has_cancel_point = True
        bt = self.block(e.body, sc)
        self.raise_eff([DEADLINE], False, e.span)
        return bt


def _tvars(t):
    out = set()
    if isinstance(t, T.TVar):
        out.add(t.name)
    elif isinstance(t, T.TCon):
        for a in t.args:
            out |= _tvars(a)
    elif isinstance(t, T.TFn):
        for p in t.params:
            out |= _tvars(p)
        out |= _tvars(t.ret)
    elif isinstance(t, T.TTuple):
        for i in t.items:
            out |= _tvars(i)
    return out
