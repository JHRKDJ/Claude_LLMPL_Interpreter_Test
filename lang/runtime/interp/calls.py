"""Calls: argument binding, boundary checks, contracts, invariants, effects,
method dispatch, and record/variant construction.

Exit ordering (V3 5.10.12-14, 7.8.6):
  normal:      save value -> (block cleanup already ran) -> return-type check ->
               postconditions (own + inherited protocol) -> invariants -> return
  exception:   (cleanup ran) -> invariants (failure abandons, noting the pending
               exception) -> written-throws check -> propagate
  cancellation:(cleanup ran, masked) -> invariants (failure abandons) -> propagate
  abandonment: nothing runs
"""
from __future__ import annotations

from ...diagnostics import Label, Note
from ...syntax import ast as A
from ... import typesys as T
from ..builtins.common import kind_of
from ..builtins.registry import METHODS
from ..capture import Budget, safe_repr
from ..core_types import ERR_CASE, OPTION, RESULT
from ..equality import type_name
from ..frozen import is_frozen
from ..signals import (Abandoned, Cancelled, ChildOrigin, Fault, ReturnSignal, Thrown)
from ..values import (UNIT, Borrow, BoundMethod, Builtin, BuiltinBound, CaseInfo, Closure, FrozenRecord,
                      ModuleValue, MutableList, MutableMap, MutableRecord, MutableSet, Namespace, RecordType,
                      TypeValue, VariantValue, FrozenList)
from .core import MAX_CALL_DEPTH, Env, Frame


class CallMixin:
    # ------------------------------------------------------------------ entry points
    def eval_Call(self, node: A.Call, env: Env, awaited: bool = False):
        callee = node.callee
        tc = node.ann.get("typed_call")
        if tc is not None:
            return self.eval_typed_call(node, env, awaited, tc)
        try:
            if callee.__class__ is A.Field:
                obj = self.eval(callee.obj, env)
                args, kwargs = self.eval_args(node, env)
                self.sched.current.frames[-1].cur_env = env
                return self.call_member(obj, callee.name, args, kwargs, node, env, awaited)
            if callee.__class__ is A.Name and callee.name == "old":
                fr = self.sched.current.frames[-1]
                if fr.snapshots is not None and node.id in fr.snapshots:
                    return fr.snapshots[node.id]
            f = self.eval(callee, env)
            args, kwargs = self.eval_args(node, env)
            self.sched.current.frames[-1].cur_env = env
            return self.call_value(f, args, kwargs, node.span, awaited, node, env)
        except Thrown as t:
            if not node.ann.get("marked", True):
                t.prov.unmarked.append(node.span)
            raise

    def eval_typed_call(self, node: A.Call, env: Env, awaited: bool, tc):
        """A call whose callee type comes from a written annotation (IMPL-004; BUG-0024,
        BUG-0026): arguments are checked before the call (writes before insertion), the
        result after it, and an escaping error against the annotation's throws set."""
        checks, ret, effect, origin = tc
        callee = node.callee
        try:
            if callee.__class__ is A.Field:
                obj = self.eval(callee.obj, env)
                f = None
            else:
                f = self.eval(callee, env)
            args, kwargs = self.eval_args(node, env)
            for i, ty in checks:
                if i < len(args):
                    self.transient_check((ty, origin), args[i], node.args[i].span, env, f"argument {i + 1}")
            self.sched.current.frames[-1].cur_env = env
            try:
                if f is None:
                    v = self.call_member(obj, callee.name, args, kwargs, node, env, awaited)
                else:
                    v = self.call_value(f, args, kwargs, node.span, awaited, node, env)
            except Thrown as t:
                if effect is not None:
                    allowed = [self.registry.nominals.get(q) for q in effect]
                    if not self.error_in(t.error, [a for a in allowed if a is not None]):
                        raise Abandoned(self.make_diag(
                            "A.EFFECT.UNDECLARED_EXCEPTION",
                            f"a call through a value typed with throws {{{', '.join(q.split('.')[-1] for q in effect) or 'nothing'}}} "
                            f"let {self.error_summary(t.error)} escape", node.span, env,
                            label="call relies on the annotated effect",
                            secondary=[Label(origin, "relied-upon function type")] if origin is not None else [],
                            help="narrow the callable to a type whose throws set includes this error, or handle "
                                 "the error inside the callable"))
                raise
            if ret is not None:
                self.transient_check((ret, origin), v, node.span, env, "the call's result")
            return v
        except Thrown as t:
            if not node.ann.get("marked", True):
                t.prov.unmarked.append(node.span)
            raise

    def eval_args(self, node: A.Call, env: Env):
        args = []
        kwargs = None
        for a in node.args:
            v = self.eval(a.value, env)
            if a.name is None:
                if kwargs:
                    raise self.abandon("A.TYPE.ARITY", "positional argument after named arguments", a.span, env)
                args.append(v)
            else:
                if kwargs is None:
                    kwargs = {}
                if a.name in kwargs:
                    raise self.abandon("A.TYPE.ARITY", f"argument `{a.name}` given twice", a.span, env)
                kwargs[a.name] = v
        return args, kwargs

    def call_value(self, f, args, kwargs=None, span=None, awaited=False, node=None, env=None):
        t = type(f)
        if t is Closure:
            return self.call_closure(f, args, kwargs, span, awaited, node=node)
        if t is BoundMethod:
            return self.call_closure(f.func, [f.receiver] + list(args), kwargs, span, awaited,
                                     self_value=f.receiver, node=node)
        if t is Builtin:
            return self.call_builtin(f, None, args, kwargs, span, awaited)
        if t is BuiltinBound:
            return self.call_builtin(f.builtin, f.receiver, args, kwargs, span, awaited)
        if t is TypeValue:
            return self.construct(f, args, kwargs, span, env, node)
        raise Fault("A.TYPE.NOT_CALLABLE", f"a value of type {type_name(f)} is not callable")

    def call_member(self, obj, name, args, kwargs, node, env, awaited):
        t = type(obj)
        if t is FrozenRecord or t is MutableRecord:
            m = obj.rtype.methods.get(name)
            if m is not None:
                if not m.decl.has_self:
                    raise self.abandon("A.TYPE.UNKNOWN_METHOD",
                                       f"`{name}` is an associated function of {obj.rtype.name}; call it as "
                                       f"`{obj.rtype.name}.{name}(...)`", node.span, env)
                return self.call_closure(m, [obj] + args, kwargs, node.span, awaited, self_value=obj, node=node)
        elif t is VariantValue:
            m = obj.case.etype.methods.get(name)
            if m is not None:
                return self.call_closure(m, [obj] + args, kwargs, node.span, awaited, self_value=obj, node=node)
        elif t is Borrow:
            target = self.borrow_target(obj, node.span, env)
            if type(target) in (FrozenRecord, MutableRecord):
                m = target.rtype.methods.get(name)
                if m is not None:
                    return self.call_closure(m, [obj] + args, kwargs, node.span, awaited, self_value=obj, node=node)
            k = kind_of(target)
            if k is not None:
                b = METHODS.get(k, {}).get(name)
                if b is not None:
                    return self.call_builtin(b, target, args, kwargs, node.span, awaited)
        else:
            k = kind_of(obj)
            if k is not None:
                b = METHODS.get(k, {}).get(name)
                if b is not None:
                    return self.call_builtin(b, obj, args, kwargs, node.span, awaited)
        f = self.get_member(obj, name, node, env, call=True)
        return self.call_value(f, args, kwargs, node.span, awaited, node, env)

    # ------------------------------------------------------------------ builtins
    def call_builtin(self, b: Builtin, recv, args, kwargs, span, awaited):
        if kwargs:
            raise Fault("A.TYPE.ARITY", f"`{b.name}` does not take named arguments")
        n = len(args)
        if n < b.min_args or (b.max_args is not None and n > b.max_args):
            want = str(b.min_args) if b.min_args == b.max_args else f"{b.min_args}..{b.max_args}"
            raise Fault("A.TYPE.ARITY", f"`{b.name}` expects {want} argument(s), got {n}")
        if b.is_async and not awaited:
            fr = self.sched.current.frames[-1]
            if not fr.is_async:
                raise Fault("A.ASYNC.SYNC_CONTEXT", f"`{b.name}` is async and can only be called from an async "
                                                    f"function (with `await`)",
                            help="mark the enclosing function `async fn` and write `await ...`")
        if b.is_provider:
            raise Fault("A.RESOURCE.PROVIDER_OUTSIDE_USE",
                        f"`{b.name}` is a resource provider; it can only initialise a `use` scope",
                        help=f"write `use x = try {b.name.rsplit('.', 1)[-1]}(...) {{ ... }}`")
        if type(recv) is TypeValue and recv.kind == "builtin":
            return b.impl(self, args, span, recv)
        if recv is None:
            return b.impl(self, args, span)
        if type(recv) is Borrow:
            recv = recv.target
        return b.impl(self, recv, args, span)

    # ------------------------------------------------------------------ closures
    def call_closure(self, clo: Closure, args, kwargs, span, awaited=False, self_value=None, node=None,
                     provider_body=None):
        decl = clo.decl
        task = self.sched.current
        if clo.is_resource and provider_body is None:
            raise Fault("A.RESOURCE.PROVIDER_OUTSIDE_USE",
                        f"`{clo.name}` is a resource provider; it can only initialise a `use` scope",
                        help=f"write `use x = try {clo.name}(...) {{ ... }}`")
        if clo.is_async and not awaited and not task.frames[-1].is_async:
            raise Fault("A.ASYNC.SYNC_CONTEXT",
                        f"async function `{clo.name}` called from a non-async function",
                        help="only async functions may suspend: mark the caller `async fn` and use `await`")
        if task.depth >= MAX_CALL_DEPTH:
            raise Fault("A.RUNTIME.STACK_OVERFLOW", f"call depth limit ({MAX_CALL_DEPTH}) exceeded in `{clo.name}`",
                        help="check for unbounded recursion")
        fenv = Env(clo.env, kind="fn")
        params = decl.params
        self.bind_params(clo, params, args, kwargs, fenv, span, node)
        frame = Frame(clo.name, decl, span, fenv, clo.is_async, clo)
        frame.self_value = self_value
        frame.provider_state = provider_body
        task.frames.append(frame)
        task.depth += 1
        inv_obj = None
        if self_value is not None:
            tgt = self_value.target if type(self_value) is Borrow else self_value
            if type(tgt) is MutableRecord and tgt.rtype.invariants:
                inv_obj = tgt
        outermost = False
        counted = False
        try:
            # boundary checks of written parameter annotations (V3 5.3.2, 5.3.6)
            self.check_param_annotations(clo, params, fenv, span, node)
            contracts = self.contracts_for(clo)
            if contracts:
                self.check_preconditions(clo, contracts, fenv, span, node)
                self.take_snapshots(clo, contracts, fenv, frame)
            if inv_obj is not None:
                if inv_obj.op_depth == 0:
                    self.check_invariants(inv_obj, span, f"on entry to `{clo.name}`", fenv)
                    outermost = True
                inv_obj.op_depth += 1
                counted = True
            ret_span = None
            try:
                if decl.__class__ is A.Lambda and not decl.is_block:
                    value = self.eval(decl.body, fenv)
                elif decl.__class__ is A.PredicateDecl:
                    value = self.exec_block(decl.body, fenv, scope=False)
                elif provider_body is not None:
                    value = self.run_provider_body(clo, decl, fenv, provider_body)
                else:
                    self.exec_block(decl.body, fenv, scope=False)
                    value = UNIT
            except ReturnSignal as r:
                value = r.value
                ret_span = r.span
            # ---- normal exit: value saved; block cleanup already ran
            if counted:
                inv_obj.op_depth -= 1
                counted = False
            if type(value) is Borrow and provider_body is None:
                raise self.abandon("A.RESOURCE.ESCAPE",
                                   f"`{clo.name}` returns a resource borrow; resources cannot escape their scope",
                                   ret_span or span, fenv, help="return data derived from the resource instead")
            self.check_return(clo, value, ret_span, fenv)
            if contracts:
                self.check_postconditions(clo, contracts, fenv, value, span, frame)
            if outermost:
                self.check_invariants(inv_obj, span, f"on exit from `{clo.name}`", fenv)
            return value
        except Thrown as t:
            if counted:
                inv_obj.op_depth -= 1
                counted = False
            if outermost:
                self.check_invariants(inv_obj, span, f"while `{clo.name}` was propagating an exception", fenv,
                                      pending=f"pending exception: {safe_repr(t.error, Budget(160))}")
            self.check_effect(clo, t, span, fenv)
            raise
        except Cancelled:
            if counted:
                inv_obj.op_depth -= 1
                counted = False
            if outermost:
                self.check_invariants(inv_obj, span, f"while `{clo.name}` was being cancelled", fenv,
                                      pending="cancellation was pending; the invariant failure supersedes it")
            raise
        finally:
            if counted:
                inv_obj.op_depth -= 1
            task.frames.pop()
            task.depth -= 1

    def _dec_op(self, sv):
        tgt = sv.target if type(sv) is Borrow else sv
        if type(tgt) is MutableRecord and tgt.rtype.invariants and tgt.op_depth > 0:
            tgt.op_depth -= 1

    def bind_params(self, clo, params, args, kwargs, fenv: Env, span, node) -> None:
        nparams = len(params)
        if len(args) > nparams:
            raise self.arity_error(clo, f"`{clo.name}` takes {self._param_desc(params)} but {len(args)} "
                                        f"argument(s) were given", span, node)
        vs = fenv.vars
        for i, a in enumerate(args):
            vs[params[i].name] = a
        if kwargs:
            names = {p.name for p in params}
            for k, v in kwargs.items():
                if k not in names:
                    raise self.arity_error(clo, f"`{clo.name}` has no parameter named `{k}`", span, node)
                if k in vs:
                    raise self.arity_error(clo, f"argument `{k}` given twice", span, node)
                vs[k] = v
        if len(vs) < nparams:
            for p in params:
                if p.name not in vs:
                    if p.default is not None:
                        vs[p.name] = self.eval(p.default, clo.env)
                    else:
                        raise self.arity_error(clo, f"missing argument `{p.name}` for `{clo.name}`", span, node)

    def _param_desc(self, params):
        n = len([p for p in params if not p.is_self])
        return f"{n} argument(s)"

    def arity_error(self, clo, msg, span, node):
        d = self.make_diag("A.TYPE.ARITY", msg, span)
        if getattr(clo.decl, "span", None) is not None:
            d.secondary.append(Label(clo.decl.span, "declared here"))
        return Abandoned(d)

    # ------------------------------------------------------------------ annotations
    def type_of_expr(self, texpr, env: Env):
        ty = texpr.ann.get("ty")
        if ty is None:
            ty = self.convert_type(texpr, env)
            texpr.ann["ty"] = ty
        return ty

    def check_param_annotations(self, clo, params, fenv, span, node) -> None:
        reg = self.registry
        for i, p in enumerate(params):
            if p.type is None:
                continue
            ty = self.type_of_expr(p.type, clo.env)
            v = fenv.vars[p.name]
            if p.borrow:
                if type(v) is not Borrow:
                    raise self.mismatch(f"`{clo.name}` expects a borrowed resource for `{p.name}`, received "
                                        f"{type_name(v)}", self.arg_span(node, i, p.name, span), p.type, clo,
                                        f"borrow {ty}", type_name(v), fenv)
                if not reg.check(ty, v.target):
                    raise self.mismatch(f"argument `{p.name}` of `{clo.name}` has the wrong resource type",
                                        self.arg_span(node, i, p.name, span), p.type, clo, f"borrow {ty}",
                                        type_name(v.target), fenv)
                continue
            if not reg.check(ty, v):
                shape = None
                if isinstance(ty, T.TNominal) and ty.kind == "protocol":
                    shape = reg.protocol_shape(ty.qualname, v)
                elif isinstance(ty, T.TFn):
                    shape = reg.check_callable(ty, v)
                msg = (f"argument `{p.name}` of `{clo.name}` expects {ty}, received {type_name(v)}" if not shape
                       else f"argument `{p.name}` of `{clo.name}` does not satisfy {ty}: {shape}")
                raise self.mismatch(msg, self.arg_span(node, i, p.name, span), p.type, clo, str(ty),
                                    type_name(v), fenv, origin_node=self.arg_node(node, i, p.name))

    def arg_node(self, node, i, name):
        if node is None or not isinstance(node, A.Call):
            return None
        offset = 1 if isinstance(node.callee, A.Field) and i > 0 else 0
        for j, a in enumerate(node.args):
            if a.name == name or (a.name is None and j == i - offset):
                return a.value
        return None

    def arg_span(self, node, i, name, default):
        a = self.arg_node(node, i, name)
        return a.span if a is not None else default

    def mismatch(self, msg, span, annot_node, clo, expected, found, env, origin_node=None) -> Abandoned:
        secondary = []
        if annot_node is not None:
            secondary.append(Label(annot_node.span, f"`{clo.name}` relies on this annotation" if clo else
                                   "relied-upon annotation"))
        if origin_node is not None:
            ol = self.origin_label(origin_node, env)
            if ol is not None:
                secondary.append(ol)
        d = self.make_diag("A.TYPE.DYNAMIC_MISMATCH", msg, span, None, label=f"expected {expected}, received {found}",
                           expected=expected, found=found, secondary=secondary)
        return Abandoned(d)

    def origin_label(self, expr, env):
        """Value origin for a dynamic mismatch: where an argument's binding was initialised."""
        if isinstance(expr, A.Name):
            init = expr.ann.get("init_span")
            if init is not None:
                return Label(init, f"value of `{expr.name}` originated here")
        return None

    def check_annotation(self, ty, v, span, annot_node, env, what: str) -> None:
        if not self.registry.check(ty, v):
            secondary = [Label(annot_node.span, f"relied-upon {what}")] if annot_node is not None else []
            raise Abandoned(self.make_diag("A.TYPE.DYNAMIC_MISMATCH", f"value does not match {what} {ty}: found "
                                           f"{type_name(v)}", span, env, label=f"expected {ty}",
                                           expected=str(ty), found=type_name(v), secondary=secondary))

    def transient_check(self, rc, v, span, env, what: str) -> None:
        """IMPL-004 / V3 5.3.7: typed code consumed a nested value whose static type
        relies on a written annotation that the boundary checked only shallowly."""
        ty, origin = rc
        if type(v) is Borrow:
            v = v.target
        if not self.registry.check(ty, v):
            raise Abandoned(self.make_diag(
                "A.TYPE.DYNAMIC_MISMATCH", f"{what} is {type_name(v)}, but the annotation relied on here says {ty}",
                span, env, label=f"expected {ty}", expected=str(ty), found=type_name(v),
                secondary=[Label(origin, "relied-upon annotation")] if origin is not None else [],
                help="the value entered typed code through a dynamic boundary; validate or convert it there"))

    def check_return(self, clo, value, ret_span, env) -> None:
        decl = clo.decl
        rt = getattr(decl, "ret", None)
        if rt is None:
            return
        ty = self.type_of_expr(rt, clo.env)
        if not self.registry.check(ty, value):
            d = self.make_diag("A.TYPE.DYNAMIC_MISMATCH",
                               f"`{clo.name}` returned {type_name(value)}, but its annotation promises {ty}",
                               ret_span or decl.span, env, label=f"returns {type_name(value)}",
                               expected=str(ty), found=type_name(value),
                               secondary=[Label(rt.span, "declared return type")])
            raise Abandoned(d)

    def check_field_value(self, rt: RecordType, f, v, span, env):
        if type(v) is Borrow:
            raise self.abandon("A.RESOURCE.ESCAPE",
                               f"a resource borrow cannot be stored in field `{f.name}` of {rt.name}",
                               span, env, help="resources stay inside their `use` scope")
        if not rt.mutable and not is_frozen(v):
            raise self.abandon("A.TYPE.FROZEN_MUTATION",
                               f"field `{f.name}` of frozen record {rt.name} must hold a frozen value, found "
                               f"mutable {type_name(v)}", span, env,
                               help="freeze it (`.freeze()`) or declare `mutable record " + rt.name + "`")
        if f.type is not None and f.type is not T.DYN and not self.registry.check(f.type, v):
            secondary = [Label(f.span, f"field `{f.name}` declared here")] if f.span is not None and f.span.file.text else []
            raise Abandoned(self.make_diag("A.TYPE.DYNAMIC_MISMATCH",
                                           f"field `{f.name}` of {rt.name} expects {f.type}, received {type_name(v)}",
                                           span, env, label=f"expected {f.type}", expected=str(f.type),
                                           found=type_name(v), secondary=secondary))
        return v

    # ------------------------------------------------------------------ effects
    def check_effect(self, clo, t: Thrown, span, env) -> None:
        allowed = self.allowed_errors(clo)
        if allowed is None:
            allowed = self.allowed_errors_bound(clo, env)
        if allowed is None:
            return
        err = t.error
        if self.error_in(err, allowed):
            return
        d = self.make_diag("A.EFFECT.UNDECLARED_EXCEPTION",
                           f"`{clo.name}` let {self.error_summary(err)} escape, but its throws clause does not "
                           f"declare {type_name(err)}", t.prov.created_at or span, env,
                           label="error raised here",
                           secondary=[Label(clo.decl.span, f"`{clo.name}` declares its throws set here")],
                           help=f"add `{type_name(err)}` to the throws clause of `{clo.name}`, or handle it with "
                                f"`try ... catch {type_name(err)} => ...`")
        raise Abandoned(d)

    def allowed_errors(self, clo):
        """None if unannotated/permissive; else a list of runtime error types."""
        decl = clo.decl
        cached = decl.ann.get("rt_throws", 0)
        if cached != 0:
            return cached
        throws = getattr(decl, "throws", None)
        if throws is None:
            decl.ann["rt_throws"] = None
            return None
        out = []
        for texpr in throws:
            ty = self.type_of_expr(texpr, clo.env)
            if isinstance(ty, T.TVar) or ty is T.DYN:
                decl.ann["rt_throws"] = None
                return None
            if isinstance(ty, T.TNominal):
                rtt = self.registry.nominals.get(ty.qualname)
                if rtt is not None:
                    out.append(rtt)
        decl.ann["rt_throws"] = out
        return out

    def allowed_errors_bound(self, clo, fenv):
        """Written throws sets with error-set variables (`throws E`): each variable is
        bound per call by the effects of the callable arguments whose annotated type
        mentions it (V3 5.8, 7.7.5; BUG-0027). None (permissive) if any binding callable
        has an unknown effect or a variable is unbound."""
        decl = clo.decl
        throws = getattr(decl, "throws", None)
        if not throws:
            return None
        out, variables = [], set()
        for texpr in throws:
            ty = self.type_of_expr(texpr, clo.env)
            if ty is T.DYN:
                return None
            if isinstance(ty, T.TVar):
                variables.add(ty.name)
            elif isinstance(ty, T.TNominal):
                rtt = self.registry.nominals.get(ty.qualname)
                if rtt is not None:
                    out.append(rtt)
        bound = {v: set() for v in variables}
        seen = set()
        for p in decl.params:
            if p.is_self or p.type is None:
                continue
            pty = self.type_of_expr(p.type, clo.env)
            if not isinstance(pty, T.TFn) or pty.effect is None:
                continue
            vars_here = [i.name for i in pty.effect.items if isinstance(i, T.TVar) and i.name in bound]
            if not vars_here:
                continue
            arg = fenv.vars.get(p.name)
            eff = _callable_effect(arg)
            if eff is None:
                return None
            for v in vars_here:
                bound[v] |= set(eff)
                seen.add(v)
        if seen != variables:
            return None
        for names in bound.values():
            for q in names:
                rtt = self.registry.nominals.get(q)
                if rtt is not None:
                    out.append(rtt)
        return out

    def error_in(self, err, allowed) -> bool:
        for a in allowed:
            if type(err) is FrozenRecord and err.rtype is a:
                return True
            if type(err) is VariantValue and err.case.etype is a:
                return True
        return False

    # ------------------------------------------------------------------ contracts
    def contracts_for(self, clo):
        decl = clo.decl
        cached = decl.ann.get("contracts")
        if cached is not None:
            return cached
        items = []  # (kind, expr, protocol_decl_or_None)
        for r in getattr(decl, "requires", []) or []:
            items.append(("requires", r, None))
        for e in getattr(decl, "ensures", []) or []:
            items.append(("ensures", e, None))
        owner = clo.owner
        if owner is not None:
            for pdecl in owner.protocol_contracts.get(clo.name, []):
                for r in pdecl.requires:
                    items.append(("requires", r, pdecl))
                for e in pdecl.ensures:
                    items.append(("ensures", e, pdecl))
        decl.ann["contracts"] = items
        return items

    def contract_env(self, clo, pdecl, fenv: Env) -> Env:
        if pdecl is None:
            return fenv
        cenv = Env(clo.env, kind="fn")
        impl_params = clo.decl.params
        for pp, ip in zip(pdecl.params, impl_params):
            cenv.vars[pp.name] = fenv.vars.get(ip.name)
        return cenv

    def eval_contract(self, expr, env, frame=None):
        task = self.sched.current
        fr = task.frames[-1]
        saved = fr.contract_mode
        fr.contract_mode = True
        try:
            return self.eval(expr, env)
        except Abandoned as a:
            a.diagnostic.notes.append(Note("raised while evaluating a contract expression", expr.span))
            raise
        except Thrown as t:
            raise self.abandon("A.CONTRACT.EVALUATION_FAILED",
                               "contract expression threw a recoverable error (contracts must be total)",
                               expr.span, env)
        finally:
            fr.contract_mode = saved

    def check_preconditions(self, clo, contracts, fenv, span, node) -> None:
        for kind, expr, pdecl in contracts:
            if kind != "requires":
                continue
            cenv = self.contract_env(clo, pdecl, fenv)
            v = self.eval_contract(expr, cenv)
            if v is not True:
                if type(v) is not bool:
                    raise self.abandon("A.CONTRACT.EVALUATION_FAILED",
                                       f"precondition evaluated to {type_name(v)}, not Bool", expr.span, cenv)
                origin = f" (inherited from protocol {pdecl.owner})" if pdecl is not None else ""
                d = self.make_diag("A.CONTRACT.PRECONDITION_FAILED",
                                   f"call to `{clo.name}` violates its precondition `{expr.span.text}`{origin}",
                                   span, cenv, label="this call violates the precondition",
                                   secondary=[Label(expr.span, "precondition declared here")],
                                   values=self.explain_values(expr, cenv))
                d.notes.append(Note("the caller is responsible for satisfying preconditions (blame: caller)"))
                frames = d.frames
                if frames:
                    # the callee frame is innermost; blame lies with the caller's frame
                    d.frames = frames[1:] if len(frames) > 1 else frames
                raise Abandoned(d)

    def take_snapshots(self, clo, contracts, fenv, frame) -> None:
        olds = []
        for kind, expr, pdecl in contracts:
            if kind != "ensures":
                continue
            for n in A.walk(expr):
                if isinstance(n, A.Call) and isinstance(n.callee, A.Name) and n.callee.name == "old" and len(n.args) == 1:
                    olds.append((n, pdecl))
        if not olds:
            return
        frame.snapshots = {}
        for n, pdecl in olds:
            cenv = self.contract_env(clo, pdecl, fenv)
            v = self.eval_contract(n.args[0].value, cenv)
            if not is_frozen(v):
                raise self.abandon("A.CONTRACT.EVALUATION_FAILED",
                                   f"old(...) captured a mutable {type_name(v)}; only primitive/frozen results can be "
                                   f"snapshotted", n.span, cenv,
                                   help="snapshot a primitive or frozen projection, e.g. old(account.balance)")
            frame.snapshots[n.id] = v

    def check_postconditions(self, clo, contracts, fenv, value, span, frame) -> None:
        for kind, expr, pdecl in contracts:
            if kind != "ensures":
                continue
            cenv = Env(self.contract_env(clo, pdecl, fenv))
            cenv.vars["result"] = value
            v = self.eval_contract(expr, cenv)
            if v is not True:
                if type(v) is not bool:
                    raise self.abandon("A.CONTRACT.EVALUATION_FAILED",
                                       f"postcondition evaluated to {type_name(v)}, not Bool", expr.span, cenv)
                origin = f" (inherited from protocol {pdecl.owner})" if pdecl is not None else ""
                values = self.explain_values(expr, cenv)
                if frame.snapshots:
                    for n in A.walk(expr):
                        if isinstance(n, A.Call) and n.id in frame.snapshots:
                            values[n.span.text] = safe_repr(frame.snapshots[n.id], Budget(120))
                d = self.make_diag("A.CONTRACT.POSTCONDITION_FAILED",
                                   f"`{clo.name}` broke its postcondition `{expr.span.text}`{origin}",
                                   expr.span, cenv, label="this postcondition is false on return",
                                   secondary=[Label(clo.decl.span, f"`{clo.name}` (blame: implementation)")],
                                   values=values)
                raise Abandoned(d)

    def check_invariants(self, obj, span, context: str, env, pending: str | None = None) -> None:
        rt = obj.rtype if type(obj) is not Borrow else obj.target.rtype
        target = obj.target if type(obj) is Borrow else obj
        for inv in rt.invariants:
            ienv = Env(rt.module_env if getattr(rt, "module_env", None) is not None else env, kind="fn")
            for f, v in zip(rt.fields, target.values):
                ienv.vars[f.name] = v
            ienv.vars["self"] = target
            v = self.eval_contract(inv, ienv)
            if v is not True:
                if type(v) is not bool:
                    raise self.abandon("A.CONTRACT.EVALUATION_FAILED",
                                       f"invariant evaluated to {type_name(v)}, not Bool", inv.span, ienv)
                d = self.make_diag("A.CONTRACT.INVARIANT_VIOLATED",
                                   f"invariant `{inv.span.text}` of {rt.name} does not hold {context}",
                                   inv.span, ienv, label="invariant violated",
                                   secondary=[Label(span, "operation boundary")] if span is not None else [],
                                   values=self.explain_values(inv, ienv))
                if pending:
                    d.notes.append(Note(pending))
                raise Abandoned(d)

    # ------------------------------------------------------------------ construction
    def construct(self, tv: TypeValue, args, kwargs, span, env, node=None):
        k = tv.kind
        if k == "record":
            obj = self.construct_record(tv.target, args, kwargs, span, env, node)
            if tv.args and getattr(tv.target, "type_params", None):
                self.check_type_arguments(tv, obj, span, env, node)
            return obj
        if k == "case":
            return self.construct_case(tv.target, args, kwargs, span, env)
        if k == "builtin":
            name = tv.target
            if args or kwargs:
                raise Fault("A.TYPE.ARITY", f"`{name}()` takes no arguments; use `{name}.of(...)` to provide elements")
            elem_ty = None
            if tv.args:
                elem_ty = tv.args[0] if not isinstance(tv.args[0], TypeValue) else None
            if name == "MutableList":
                return MutableList([], self.type_arg(tv, 0))
            if name == "MutableMap":
                return MutableMap({}, self.type_arg(tv, 0), self.type_arg(tv, 1))
            if name == "MutableSet":
                return MutableSet({}, self.type_arg(tv, 0))
            del elem_ty
            raise Fault("A.TYPE.NOT_CALLABLE", f"`{name}` cannot be constructed by calling it",
                        help=f"use `{name}.of(...)`, a literal, or the documented constructor")
        if k == "enum":
            raise Fault("A.TYPE.NOT_CALLABLE", f"enum `{tv.name}` is not constructible directly; choose a case, "
                                               f"e.g. `{tv.name}.{next(iter(tv.target.cases), 'Case')}(...)`")
        raise Fault("A.TYPE.NOT_CALLABLE", f"`{tv.name}` is not callable")

    def check_type_arguments(self, tv: TypeValue, obj, span, env, node) -> None:
        """`Box[Int](v: ...)`: explicitly written type arguments are annotations, so the
        fields whose declared type mentions a parameter are checked (BUG-0025)."""
        rt = tv.target
        sub = {p: self.type_arg(tv, i) for i, p in enumerate(rt.type_params)}
        sub = {k: v for k, v in sub.items() if v is not None}
        for f, v in zip(rt.fields, obj.values):
            if f.type is None:
                continue
            want = T.substitute(f.type, sub)
            if want is f.type or str(want) == str(f.type):
                continue
            if not self.registry.check(want, v):
                raise Abandoned(self.make_diag(
                    "A.TYPE.DYNAMIC_MISMATCH", f"field `{f.name}` of {tv.name}[...] expects {want}, received "
                    f"{type_name(v)}", self._field_arg_span(node, f.name, span), env, label=f"expected {want}",
                    expected=str(want), found=type_name(v)))

    def type_arg(self, tv: TypeValue, i: int):
        if i < len(tv.args):
            a = tv.args[i]
            if isinstance(a, TypeValue):
                return self.type_value_to_ty(a)
            return a
        return None

    def construct_record(self, rt: RecordType, args, kwargs, span, env, node=None):
        fields = rt.fields
        vals = [None] * len(fields)
        given = [False] * len(fields)
        if args:
            if len(fields) == 1 and len(args) == 1 and not kwargs:
                vals[0] = args[0]
                given[0] = True
            else:
                raise Fault("A.TYPE.ARITY", f"{rt.name} must be constructed with named fields, e.g. "
                                            f"{rt.name}({', '.join(f.name + ': ...' for f in fields[:3])})")
        for name, v in (kwargs or {}).items():
            i = rt.field_index.get(name)
            if i is None:
                import difflib
                close = difflib.get_close_matches(name, list(rt.field_index), n=2)
                raise Fault("A.TYPE.UNKNOWN_FIELD", f"{rt.name} has no field `{name}`",
                            help=("did you mean " + ", ".join(f"`{c}`" for c in close) + "?") if close else None)
            vals[i] = v
            given[i] = True
        for i, f in enumerate(fields):
            if not given[i]:
                if f.default is not None:
                    vals[i] = self.eval(f.default, rt.module_env)
                else:
                    raise Fault("A.TYPE.MISSING_FIELD", f"{rt.name} is missing field `{f.name}`",
                                help=f"provide `{f.name}: ...`")
        for i, f in enumerate(fields):
            vals[i] = self.check_field_value(rt, f, vals[i], self._field_arg_span(node, f.name, span), env)
        if rt.mutable:
            obj = MutableRecord(rt, vals, self.sched.current)
        else:
            obj = FrozenRecord(rt, tuple(vals))
        if rt.invariants:
            self.check_invariants(obj, span, "after construction", env)
        return obj

    def _field_arg_span(self, node, name, default):
        if isinstance(node, A.Call):
            for a in node.args:
                if a.name == name:
                    return a.value.span
        return default

    def construct_case(self, ci: CaseInfo, args, kwargs, span, env):
        fields = ci.fields or []
        if ci.fields is None:
            raise Fault("A.TYPE.ARITY", f"`{ci.qualname}` has no payload; write it without parentheses")
        vals = [None] * len(fields)
        given = [False] * len(fields)
        if len(args) > len(fields):
            raise Fault("A.TYPE.ARITY", f"`{ci.qualname}` takes {len(fields)} field(s), got {len(args)}")
        for i, v in enumerate(args):
            vals[i] = v
            given[i] = True
        for name, v in (kwargs or {}).items():
            i = ci.field_index.get(name)
            if i is None:
                raise Fault("A.TYPE.UNKNOWN_FIELD", f"`{ci.qualname}` has no field `{name}`")
            if given[i]:
                raise Fault("A.TYPE.ARITY", f"field `{name}` given twice")
            vals[i] = v
            given[i] = True
        for i, f in enumerate(fields):
            if not given[i]:
                raise Fault("A.TYPE.MISSING_FIELD", f"`{ci.qualname}` is missing field `{f.name}`")
            v = vals[i]
            if type(v) is Borrow:
                raise Fault("A.RESOURCE.ESCAPE", "a resource borrow cannot be stored in a variant payload")
            if f.type is not None and not isinstance(f.type, T.TVar) and f.type is not T.DYN and \
                    not self.registry.check(f.type, v):
                raise Fault("A.TYPE.DYNAMIC_MISMATCH",
                            f"field `{f.name}` of {ci.qualname} expects {f.type}, received {type_name(v)}",
                            expected=str(f.type), found=type_name(v))
        if ci is ERR_CASE:
            return VariantValue(ci, tuple(vals), self.new_provenance(span))
        return VariantValue(ci, tuple(vals))


def _callable_effect(v):
    """The known effect (qualified error names) of a runtime callable, or None."""
    t = type(v)
    if t is Closure:
        return v.effect
    if t is BoundMethod:
        return v.func.effect
    if t is Builtin:
        return frozenset(v.effect or ())
    if t is BuiltinBound:
        return frozenset(v.builtin.effect or ())
    return None
