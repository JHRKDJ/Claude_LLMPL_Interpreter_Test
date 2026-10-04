"""Expression typing for the static checker (mixed into Checker)."""
from __future__ import annotations

from typing import Optional

from .. import typesys as T
from ..diagnostics import Label
from ..runtime.builtins.registry import METHODS, MODULES, PRELUDE, PROPS, STATICS
from ..runtime.core_types import ALL_CORE_TYPES
from ..runtime.values import Builtin, TypeValue
from ..syntax import ast as A
from .decls import FnSig, TypeInfo
from .exhaustive import check_match
from .types import DYN, consistent, is_mutable_type, join, kind_of_type, receiver_bindings, sig_type, unify
from .walk import AGG, CHCLOSED, DEADLINE, CORE_CASES, short


class TypeRef(T.Ty):
    """A nominal type used as a value (constructor / namespace)."""
    __slots__ = ("info", "args")

    def __init__(self, info: TypeInfo, args=()):
        self.info = info
        self.args = tuple(args)

    def _key(self):
        return (self.info.qualname, self.args)

    def __str__(self):
        return f"type {self.info.name}"


class BuiltinTypeRef(T.Ty):
    __slots__ = ("name", "args")

    def __init__(self, name: str, args=()):
        self.name = name
        self.args = tuple(args)

    def _key(self):
        return (self.name, self.args)

    def __str__(self):
        return f"type {self.name}"


class ModRef(T.Ty):
    __slots__ = ("module",)

    def __init__(self, module: str):
        self.module = module

    def _key(self):
        return self.module

    def __str__(self):
        return f"module {self.module}"


class CaseRef(T.Ty):
    __slots__ = ("info", "case")

    def __init__(self, info: Optional[TypeInfo], case: str):
        self.info = info
        self.case = case

    def _key(self):
        return (self.info.qualname if self.info else "core", self.case)

    def __str__(self):
        return f"case {self.case}"


class SigRef(T.Ty):
    """A callable with a full declaration signature (better diagnostics than TFn)."""
    __slots__ = ("sig", "self_ty", "bound")

    def __init__(self, sig: FnSig, self_ty=None, bound: bool = False):
        self.sig = sig
        self.self_ty = self_ty
        self.bound = bound

    def _key(self):
        return (id(self.sig), self.bound)

    def __str__(self):
        return str(self.sig.as_fn_type())


class BuiltinRef(T.Ty):
    __slots__ = ("b", "recv", "static_args")

    def __init__(self, b: Builtin, recv=None, static_args=()):
        self.b = b
        self.recv = recv
        self.static_args = static_args

    def _key(self):
        return (id(self.b), str(self.recv))

    def __str__(self):
        return f"builtin {self.b.name}"


PRIMS = {"Int", "Float", "Bool", "Str", "Unit", "Dyn", "Never"}
BUILTIN_TYPES = {"List", "Map", "Set", "MutableList", "MutableMap", "MutableSet", "Duration", "Instant", "Channel",
                 "Broadcast", "Task", "SendPort", "ReceivePort", "Range", "Option", "Result"}


def opt(t):
    return T.TCon("Option", (t,))


class ExprMixin:
    def callable_type(self, t):
        if isinstance(t, SigRef):
            return t.sig.as_fn_type()
        return t

    # ------------------------------------------------------------------ names
    def name_type(self, node: A.Name, sc) -> T.Ty:
        ent = sc.get(node.name)
        if ent is not None:
            return ent[0]
        return self.global_type(node.name, node)

    def global_type(self, name: str, node=None) -> T.Ty:
        if name in CORE_CASES:
            if name == "None":
                return opt(DYN)
            return CaseRef(None, name)
        ent = self.lookup_global(self.cur_module, name)
        if ent is None:
            if name in PRIMS:
                return BuiltinTypeRef(name)
            if name in BUILTIN_TYPES:
                return BuiltinTypeRef(name)
            if name in ("time", "cancel"):
                return ModRef(f"prelude.{name}")
            return DYN
        kind, v = ent
        if kind in ("fn", "predicate"):
            return SigRef(v) if v is not None else DYN
        if kind == "type":
            return TypeRef(v)
        if kind == "const":
            return v if v is not None else DYN
        if kind == "module":
            return ModRef(v)
        if kind == "prelude":
            return BuiltinRef(v)
        if kind == "native":
            if isinstance(v, Builtin):
                return BuiltinRef(v)
            if isinstance(v, TypeValue):
                return BuiltinTypeRef(v.target)
            if isinstance(v, float):
                return T.FLOAT
            return DYN
        if kind == "category":
            return DYN
        return DYN

    def module_member(self, m: str, name: str) -> T.Ty:
        if m.startswith("prelude."):
            b = MODULES.get(m, {}).get(name)
            return BuiltinRef(b) if b is not None else DYN
        ent = self.modules.get(m, {}).get(name)
        if ent is None:
            return DYN
        kind, v = ent
        if kind in ("fn", "predicate") and v is not None:
            return SigRef(v)
        if kind == "type":
            return TypeRef(v)
        if kind == "const":
            return v if v is not None else DYN
        if kind == "native":
            if isinstance(v, Builtin):
                return BuiltinRef(v)
            if isinstance(v, TypeValue):
                return BuiltinTypeRef(v.target)
            if isinstance(v, float):
                return T.FLOAT
        return DYN

    # ------------------------------------------------------------------ dispatch
    def expr(self, e, sc) -> T.Ty:
        m = getattr(self, "x_" + e.__class__.__name__, None)
        if m is None:
            return DYN
        t = m(e, sc)
        return t if t is not None else DYN

    def x_Literal(self, e, sc):
        return {"int": T.INT, "float": T.FLOAT, "bool": T.BOOL, "null": opt(DYN), "unit": T.UNIT,
                "str": T.STR}.get(e.kind, DYN)

    def x_StringLit(self, e, sc):
        for p in e.parts:
            if isinstance(p, A.InterpPart):
                t = self.expr(p.expr, sc)
                if p.spec and "." in p.spec and t not in (T.FLOAT, DYN):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"precision format applies to Float, found {t}", p.span)
        return T.STR

    def x_Name(self, e, sc):
        t = self.name_type(e, sc)
        if isinstance(t, (BuiltinTypeRef,)) and t.name in PRIMS:
            return t
        return t

    def x_ListLit(self, e, sc):
        t = T.NEVER
        for i in e.items:
            it = self.expr(i, sc)
            if isinstance(it, T.TBorrow):
                self.oblig("S.RESOURCE.ESCAPE", "a resource borrow cannot be stored in a collection", i.span)
            if is_mutable_type(it):
                self.oblig("S.TYPE.FROZEN_MUTATION", f"a frozen List cannot contain mutable {it}", i.span,
                           help="freeze it first or use `MutableList.of(...)`")
            t = join(t, it)
        return T.TCon("List", (DYN if t is T.NEVER else t,))

    def x_MapLit(self, e, sc):
        kt = vt = T.NEVER
        for k, v in e.entries:
            kt = join(kt, self.expr(k, sc))
            vv = self.expr(v, sc)
            if is_mutable_type(vv):
                self.oblig("S.TYPE.FROZEN_MUTATION", f"a frozen Map cannot contain mutable {vv}", v.span)
            vt = join(vt, vv)
        return T.TCon("Map", (DYN if kt is T.NEVER else kt, DYN if vt is T.NEVER else vt))

    def x_TupleLit(self, e, sc):
        return T.TTuple(self.expr(i, sc) for i in e.items)

    def x_Range(self, e, sc):
        for x in (e.lo, e.hi):
            t = self.expr(x, sc)
            if not consistent(t, T.INT):
                self.oblig("S.TYPE.STATIC_MISMATCH", f"range bounds must be Int, found {t}", x.span)
        return T.RANGE

    def x_Unary(self, e, sc):
        t = self.expr(e.operand, sc)
        if e.op == "!":
            if not consistent(t, T.BOOL):
                self.oblig("S.TYPE.INVALID_OPERATOR", f"`!` requires Bool, found {t}", e.span)
            return T.BOOL
        if t in (T.INT, T.FLOAT, T.DURATION) or t is DYN:
            return t
        self.oblig("S.TYPE.INVALID_OPERATOR", f"unary `-` is not defined for {t}", e.span)
        return DYN

    def x_Binary(self, e, sc):
        op = e.op
        a = self.expr(e.left, sc)
        if op in ("&&", "||"):
            b = self.expr(e.right, sc)
            for side, t in (("left", a), ("right", b)):
                if not consistent(t, T.BOOL):
                    self.oblig("S.TYPE.INVALID_OPERATOR", f"`{op}` requires Bool operands, {side} is {t}",
                               e.left.span if side == "left" else e.right.span,
                               help="there is no truthiness; compare explicitly")
            return T.BOOL
        b = self.expr(e.right, sc)
        if isinstance(a, T.TBorrow):
            a = a.inner
        if isinstance(b, T.TBorrow):
            b = b.inner
        if op in ("==", "!="):
            if {a, b} == {T.INT, T.FLOAT}:
                self.oblig("S.TYPE.INVALID_OPERATOR", "comparing Int with Float abandons at runtime (no implicit "
                           "coercion)", e.span, help="convert explicitly with toFloat()/toInt()")
            elif a is not DYN and b is not DYN and not consistent(a, b) and not consistent(b, a) \
                    and not (isinstance(a, T.TVar) or isinstance(b, T.TVar)):
                self.oblig("S.TYPE.ALWAYS_FALSE_EQUALITY",
                           f"comparison between {a} and {b} is always {'false' if op == '==' else 'true'}", e.span,
                           help="values of different types are never equal (no implicit conversion); convert "
                                "explicitly or compare like with like")
            elif is_mutable_type(a):
                self.advise("W.TYPE.IDENTITY_EQUALITY", f"`{op}` on {a} compares identity, not contents", e.span,
                            help="compare frozen snapshots (`a.freeze() == b.freeze()`) to compare contents")
            return T.BOOL
        if op in ("<", "<=", ">", ">="):
            if a is not DYN and b is not DYN and a != b and not isinstance(a, T.TVar) and not isinstance(b, T.TVar):
                self.oblig("S.TYPE.INVALID_OPERATOR", f"cannot order {a} and {b}", e.span,
                           help=self.mismatch_help(a, b))
            elif a is not DYN and a not in (T.INT, T.FLOAT, T.STR, T.DURATION, T.INSTANT) and \
                    not isinstance(a, (T.TTuple, T.TVar)) and not (isinstance(a, T.TCon) and a.name == "List"):
                self.oblig("S.TYPE.INVALID_OPERATOR", f"values of type {a} are not ordered", e.span)
            return T.BOOL
        if a is DYN or b is DYN or isinstance(a, T.TVar) or isinstance(b, T.TVar):
            if op == "/" and a == T.INT and b in (DYN, T.INT):
                return T.FLOAT
            return DYN
        res = None
        if a == b:
            if a == T.INT:
                res = T.FLOAT if op == "/" else T.INT
            elif a == T.FLOAT:
                res = T.FLOAT
            elif a == T.STR and op == "+":
                res = T.STR
            elif isinstance(a, T.TCon) and a.name == "List" and op == "+":
                res = a
            elif a == T.DURATION and op in ("+", "-"):
                res = T.DURATION
            elif a == T.INSTANT and op == "-":
                res = T.DURATION
        elif a == T.INSTANT and b == T.DURATION and op in ("+", "-"):
            res = T.INSTANT
        elif a == T.DURATION and b == T.INSTANT and op == "+":
            res = T.INSTANT
        elif a == T.DURATION and b == T.INT and op in ("*", "/"):
            res = T.DURATION
        elif a == T.INT and b == T.DURATION and op == "*":
            res = T.DURATION
        if res is None:
            help_ = "convert explicitly with toFloat()/toInt()" if {a, b} == {T.INT, T.FLOAT} else (
                "build strings with interpolation" if op == "+" and T.STR in (a, b) else None)
            self.oblig("S.TYPE.INVALID_OPERATOR", f"`{op}` is not defined for {a} and {b}", e.span, help=help_)
            return DYN
        return res

    # ------------------------------------------------------------------ members
    def x_Field(self, e, sc):
        ot = self.expr(e.obj, sc)
        return self.member_type(ot, e, sc)

    def member_type(self, ot, e: A.Field, sc, for_call: bool = False):
        name = e.name
        if isinstance(ot, T.TBorrow):
            ot = ot.inner
        if isinstance(ot, ModRef):
            return self.module_member(ot.module, name)
        if isinstance(ot, TypeRef):
            ti = ot.info
            if name in ti.cases:
                if ti.cases[name] is None:
                    return ti.ty
                return CaseRef(ti, name)
            m = ti.methods.get(name)
            if m is not None:
                return SigRef(m)
            if ti.kind != "protocol":
                self.oblig("S.TYPE.UNKNOWN_FIELD", f"`{ti.name}` has no case or associated function `{name}`",
                           e.name_span or e.span)
            return DYN
        if isinstance(ot, BuiltinTypeRef):
            st = STATICS.get(ot.name, {}).get(name)
            if st is not None:
                return BuiltinRef(st, ot)
            if ot.name in BUILTIN_TYPES:
                self.oblig("S.TYPE.UNKNOWN_FIELD", f"`{ot.name}` has no associated function `{name}`",
                           e.name_span or e.span,
                           help=("available: " + ", ".join(sorted(STATICS.get(ot.name, {})))) or None)
            return DYN
        if isinstance(ot, T.TNominal):
            ti = self.types.get(ot.qualname)
            if ti is None:
                return DYN
            if name in ti.fields:
                return self.subst_owner(ti, ot, ti.fields[name])
            m = ti.methods.get(name)
            if m is not None:
                return SigRef(m, ot, bound=True)
            if ti.qualname == "core.AggregateException":
                b = METHODS.get("AggregateException", {}).get(name)
                if b is not None:
                    return BuiltinRef(b, ot)
            if ti.kind in ("enum", "errorenum"):
                for c in ti.cases.values():
                    if c and any(fn == name for fn, _ in c):
                        self.oblig("S.TYPE.UNKNOWN_FIELD", f"variant payload field `{name}` cannot be read with `.`",
                                   e.name_span or e.span, help="match on the case to read its payload")
                        return DYN
            if ti.kind != "protocol" or name not in ti.methods:
                self.unknown_member(e, ti.name, list(ti.fields) + list(ti.methods), for_call)
            return DYN
        if isinstance(ot, T.TTuple):
            if name.isdigit():
                i = int(name)
                if i < len(ot.items):
                    return ot.items[i]
                self.oblig("S.TYPE.UNKNOWN_FIELD", f"tuple has no element .{i}", e.span)
                return DYN
        k = kind_of_type(ot)
        if k is not None:
            p = PROPS.get(k, {}).get(name)
            if p is not None:
                return self.parse_prop_type(p[1], ot)
            b = METHODS.get(k, {}).get(name)
            if b is not None:
                return BuiltinRef(b, ot)
            members = list(PROPS.get(k, {})) + list(METHODS.get(k, {}))
            self.unknown_member(e, str(ot), members, for_call)
        return DYN

    def subst_owner(self, ti, ot, t):
        if ti.type_params and getattr(ot, "args", None):
            return T.substitute(t, dict(zip(ti.type_params, ot.args)))
        return t

    def parse_prop_type(self, sig: str, recv):
        if not sig or sig == "Dyn":
            return DYN
        ft, _ = sig_type(f"fn() -> {sig}", receiver_bindings(recv), self.core_resolver)
        return ft.ret if ft is not None else DYN

    def core_resolver(self, path, node):
        name = path[-1]
        core = ALL_CORE_TYPES.get(name)
        if core is not None and core.qualname in self.types:
            ti = self.types[core.qualname]
            return T.TNominal(ti.qualname, ti.kind)
        if name in ("File", "Dir", "PublishPort"):
            return T.TCon(name, ()) if name != "PublishPort" else T.TCon(name, (DYN,))
        return None

    def x_Index(self, e, sc):
        ot = self.expr(e.obj, sc)
        its = [self.expr(i, sc) for i in e.indices]
        if isinstance(ot, T.TBorrow):
            ot = ot.inner
        if isinstance(ot, (BuiltinTypeRef, TypeRef)):
            args = [self.type_from_value_expr(i) for i in e.indices]
            if isinstance(ot, TypeRef):
                return TypeRef(ot.info, args)
            return BuiltinTypeRef(ot.name, args)
        if isinstance(ot, SigRef):
            return ot
        if len(its) != 1:
            return DYN
        it = its[0]
        if isinstance(ot, T.TCon):
            if ot.name in ("List", "MutableList"):
                if not consistent(it, T.INT):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"list index must be Int, found {it}", e.indices[0].span)
                elem = ot.args[0]
                if elem is not DYN and not isinstance(elem, T.TVar):
                    e.ann["rt_check"] = elem
                return elem
            if ot.name in ("Map", "MutableMap"):
                if not consistent(it, ot.args[0]):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"map key must be {ot.args[0]}, found {it}",
                               e.indices[0].span)
                v = ot.args[1]
                if v is not DYN and not isinstance(v, T.TVar):
                    e.ann["rt_check"] = v
                return v
            if ot.name in ("Set", "MutableSet"):
                self.oblig("S.TYPE.INVALID_OPERATOR", "sets cannot be indexed; use `.contains(x)`", e.span)
                return DYN
        if ot == T.STR:
            return T.STR
        if ot is DYN:
            return DYN
        if isinstance(ot, (T.TNominal, T.TTuple)) or ot in (T.INT, T.FLOAT, T.BOOL):
            self.oblig("S.TYPE.INVALID_OPERATOR", f"{ot} cannot be indexed", e.span)
        return DYN

    def type_from_value_expr(self, e) -> T.Ty:
        """Interpret an expression used as a type argument (e.g. `Int` in `Channel[Int]`)."""
        if isinstance(e, A.Name):
            if e.name in T.PRIMS:
                return T.PRIMS[e.name]
            ent = self.lookup_global(self.cur_module, e.name)
            if ent is not None and ent[0] == "type":
                return ent[1].ty
            if e.name in T.CON_ARITY:
                return T.TCon(e.name, tuple(DYN for _ in range(T.CON_ARITY[e.name])))
            for fs in self.fn_stack:
                d = fs.decl
                if d is not None and e.name in (getattr(d, "type_params", []) or []):
                    return T.TVar(e.name)
        if isinstance(e, A.Index) and isinstance(e.obj, A.Name) and e.obj.name in T.CON_ARITY:
            return T.TCon(e.obj.name, tuple(self.type_from_value_expr(i) for i in e.indices))
        return DYN

    # ------------------------------------------------------------------ records
    def x_WithUpdate(self, e, sc):
        ot = self.expr(e.obj, sc)
        ti = self.types.get(ot.qualname) if isinstance(ot, T.TNominal) else None
        if ti is not None and ti.kind not in ("record", "error"):
            self.oblig("S.TYPE.INVALID_WITH", f"`with` creates an updated copy of a frozen record; {ti.name} is "
                       f"{'mutable' if ti.kind == 'mrecord' else 'not a record'}", e.span,
                       help="assign fields directly on mutable records" if ti.kind == "mrecord" else None)
        for name, v, span in e.fields:
            vt = self.expr(v, sc)
            if ti is not None and ti.kind in ("record", "error"):
                if name not in ti.fields:
                    self.oblig("S.TYPE.UNKNOWN_FIELD", f"{ti.name} has no field `{name}`", span)
                elif not consistent(vt, ti.fields[name], self.satisfies):
                    self.mismatch(v.span, ti.fields[name], vt, f"field `{name}`", ti.field_spans.get(name))
        return ot

    # ------------------------------------------------------------------ lambdas
    def x_Lambda(self, e: A.Lambda, sc):
        from .typecheck import FnState, Scope
        lsc = Scope(sc)
        ptys = []
        for p in e.params:
            t = self.ty(p.type, self.cur_module, self.tparams())
            if p.borrow:
                t = T.TBorrow(t)
            ptys.append(t)
            lsc.vars[p.name] = (t, "param", p.span)
        ret_ann = self.ty(e.ret, self.cur_module, self.tparams()) if e.ret is not None else None
        sig = FnSig("<lambda>", [(p.name, t, False, p.borrow) for p, t in zip(e.params, ptys)],
                    ret_ann if ret_ann is not None else DYN, None, e.is_async, decl=e, ret_written=ret_ann is not None)
        if e.throws is not None:
            names = set()
            for te in e.throws:
                tt = self.ty(te, self.cur_module, self.tparams())
                if isinstance(tt, T.TNominal):
                    names.add(tt.qualname)
                elif isinstance(tt, T.TVar):
                    names.add("$" + tt.name)
            sig.effect = frozenset(names)
        outer = self.fn_stack[-1] if self.fn_stack else None
        st = FnState(sig, e, e.is_async, "lambda", outer.owner if outer else None)
        self.fn_stack.append(st)
        try:
            if e.is_block:
                body_t, coll = self.with_collector(lambda: self.block(e.body, lsc))
                body_t = sig.ret if ret_ann is not None else DYN
            else:
                body_t, coll = self.with_collector(lambda: self.expr(e.body, lsc))
                if ret_ann is not None and not consistent(body_t, ret_ann, self.satisfies):
                    self.mismatch(e.body.span, ret_ann, body_t, "lambda return type", e.ret.span)
        finally:
            self.fn_stack.pop()
        if sig.effect is not None:
            for n, s in coll.names.items():
                if n not in sig.effect and not any(x.startswith("$") for x in sig.effect):
                    self.oblig("S.EFFECT.UNDECLARED_THROWS", f"{short(n)} may escape this lambda, but its throws "
                               f"clause does not declare it", s or e.span)
            eff = T.Effect([T.TNominal(n, "error") if not n.startswith("$") else T.TVar(n[1:]) for n in sig.effect])
        else:
            eff = None if coll.unknown else T.Effect([T.TNominal(n, "error") for n in coll.names
                                                     if not n.startswith("$")] +
                                                    [T.TVar(n[1:]) for n in coll.names if n.startswith("$")])
            e.ann["effect"] = None if coll.unknown else frozenset(n for n in coll.names if not n.startswith("$"))
        return T.TFn(ptys, ret_ann if ret_ann is not None else body_t, eff, e.is_async)

    # ------------------------------------------------------------------ control flow
    def x_If(self, e: A.If, sc):
        from .typecheck import Scope
        then_sc = Scope(sc)
        self.cond(e.cond, sc, then_sc)
        a = self.block(e.then, then_sc, new_scope=False)
        if e.else_ is None:
            return T.UNIT
        b = self.expr(e.else_, sc) if isinstance(e.else_, A.If) else self.block(e.else_, sc)
        return join(a, b)

    def cond(self, c, sc, then_sc) -> None:
        if isinstance(c, A.Is):
            t = self.expr(c.expr, sc)
            self.bind_pattern(c.pattern, t, then_sc)
            return
        if isinstance(c, A.Binary) and c.op == "&&" and any(isinstance(n, A.Is) for n in A.walk(c)):
            self.cond(c.left, sc, then_sc)
            from .typecheck import Scope
            mid = Scope(sc)
            mid.vars.update(then_sc.vars)
            self.cond(c.right, mid, then_sc)
            return
        t = self.expr(c, sc)
        if not consistent(t, T.BOOL):
            self.oblig("S.TYPE.STATIC_MISMATCH", f"condition must be a Bool, found {t} (there is no truthiness)",
                       c.span, help="compare explicitly, e.g. `!xs.isEmpty()`, `n != 0`, `opt is Some`")

    def x_Is(self, e: A.Is, sc):
        from .typecheck import Scope
        t = self.expr(e.expr, sc)
        self.bind_pattern(e.pattern, t, Scope(sc))
        return T.BOOL

    def x_As(self, e: A.As, sc):
        self.expr(e.expr, sc)
        return self.ty(e.type, self.cur_module, self.tparams())

    def x_Match(self, e: A.Match, sc):
        from .typecheck import Scope
        st = self.expr(e.scrutinee, sc)
        result = T.NEVER
        for arm in e.arms:
            asc = Scope(sc)
            self.bind_pattern(arm.pattern, st, asc)
            if arm.guard is not None:
                gt = self.expr(arm.guard, asc)
                if not consistent(gt, T.BOOL):
                    self.oblig("S.TYPE.STATIC_MISMATCH", f"match guard must be a Bool, found {gt}", arm.guard.span)
            bt = self.block(arm.body, asc, new_scope=False) if isinstance(arm.body, A.Block) else self.expr(arm.body, asc)
            if not (isinstance(arm.body, A.Block) and arm.body.stmts and
                    isinstance(arm.body.stmts[-1], (A.ThrowStmt, A.ReturnStmt))):
                result = join(result, bt)
        if self.report:
            check_match(self, e, st)
        return DYN if result is T.NEVER else result

    # ------------------------------------------------------------------ patterns
    def bind_pattern(self, p, t, sc) -> None:
        c = p.__class__
        if isinstance(t, T.TBorrow):
            t = t.inner
        if c is A.BindPat:
            bt = t
            if p.type is not None:
                bt = self.ty(p.type, self.cur_module, self.tparams())
            sc.vars[p.name] = (bt, "pattern", p.span)
            return
        if c is A.WildcardPat or c is A.LiteralPat:
            if c is A.LiteralPat and t is not DYN:
                lt = {"int": T.INT, "float": T.FLOAT, "str": T.STR, "bool": T.BOOL}.get(p.kind)
                if lt is not None and not consistent(lt, t) and not isinstance(t, T.TVar):
                    self.oblig("S.MATCH.INVALID_PATTERN", f"{p.kind} literal pattern can never match {t}", p.span)
            return
        if c is A.TuplePat:
            items = t.items if isinstance(t, T.TTuple) and len(t.items) == len(p.items) else [DYN] * len(p.items)
            if isinstance(t, T.TTuple) and len(t.items) != len(p.items):
                self.oblig("S.MATCH.INVALID_PATTERN", f"tuple pattern has {len(p.items)} elements, value has "
                           f"{len(t.items)}", p.span)
            for sp, it in zip(p.items, items):
                self.bind_pattern(sp, it, sc)
            return
        if c is A.OrPat:
            for alt in p.alts:
                self.bind_pattern(alt, t, sc)
            return
        if c is A.CasePat:
            fields = self.case_fields(p, t)
            if fields is None:
                for _, sp in p.args or []:
                    self.bind_pattern(sp, DYN, sc)
                return
            pos = 0
            for fname, sp in p.args or []:
                if fname is None:
                    ft = fields[pos][1] if pos < len(fields) else DYN
                    pos += 1
                else:
                    match = [ft for fn, ft in fields if fn == fname]
                    if not match:
                        self.oblig("S.MATCH.INVALID_PATTERN", f"`{p.name}` has no field `{fname}`", sp.span)
                    ft = match[0] if match else DYN
                if isinstance(sp, A.BindPat) and sp.type is None and ft is not DYN and not isinstance(ft, T.TVar):
                    sp.ann["rt_check"] = ft
                self.bind_pattern(sp, ft, sc)

    def case_fields(self, p: A.CasePat, t):
        """Payload (name, Ty) list for a case/record pattern, checking it fits `t`."""
        path = p.path
        if len(path) == 1 and path[0] in CORE_CASES:
            if isinstance(t, T.TCon) and t.name == "Option" and path[0] in ("Some", "None"):
                return [("value", t.args[0])] if path[0] == "Some" else []
            if isinstance(t, T.TCon) and t.name == "Result" and path[0] in ("Ok", "Err"):
                return [("value", t.args[0])] if path[0] == "Ok" else [("error", t.args[1])]
            if t is not DYN and not isinstance(t, T.TVar):
                self.oblig("S.MATCH.INVALID_PATTERN", f"`{path[0]}` pattern cannot match {t}", p.span)
            if path[0] == "Some" or path[0] == "Ok":
                return [("value", DYN)]
            if path[0] == "Err":
                return [("error", DYN)]
            return []
        ti, case = self.resolve_pattern_path(path)
        if ti is None:
            return None
        if case is None:
            if ti.kind in ("record", "mrecord", "error"):
                if isinstance(t, T.TNominal) and t.qualname != ti.qualname:
                    self.oblig("S.MATCH.INVALID_PATTERN", f"{ti.name} pattern can never match {t}", p.span)
                return list(ti.fields.items())
            return []
        if isinstance(t, T.TNominal) and t.qualname != ti.qualname and t.kind != "protocol":
            self.oblig("S.MATCH.INVALID_PATTERN", f"{ti.name}.{case} pattern can never match {t}", p.span)
        if case not in ti.cases:
            self.oblig("S.MATCH.INVALID_PATTERN", f"{ti.name} has no case `{case}`", p.span)
            return None
        fields = ti.cases[case] or []
        if p.args is not None and ti.cases[case] is None:
            self.oblig("S.MATCH.INVALID_PATTERN", f"`{ti.name}.{case}` has no payload", p.span)
        if p.args is not None and len([a for a in p.args if a[0] is None]) > len(fields):
            self.oblig("S.MATCH.INVALID_PATTERN", f"`{ti.name}.{case}` has {len(fields)} field(s)", p.span)
        return fields

    def resolve_pattern_path(self, path):
        """-> (TypeInfo, case|None)"""
        ent = self.lookup_global(self.cur_module, path[0])
        i = 1
        while ent is not None and ent[0] == "module" and i < len(path):
            ent = self.modules.get(ent[1], {}).get(path[i])
            i += 1
        if ent is None or ent[0] != "type":
            return None, None
        ti = ent[1]
        rest = path[i:]
        if not rest:
            return ti, None
        return ti, rest[0]
