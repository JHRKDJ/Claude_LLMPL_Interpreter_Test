"""Layering rules from ARCHITECTURE.md, enforced on the actual import graph.

Units: source, diagnostics, syntax, typesys, format, modules, check, runtime.core
(lang/runtime/*.py), runtime.builtins, runtime.interp, tooling."""
import ast
from pathlib import Path

LANG = Path(__file__).resolve().parents[2] / "lang"

LOWER = {"source", "diagnostics", "syntax", "typesys"}
ALLOWED = {
    "source": set(),
    "diagnostics": {"source"},
    "syntax": {"source", "diagnostics"},
    "typesys": {"source", "diagnostics", "syntax"},
    "format": LOWER,
    "modules": LOWER,
    "runtime.core": LOWER,
    "runtime.builtins": LOWER | {"runtime.core"},
    "runtime.interp": LOWER | {"runtime.core", "runtime.builtins"},
    # the checker reads runtime *metadata* (builtin registry, core types) but never the evaluator
    "check": LOWER | {"modules", "runtime.core", "runtime.builtins"},
    "tooling": LOWER | {"format", "modules", "check", "runtime.core", "runtime.builtins", "runtime.interp"},
    "lang": set(),
}


def unit_of(path: Path) -> str:
    parts = path.relative_to(LANG).with_suffix("").parts
    if parts == ("__init__",) or parts == ("__main__",):
        return "lang"
    if parts[0] == "runtime":
        if len(parts) > 2 and parts[1] in ("interp", "builtins"):
            return "runtime." + parts[1]
        return "runtime.core"
    if parts[0] in ("source", "typesys"):
        return parts[0]
    return parts[0]


def resolve(path: Path, node: ast.ImportFrom):
    pkg = path.parent if path.name != "__init__.py" else path.parent
    base = pkg
    for _ in range(node.level - 1):
        base = base.parent
    targets = []
    mods = [node.module] if node.module else [a.name for a in node.names]
    for m in mods:
        t = base.joinpath(*m.split("."))
        for cand in (t.with_suffix(".py"), t / "__init__.py"):
            if cand.exists():
                targets.append(cand)
                break
    return targets


def edges():
    out = []
    for p in LANG.rglob("*.py"):
        if p.name == "__main__.py":  # script entry point: absolute import of the CLI
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.ImportFrom) and n.level > 0:
                for t in resolve(p, n):
                    a, b = unit_of(p), unit_of(t)
                    if a != b and b != "lang":
                        out.append((a, b, p.relative_to(LANG), n.lineno))
            elif isinstance(n, ast.Import) or (isinstance(n, ast.ImportFrom) and n.level == 0):
                names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
                for nm in names:
                    assert not nm.startswith("lang."), f"{p}: use relative imports inside lang ({nm})"
    return out


def test_layering_respected():
    bad = [f"{f}:{line}: {a} -> {b}" for a, b, f, line in edges() if b not in ALLOWED[a]]
    assert not bad, "\n".join(bad)


def test_runtime_never_imports_checker_or_formatter():
    assert not [e for e in edges() if e[0].startswith("runtime") and e[1] in ("check", "format", "tooling")]


def test_no_third_party_runtime_dependencies():
    import sys
    std = set(sys.stdlib_module_names) | {"lang"}
    for p in LANG.rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Import):
                for a in n.names:
                    assert a.name.split(".")[0] in std, f"{p}: {a.name}"
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                assert n.module.split(".")[0] in std | {"__future__"}, f"{p}: {n.module}"
