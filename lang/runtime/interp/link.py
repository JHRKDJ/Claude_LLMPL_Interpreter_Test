"""Linking: module ASTs -> runtime environments, types, closures, imports.

Also computes the global structural conformance table (AMB-001): every nominal
type is checked against every protocol in the loaded program; satisfied protocols
contribute their method contracts to the type's methods.
"""
from __future__ import annotations

from typing import Optional

from ... import typesys as T
from ...diagnostics import Diagnostic, Label, Note, code
from ...syntax import ast as A
from ..builtins.registry import MODULES, PRELUDE, STATICS
from ..core_types import ALL_CORE_TYPES, CATEGORIES, CORE_ENUMS, CORE_RECORDS, NONE, OPTION, RESULT
from ..rtypes import method_conforms
from ..signals import Abandoned, Fault
from ..values import (CaseInfo, CategoryType, Closure, EnumType, FieldInfo, ModuleValue, Namespace, ProtocolType,
                      RecordType, TypeValue)
from .core import Env
from .exprs import ConstThunk

BUILTIN_TYPE_NAMES = ["List", "Map", "Set", "MutableList", "MutableMap", "MutableSet", "Duration", "Instant",
                      "Channel", "Broadcast", "Task", "SendPort", "ReceivePort", "Range"]
PRIM_TYPE_NAMES = ["Int", "Float", "Bool", "Str", "Unit", "Dyn", "Never"]


class ModuleRT:
    def __init__(self, name: str, source, env: Env):
        self.name = name
        self.source = source
        self.env = env
        self.exports: set[str] = set()
        self.tests: list = []
        self.types: dict = {}


class LinkMixin:
    def build_prelude(self) -> Env:
        env = Env(None, kind="prelude")
        for name, b in PRELUDE.items():
            env.vars[name] = b
        for name in BUILTIN_TYPE_NAMES:
            env.vars[name] = TypeValue("builtin", name, (), name)
        for name in PRIM_TYPE_NAMES:
            env.vars[name] = TypeValue("prim", T.PRIMS[name], (), name)
        for name, et in CORE_ENUMS.items():
            env.vars[name] = TypeValue("enum", et, (), name)
            self.registry.register(et.qualname, et)
        for name, rt in CORE_RECORDS.items():
            env.vars[name] = TypeValue("record", rt, (), name)
            self.registry.register(rt.qualname, rt)
        env.vars["Some"] = TypeValue("case", OPTION.cases["Some"], (), "Some")
        env.vars["None"] = NONE
        env.vars["Ok"] = TypeValue("case", RESULT.cases["Ok"], (), "Ok")
        env.vars["Err"] = TypeValue("case", RESULT.cases["Err"], (), "Err")
        for name, cat in CATEGORIES.items():
            env.vars[name] = cat
        for ns_name in ("time", "cancel"):
            members = dict(MODULES.get(f"prelude.{ns_name}", {}))
            env.vars[ns_name] = Namespace(ns_name, members)
        return env

    # ------------------------------------------------------------------ program
    def link_program(self, prog) -> None:
        self.program = prog
        self.prelude = self.build_prelude()
        self.modules: dict[str, ModuleRT] = {}
        self.protocol_decls: list = []
        self.nominal_types: list = []
        self.const_stack: list = []
        self.category_qualnames = {}
        for name, ms in prog.modules.items():
            if ms.native:
                ns = dict(MODULES.get(name, {}))
                env = Env(self.prelude, kind="module")
                env.vars.update(ns)
                mrt = ModuleRT(name, ms, env)
                mrt.exports = set(ns)
                self.modules[name] = mrt
                continue
            env = Env(self.prelude, kind="module")
            mrt = ModuleRT(name, ms, env)
            self.modules[name] = mrt
            self.declare_module(mrt)
        for mrt in self.modules.values():
            if mrt.source.ast is not None:
                self.bind_imports(mrt)
        for mrt in self.modules.values():
            if mrt.source.ast is not None:
                self.finish_types(mrt)
        self.compute_conformance()

    def declare_module(self, mrt: ModuleRT) -> None:
        env = mrt.env
        mod = mrt.source.ast
        qual = mrt.name
        for d in mod.decls:
            annotate_tparams(d, frozenset())
            if isinstance(d, A.FnDecl):
                c = Closure(d, env, d.name, mrt)
                c.effect = self.decl_effect(d)
                env.vars[d.name] = c
            elif isinstance(d, A.RecordDecl):
                rt = RecordType(d.name, f"{qual}.{d.name}", d, d.mutable, kind=d.kind, category=d.category)
                rt.module = mrt
                rt.module_env = env
                rt.type_params = list(d.type_params)
                for i, f in enumerate(d.fields):
                    rt.fields.append(FieldInfo(f.name, None, f.type, f.default, f.sensitive, i, f.span))
                    rt.field_index[f.name] = i
                rt.invariants = list(d.invariants)
                inv_fields = set()
                for inv in d.invariants:
                    for n in A.walk(inv):
                        if isinstance(n, A.Name) and n.name in rt.field_index:
                            inv_fields.add(n.name)
                        if isinstance(n, A.Field) and isinstance(n.obj, A.Name) and n.obj.name == "self":
                            inv_fields.add(n.name)
                rt.invariant_fields = frozenset(inv_fields)
                for m in d.methods:
                    c = Closure(m, env, m.name, mrt, owner=rt)
                    c.effect = self.decl_effect(m)
                    rt.methods[m.name] = c
                env.vars[d.name] = TypeValue("record", rt, (), d.name)
                self.registry.register(rt.qualname, rt)
                mrt.types[d.name] = rt
                self.nominal_types.append(rt)
                if d.category:
                    self.category_qualnames[(rt.qualname, d.category)] = d.category
            elif isinstance(d, A.EnumDecl):
                et = EnumType(d.name, f"{qual}.{d.name}", d, is_error=d.is_error, category=d.category)
                et.module = mrt
                et.module_env = env
                et.type_params = list(d.type_params)
                for i, cd in enumerate(d.cases):
                    fields = None
                    if cd.fields is not None:
                        fields = [FieldInfo(f.name, None, f.type, None, False, j, f.span) for j, f in
                                  enumerate(cd.fields)]
                    et.cases[cd.name] = CaseInfo(cd.name, fields, i, et, cd.span)
                for m in d.methods:
                    c = Closure(m, env, m.name, mrt, owner=et)
                    c.effect = self.decl_effect(m)
                    et.methods[m.name] = c
                env.vars[d.name] = TypeValue("enum", et, (), d.name)
                self.registry.register(et.qualname, et)
                mrt.types[d.name] = et
                self.nominal_types.append(et)
            elif isinstance(d, A.ProtocolDecl):
                pt = ProtocolType(d.name, f"{qual}.{d.name}", d)
                pt.module = mrt
                for m in d.methods:
                    pt.methods[m.name] = m
                env.vars[d.name] = TypeValue("protocol", pt, (), d.name)
                self.registry.register(pt.qualname, pt)
                mrt.types[d.name] = pt
                self.protocol_decls.append((pt, mrt))
            elif isinstance(d, A.CategoryDecl):
                env.vars[d.name] = CategoryType(d.name, f"{qual}.{d.name}")
            elif isinstance(d, A.PredicateDecl):
                c = Closure(d, env, d.name, mrt)
                c.effect = frozenset()
                env.vars[d.name] = c
            elif isinstance(d, A.ConstDecl):
                env.vars[d.name] = ConstThunk(d, mrt)
                env.define(d.name, env.vars[d.name], const=True)
            elif isinstance(d, A.TestDecl):
                mrt.tests.append(d)
            if getattr(d, "is_pub", False):
                mrt.exports.add(d.name)

    def decl_effect(self, d) -> Optional[frozenset]:
        eff = d.ann.get("effect")
        if eff is not None:
            return eff
        return None  # computed lazily from the throws clause when needed

    def bind_imports(self, mrt: ModuleRT) -> None:
        env = mrt.env
        for imp in mrt.source.ast.imports:
            full = ".".join(imp.path)
            target = self.modules.get(full)
            if target is None:
                continue
            if imp.names is not None:
                for n, _ in imp.names:
                    if n in target.env.vars:
                        env.vars[n] = target.env.vars[n]
            else:
                alias = imp.alias or imp.path[-1]
                ns = {k: target.env.vars[k] for k in target.exports if k in target.env.vars}
                env.vars[alias] = ModuleValue(full, ns, target)

    def finish_types(self, mrt: ModuleRT) -> None:
        for t in mrt.types.values():
            if isinstance(t, RecordType):
                for f in t.fields:
                    if f.type_expr is not None:
                        f.type = self.convert_type(f.type_expr, mrt.env)
            elif isinstance(t, EnumType):
                for ci in t.cases.values():
                    for f in ci.fields or []:
                        if f.type_expr is not None:
                            f.type = self.convert_type(f.type_expr, mrt.env)
            elif isinstance(t, ProtocolType):
                for m in t.methods.values():
                    if m.throws is None:
                        m.ann["effect_names"] = frozenset()
                    else:
                        names = set()
                        permissive = False
                        for te in m.throws:
                            ty = self.convert_type(te, mrt.env)
                            if isinstance(ty, T.TNominal):
                                names.add(ty.qualname)
                            else:
                                permissive = True
                        m.ann["effect_names"] = None if permissive else frozenset(names)
        # closures' declared effects (qualnames) for shape/effect checks
        for v in list(mrt.env.vars.values()):
            if isinstance(v, Closure):
                self.set_closure_effect(v)
            elif isinstance(v, TypeValue) and v.kind in ("record", "enum"):
                for m in v.target.methods.values():
                    self.set_closure_effect(m)

    def set_closure_effect(self, c: Closure) -> None:
        d = c.decl
        if getattr(d, "throws", None) is not None:
            names = set()
            for te in d.throws:
                try:
                    ty = self.convert_type(te, c.env)
                except Fault:
                    continue
                if isinstance(ty, T.TNominal):
                    names.add(ty.qualname)
                else:
                    return
            c.effect = frozenset(names)
        elif d.ann.get("effect") is not None:
            c.effect = d.ann["effect"]

    # ------------------------------------------------------------------ conformance
    def compute_conformance(self) -> None:
        for t in self.nominal_types:
            for pt, mrt in self.protocol_decls:
                reason = None
                for mname, pdecl in pt.methods.items():
                    m = t.methods.get(mname)
                    if m is None:
                        reason = f"missing `{mname}`"
                        break
                    pdecl._effect_names = pdecl.ann.get("effect_names")
                    r = method_conforms(pdecl, m)
                    if r:
                        reason = r
                        break
                if reason is None:
                    for mname, pdecl in pt.methods.items():
                        if pdecl.requires or pdecl.ensures:
                            t.protocol_contracts.setdefault(mname, []).append(pdecl)
        for pt, _ in self.protocol_decls:
            for pdecl in pt.methods.values():
                pdecl._effect_names = pdecl.ann.get("effect_names")

    # ------------------------------------------------------------------ types
    def convert_type(self, texpr, env: Env) -> T.Ty:
        tparams = texpr.ann.get("tparams", frozenset())

        def resolve(path, node):
            v = None
            e = env.find(path[0])
            if e is None:
                return None
            v = e.vars[path[0]]
            for seg in path[1:]:
                if isinstance(v, ModuleValue):
                    v = v.namespace.get(seg)
                else:
                    return None
            return self.value_to_nominal(v)
        try:
            return T.from_expr(texpr, resolve, tparams)
        except T.TypeConversionError as e:
            raise Fault("A.RUNTIME.UNREACHABLE", f"unresolved type: {e.message}")

    def value_to_nominal(self, v) -> Optional[T.Ty]:
        if isinstance(v, TypeValue):
            if v.kind == "record":
                rt = v.target
                kind = "error" if rt.is_error else ("mrecord" if rt.mutable else "record")
                return T.TNominal(rt.qualname, kind)
            if v.kind == "enum":
                return T.TNominal(v.target.qualname, "errorenum" if v.target.is_error else "enum")
            if v.kind == "protocol":
                return T.TNominal(v.target.qualname, "protocol")
            if v.kind == "prim":
                return v.target
            if v.kind == "builtin":
                if v.target in T.CON_ARITY:
                    return T.TCon(v.target, tuple(T.DYN for _ in range(T.CON_ARITY[v.target])))
                return T.PRIMS.get(v.target)
        return None

    def type_value_to_ty(self, tv) -> T.Ty:
        if not isinstance(tv, TypeValue):
            return T.DYN
        base = self.value_to_nominal(tv)
        if tv.kind == "builtin" and tv.target in T.CON_ARITY:
            args = [self.type_value_to_ty(a) for a in tv.args]
            want = T.CON_ARITY[tv.target]
            if len(args) != want:
                args = [T.DYN] * want
            return T.TCon(tv.target, tuple(args))
        return base if base is not None else T.DYN

    # ------------------------------------------------------------------ constants
    def force_const(self, thunk: ConstThunk, span):
        if thunk.state == "done":
            return thunk.value
        if thunk.state == "evaluating":
            cycle = [t.decl for t in self.const_stack[self.const_stack.index(thunk):]] + [thunk.decl]
            names = " -> ".join(f"{t.module.name}.{t.decl.name}" for t in
                                self.const_stack[self.const_stack.index(thunk):]) + f" -> {thunk.module.name}.{thunk.decl.name}"
            d = Diagnostic(code("A.MODULE.INIT_CYCLE"),  # runtime backstop of the static check
                           f"module constant initialisation cycle: {names}",
                           primary=Label(thunk.decl.span, "cycle starts here"))
            for c in cycle[1:-1]:
                d.secondary.append(Label(c.span, f"`{c.name}` depends on the next constant"))
            d.help.append("break the cycle by computing one constant without reading the other")
            raise Abandoned(d)
        thunk.state = "evaluating"
        self.const_stack.append(thunk)
        try:
            v = self.eval(thunk.decl.value, thunk.module.env)
        finally:
            self.const_stack.pop()
        from ..frozen import is_frozen
        if not is_frozen(v):
            thunk.state = "pending"
            d = Diagnostic(code("A.MODULE.MUTABLE_GLOBAL"),
                           f"module constant `{thunk.decl.name}` must be a frozen value",
                           primary=Label(thunk.decl.value.span, "this value is mutable"))
            d.help.append("module-level state must be frozen; create mutable state in `main` and pass it explicitly")
            raise Abandoned(d)
        if thunk.decl.type is not None:
            ty = self.convert_type(thunk.decl.type, thunk.module.env)
            self.check_annotation(ty, v, thunk.decl.value.span, thunk.decl.type, None, "constant annotation")
        thunk.state = "done"
        thunk.value = v
        thunk.module.env.vars[thunk.decl.name] = v
        return v

    def init_consts(self) -> None:
        for mrt in self.modules.values():
            for v in list(mrt.env.vars.values()):
                if isinstance(v, ConstThunk):
                    self.force_const(v, v.decl.span)

    def current_module(self):
        fr = self.sched.current.frames[-1] if self.sched.current and self.sched.current.frames else None
        if fr is not None and fr.closure is not None:
            return fr.closure.module
        return None


def annotate_tparams(node, scope: frozenset) -> None:
    """Record, on every TypeExpr, the generic type parameters in scope."""
    if isinstance(node, (A.FnDecl, A.RecordDecl, A.EnumDecl, A.ProtocolDecl)):
        scope = scope | frozenset(getattr(node, "type_params", []) or [])
    if isinstance(node, A.TypeExpr):
        node.ann["tparams"] = scope
    for ch in A.iter_children(node):
        annotate_tparams(ch, scope)
