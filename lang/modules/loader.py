"""Module graph loading (V3 6.11, 7.4.1; SPEC-020).

One file is one module. Module `a.b.c` resolves to `<root>/a/b/c.lang`, or to the
directory module `<root>/a/b/c/mod.lang`. `std.*` names the standard library
(native modules implemented in Python plus `.lang` files under lang/stdlib/).
A first path segment naming a pinned dependency resolves inside that dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..diagnostics import Diagnostic, Label, code
from ..source import SourceFile, Span
from ..syntax import ast as A
from ..syntax.parser import parse_source
from .project import Project, load_project

STDLIB_DIR = Path(__file__).resolve().parent.parent / "stdlib"
# Native standard-library modules (implemented in lang/runtime/builtins).
NATIVE_STD = {"std.fs", "std.json", "std.math", "std.strings", "std.time", "std.text"}


@dataclass
class ModuleSource:
    name: str
    path: Optional[Path]
    file: Optional[SourceFile]
    ast: Optional[A.Module]
    native: bool = False
    is_std: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)
    comments: list = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # resolved module names


@dataclass
class ProgramSource:
    project: Project
    entry: str
    modules: dict[str, ModuleSource] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def parse_ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics) and not any(
            d.severity == "error" for m in self.modules.values() for d in m.diagnostics)

    def all_diagnostics(self) -> list[Diagnostic]:
        out = list(self.diagnostics)
        for m in self.modules.values():
            out.extend(m.diagnostics)
        return out


def module_name_for(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = Path(path.name)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "mod" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


class Loader:
    def __init__(self, project: Project):
        self.project = project
        self.modules: dict[str, ModuleSource] = {}
        self.diagnostics: list[Diagnostic] = []

    def locate(self, name: str) -> Optional[Path]:
        parts = name.split(".")
        if parts[0] == "std":
            base = STDLIB_DIR
            parts = parts[1:]
        elif parts[0] in self.project.dependencies:
            base = self.project.dependencies[parts[0]].path
            parts = parts[1:]
        else:
            base = self.project.root
        if not parts:
            cand = base / "mod.lang"
            return cand if cand.exists() else None
        f = base.joinpath(*parts).with_suffix(".lang")
        if f.exists():
            return f
        d = base.joinpath(*parts) / "mod.lang"
        if d.exists():
            return d
        return None

    def load_file(self, path: Path, name: str, text: Optional[str] = None) -> ModuleSource:
        if name in self.modules:
            return self.modules[name]
        if text is None:
            text = path.read_text(encoding="utf-8")
        sf = SourceFile(str(path), text, module_name=name)
        pr = parse_source(sf)
        ms = ModuleSource(name=name, path=path, file=sf, ast=pr.module, diagnostics=list(pr.diagnostics),
                          comments=pr.comments, is_std=name.startswith("std."))
        self.modules[name] = ms
        for imp in pr.module.imports:
            target = self.resolve_import(imp, ms)
            if target is not None:
                ms.imports.append(target)
        return ms

    def resolve_import(self, imp: A.Import, importer: ModuleSource) -> Optional[str]:
        """Returns the module name an import refers to, loading it; emits diagnostics."""
        full = ".".join(imp.path)
        # `import a.b.c` -> module a.b.c ; `import a.b.{x}` -> module a.b
        candidates = [full]
        if full in self.modules:
            return full
        if full in NATIVE_STD:
            self.modules.setdefault(full, ModuleSource(name=full, path=None, file=None, ast=None, native=True,
                                                       is_std=True))
            return full
        path = self.locate(full)
        if path is not None:
            self.load_file(path, full)
            return full
        first = imp.path[0]
        if first != "std" and first not in self.project.dependencies and not (self.project.root / first).exists():
            msg = f"module `{full}` not found: `{first}` is not part of this project, the standard library, or a pinned dependency"
            stable = "S.MODULE.UNKNOWN_DEPENDENCY"
            help_ = ("new external dependencies must be added explicitly to lang.toml [dependencies] and lang.lock; "
                     "the toolchain never installs packages from an unresolved name")
        else:
            msg = f"module `{full}` not found"
            stable = "S.MODULE.NOT_FOUND"
            help_ = None
        d = Diagnostic(code(stable), msg, primary=Label(imp.span, "unresolved import"))
        if help_:
            d.help.append(help_)
        sugg = self.suggest_modules(full)
        if sugg:
            d.help.append("similar modules: " + ", ".join(f"`{s}`" for s in sugg))
        importer.diagnostics.append(d)
        del candidates
        return None

    def suggest_modules(self, name: str) -> list[str]:
        import difflib
        known = list(NATIVE_STD) + [f"std.{p.stem}" for p in STDLIB_DIR.glob("*.lang")]
        for p in self.project.root.rglob("*.lang"):
            if any(part.startswith(".") for part in p.parts):
                continue
            known.append(module_name_for(p, self.project.root))
        return difflib.get_close_matches(name, known, n=3, cutoff=0.6)


def load_program(entry_path: str | Path, project: Optional[Project] = None,
                 text: Optional[str] = None) -> ProgramSource:
    entry = Path(entry_path)
    if project is None:
        project = load_project(entry)
    loader = Loader(project)
    if text is None and not entry.exists():
        prog = ProgramSource(project=project, entry="")
        sf = SourceFile(str(entry), "")
        prog.diagnostics.append(Diagnostic(code("S.MODULE.NOT_FOUND"), f"file `{entry}` does not exist",
                                           primary=Label(Span(sf, 0, 0))))
        return prog
    name = module_name_for(entry, project.root) or "main"
    loader.load_file(entry, name, text=text)
    prog = ProgramSource(project=project, entry=name, modules=loader.modules, diagnostics=loader.diagnostics)
    for p in project.problems:
        sf = SourceFile(str(project.manifest_path or entry), "")
        prog.diagnostics.append(Diagnostic(code("S.MODULE.MANIFEST"), p, primary=Label(Span(sf, 0, 0))))
    return prog
