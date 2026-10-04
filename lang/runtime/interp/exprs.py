"""Expression evaluation (non-call, non-concurrency, non-resource expressions)."""
from __future__ import annotations

import math
import re

from ...syntax import ast as A
from ..builtins.colls import flist, fmap
from ..builtins.common import kind_of, no_borrow, want_frozen_element
from ..builtins.registry import METHODS, PROPS, STATICS
from ..capture import Budget, safe_repr
from ..core_types import ERR_CASE, NONE, OK_CASE, RESULT, err, ok
from ..equality import compare, display, hash_key, lang_eq, type_name
from ..frozen import is_frozen
from ..signals import ChildOrigin, ErrorProvenance, Fault, ReturnSignal, Thrown
from ..values import (UNIT, Borrow, BoundMethod, BuiltinBound, CategoryType, Closure, Duration, EnumType,
                      FrozenList, FrozenMap, FrozenRecord, FrozenSet, Instant, ModuleValue, MutableList, MutableMap,
                      MutableRecord, MutableSet, Namespace, ProtocolType, RangeValue, RecordType, TupleValue,
                      TypeValue, Uninit, UnitType, VariantValue)
from .core import Env

_SPEC = re.compile(r"^([<>^])?(\d+)?(?:\.(\d+))?$")


class ConstThunk:
    """Module constant awaiting (lazy, cycle-checked) initialisation."""

    __slots__ = ("decl", "module", "state", "value")

    def __init__(self, decl, module):
        self.decl = decl
        self.module = module
        self.state = "pending"  # pending | evaluating | done
        self.value = None


class ExprMixin:
    # ------------------------------------------------------------------ literals
    def eval_Literal(self, node: A.Literal, env: Env):
        k = node.kind
        if k == "unit":
            return UNIT
        if k == "null":
            return NONE
        return node.value

    def eval_StringLit(self, node: A.StringLit, env: Env):
        out = []
        for p in node.parts:
            if p.__class__ is str:
                out.append(p)
            else:
                v = self.eval(p.expr, env)
                out.append(self.format_value(v, p.spec, p.span, env))
        return "".join(out)

    def format_value(self, v, spec, span, env):
        if type(v) is Borrow:
            v = v.target
        if not spec:
            return display(v)
        m = _SPEC.match(spec)
        if not m:
            raise self.abandon("A.RUNTIME.INVALID_ARGUMENT", f"invalid format spec `{spec}`", span, env,
                               help="format specs are `[<|>|^]width` and/or `.precision`, e.g. {x:>8.2}")
        align, width, prec = m.groups()
        if prec is not None:
            if type(v) is not float:
                raise self.abandon("A.TYPE.OPERAND_MISMATCH",
                                   f"precision `.{prec}` applies to Float values, found {type_name(v)}", span, env,
                                   help="convert with `toFloat()` first")
            if math.isfinite(v):
                s = f"{v:.{int(prec)}f}"
            else:
                s = display(v)
        else:
            s = display(v)
        if width is not None:
            w = int(width)
            if align == "<":
                s = s.ljust(w)
            elif align == "^":
                s = s.center(w)
            else:
                s = s.rjust(w) if (align == ">" or type(v) in (int, float)) else s.ljust(w)
        return s

    # ------------------------------------------------------------------ names
    def eval_Name(self, node: A.Name, env: Env):
        name = node.name
        e = env
        while e is not None:
            vs = e.vars
            if name in vs:
                v = vs[name]
                c = v.__class__
                if c is Uninit:
                    raise self.abandon("A.BINDING.UNINITIALISED", f"`{name}` is read before it is initialised",
                                       node.span, env, help="assign the binding on every path before reading it")
                if c is ConstThunk:
                    return self.force_const(v, node.span)
                return v
            e = e.parent
        raise self.abandon("A.RUNTIME.UNREACHABLE", f"unresolved name `{name}` at runtime", node.span, env)

    # ------------------------------------------------------------------ collections
    def eval_ListLit(self, node: A.ListLit, env: Env):
        return flist([self.eval(i, env) for i in node.items])

    def eval_MapLit(self, node: A.MapLit, env: Env):
        pairs = []
        for k, v in node.entries:
            pairs.append((self.eval(k, env), self.eval(v, env)))
        return fmap(pairs)

    def eval_TupleLit(self, node: A.TupleLit, env: Env):
        items = tuple(no_borrow(self.eval(i, env), "tuple") for i in node.items)
        return TupleValue(items)

    def eval_Range(self, node: A.Range, env: Env):
        lo = self.eval(node.lo, env)
        hi = self.eval(node.hi, env)
        if type(lo) is not int or type(hi) is not int:
            raise self.abandon("A.TYPE.OPERAND_MISMATCH",
                               f"range bounds must be Int, found {type_name(lo)}..{type_name(hi)}", node.span, env)
        return RangeValue(lo, hi, node.inclusive)

    # ------------------------------------------------------------------ operators
    def eval_Unary(self, node: A.Unary, env: Env):
        v = self.eval(node.operand, env)
        if node.op == "!":
            if type(v) is not bool:
                raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`!` requires a Bool, found {type_name(v)}",
                                   node.span, env, expected="Bool", found=type_name(v))
            return not v
        t = type(v)
        if t is int or t is float:
            return -v
        if t is Duration:
            return Duration(-v.nanos)
        raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"unary `-` is not defined for {type_name(v)}", node.span, env)

    def eval_Binary(self, node: A.Binary, env: Env):
        op = node.op
        if op == "&&" or op == "||":
            a = self.eval(node.left, env)
            if type(a) is not bool:
                raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`{op}` requires Bool operands, left is {type_name(a)}",
                                   node.left.span, env, expected="Bool", found=type_name(a),
                                   help="there is no truthiness; compare explicitly")
            if op == "&&" and not a:
                return False
            if op == "||" and a:
                return True
            b = self.eval(node.right, env)
            if type(b) is not bool:
                raise self.abandon("A.TYPE.OPERAND_MISMATCH",
                                   f"`{op}` requires Bool operands, right is {type_name(b)}",
                                   node.right.span, env, expected="Bool", found=type_name(b))
            return b
        a = self.eval(node.left, env)
        b = self.eval(node.right, env)
        if type(a) is Borrow:
            a = self.borrow_target(a, node.left.span, env)
        if type(b) is Borrow:
            b = self.borrow_target(b, node.right.span, env)
        try:
            return binop(op, a, b)
        except Fault as f:
            f.values.setdefault("left", safe_repr(a, Budget(120)))
            f.values.setdefault("right", safe_repr(b, Budget(120)))
            raise

    # ------------------------------------------------------------------ index / field
    def eval_Index(self, node: A.Index, env: Env):
        obj = self.eval(node.obj, env)
        if type(obj) is TypeValue:
            return self.type_apply(obj, [self.eval(i, env) for i in node.indices], node, env)
        if len(node.indices) != 1:
            raise self.abandon("A.RUNTIME.INVALID_ARGUMENT", "exactly one index is supported", node.span, env)
        idx = self.eval(node.indices[0], env)
        v = self.index_get(obj, idx, node, env)
        rc = node.ann.get("rt_check")
        if rc is not None:
            self.transient_check(rc, v, node.span, env, "this element")
        return v

    def index_get(self, obj, idx, node, env):
        if type(obj) is Borrow:
            obj = self.borrow_target(obj, node.span, env)
        t = type(obj)
        if t is FrozenList or t is MutableList:
            n = len(obj.items)
            if type(idx) is not int:
                raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"list index must be an Int, found {type_name(idx)}",
                                   node.span, env)
            if idx < 0 or idx >= n:
                raise self.abandon("A.INDEX.OUT_OF_RANGE", f"index {idx} is out of range for length {n}",
                                   node.span, env, values={"index": str(idx), "length": str(n)},
                                   help="use `.get(i)` for a checked alternative returning an Option"
                                        + ("; negative indices are not supported" if idx < 0 else ""))
            return obj.items[idx]
        if t is FrozenMap or t is MutableMap:
            e = obj.data.get(hash_key(idx))
            if e is None:
                raise self.abandon("A.MAP.MISSING_KEY", f"map has no key {safe_repr(idx, Budget(120))}",
                                   node.span, env, help="use `.get(key)` for a checked alternative returning an Option")
            return e[1]
        if t is str:
            if type(idx) is not int:
                raise self.abandon("A.TYPE.OPERAND_MISMATCH", "string index must be an Int", node.span, env)
            if idx < 0 or idx >= len(obj):
                raise self.abandon("A.INDEX.OUT_OF_RANGE", f"index {idx} is out of range for Str of length {len(obj)}",
                                   node.span, env, help="use `.charAt(i)` for a checked alternative")
            return obj[idx]
        if t is TypeValue:
            return self.type_apply(obj, [idx], node, env)
        if t is Closure:
            return obj  # explicit generic instantiation f[T] is a no-op at runtime (types erased)
        raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"{type_name(obj)} cannot be indexed", node.span, env)

    def eval_Field(self, node: A.Field, env: Env):
        obj = self.eval(node.obj, env)
        return self.get_member(obj, node.name, node, env)

    def get_member(self, obj, name: str, node, env):
        t = type(obj)
        if t is Borrow:
            target = self.borrow_target(obj, node.span, env)
            tt = type(target)
            if tt in (FrozenRecord, MutableRecord):
                if name in target.rtype.field_index:
                    return target.values[target.rtype.field_index[name]]
                m = target.rtype.methods.get(name)
                if m is not None:
                    return BoundMethod(obj, m)
            k = kind_of(target)
            if k is not None:
                b = METHODS.get(k, {}).get(name)
                if b is not None:
                    return BuiltinBound(obj, b)
                p = PROPS.get(k, {}).get(name)
                if p is not None:
                    return p[0](self, target)
            return self.get_member(target, name, node, env)
        if t is FrozenRecord or t is MutableRecord:
            rt = obj.rtype
            i = rt.field_index.get(name)
            if i is not None:
                return obj.values[i]
            m = rt.methods.get(name)
            if m is not None:
                return BoundMethod(obj, m)
            k = kind_of(obj)
            if k is not None:
                b = METHODS.get(k, {}).get(name)
                if b is not None:
                    return BuiltinBound(obj, b)
            raise self.unknown_member(obj, name, node, env, list(rt.field_index) + list(rt.methods))
        if t is VariantValue:
            m = obj.case.etype.methods.get(name)
            if m is not None:
                return BoundMethod(obj, m)
            k = kind_of(obj)
            if k is not None:
                b = METHODS.get(k, {}).get(name)
                if b is not None:
                    return BuiltinBound(obj, b)
            fields = obj.case.fields or []
            if any(f.name == name for f in fields):
                raise self.abandon("A.TYPE.UNKNOWN_FIELD",
                                   f"variant payload field `{name}` cannot be read with `.`; match on the case",
                                   node.span, env,
                                   help=f"write `match v {{ {obj.case.qualname}({name}: x) => ... }}`")
            raise self.unknown_member(obj, name, node, env, list(obj.case.etype.methods))
        if t is TupleValue:
            if name.isdigit():
                i = int(name)
                if i < len(obj.items):
                    return obj.items[i]
                raise self.abandon("A.INDEX.OUT_OF_RANGE", f"tuple has no element .{i} (length {len(obj.items)})",
                                   node.span, env)
        if t is TypeValue:
            return self.type_member(obj, name, node, env)
        if t is ModuleValue:
            if name in obj.namespace:
                v = obj.namespace[name]
                if v.__class__ is ConstThunk:
                    return self.force_const(v, node.span)
                return v
            raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"module `{obj.name}` has no exported member `{name}`",
                               node.span, env)
        if t is Namespace:
            if name in obj.members:
                return obj.members[name]
            raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"`{obj.name}` has no member `{name}`", node.span, env,
                               help="available: " + ", ".join(sorted(obj.members)))
        if t is CategoryType:
            raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"category `{obj.name}` has no members", node.span, env)
        k = kind_of(obj)
        if k is not None:
            p = PROPS.get(k, {}).get(name)
            if p is not None:
                return p[0](self, obj)
            b = METHODS.get(k, {}).get(name)
            if b is not None:
                return BuiltinBound(obj, b)
            members = list(PROPS.get(k, {})) + list(METHODS.get(k, {}))
            raise self.unknown_member(obj, name, node, env, members)
        raise self.unknown_member(obj, name, node, env, [])

    def unknown_member(self, obj, name, node, env, members):
        import difflib
        tn = type_name(obj)
        help_ = None
        close = difflib.get_close_matches(name, members, n=3, cutoff=0.5)
        aliases = {"size": "length", "len": "length", "count": "length", "push_back": "push", "append": "push",
                   "add": "push", "lower": "toLower", "upper": "toUpper", "strip": "trim", "has": "contains",
                   "includes": "contains", "toString": "toStr", "str": "toStr"}
        if name in aliases and aliases[name] in members:
            close = [aliases[name]] + [c for c in close if c != aliases[name]]
        if close:
            help_ = "did you mean " + ", ".join(f"`{c}`" for c in close) + "?"
        if name == "length" and tn in ("Int", "Float", "Bool"):
            help_ = None
        return self.abandon("A.TYPE.UNKNOWN_FIELD" if not members or name not in members else "A.TYPE.UNKNOWN_METHOD",
                            f"{tn} has no field or method `{name}`", node.span, env, help=help_)

    def type_member(self, tv: TypeValue, name: str, node, env):
        k = tv.kind
        if k == "enum":
            et: EnumType = tv.target
            ci = et.cases.get(name)
            if ci is not None:
                if ci.fields is None:
                    return et.nullary(name)
                return TypeValue("case", ci, tv.args, f"{et.name}.{name}")
            m = et.methods.get(name)
            if m is not None:
                return m
            import difflib
            close = difflib.get_close_matches(name, list(et.cases) + list(et.methods), n=3, cutoff=0.5)
            raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"enum `{et.name}` has no case or function `{name}`",
                               node.span, env, help=("did you mean " + ", ".join(f"`{c}`" for c in close) + "?")
                               if close else None)
        if k == "record":
            rt: RecordType = tv.target
            m = rt.methods.get(name)
            if m is not None:
                return m
            raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"type `{rt.name}` has no associated function `{name}`",
                               node.span, env)
        if k == "builtin":
            st = STATICS.get(tv.target, {}).get(name)
            if st is not None:
                return BuiltinBound(tv, st)
            raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"`{tv.name}` has no associated function `{name}`",
                               node.span, env,
                               help="available: " + ", ".join(sorted(STATICS.get(tv.target, {}))) or None)
        raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"`{tv.name}` has no member `{name}`", node.span, env)

    def type_apply(self, tv: TypeValue, args, node, env):
        """`Name[TypeArgs]` used as a value: generic instantiation (types are erased at
        runtime except for element annotations on mutable collections)."""
        return TypeValue(tv.kind, tv.target, tuple(args), tv.name)

    # ------------------------------------------------------------------ records
    def eval_WithUpdate(self, node: A.WithUpdate, env: Env):
        obj = self.eval(node.obj, env)
        if type(obj) is not FrozenRecord:
            raise self.abandon("A.TYPE.FROZEN_MUTATION" if type(obj) is MutableRecord else "A.TYPE.OPERAND_MISMATCH",
                               f"`with` creates an updated copy of a frozen record; found {type_name(obj)}",
                               node.span, env,
                               help="assign fields directly on mutable records" if type(obj) is MutableRecord else None)
        rt = obj.rtype
        vals = list(obj.values)
        for fname, fexpr, fspan in node.fields:
            i = rt.field_index.get(fname)
            if i is None:
                raise self.abandon("A.TYPE.UNKNOWN_FIELD", f"record `{rt.name}` has no field `{fname}`", fspan, env)
            v = self.eval(fexpr, env)
            vals[i] = self.check_field_value(rt, rt.fields[i], v, fexpr.span, env)
        new = FrozenRecord(rt, tuple(vals))
        if rt.invariants:
            self.check_invariants(new, node.span, "after `with` update", env)
        return new

    # ------------------------------------------------------------------ closures
    def eval_Lambda(self, node: A.Lambda, env: Env):
        c = Closure(node, env, "<lambda>", self.current_module(), is_lambda=True)
        c.effect = node.ann.get("effect")
        return c

    # ------------------------------------------------------------------ control
    def eval_If(self, node: A.If, env: Env):
        ok, bindings = self.eval_cond(node.cond, env)
        if ok:
            if bindings:
                benv = Env(env)
                benv.vars.update(bindings)
                return self.exec_block(node.then, benv)
            return self.exec_block(node.then, env)
        if node.else_ is None:
            return UNIT
        if node.else_.__class__ is A.If:
            return self.eval_If(node.else_, env)
        return self.exec_block(node.else_, env)

    def eval_cond(self, node, env: Env):
        """Evaluate a condition; `is` patterns may bind names for the guarded block."""
        c = node.__class__
        if c is A.Is:
            v = self.eval(node.expr, env)
            b: dict = {}
            return self.match_pattern(node.pattern, v, b, env), b
        if c is A.Binary and node.op == "&&" and _binds(node):
            ok1, b1 = self.eval_cond(node.left, env)
            if not ok1:
                return False, None
            env2 = env
            if b1:
                env2 = Env(env)
                env2.vars.update(b1)
            ok2, b2 = self.eval_cond(node.right, env2)
            if not ok2:
                return False, None
            if b1 and b2:
                b1 = dict(b1)
                b1.update(b2)
                return True, b1
            return True, (b1 or b2)
        v = self.eval(node, env)
        if type(v) is not bool:
            raise self.abandon("A.TYPE.NON_BOOL_CONDITION",
                               f"condition must be a Bool, found {type_name(v)} (there is no truthiness)",
                               node.span, env, expected="Bool", found=type_name(v),
                               help="compare explicitly, e.g. `!xs.isEmpty()`, `n != 0`, `opt is Some`")
        return v, None

    def eval_Is(self, node: A.Is, env: Env):
        v = self.eval(node.expr, env)
        return self.match_pattern(node.pattern, v, {}, env)

    def eval_As(self, node: A.As, env: Env):
        v = self.eval(node.expr, env)
        ty = self.type_of_expr(node.type, env)
        if not self.registry.check(ty, v):
            raise self.abandon("A.TYPE.DYNAMIC_MISMATCH",
                               f"`as {ty}` narrowing failed: value is {type_name(v)}", node.span, env,
                               expected=str(ty), found=type_name(v),
                               secondary=[self.origin_label(node.expr, env)] if self.origin_label(node.expr, env) else None)
        return v

    def eval_Match(self, node: A.Match, env: Env):
        v = self.eval(node.scrutinee, env)
        for arm in node.arms:
            b: dict = {}
            if self.match_pattern(arm.pattern, v, b, env):
                aenv = env
                if b:
                    aenv = Env(env)
                    aenv.vars.update(b)
                if arm.guard is not None:
                    g = self.eval(arm.guard, aenv)
                    if type(g) is not bool:
                        raise self.abandon("A.TYPE.NON_BOOL_CONDITION", "match guard must be a Bool", arm.guard.span,
                                           aenv)
                    if not g:
                        continue
                body = arm.body
                if body.__class__ is A.Block:
                    return self.exec_block(body, aenv)
                return self.eval(body, aenv)
        raise self.abandon("A.MATCH.NO_ARM", f"no match arm matches {safe_repr(v, Budget(200))}", node.span, env,
                           found=type_name(v),
                           help="the match is not exhaustive for this value; add the missing case "
                                "(verified mode rejects non-exhaustive matches statically)")

    # ------------------------------------------------------------------ errors
    def eval_Try(self, node: A.Try, env: Env):
        try:
            return self.eval(node.expr, env)
        except Thrown as t:
            for clause in node.catches:
                if self.catch_matches(clause, t.error, env):
                    if t.origin is not None:
                        t.origin.observed = True
                    henv = env
                    if clause.binding:
                        henv = Env(env)
                        henv.vars[clause.binding] = t.error
                    h = clause.handler
                    if h.__class__ is A.Block:
                        return self.exec_block(h, henv)
                    return self.eval(h, henv)
            if node.fallback is not None:
                # V3 7.7.3: an unqualified fallback handles exactly the one concrete error
                # type the checker proved (`fallback_qual`); anything else propagates
                fq = node.ann.get("fallback_qual")
                if fq is None or self.error_qualname(t.error) == fq:
                    if t.origin is not None:
                        t.origin.observed = True
                    return self.eval(node.fallback, env)
            t.prov.chain.append(node.span)
            raise

    def catch_matches(self, clause: A.CatchClause, error, env) -> bool:
        target = clause.ann.get("target")
        if target is None:
            target = self.resolve_path(clause.path, env, clause.span)
            clause.ann["target"] = target
        if clause.is_category or type(target) is CategoryType:
            cats = self.error_categories(error)
            return target.qualname in cats or target.name in cats
        return self.error_is_type(error, target)

    def error_is_type(self, error, target) -> bool:
        t = type(target)
        if t is TypeValue:
            if target.kind == "record":
                return type(error) is FrozenRecord and error.rtype is target.target
            if target.kind == "enum":
                return type(error) is VariantValue and error.case.etype is target.target
            if target.kind == "case":
                return type(error) is VariantValue and error.case is target.target
        if t is VariantValue:  # nullary error-enum case
            return type(error) is VariantValue and error.case is target.case
        if t is RecordType:
            return type(error) is FrozenRecord and error.rtype is target
        if t is EnumType:
            return type(error) is VariantValue and error.case.etype is target
        return False

    @staticmethod
    def error_qualname(error):
        if type(error) is FrozenRecord:
            return error.rtype.qualname
        if type(error) is VariantValue:
            return error.case.etype.qualname
        return None

    def error_categories(self, error) -> tuple:
        if type(error) is FrozenRecord:
            return error.rtype.categories + tuple(f"core.{c}" for c in error.rtype.categories) + tuple(
                self.qual_category(error.rtype, c) for c in error.rtype.categories)
        if type(error) is VariantValue:
            et = error.case.etype
            return et.categories + tuple(self.qual_category(et, c) for c in et.categories)
        return ()

    def qual_category(self, t, c: str) -> str:
        return self.category_qualnames.get((t.qualname, c), c)

    def eval_Capture(self, node: A.Capture, env: Env):
        try:
            v = self.eval(node.expr, env)
        except Thrown as t:
            if t.origin is not None:
                t.origin.observed = True
            t.prov.chain.append(node.span)
            return err(t.error, t.prov)
        return ok(v)

    def eval_Propagate(self, node: A.Propagate, env: Env):
        v = self.eval(node.expr, env)
        if type(v) is not VariantValue or v.case.etype is not RESULT:
            raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"`propagate` expects a Result, found {type_name(v)}",
                               node.span, env, expected="Result", found=type_name(v))
        if v.case is OK_CASE:
            return v.values[0]
        fr = self.frame
        ret = getattr(fr.decl, "ret", None) if fr.decl is not None else None
        if ret is not None and not (isinstance(ret, A.TypeName) and ret.path == ["Result"]):
            raise self.abandon("A.EFFECT.UNDECLARED_PROPAGATE",
                               "`propagate` returns the Err from the enclosing function, which does not return a Result",
                               node.span, env, help="use `try r.orThrow()` to turn the Err into an exception")
        prov = v.prov.copy() if v.prov is not None else self.new_provenance(node.span)
        prov.chain.append(node.span)
        raise ReturnSignal(VariantValue(ERR_CASE, v.values, prov), node.span)

    def new_provenance(self, span) -> ErrorProvenance:
        t = self.sched.current
        return ErrorProvenance(span, t.path if t is not None else None)

    def check_throwable(self, value, span) -> None:
        ok_ = (type(value) is FrozenRecord and value.rtype.is_error) or (
            type(value) is VariantValue and value.case.etype.is_error)
        if not ok_:
            raise Fault("A.TYPE.OPERAND_MISMATCH",
                        f"only declared error types can be thrown; found {type_name(value)}",
                        help="declare it with `error Name { ... }` or `error enum Name { ... }`")


def _binds(node) -> bool:
    b = node.ann.get("binds")
    if b is None:
        b = any(isinstance(n, A.Is) for n in A.walk(node))
        node.ann["binds"] = b
    return b


def binop(op: str, a, b):
    ta, tb = type(a), type(b)
    if op == "==":
        return lang_eq(a, b)
    if op == "!=":
        return not lang_eq(a, b)
    if op in ("<", "<=", ">", ">="):
        c = compare(a, b)
        return c < 0 if op == "<" else c <= 0 if op == "<=" else c > 0 if op == ">" else c >= 0
    if ta is tb:
        if ta is int:
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                if b == 0:
                    raise Fault("A.NUMERIC.DIVISION_BY_ZERO", "division by zero",
                                help="Int / Int yields Float; guard the divisor or use `checkedDiv`")
                return a / b
            if op == "%":
                if b == 0:
                    raise Fault("A.NUMERIC.DIVISION_BY_ZERO", "modulo by zero")
                return a % b
        elif ta is float:
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                if b == 0.0:
                    if a != a or a == 0.0:
                        return math.nan
                    return math.copysign(math.inf, a) * math.copysign(1.0, b)
                return a / b
            if op == "%":
                if b == 0.0:
                    return math.nan
                return a % b  # floored modulo (sign of divisor), consistent with Int
        elif ta is str:
            if op == "+":
                return a + b
        elif ta is FrozenList:
            if op == "+":
                return FrozenList(a.items + b.items)
        elif ta is Duration:
            if op == "+":
                return Duration(a.nanos + b.nanos)
            if op == "-":
                return Duration(a.nanos - b.nanos)
        elif ta is Instant:
            if op == "-":
                return Duration(a.nanos - b.nanos)
    if ta is Instant and tb is Duration:
        if op == "+":
            return Instant(a.nanos + b.nanos)
        if op == "-":
            return Instant(a.nanos - b.nanos)
    if ta is Duration and tb is Instant and op == "+":
        return Instant(a.nanos + b.nanos)
    if ta is Duration and tb is int:
        if op == "*":
            return Duration(a.nanos * b)
        if op == "/":
            if b == 0:
                raise Fault("A.NUMERIC.DIVISION_BY_ZERO", "duration divided by zero")
            return Duration(a.nanos // b)
    if ta is int and tb is Duration and op == "*":
        return Duration(a * b.nanos)
    help_ = None
    if {ta, tb} == {int, float}:
        help_ = "no implicit numeric coercion: convert with `toFloat()` or `toInt()`"
    elif op == "+" and (ta is str or tb is str):
        help_ = "build strings with interpolation: \"{a}{b}\""
    raise Fault("A.TYPE.OPERAND_MISMATCH", f"`{op}` is not defined for {type_name(a)} and {type_name(b)}",
                help=help_)
