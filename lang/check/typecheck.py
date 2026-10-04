"""Gradual static checker: types, effects, async/resource/task rules, exhaustiveness
dispatch and verified-mode obligations. See docs/semantics/typing_and_effects.md.

The checker walks every function body with a static type environment. Unknown types
are `Dyn`. Effects are accumulated in a stack of collectors (handlers pop and filter
them). Unannotated functions get inferred effects by fixpoint iteration before the
reporting pass.
"""
from __future__ import annotations

import difflib
from typing import Optional

from .. import typesys as T
from ..diagnostics import Diagnostic, Label, Note, code
from ..runtime.builtins.registry import METHODS, MODULES, PRELUDE, PROPS, STATICS
from ..runtime.core_types import ALL_CORE_TYPES, CATEGORIES
from ..syntax import ast as A
from .decls import CORE_CATEGORY_QUALS, FnSig, TypeInfo, core_type_infos
from .exhaustive import check_match
from .types import (DYN, consistent, is_mutable_type, join, kind_of_type, receiver_bindings, sig_type, unify)
from .callcheck import CallMixin
from .expr import ExprMixin
from .selectcheck import SelectCheckMixin
from .walk import WalkMixin

AGG = "core.AggregateException"
DEADLINE = "core.DeadlineExceeded"
CHCLOSED = "core.ChannelClosed"


class Collector:
    __slots__ = ("names", "unknown", "sites", "unknown_site")

    def __init__(self):
        self.names: dict[str, object] = {}
        self.unknown = False
        self.sites: dict[str, object] = {}
        self.unknown_site = None

    def add(self, names, unknown: bool, span) -> None:
        for n in names:
            if n not in self.names:
                self.names[n] = span
        if unknown and not self.unknown:
            self.unknown = True
            self.unknown_site = span

    @property
    def empty(self) -> bool:
        return not self.names and not self.unknown


class Scope:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars: dict[str, tuple] = {}  # name -> (Ty, kind, span)
        self.parent = parent

    def get(self, name):
        s = self
        while s is not None:
            if name in s.vars:
                return s.vars[name]
            s = s.parent
        return None


class FnState:
    def __init__(self, sig: Optional[FnSig], decl, is_async: bool, kind: str = "fn", owner: Optional[TypeInfo] = None):
        self.sig = sig
        self.decl = decl
        self.is_async = is_async
        self.kind = kind
        self.owner = owner
        self.loop_depth = 0
        self.has_cancel_point = False
        self.in_use_init = False


class Checker(WalkMixin, CallMixin, SelectCheckMixin, ExprMixin):
    def __init__(self, program, mode: str, prior):
        self.program = program
        self.mode = mode
        self.verified = mode == "verified"
        self.diags: list[Diagnostic] = []
        self.report = False
        self.types: dict[str, TypeInfo] = core_type_infos()
        self.modules: dict[str, dict] = {}  # module -> name -> entity
        self.exports: dict[str, set] = {}
        self.fn_sigs: list[FnSig] = []
        self.eff_stack: list[Collector] = []
        self.fn_stack: list[FnState] = []
        self.cur_module = ""
        self._dedupe: set = set()
        self.blocked_files = {d.span.file.path for d in prior if d.severity == "error" and d.span is not None}

    # ------------------------------------------------------------------ diagnostics
    def emit(self, stable: str, msg: str, span, sev: str, label: str = "", help: Optional[str] = None,
             secondary=None, notes=None, expected=None, found=None) -> Optional[Diagnostic]:
        if not self.report or span is None:
            return None
        key = (stable, span.file.path, span.start, span.end, msg)
        if key in self._dedupe:
            return None
        self._dedupe.add(key)
        d = Diagnostic(code(stable), msg, severity=sev, primary=Label(span, label), expected=expected, found=found)
        d.blocking = sev == "error"
        if help:
            d.help.append(help)
        for s in secondary or []:
            d.secondary.append(s)
        for n in notes or []:
            d.notes.append(Note(n))
        self.diags.append(d)
        return d

    def legal(self, stable, msg, span, **kw):
        return self.emit(stable, msg, span, "error", **kw)

    def oblig(self, stable, msg, span, **kw):
        return self.emit(stable, msg, span, "error" if self.verified else "warning", **kw)

    def verified_only(self, stable, msg, span, **kw):
        if self.verified:
            return self.emit(stable, msg, span, "error", **kw)
        return None

    def advise(self, stable, msg, span, **kw):
        return self.emit(stable, msg, span, "warning", **kw)

    # ------------------------------------------------------------------ setup
    def run(self) -> list[Diagnostic]:
        mods = [(n, m) for n, m in self.program.modules.items() if m.ast is not None]
        for name, ms in self.program.modules.items():
            if ms.native:
                ents = {}
                for k, v in MODULES.get(name, {}).items():
                    ents[k] = ("native", v)
                self.modules[name] = ents
                self.exports[name] = set(ents)
        for name, ms in mods:
            self.declare_types(name, ms.ast)
        for name, ms in mods:
            self.bind_imports(name, ms.ast)
        for name, ms in mods:
            self.fill_types(name, ms.ast)
        self.check_declarations(mods)
        # effect inference fixpoint for unannotated functions (no reporting)
        for _ in range(6):
            before = [(s.inferred, s.inferred_unknown) for s in self.fn_sigs]
            for name, ms in mods:
                self.check_module_bodies(name, ms.ast)
            after = [(s.inferred, s.inferred_unknown) for s in self.fn_sigs]
            if before == after:
                break
        self.report = True
        for name, ms in mods:
            if ms.file is not None and ms.file.path in self.blocked_files:
                continue
            self.check_module_bodies(name, ms.ast)
        from .advisories import run_advisories
        run_advisories(self, [(n, m) for n, m in mods if m.file is None or m.file.path not in self.blocked_files])
        return self.diags

    def declare_types(self, mname: str, mod: A.Module) -> None:
        ents = self.modules.setdefault(mname, {})
        self.exports[mname] = set()
        for d in mod.decls:
            q = f"{mname}.{d.name}"
            if isinstance(d, A.RecordDecl):
                kind = "error" if d.kind == "error" else ("mrecord" if d.mutable else "record")
                ti = TypeInfo(q, d.name, kind, d, type_params=list(d.type_params), module=mname)
                if d.category:
                    ti.categories = (self.category_qual(mname, d.category),)
                self.types[q] = ti
                ents[d.name] = ("type", ti)
            elif isinstance(d, A.EnumDecl):
                ti = TypeInfo(q, d.name, "errorenum" if d.is_error else "enum", d, type_params=list(d.type_params),
                              module=mname)
                if d.category:
                    ti.categories = (self.category_qual(mname, d.category),)
                self.types[q] = ti
                ents[d.name] = ("type", ti)
            elif isinstance(d, A.ProtocolDecl):
                ti = TypeInfo(q, d.name, "protocol", d, type_params=list(d.type_params), module=mname)
                self.types[q] = ti
                ents[d.name] = ("type", ti)
            elif isinstance(d, A.CategoryDecl):
                ents[d.name] = ("category", q)
            elif isinstance(d, A.FnDecl):
                ents[d.name] = ("fn", None)
            elif isinstance(d, A.PredicateDecl):
                ents[d.name] = ("predicate", None)
            elif isinstance(d, A.ConstDecl):
                ents[d.name] = ("const", None)
            if getattr(d, "is_pub", False):
                self.exports[mname].add(d.name)

    def category_qual(self, mname: str, cat: str) -> str:
        ent = self.modules.get(mname, {}).get(cat)
        if ent is not None and ent[0] == "category":
            return ent[1]
        if cat in CORE_CATEGORY_QUALS:
            return CORE_CATEGORY_QUALS[cat]
        return f"{mname}.{cat}"

    def bind_imports(self, mname: str, mod: A.Module) -> None:
        ents = self.modules[mname]
        for imp in mod.imports:
            full = ".".join(imp.path)
            if full not in self.modules:
                continue
            if imp.names is not None:
                for n, _ in imp.names:
                    if n in self.modules[full]:
                        ents.setdefault(n, self.modules[full][n])
            else:
                ents.setdefault(imp.alias or imp.path[-1], ("module", full))

    # ------------------------------------------------------------------ type conversion
    def resolver_for(self, mname: str):
        def resolve(path, node):
            ent = self.lookup_global(mname, path[0])
            for seg in path[1:]:
                if ent is not None and ent[0] == "module":
                    ent = self.modules.get(ent[1], {}).get(seg)
                elif ent is not None and ent[0] == "native" and False:
                    ent = None
                else:
                    ent = None
            if ent is None:
                return None
            if ent[0] == "type":
                ti = ent[1]
                return T.TNominal(ti.qualname, ti.kind)
            if ent[0] == "native":
                from ..runtime.values import TypeValue
                v = ent[1]
                if isinstance(v, TypeValue) and v.kind == "builtin":
                    return T.TCon(v.target, ())
            return None
        return resolve

    def lookup_global(self, mname: str, name: str):
        ent = self.modules.get(mname, {}).get(name)
        if ent is not None:
            return ent
        core = ALL_CORE_TYPES.get(name)
        if core is not None and core.qualname in self.types:
            return ("type", self.types[core.qualname])
        if name in CATEGORIES:
            return ("category", f"core.{name}")
        if name in PRELUDE:
            return ("prelude", PRELUDE[name])
        return None

    def ty(self, texpr, mname: Optional[str] = None, tparams=frozenset()) -> T.Ty:
        if texpr is None:
            return DYN
        try:
            return T.from_expr(texpr, self.resolver_for(mname or self.cur_module),
                               frozenset(tparams) | texpr.ann.get("tparams", frozenset()))
        except T.TypeConversionError as err:
            if err.stable == "S.TYPE.GENERIC_ARITY":
                saved = self.report
                self.report = True  # annotation errors are reported once, whatever pass converts them
                self.legal(err.stable, err.message, err.node.span, help=err.help or None)
                self.report = saved
            return DYN

    # ------------------------------------------------------------------ declarations
    def fill_types(self, mname: str, mod: A.Module) -> None:
        self.cur_module = mname
        for d in mod.decls:
            if isinstance(d, A.RecordDecl):
                ti = self.types[f"{mname}.{d.name}"]
                tps = set(d.type_params)
                for f in d.fields:
                    ti.fields[f.name] = self.ty(f.type, mname, tps)
                    ti.field_spans[f.name] = f.span
                inv = set()
                for e in d.invariants:
                    for n in A.walk(e):
                        if isinstance(n, A.Name) and n.name in ti.fields:
                            inv.add(n.name)
                        if isinstance(n, A.Field) and isinstance(n.obj, A.Name) and n.obj.name == "self":
                            inv.add(n.name)
                ti.invariant_fields = frozenset(inv)
                for m in d.methods:
                    ti.methods[m.name] = self.make_sig(m, mname, tps, owner=ti)
            elif isinstance(d, A.EnumDecl):
                ti = self.types[f"{mname}.{d.name}"]
                tps = set(d.type_params)
                for c in d.cases:
                    ti.cases[c.name] = None if c.fields is None else [(f.name, self.ty(f.type, mname, tps))
                                                                      for f in c.fields]
                for m in d.methods:
                    ti.methods[m.name] = self.make_sig(m, mname, tps, owner=ti)
            elif isinstance(d, A.ProtocolDecl):
                ti = self.types[f"{mname}.{d.name}"]
                for m in d.methods:
                    ti.methods[m.name] = self.make_sig(m, mname, set(d.type_params), owner=ti)
            elif isinstance(d, A.FnDecl):
                self.modules[mname][d.name] = ("fn", self.make_sig(d, mname, set()))
            elif isinstance(d, A.PredicateDecl):
                sig = FnSig(d.name, [(p.name, self.ty(p.type, mname), False, False) for p in d.params], T.BOOL,
                            frozenset(), decl=d, ret_written=True)
                self.modules[mname][d.name] = ("predicate", sig)
            elif isinstance(d, A.ConstDecl):
                self.modules[mname][d.name] = ("const", self.ty(d.type, mname) if d.type else None)

    def make_sig(self, d: A.FnDecl, mname: str, outer_tps: set, owner: Optional[TypeInfo] = None) -> FnSig:
        tps = set(outer_tps) | set(d.type_params)
        params = []
        for p in d.params:
            if p.is_self:
                continue
            t = self.ty(p.type, mname, tps)
            if p.borrow:
                t = T.TBorrow(t)
            params.append((p.name, t, p.default is not None, p.borrow))
        effect = None
        if d.throws is not None:
            names = set()
            for te in d.throws:
                if isinstance(te, A.TypeName) and len(te.path) == 1 and te.path[0] in tps:
                    names.add("$" + te.path[0])
                    continue
                t = self.ty(te, mname, tps)
                if isinstance(t, T.TNominal):
                    names.add(t.qualname)
            effect = frozenset(names)
        ret = self.ty(d.ret, mname, tps) if d.ret is not None else (DYN if not d.is_resource else T.UNIT)
        sig = FnSig(d.name, params, ret, effect, d.is_async, d.is_resource,
                    self.ty(d.yields, mname, tps) if d.yields is not None else None,
                    list(d.type_params), d, owner.qualname if owner else None, d.has_self,
                    ret_written=d.ret is not None)
        if d.ret is None and d.body is not None and not d.is_resource:
            sig.ret = DYN if self._returns_value(d) else T.UNIT
        self.fn_sigs.append(sig)
        return sig

    @staticmethod
    def _returns_value(d) -> bool:
        for n in A.walk(d.body):
            if isinstance(n, A.ReturnStmt) and n.value is not None:
                return True
            if isinstance(n, A.Propagate):
                return True
        return False

    def check_declarations(self, mods) -> None:
        self.report = True
        for mname, ms in mods:
            self.cur_module = mname
            for d in ms.ast.decls:
                if isinstance(d, A.RecordDecl):
                    self.check_record_decl(mname, d)
                elif isinstance(d, A.EnumDecl):
                    for m in d.methods:
                        self.check_sig_rules(m, mname)
                elif isinstance(d, A.FnDecl):
                    self.check_sig_rules(d, mname)
                elif isinstance(d, A.PredicateDecl):
                    from .contracts_check import check_predicate
                    check_predicate(self, d, mname)
        self.report = False

    def check_record_decl(self, mname: str, d: A.RecordDecl) -> None:
        ti = self.types[f"{mname}.{d.name}"]
        if not d.mutable:
            for f in d.fields:
                t = ti.fields[f.name]
                fr = T.is_frozen_type(t, lambda n: self.types.get(n.qualname) is None or
                                      self.types[n.qualname].kind != "mrecord")
                if fr is False:
                    self.legal("S.TYPE.FROZEN_FIELD_TYPE",
                               f"field `{f.name}` of frozen record {d.name} has mutable type {t}", f.span,
                               help="ordinary records are transitively frozen: use a frozen type (List/Map/Set) or "
                                    f"declare `mutable record {d.name}`")
        if d.mutable and len(d.fields) > 12:
            self.advise("W.STATE.LARGE_MUTABLE_RECORD",
                        f"mutable record {d.name} has {len(d.fields)} fields; large state bags widen the "
                        f"mutable-state horizon", d.name_span or d.span,
                        help="decompose into narrowly purposed records passed only to the code that needs them (V3 3.1)")
        for s in d.satisfies:
            pt = self.ty(s, mname)
            if not (isinstance(pt, T.TNominal) and pt.kind == "protocol"):
                self.legal("S.PROTOCOL.NOT_SATISFIED", f"`{s.span.text}` is not a protocol", s.span)
                continue
            reason = self.conformance(ti.ty, pt, explain=True)
            if reason:
                stable = "S.PROTOCOL.ADDED_PRECONDITION" if "precondition" in reason else "S.PROTOCOL.NOT_SATISFIED"
                self.legal(stable, f"{d.name} does not satisfy {pt}: {reason}", s.span,
                           secondary=[Label(d.name_span or d.span, f"{d.name} declared here")])
        for m in d.methods:
            self.check_sig_rules(m, mname)

    def check_sig_rules(self, d: A.FnDecl, mname: str) -> None:
        if d.throws is not None and d.ret is not None and isinstance(d.ret, A.TypeName) and d.ret.path == ["Result"]:
            self.legal("S.EFFECT.THROWS_AND_RESULT",
                       f"`{d.name}` both declares `throws` and returns `Result`; choose one failure channel",
                       d.name_span or d.span,
                       help="return `Result` for failures-as-data, or throw for immediate control flow (V3 5.7.3)")
        if d.is_pub and self.verified:
            for p in d.params:
                if not p.is_self and p.type is None:
                    self.verified_only("S.TYPE.MISSING_ANNOTATION",
                                       f"exported function `{d.name}` needs a type for parameter `{p.name}`", p.span)
            if d.ret is None and not d.is_resource and self._returns_value(d):
                self.verified_only("S.TYPE.MISSING_ANNOTATION",
                                   f"exported function `{d.name}` returns a value but has no return annotation",
                                   d.name_span or d.span)

    # ------------------------------------------------------------------ conformance
    def conformance(self, src: T.Ty, proto: T.TNominal, explain: bool = False):
        """None if `src` satisfies the protocol, else a reason string; True if unknown."""
        pt = self.types.get(proto.qualname)
        if pt is None:
            return None
        if isinstance(src, T.TNominal):
            st = self.types.get(src.qualname)
            if st is None:
                return None
            for mname, psig in pt.methods.items():
                m = st.methods.get(mname)
                if m is None:
                    return f"missing method `{mname}`"
                if len(m.params) != len(psig.params):
                    return f"method `{mname}` takes {len(m.params)} parameter(s) but the protocol requires {len(psig.params)}"
                if m.is_async != psig.is_async:
                    return f"method `{mname}` differs in async-ness"
                if m.decl is not None and m.decl.requires:
                    return f"method `{mname}` adds a `requires` precondition"
                pe = psig.effect if psig.effect is not None else frozenset()
                if m.effect is not None and not any(n.startswith("$") for n in pe):
                    extra = [n for n in m.effect if n not in pe]
                    if extra:
                        return f"method `{mname}` may throw {', '.join(sorted(x.rsplit('.', 1)[-1] for x in extra))}"
                for (pn, pty, _, _), (mn, mty, _, _) in zip(psig.params, m.params):
                    if not consistent(pty, mty, self.satisfies):
                        return f"method `{mname}` parameter `{mn}` has type {mty}, protocol expects {pty}"
                if not consistent(m.ret, psig.ret, self.satisfies):
                    return f"method `{mname}` returns {m.ret}, protocol expects {psig.ret}"
            return None
        k = kind_of_type(src)
        if k is not None:
            table = METHODS.get(k, {})
            for mname in pt.methods:
                if mname not in table:
                    return f"missing method `{mname}`"
            return None
        return True

    def satisfies(self, src, proto):
        r = self.conformance(src, proto)
        return None if r is True else r


def typecheck_program(program, mode: str, prior_diags) -> list[Diagnostic]:
    return Checker(program, mode, prior_diags).run()
