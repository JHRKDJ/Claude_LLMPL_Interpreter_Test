"""Name resolution and structural placement checks.

Produces diagnostics and AST annotations used by the runtime and the type checker:
  Name.ann["binding"]      -> Binding
  Name.ann["init_span"]    -> span of the binding's initialiser (value origin)
  Lambda/Spawn.ann["captures"] -> [(name, reassigned)]
  Call.ann["marked"]       -> whether a `try`/`capture`/handler covers this call
Rules enforced (both modes unless noted): unresolved names (V3 2.4, AMB-010),
duplicate declarations, const reassignment, captured reassignment without
`nonlocal` (SPEC-003), definite assignment (V3 5.4, 6.3), placement of await /
spawn / yield / onAbandon / break / continue / return-in-defer / old / result,
module visibility (pub).
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional

from ..diagnostics import Diagnostic, Fix, Label, Note, TextEdit, code
from ..source import Span
from ..syntax import ast as A
from ..syntax.parser import parse_source
from ..source import SourceFile
from .names import BUILTIN_TYPE_NAMES, CORE_CASES, PRELUDE_VALUES, PRIM_TYPES, native_module_exports

TOP = None  # unreachable marker for definite-assignment sets


class Binding:
    __slots__ = ("name", "kind", "node", "span", "level", "is_const", "assigned", "uninit", "init_span",
                 "module_level", "target", "used")

    def __init__(self, name, kind, node, span, level, is_const=False, uninit=False, init_span=None,
                 module_level=False, target=None):
        self.name = name
        self.kind = kind
        self.node = node
        self.span = span
        self.level = level
        self.is_const = is_const
        self.assigned = False  # reassigned after declaration
        self.uninit = uninit
        self.init_span = init_span
        self.module_level = module_level
        self.target = target  # for imports: (module name, member) or module name
        self.used = False

    def __repr__(self) -> str:
        return f"<{self.kind} {self.name}>"


class Scope:
    __slots__ = ("names", "parent", "level", "kind")

    def __init__(self, parent: Optional["Scope"], level: int, kind: str):
        self.names: dict[str, Binding] = {}
        self.parent = parent
        self.level = level
        self.kind = kind

    def lookup(self, name: str) -> Optional[Binding]:
        s = self
        while s is not None:
            b = s.names.get(name)
            if b is not None:
                return b
            s = s.parent
        return None

    def all_names(self) -> list[str]:
        out = []
        s = self
        while s is not None:
            out.extend(s.names)
            s = s.parent
        return out


class FnCtx:
    __slots__ = ("kind", "level", "is_async", "provider", "captures", "nonlocals", "parallel_depth", "loop_depth",
                 "in_defer", "decl", "contract")

    def __init__(self, kind, level, is_async=False, provider=False, decl=None):
        self.kind = kind  # fn | lambda | spawn | contract | test | const
        self.level = level
        self.is_async = is_async
        self.provider = provider
        self.captures: dict[str, Binding] = {}
        self.nonlocals: set[str] = set()
        self.parallel_depth = 0
        self.loop_depth = 0
        self.in_defer = 0
        self.decl = decl
        self.contract = None  # "requires" | "ensures" | "invariant" | "predicate"


class ProjectIndex:
    """Exported names of project modules, stdlib modules and pinned dependencies,
    used for import suggestions (V3 2.4, 8.19)."""

    def __init__(self, program):
        self.by_name: dict[str, list[str]] = {}
        self.modules: set[str] = set()
        self._build(program)

    def module_candidates(self, name: str) -> list[str]:
        """Known modules whose last path segment is `name` (e.g. `fs` -> `std.fs`)."""
        return sorted(m for m in self.modules if m.rsplit(".", 1)[-1] == name)

    def _add(self, module: str, name: str) -> None:
        self.modules.add(module)
        self.by_name.setdefault(name, [])
        if module not in self.by_name[name]:
            self.by_name[name].append(module)

    def _build(self, program) -> None:
        from ..modules.loader import STDLIB_DIR, module_name_for
        for mod, names in native_module_exports().items():
            for n in names:
                self._add(mod, n)
        files: list[tuple[str, Path]] = []
        for p in STDLIB_DIR.glob("*.lang"):
            files.append((f"std.{p.stem}", p))
        root = program.project.root
        count = 0
        for p in sorted(root.rglob("*.lang")):
            if any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            count += 1
            if count > 400:
                break
            files.append((module_name_for(p, root), p))
        for name, dep in program.project.dependencies.items():
            for p in sorted(dep.path.rglob("*.lang")):
                rel = module_name_for(p, dep.path)
                files.append((f"{name}.{rel}" if rel else name, p))
        loaded = {m.name: m for m in program.modules.values() if m.ast is not None}
        for mod, path in files:
            ms = loaded.get(mod)
            if ms is not None:
                ast_ = ms.ast
            else:
                try:
                    ast_ = parse_source(SourceFile(str(path), path.read_text(encoding="utf-8"))).module
                except (OSError, UnicodeDecodeError):
                    continue
            for d in ast_.decls:
                if getattr(d, "is_pub", False):
                    self._add(mod, d.name)

    def candidates(self, name: str, exclude: str) -> list[str]:
        return [m for m in self.by_name.get(name, []) if m != exclude]


class Resolver:
    def __init__(self, program, mode: str):
        self.program = program
        self.mode = mode
        self.diags: list[Diagnostic] = []
        self._index: Optional[ProjectIndex] = None
        self.module_scopes: dict[str, Scope] = {}
        self.module_exports: dict[str, dict[str, A.Decl]] = {}
        self.module_decls: dict[str, dict[str, A.Decl]] = {}

    # ------------------------------------------------------------------ diagnostics
    def err(self, stable: str, msg: str, span: Span, label: str = "", help: Optional[str] = None,
            fixes=None, secondary=None, severity: Optional[str] = None) -> Diagnostic:
        d = Diagnostic(code(stable), msg, primary=Label(span, label))
        if severity is not None:
            d.severity = severity
            d.blocking = severity == "error"
        if help:
            d.help.append(help)
        for f in fixes or []:
            d.fixes.append(f)
        for s in secondary or []:
            d.secondary.append(s)
        self.diags.append(d)
        return d

    def obligation(self, stable_verified: str, msg: str, span: Span, **kw) -> Diagnostic:
        """A verified-mode obligation: error in verified, warning in draft (V3 5.15)."""
        sev = "error" if self.mode == "verified" else "warning"
        return self.err(stable_verified, msg, span, severity=sev, **kw)

    @property
    def index(self) -> ProjectIndex:
        if self._index is None:
            self._index = ProjectIndex(self.program)
        return self._index

    # ------------------------------------------------------------------ program
    def run(self) -> list[Diagnostic]:
        for name, ms in self.program.modules.items():
            if ms.native or ms.ast is None:
                exports = {n: None for n in native_module_exports().get(name, [])}
                self.module_exports[name] = exports
                continue
            decls = {}
            exports = {}
            for d in ms.ast.decls:
                if isinstance(d, A.TestDecl):
                    continue
                if d.name in decls:
                    self.err("S.NAME.DUPLICATE", f"`{d.name}` is declared twice in module `{name}`",
                             getattr(d, "name_span", None) or d.span, "second declaration",
                             secondary=[Label(getattr(decls[d.name], "name_span", None) or decls[d.name].span,
                                              "first declared here")])
                    continue
                decls[d.name] = d
                if getattr(d, "is_pub", False):
                    exports[d.name] = d
            self.module_decls[name] = decls
            self.module_exports[name] = exports
        for name, ms in self.program.modules.items():
            if ms.ast is not None:
                self.resolve_module(name, ms)
        return self.diags

    def resolve_module(self, mname: str, ms) -> None:
        mod: A.Module = ms.ast
        prelude = Scope(None, 0, "prelude")
        for n in PRELUDE_VALUES:
            prelude.names[n] = Binding(n, "prelude", None, None, 0, is_const=True, module_level=True)
        for n in PRIM_TYPES + BUILTIN_TYPE_NAMES:
            prelude.names.setdefault(n, Binding(n, "type", None, None, 0, is_const=True, module_level=True))
        mscope = Scope(prelude, 0, "module")
        self.module_scopes[mname] = mscope
        self.cur_module = mname
        self.cur_file = ms.file
        self.cur_ast = mod
        for imp in mod.imports:
            full = ".".join(imp.path)
            exports = self.module_exports.get(full)
            if exports is None:
                continue  # loader already reported the missing module
            if imp.names is not None:
                for n, sp in imp.names:
                    if n not in exports:
                        decls = self.module_decls.get(full, {})
                        if n in decls:
                            self.err("S.NAME.PRIVATE", f"`{n}` is private to module `{full}`", sp, "not exported",
                                     help=f"mark it `pub` in {full} to export it")
                        else:
                            close = difflib.get_close_matches(n, list(exports), n=3)
                            self.err("S.NAME.UNRESOLVED", f"module `{full}` has no exported member `{n}`", sp,
                                     help=("did you mean " + ", ".join(f"`{c}`" for c in close) + "?") if close else None)
                        continue
                    self.declare(mscope, Binding(n, "import", exports[n], sp, 0, is_const=True, module_level=True,
                                                 target=(full, n)), sp)
            else:
                alias = imp.alias or imp.path[-1]
                self.declare(mscope, Binding(alias, "module", None, imp.span, 0, is_const=True, module_level=True,
                                             target=full), imp.span)
        for d in mod.decls:
            if isinstance(d, A.TestDecl):
                continue
            kind = {A.FnDecl: "fn", A.RecordDecl: "type", A.EnumDecl: "type", A.ProtocolDecl: "type",
                    A.CategoryDecl: "category", A.PredicateDecl: "predicate", A.ConstDecl: "const"}.get(type(d), "decl")
            b = Binding(d.name, kind, d, getattr(d, "name_span", None) or d.span, 0, is_const=True, module_level=True)
            if d.name in mscope.names and mscope.names[d.name].kind in ("import", "module"):
                self.err("S.NAME.DUPLICATE", f"`{d.name}` is both imported and declared in this module",
                         b.span, secondary=[Label(mscope.names[d.name].span, "imported here")])
                continue
            mscope.names.setdefault(d.name, b)
        for d in mod.decls:
            self.resolve_decl(d, mscope)

    def declare(self, scope: Scope, b: Binding, span) -> None:
        if b.name in scope.names and scope.kind != "prelude":
            prev = scope.names[b.name]
            self.err("S.NAME.DUPLICATE", f"`{b.name}` is already declared in this scope", span, "redeclared here",
                     secondary=[Label(prev.span, "previous declaration")] if prev.span else None,
                     help="bindings are reassignable: use `name = value` to rebind, or choose a new name")
            return
        scope.names[b.name] = b

    # ------------------------------------------------------------------ declarations
    def resolve_decl(self, d, mscope: Scope) -> None:
        if isinstance(d, A.FnDecl):
            self.resolve_fn(d, mscope, set(d.type_params))
        elif isinstance(d, A.RecordDecl):
            tps = set(d.type_params)
            names = set()
            for f in d.fields:
                if f.name in names:
                    self.err("S.NAME.DUPLICATE", f"field `{f.name}` declared twice in {d.name}", f.span)
                names.add(f.name)
                self.resolve_type(f.type, mscope, tps)
                if f.default is not None:
                    self.resolve_expr_in_new_fn(f.default, mscope, "const")
            for m in d.methods:
                if m.name in names:
                    self.err("S.NAME.DUPLICATE", f"`{m.name}` is both a field and a method of {d.name}", m.name_span or m.span)
                names.add(m.name)
                self.resolve_fn(m, mscope, tps | set(m.type_params), owner=d)
            for s in d.satisfies:
                self.resolve_type(s, mscope, tps)
            for inv in d.invariants:
                scope = Scope(mscope, 1, "fn")
                ctx = FnCtx("contract", 1, decl=d)
                ctx.contract = "invariant"
                for f in d.fields:
                    scope.names[f.name] = Binding(f.name, "field", f, f.span, 1, is_const=True)
                scope.names["self"] = Binding("self", "param", None, d.span, 1, is_const=True)
                self.with_ctx(ctx, lambda: self.expr(inv, scope, set()))
        elif isinstance(d, A.EnumDecl):
            tps = set(d.type_params)
            seen = set()
            for c in d.cases:
                if c.name in seen:
                    self.err("S.NAME.DUPLICATE", f"case `{c.name}` declared twice in {d.name}", c.span)
                seen.add(c.name)
                for f in c.fields or []:
                    self.resolve_type(f.type, mscope, tps)
            for m in d.methods:
                if m.name in seen:
                    self.err("S.NAME.DUPLICATE", f"`{m.name}` is both a case and a method of {d.name}", m.name_span or m.span)
                self.resolve_fn(m, mscope, tps | set(m.type_params), owner=d)
        elif isinstance(d, A.ProtocolDecl):
            for m in d.methods:
                self.resolve_fn(m, mscope, set(d.type_params) | set(m.type_params), owner=d, signature_only=True)
        elif isinstance(d, A.PredicateDecl):
            scope = Scope(mscope, 1, "fn")
            for p in d.params:
                self.resolve_type(p.type, mscope, set())
                scope.names[p.name] = Binding(p.name, "param", p, p.span, 1, is_const=True)
            ctx = FnCtx("contract", 1, decl=d)
            ctx.contract = "predicate"
            self.with_ctx(ctx, lambda: self.block(d.body, scope, set(), new_scope=False))
        elif isinstance(d, A.ConstDecl):
            self.resolve_type(d.type, mscope, set())
            self.resolve_expr_in_new_fn(d.value, mscope, "const")
        elif isinstance(d, A.TestDecl):
            scope = Scope(mscope, 1, "fn")
            ctx = FnCtx("test", 1, is_async=True, decl=d)
            self.with_ctx(ctx, lambda: self.block(d.body, scope, set(), new_scope=False))

    def resolve_expr_in_new_fn(self, e, mscope, kind):
        scope = Scope(mscope, 1, "fn")
        ctx = FnCtx(kind, 1, decl=None)
        self.with_ctx(ctx, lambda: self.expr(e, scope, set()))

    def with_ctx(self, ctx: FnCtx, fn):
        saved = getattr(self, "ctx", None)
        saved_stack = getattr(self, "ctx_stack", [])
        self.ctx_stack = saved_stack + [ctx]
        self.ctx = ctx
        try:
            return fn()
        finally:
            self.ctx = saved
            self.ctx_stack = saved_stack

    def resolve_fn(self, d: A.FnDecl, mscope: Scope, tps: set, owner=None, signature_only: bool = False) -> None:
        scope = Scope(mscope, 1, "fn")
        names = set()
        for i, p in enumerate(d.params):
            if p.is_self:
                if owner is None:
                    self.err("S.SYNTAX.MISPLACED_CONSTRUCT", "`self` parameter outside a record/enum/protocol method",
                             p.span)
                elif i != 0:
                    self.err("S.SYNTAX.MISPLACED_CONSTRUCT", "`self` must be the first parameter", p.span)
                scope.names["self"] = Binding("self", "param", p, p.span, 1, is_const=True, init_span=p.span)
                continue
            if p.name in names:
                self.err("S.NAME.DUPLICATE", f"parameter `{p.name}` declared twice", p.span)
            names.add(p.name)
            self.resolve_type(p.type, mscope, tps)
            if p.default is not None:
                self.resolve_expr_in_new_fn(p.default, mscope, "const")
            scope.names[p.name] = Binding(p.name, "param", p, p.span, 1, init_span=p.span)
        self.resolve_type(d.ret, mscope, tps)
        self.resolve_type(d.yields, mscope, tps)
        for t in d.throws or []:
            self.resolve_type(t, mscope, tps)
        for kind, clauses in (("requires", d.requires), ("ensures", d.ensures)):
            for c in clauses:
                cscope = Scope(scope, 1, "block")
                if kind == "ensures":
                    cscope.names["result"] = Binding("result", "result", None, c.span, 1, is_const=True)
                ctx = FnCtx("contract", 1, decl=d)
                ctx.contract = kind
                self.with_ctx(ctx, lambda c=c, cscope=cscope: self.expr(c, cscope, set()))
        if signature_only or d.body is None:
            return
        ctx = FnCtx("fn", 1, is_async=d.is_async, provider=d.is_resource, decl=d)
        self.with_ctx(ctx, lambda: self.block(d.body, scope, set(), new_scope=False))

    # ------------------------------------------------------------------ types
    def resolve_type(self, t, scope: Scope, tps: set) -> None:
        if t is None:
            return
        if isinstance(t, A.TypeName):
            first = t.path[0]
            if len(t.path) == 1 and (first in tps or first in PRIM_TYPES or first in BUILTIN_TYPE_NAMES):
                pass
            else:
                b = scope.lookup(first)
                if b is None:
                    self.unresolved(first, t.span, scope, as_type=True)
                elif b.kind in ("let", "param", "pattern", "use", "catch", "loop", "fn", "const", "predicate") and len(t.path) == 1:
                    self.err("S.NAME.NOT_A_TYPE", f"`{first}` is not a type", t.span,
                             secondary=[Label(b.span, "declared here")] if b.span else None)
                else:
                    b.used = True
                    if b.kind == "module" and len(t.path) > 1:
                        self.check_module_member(b.target, t.path[1], t.span)
            for a in t.args:
                self.resolve_type(a, scope, tps)
        elif isinstance(t, A.OptionalType):
            self.resolve_type(t.inner, scope, tps)
        elif isinstance(t, A.TupleType):
            for i in t.items:
                self.resolve_type(i, scope, tps)
        elif isinstance(t, A.FnType):
            for p in t.params:
                self.resolve_type(p, scope, tps)
            self.resolve_type(t.ret, scope, tps)
            for e in t.throws or []:
                self.resolve_type(e, scope, tps)
        elif isinstance(t, A.BorrowType):
            self.resolve_type(t.inner, scope, tps)

    def check_module_member(self, module: str, member: str, span) -> None:
        exports = self.module_exports.get(module)
        if exports is None or member in exports:
            return
        if member in self.module_decls.get(module, {}):
            self.err("S.NAME.PRIVATE", f"`{member}` is private to module `{module}`", span, "not exported",
                     help=f"mark it `pub` in {module} to export it")
        else:
            close = difflib.get_close_matches(member, list(exports), n=3)
            self.err("S.NAME.UNRESOLVED", f"module `{module}` has no exported member `{member}`", span,
                     help=("did you mean " + ", ".join(f"`{c}`" for c in close) + "?") if close else None)

    # ------------------------------------------------------------------ unresolved names
    def unresolved(self, name: str, span, scope: Scope, as_type: bool = False) -> None:
        cands = self.index.candidates(name, self.cur_module)
        fixes = []
        help_ = None
        notes = []
        mod_cands = [] if as_type else self.index.module_candidates(name)
        if len(mod_cands) == 1 and not cands:
            mod = mod_cands[0]
            f = self.cur_file
            imports = self.cur_ast.imports
            pos = imports[-1].span.end if imports else 0
            text = f"\nimport {mod}" if imports else f"import {mod}\n\n"
            fixes.append(Fix(f"add `import {mod}`", [TextEdit(Span(f, pos, pos), text)]))
            help_ = f"`{name}` is the module `{mod}`; add `import {mod}` (applied automatically by `lang check --fix`)"
            notes.append("known missing module import")
        elif len(cands) == 1:
            mod = cands[0]
            fixes.append(Fix(f"add `import {mod}.{{{name}}}`", [self.import_edit(mod, name)]))
            help_ = f"`{name}` is exported by `{mod}`; add the import (applied automatically by `lang check --fix`)"
            notes.append("known missing import")
        elif len(cands) > 1:
            for mod in cands[:5]:
                fixes.append(Fix(f"add `import {mod}.{{{name}}}`", [self.import_edit(mod, name)]))
            help_ = "several known modules export `" + name + "`: " + ", ".join(f"`{m}`" for m in cands[:5]) + \
                    "; choose one"
            notes.append("ambiguous known import")
        else:
            pool = [n for n in scope.all_names() if not n.startswith("$")]
            close = difflib.get_close_matches(name, pool, n=3, cutoff=0.7)
            if close:
                help_ = "did you mean " + ", ".join(f"`{c}`" for c in close) + "?"
            notes.append("unknown name: not defined in scope, the project, the standard library or pinned "
                         "dependencies (adding a new dependency requires an explicit manifest change)")
        what = "type" if as_type else "name"
        d = self.err("S.NAME.UNRESOLVED", f"cannot find {what} `{name}` in this scope", span, "not found",
                     help=help_, fixes=fixes)
        for n in notes:
            d.notes.append(Note(n))
        d.extra["import_candidates"] = cands

    def import_edit(self, mod: str, name: str) -> TextEdit:
        f = self.cur_file
        imports = self.cur_ast.imports
        if imports:
            pos = imports[-1].span.end
            text = f"\nimport {mod}.{{{name}}}"
        else:
            pos = 0
            text = f"import {mod}.{{{name}}}\n\n"
        return TextEdit(Span(f, pos, pos), text)

    # ------------------------------------------------------------------ statements
    def block(self, blk: A.Block, scope: Scope, da: Optional[set], new_scope: bool = True) -> Optional[set]:
        s = Scope(scope, scope.level, "block") if new_scope else scope
        for st in blk.stmts:
            da = self.stmt(st, s, da)
        return da

    def stmt(self, st, scope: Scope, da):
        c = st.__class__
        ctx = self.ctx
        if c is A.ExprStmt:
            return self.expr(st.expr, scope, da)
        if c is A.LetStmt:
            if st.value is not None:
                da = self.expr(st.value, scope, da)
            self.resolve_type(st.type, scope, self.type_params_in_scope())
            for name, span in st.names:
                b = Binding(name, "let" if not st.is_const else "constlocal", st, span, scope.level,
                            is_const=st.is_const, uninit=st.value is None,
                            init_span=st.value.span if st.value is not None else None)
                self.declare(scope, b, span)
                if st.value is None and da is not TOP:
                    pass
            return da
        if c is A.AssignStmt:
            da = self.expr(st.value, scope, da)
            t = st.target
            if t.__class__ is A.Name:
                b = scope.lookup(t.name)
                if b is None:
                    self.unresolved(t.name, t.span, scope)
                    return da
                t.ann["binding"] = b
                if b.module_level or b.kind in ("fn", "type", "const", "import", "module", "prelude", "predicate",
                                                "category"):
                    self.err("S.NAME.CONST_REASSIGN", f"`{t.name}` is not a reassignable binding", t.span,
                             help="module-level names are frozen constants; create mutable state in a function")
                    return da
                if b.is_const or b.kind in ("param",) and False:
                    self.err("S.NAME.CONST_REASSIGN", f"cannot reassign const `{t.name}`", t.span,
                             secondary=[Label(b.span, "declared const here")])
                if b.kind in ("use",):
                    self.err("S.RESOURCE.ESCAPE", f"resource binding `{t.name}` cannot be reassigned", t.span)
                if b.level < ctx.level and b.level > 0:
                    if t.name not in ctx.nonlocals:
                        self.err("S.NAME.CAPTURED_REASSIGN",
                                 f"closure reassigns captured binding `{t.name}` without declaring `nonlocal {t.name}`",
                                 t.span, help=f"add `nonlocal {t.name}` at the start of the closure body, or return "
                                              f"the new value instead")
                    self.note_capture(t.name, b)
                b.assigned = True
                if st.op != "=":
                    self.use_name(t, scope, da)
                if da is not TOP and b.uninit:
                    da = set(da) | {id(b)}
                return da
            if t.__class__ is A.Field:
                return self.expr(t.obj, scope, da)
            if t.__class__ is A.Index:
                da = self.expr(t.obj, scope, da)
                for i in t.indices:
                    da = self.expr(i, scope, da)
                return da
            return da
        if c is A.ReturnStmt:
            if ctx.in_defer:
                self.err("S.SYNTAX.MISPLACED_CONSTRUCT", "`return` inside `defer` is not allowed", st.span)
            if ctx.kind in ("contract", "const"):
                self.err("S.SYNTAX.MISPLACED_CONSTRUCT", "`return` is not allowed here", st.span)
            if st.value is not None:
                self.expr(st.value, scope, da)
            return TOP
        if c in (A.BreakStmt, A.ContinueStmt):
            word = "break" if c is A.BreakStmt else "continue"
            if ctx.loop_depth == 0:
                self.err("S.SYNTAX.MISPLACED_CONSTRUCT", f"`{word}` outside a loop", st.span)
            if ctx.in_defer:
                self.err("S.SYNTAX.MISPLACED_CONSTRUCT", f"`{word}` inside `defer` is not allowed", st.span)
            return TOP
        if c is A.ThrowStmt:
            self.expr(st.value, scope, da)
            return TOP
        if c is A.DeferStmt:
            ctx.in_defer += 1
            try:
                if st.body.__class__ is A.Block:
                    self.block(st.body, scope, da)
                else:
                    self.expr(st.body, scope, da)
            finally:
                ctx.in_defer -= 1
            return da
        if c is A.OnAbandonStmt:
            if not ctx.provider or ctx.kind != "fn":
                self.err("S.RESOURCE.ON_ABANDON_RESTRICTED", "`onAbandon` is only allowed inside a resource provider",
                         st.span)
            return self.expr(st.call, scope, da)
        if c is A.NonlocalStmt:
            if ctx.kind not in ("lambda", "spawn"):
                self.err("S.NAME.NONLOCAL_INVALID", "`nonlocal` is only meaningful inside a closure", st.span)
            for n in st.names:
                b = scope.lookup(n)
                if b is None or b.module_level or b.level >= ctx.level:
                    self.err("S.NAME.NONLOCAL_INVALID", f"`{n}` is not a binding of an enclosing function", st.span)
                    continue
                if b.is_const:
                    self.err("S.NAME.CONST_REASSIGN", f"`{n}` is const and cannot be declared nonlocal", st.span)
                ctx.nonlocals.add(n)
                b.assigned = True
            return da
        if c is A.AssertStmt:
            da = self.expr(st.cond, scope, da)
            if st.message is not None:
                self.expr(st.message, scope, da)
            return da
        if c is A.WhileStmt:
            body_scope = Scope(scope, scope.level, "block")
            da2 = self.cond(st.cond, scope, body_scope, da)
            ctx.loop_depth += 1
            try:
                self.block(st.body, body_scope, da2, new_scope=False)
            finally:
                ctx.loop_depth -= 1
            return da
        if c is A.ForStmt:
            da = self.expr(st.iterable, scope, da)
            body_scope = Scope(scope, scope.level, "block")
            self.pattern(st.pattern, body_scope, "loop")
            if st.is_await and not ctx.is_async:
                self.err("S.ASYNC.AWAIT_OUTSIDE_ASYNC", "`for await` is only allowed in async functions", st.span)
            ctx.loop_depth += 1
            try:
                self.block(st.body, body_scope, da, new_scope=False)
            finally:
                ctx.loop_depth -= 1
            return da
        return da

    def type_params_in_scope(self) -> set:
        out = set()
        for c in getattr(self, "ctx_stack", []):
            d = c.decl
            if d is not None:
                out |= set(getattr(d, "type_params", []) or [])
        return out

    # ------------------------------------------------------------------ expressions
    def use_name(self, node: A.Name, scope: Scope, da) -> None:
        name = node.name
        b = scope.lookup(name)
        ctx = self.ctx
        if b is None:
            if name in ("result", "old") and ctx.kind == "contract":
                self.err("S.CONTRACT.RESULT_OUTSIDE_ENSURES" if name == "result" else "S.CONTRACT.OLD_OUTSIDE_ENSURES",
                         f"`{name}` is only available in `ensures` clauses", node.span)
                return
            self.unresolved(name, node.span, scope)
            return
        b.used = True
        node.ann["binding"] = b
        if b.init_span is not None:
            node.ann["init_span"] = b.init_span
        if not b.module_level and b.level < ctx.level:
            self.note_capture(name, b)
        if b.uninit and da is not TOP and id(b) not in da:
            self.obligation("S.NAME.UNINITIALISED",
                            f"`{name}` may be read before it is initialised", node.span, label="possibly uninitialised",
                            secondary=[Label(b.span, "declared without an initial value")],
                            help="assign it on every path before this read (the runtime abandons if it is unset)")

    def note_capture(self, name: str, b: Binding) -> None:
        for c in reversed(self.ctx_stack):
            if c.level <= b.level:
                break
            c.captures[name] = b

    def cond(self, e, scope: Scope, then_scope: Scope, da):
        """Resolve a condition; names bound by `is` patterns go into then_scope."""
        if e.__class__ is A.Is:
            da = self.expr(e.expr, scope, da)
            self.pattern(e.pattern, then_scope, "pattern")
            return da
        if e.__class__ is A.Binary and e.op == "&&" and any(isinstance(n, A.Is) for n in A.walk(e)):
            da = self.cond(e.left, scope, then_scope, da)
            mid = Scope(scope, scope.level, "block")
            mid.names.update(then_scope.names)
            da = self.cond(e.right, mid, then_scope, da)
            return da
        return self.expr(e, scope, da)

    def expr(self, e, scope: Scope, da):
        c = e.__class__
        ctx = self.ctx
        if c is A.Name:
            self.use_name(e, scope, da)
            return da
        if c is A.Literal:
            return da
        if c is A.StringLit:
            for p in e.parts:
                if isinstance(p, A.InterpPart):
                    da = self.expr(p.expr, scope, da)
            return da
        if c in (A.ListLit, A.TupleLit):
            for i in e.items:
                da = self.expr(i, scope, da)
            return da
        if c is A.MapLit:
            for k, v in e.entries:
                da = self.expr(k, scope, da)
                da = self.expr(v, scope, da)
            return da
        if c is A.Unary:
            return self.expr(e.operand, scope, da)
        if c is A.Binary:
            da = self.expr(e.left, scope, da)
            if e.op in ("&&", "||"):
                self.expr(e.right, scope, da)
                return da
            return self.expr(e.right, scope, da)
        if c is A.Range:
            da = self.expr(e.lo, scope, da)
            return self.expr(e.hi, scope, da)
        if c is A.Call:
            e.ann["marked"] = self.marked_depth() > 0
            if isinstance(e.callee, A.Name) and e.callee.name == "old" and scope.lookup("old") is None:
                if ctx.kind != "contract" or ctx.contract != "ensures":
                    self.err("S.CONTRACT.OLD_OUTSIDE_ENSURES", "`old(...)` is only allowed in `ensures` clauses",
                             e.span)
                for a in e.args:
                    da = self.expr(a.value, scope, da)
                return da
            da = self.expr(e.callee, scope, da)
            for a in e.args:
                da = self.expr(a.value, scope, da)
            return da
        if c is A.Index:
            da = self.expr(e.obj, scope, da)
            for i in e.indices:
                # A generic type parameter written as a type argument in value position,
                # e.g. `MutableList[T]()` (BUG-0011); it is erased at runtime (IMPL-006).
                if (i.__class__ is A.Name and scope.lookup(i.name) is None
                        and i.name in self.type_params_in_scope()):
                    i.ann["tparam"] = True
                    continue
                da = self.expr(i, scope, da)
            return da
        if c is A.Field:
            if isinstance(e.obj, A.Name):
                b = scope.lookup(e.obj.name)
                if b is not None and b.kind == "module":
                    self.check_module_member(b.target, e.name, e.name_span or e.span)
            return self.expr(e.obj, scope, da)
        if c is A.WithUpdate:
            da = self.expr(e.obj, scope, da)
            names = set()
            for n, v, sp in e.fields:
                if n in names:
                    self.err("S.NAME.DUPLICATE", f"field `{n}` updated twice", sp)
                names.add(n)
                da = self.expr(v, scope, da)
            return da
        if c is A.Lambda:
            self.lambda_(e, scope, da)
            return da
        if c is A.If:
            then_scope = Scope(scope, scope.level, "block")
            da1 = self.cond(e.cond, scope, then_scope, da)
            d_then = self.block(e.then, then_scope, da1, new_scope=False)
            if e.else_ is None:
                return self.meet(d_then, da1)
            if e.else_.__class__ is A.If:
                d_else = self.expr(e.else_, scope, da1)
            else:
                d_else = self.block(e.else_, scope, da1)
            return self.meet(d_then, d_else)
        if c is A.Match:
            da = self.expr(e.scrutinee, scope, da)
            result = TOP
            for arm in e.arms:
                s = Scope(scope, scope.level, "block")
                self.pattern(arm.pattern, s, "pattern")
                d = da
                if arm.guard is not None:
                    d = self.expr(arm.guard, s, d)
                if arm.body.__class__ is A.Block:
                    d = self.block(arm.body, s, d, new_scope=False)
                else:
                    d = self.expr(arm.body, s, d)
                result = self.meet(result, d)
            return result if e.arms else da
        if c is A.Is:
            da = self.expr(e.expr, scope, da)
            s = Scope(scope, scope.level, "block")
            self.pattern(e.pattern, s, "pattern")
            return da
        if c is A.As:
            self.resolve_type(e.type, scope, self.type_params_in_scope())
            return self.expr(e.expr, scope, da)
        if c is A.Try:
            self.marked_push()
            try:
                d_op = self.expr(e.expr, scope, da)
            finally:
                self.marked_pop()
            result = d_op
            for cl in e.catches:
                first = cl.path[0]
                b = scope.lookup(first)
                if b is None:
                    self.unresolved(first, cl.span, scope, as_type=True)
                else:
                    b.used = True
                s = Scope(scope, scope.level, "block")
                if cl.binding:
                    s.names[cl.binding] = Binding(cl.binding, "catch", cl, cl.span, scope.level, init_span=cl.span)
                if cl.handler.__class__ is A.Block:
                    d = self.block(cl.handler, s, da, new_scope=False)
                else:
                    d = self.expr(cl.handler, s, da)
                result = self.meet(result, d)
            if e.fallback is not None:
                d = self.expr(e.fallback, scope, da)
                result = self.meet(result, d)
            return result
        if c is A.Capture:
            self.marked_push()
            try:
                self.expr(e.expr, scope, da)
            finally:
                self.marked_pop()
            return da
        if c is A.Propagate:
            return self.expr(e.expr, scope, da)
        if c is A.Await:
            e.ann["marked"] = self.marked_depth() > 0
            if not ctx.is_async:
                self.err("S.ASYNC.AWAIT_OUTSIDE_ASYNC", "`await` is only allowed inside `async fn`", e.span,
                         help="mark the enclosing function `async fn` (only async functions may suspend)")
            return self.expr(e.expr, scope, da)
        if c is A.Yield:
            if not (ctx.kind == "fn" and ctx.provider):
                self.err("S.RESOURCE.YIELD_OUTSIDE_PROVIDER", "`yield` is only allowed in a `resource fn` body",
                         e.span, help="declare the provider as `resource fn name(...) yields T { ... }`")
            return self.expr(e.value, scope, da)
        if c is A.Use:
            da = self.expr(e.init, scope, da)
            s = Scope(scope, scope.level, "block")
            s.names[e.name] = Binding(e.name, "use", e, e.name_span or e.span, scope.level, is_const=True,
                                      init_span=e.init.span)
            self.block(e.body, s, da, new_scope=False)
            return da
        if c is A.Parallel:
            if not ctx.is_async:
                self.err("S.ASYNC.AWAIT_OUTSIDE_ASYNC", "`parallel` waits for its children and is only allowed in "
                         "async functions", e.span)
            ctx.parallel_depth += 1
            try:
                return self.block(e.body, scope, da)
            finally:
                ctx.parallel_depth -= 1
        if c is A.Spawn:
            if ctx.parallel_depth == 0:
                self.err("S.TASK.SPAWN_OUTSIDE_GROUP",
                         "`spawn` must appear lexically inside a `parallel` block of the same function", e.span,
                         help="wrap the spawns in `parallel { ... }` (or `parallel collect/race/firstSuccess`)")
            if e.call is not None:
                return self.expr(e.call, scope, da)
            inner = FnCtx("spawn", ctx.level + 1, is_async=True, decl=ctx.decl)
            s = Scope(scope, ctx.level + 1, "fn")

            def run():
                self.block(e.block, s, da, new_scope=False)
            self.with_ctx(inner, run)
            e.ann["captures"] = [(n, b.assigned) for n, b in inner.captures.items()]
            for n, b in inner.captures.items():
                self.note_capture(n, b)
            return da
        if c is A.Within:
            if not ctx.is_async:
                self.err("S.ASYNC.AWAIT_OUTSIDE_ASYNC", "`within` is only allowed in async functions", e.span)
            da = self.expr(e.deadline, scope, da)
            return self.block(e.body, scope, da)
        if c is A.Select:
            if e.mode != "now" and not ctx.is_async:
                self.err("S.ASYNC.AWAIT_OUTSIDE_ASYNC", "blocking `select` is only allowed in async functions",
                         e.span, help="use `select now { ... }` for a non-blocking check")
            result = TOP
            for br in e.branches:
                if br.guard is not None and br.guard not in ("true", "false"):
                    gb = scope.lookup(br.guard)
                    if gb is None:
                        self.unresolved(br.guard, br.guard_span, scope)
                    else:
                        gb.used = True
                for x in (br.target, br.value):
                    if x is not None:
                        self.expr(x, scope, da)
                s = Scope(scope, scope.level, "block")
                if br.binding:
                    s.names[br.binding] = Binding(br.binding, "pattern", br, br.span, scope.level, init_span=br.span)
                if br.body.__class__ is A.Block:
                    d = self.block(br.body, s, da, new_scope=False)
                else:
                    d = self.expr(br.body, s, da)
                result = self.meet(result, d)
            return result if e.branches else da
        return da

    def lambda_(self, e: A.Lambda, scope: Scope, da) -> None:
        ctx = self.ctx
        inner = FnCtx("lambda", ctx.level + 1, is_async=e.is_async, decl=ctx.decl)
        s = Scope(scope, ctx.level + 1, "fn")
        for p in e.params:
            if p.is_self:
                self.err("S.SYNTAX.MISPLACED_CONSTRUCT", "lambdas cannot take `self`", p.span)
                continue
            self.resolve_type(p.type, scope, self.type_params_in_scope())
            if p.name in s.names:
                self.err("S.NAME.DUPLICATE", f"parameter `{p.name}` declared twice", p.span)
            s.names[p.name] = Binding(p.name, "param", p, p.span, ctx.level + 1, init_span=p.span)
        self.resolve_type(e.ret, scope, self.type_params_in_scope())
        for t in e.throws or []:
            self.resolve_type(t, scope, self.type_params_in_scope())

        def run():
            if e.is_block:
                self.block(e.body, s, da, new_scope=False)
            else:
                self.expr(e.body, s, da)
        saved = self.marked_save()
        try:
            self.with_ctx(inner, run)
        finally:
            self.marked_restore(saved)
        e.ann["captures"] = [(n, b.assigned) for n, b in inner.captures.items()]
        e.ann["capture_bindings"] = list(inner.captures.values())
        for n, b in inner.captures.items():
            self.note_capture(n, b)

    # ------------------------------------------------------------------ patterns
    def pattern(self, p, scope: Scope, kind: str) -> None:
        c = p.__class__
        if c is A.BindPat:
            if p.type is not None:
                self.resolve_type(p.type, scope, self.type_params_in_scope())
            if p.name[:1].isupper():
                self.err("S.MATCH.INVALID_PATTERN",
                         f"`{p.name}` in a pattern binds a new variable (it does not match a case)", p.span,
                         help=f"qualify variant cases, e.g. `EnumName.{p.name}`; use a lowercase name for a binding")
            if p.name in scope.names:
                self.err("S.NAME.DUPLICATE", f"pattern binds `{p.name}` twice", p.span)
            scope.names[p.name] = Binding(p.name, kind, p, p.span, scope.level, init_span=p.span)
            return
        if c is A.CasePat:
            first = p.path[0]
            if not (len(p.path) == 1 and first in CORE_CASES):
                b = scope.lookup(first)
                if b is None:
                    self.unresolved(first, p.span, scope, as_type=True)
                else:
                    b.used = True
                    if b.kind == "module" and len(p.path) > 1:
                        self.check_module_member(b.target, p.path[1], p.span)
            for _, sub in p.args or []:
                self.pattern(sub, scope, kind)
            return
        if c is A.TuplePat:
            for i in p.items:
                self.pattern(i, scope, kind)
            return
        if c is A.OrPat:
            first_names = None
            for alt in p.alts:
                s = Scope(scope, scope.level, "block")
                self.pattern(alt, s, kind)
                names = set(s.names)
                if first_names is None:
                    first_names = names
                    for n, b in s.names.items():
                        scope.names[n] = b
                elif names != first_names:
                    self.err("S.MATCH.INVALID_PATTERN", "all alternatives of an or-pattern must bind the same names",
                             alt.span)
            return

    # ------------------------------------------------------------------ definite assignment helpers
    @staticmethod
    def meet(a, b):
        if a is TOP:
            return b
        if b is TOP:
            return a
        return a & b

    def marked_depth(self) -> int:
        return getattr(self, "_marked", 0)

    def marked_push(self):
        self._marked = self.marked_depth() + 1

    def marked_pop(self):
        self._marked = self.marked_depth() - 1

    def marked_save(self):
        v = self.marked_depth()
        self._marked = 0
        return v

    def marked_restore(self, v):
        self._marked = v


def resolve_program(program, mode: str) -> list[Diagnostic]:
    r = Resolver(program, mode)
    return r.run()
