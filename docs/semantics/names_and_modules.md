# Names, modules, imports and the manifest

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- One file is one module; explicit exports; two-level visibility (6.11, 7.4.1).
- Missing imports are diagnosed with candidates; tool edits are visible patches;
  new dependencies are never installed implicitly (2.4, 7.14.3, 8.19).
- Runtime value-initialisation cycles are rejected with the full cycle (6.11).
- No ordinary mutable module globals (5.2).

## 2. Operational interpretation
- Loader (`lang/modules/loader.py`): `import a.b.c` resolves against the project root,
  then `std.*` (native modules registered in `runtime/builtins`), then pinned
  dependencies from `lang.toml`. `a/b/mod.lang` is module `a.b`.
- Resolver (`lang/check/resolve.py`): lexical scopes, shadowing within one scope is a
  duplicate, `pub` controls cross-module visibility (`S.NAME.PRIVATE`), unresolved
  names are blocking errors in both modes with import candidates
  (`ProjectIndex`: project, stdlib, dependencies; a name equal to a known module
  suggests `import <module>`). `lang check --fix` applies only unambiguous
  candidates; `--diff` prints the patch instead.
- Unknown top-level package: `S.MODULE.UNKNOWN_DEPENDENCY` (help points at
  `lang.toml`); unknown module in a known root: `S.MODULE.NOT_FOUND`.
- Module constants are lazily initialised thunks; a dependency cycle among them is
  `S.MODULE.INIT_CYCLE` with the cycle path; a mutable value is
  `S.MODULE.MUTABLE_GLOBAL` (statically when the type is known, at link time otherwise).

## 3. Specification-stage choices
SPEC-020 (modules, `pub`, manifest, lockfile), AMB-010 (unresolved names block in draft).

## 4. Ambiguities
Declaration-level import cycles are allowed; only constant-initialiser cycles fail.

## 5. Interactions
- The REPL workspace is a module (`__repl__`); `:load` imports modules by name.
- Diagnostics carry fixes as `TextEdit`s (`diagnostics.md`).

## 6. Conformance tests
`tests/negative/test_static_errors.py` (name/module cases),
`tests/tooling/test_cli.py::test_check_fix_*`, `tests/conformance/test_functions_records.py`
(module constants), `tests/conformance/test_errors.py` (cross-module errors).
