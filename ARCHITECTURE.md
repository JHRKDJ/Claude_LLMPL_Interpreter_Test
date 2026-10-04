# ARCHITECTURE

Reference implementation of the V3 LLM-native language (`design/LLM_NATIVE_DESIGN_V3.md`)
as a Python 3.11 tree-walking interpreter with a gradual static checker. Zero runtime
dependencies; tests use `pytest`.

## Pipeline

```
source text ─► lang.source (SourceFile, Span)
           ─► lang.syntax.lexer (tokens + trivia)
           ─► lang.syntax.parser (AST with spans, error recovery)
           ─► lang.modules (manifest, module loading, imports, name resolution)
           ─► lang.check (gradual static checker: types, effects, exhaustiveness,
                          resources, async/tasks, sendability, contracts, modes)
                └─ annotates AST nodes with transient runtime checks (IMPL-004)
           ─► lang.runtime (evaluator + runtime subsystems)
lang.format     formatter (AST + trivia → canonical text)
lang.diagnostics structured diagnostics + text/JSON renderers (used by every stage)
lang.tooling    CLI (run/check/format/test/repl), test runner, REPL
```

## Packages and responsibilities (actual layout)

| Path | Responsibility |
|---|---|
| `lang/source.py` | `SourceFile`, `Span`, line/column mapping (leaf) |
| `lang/diagnostics/` | `model.py` (Diagnostic, Label, Note, Fix, TextEdit, provenance records), `codes.py` (stable code registry, `A/R/S/W/C/H.DOMAIN.REASON`), `render_text.py`, `render_json.py` |
| `lang/syntax/` | `tokens.py`, `lexer.py` (tokens, comments, string interpolation), `ast.py` (nodes with spans + `ann` slots), `parser.py` (recursive descent, newline-continuation contexts, recovery) |
| `lang/typesys.py` | Type terms shared by checker and runtime (`TPrim`, `TCon`, `TNominal`, `TFn`, `Effect`, …) and type-expression conversion |
| `lang/format/` | Canonical formatter (`__init__.py`) and structural AST equivalence (`equiv.py`) used as its safety net |
| `lang/modules/` | `project.py` (lang.toml / lang.lock), `loader.py` (module graph, import resolution, stdlib/native modules) |
| `lang/check/` | Static checking. `resolve.py` (scopes, bindings, captures, definite assignment, placement rules, import suggestions); `typecheck.py` (`Checker`: declarations, signatures, conformance, effect-inference fixpoint); mixins `walk.py` (function bodies, statements, effects collectors), `expr.py` (expressions, patterns, annotation origins), `callcheck.py` (calls, effects, try/capture/await, resources, tasks, sendability), `selectcheck.py`; `exhaustive.py` (usefulness algorithm), `contracts_check.py` (restricted contract language), `advisories.py` (state-horizon / invariant-across-await advisories), `types.py`, `decls.py` |
| `lang/runtime/` (core) | `values.py` (runtime values), `equality.py` (equality/hashing/ordering/display without Python coercions), `frozen.py`, `signals.py` (exit taxonomy), `core_types.py` (core errors, Option/Result, reports), `rtypes.py` (transient type checks, protocol shapes), `capture.py` (bounded redacting value capture), `isolation.py` (share / graph-copy / reject), `scheduler.py` (baton-passing coroutines, FIFO/seeded scheduling, real/virtual clock), `tasks.py` (tasks, cancel scopes, groups), `channels.py` |
| `lang/runtime/builtins/` | Native standard library and builtin method tables (`registry.py`), collections, strings, numbers, Option/Result, fs, json, math, time |
| `lang/runtime/interp/` | Evaluator assembled from mixins: `core.py` (Env, Frame, dispatch), `exprs.py`, `stmts.py` (defer/unwinding), `calls.py` (calls, contracts, invariants, effects, construction), `patterns.py`, `conc.py` (await/spawn/groups/within/deadlock), `res.py` (use/provider/borrow/release), `chan.py`, `selectx.py`, `link.py` (module linking, constants, conformance) |
| `lang/tooling/` | `cli.py` (run/check/format/test/repl/lock), `driver.py` (load → check → run), `testrunner.py`, `repl.py`, `fixes.py` (import fixes) |

## Allowed dependency directions

Enforced on the real import graph by `tests/unit/test_architecture.py`.

```
source
diagnostics            → source
syntax                 → source, diagnostics
typesys                → source, diagnostics, syntax
format, modules        → source, diagnostics, syntax, typesys
runtime (core)         → source, diagnostics, syntax, typesys
runtime.builtins       → + runtime core
runtime.interp         → + runtime core, runtime.builtins
check                  → + modules, runtime core, runtime.builtins   (metadata only; never runtime.interp)
tooling                → everything
```

The runtime never imports the checker, formatter or tooling: the checker communicates
with the runtime only through AST annotations (IMPL-004). No third-party runtime
dependencies.

## Key runtime design points

- **Exit taxonomy** (V3 5.6, 7.2.3): recoverable exceptions (`Thrown`), cancellation
  (`Cancelled`), abandonment (`Abandoned`) and hard termination are separate Python
  exception classes that do not share a catchable base; language `catch` only ever
  sees `Thrown`.
- **Unwinding** (V3 5.6, 7.8.6): on normal/exception/cancellation exits, `defer`
  callbacks and normal release run (cancellation masked), then postconditions and
  invariants; on abandonment only registered abandonment-safe releases run.
- **Scheduling** (V3 5.14.7-10, 7.14.5): deterministic FIFO by default; seeded random
  ready-task/select/receiver choice under `--schedule=random --seed=N`.
- **Isolation** (V3 5.11): every task boundary and channel commit classifies values:
  share frozen, graph-copy mutable, reject resources/borrows/unsafe capabilities.

## Large / complex components (living list)

- Parser with recovery and newline continuation rules.
- Static checker (gradual types + effects + exhaustiveness + resources + tasks).
- Task groups × cancellation × cleanup (`runtime/tasks.py`, `interp/conc.py`, `interp/stmts.py`).
- Select arbitration and channel commit protocol.
