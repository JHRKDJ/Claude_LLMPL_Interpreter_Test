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

## Packages and responsibilities

| Package | Responsibility | Notes |
|---|---|---|
| `lang/source.py` | Source files, spans, line/column mapping | leaf |
| `lang/diagnostics/` | `model.py` (Diagnostic, Label, Code, Note, provenance records), `codes.py` (stable code registry), `render_text.py`, `render_json.py` | never imports runtime/check |
| `lang/syntax/` | `tokens.py`, `lexer.py`, `ast.py` (node classes), `parser.py` (recursive descent + recovery) | |
| `lang/typesys.py` | Type terms shared by checker and runtime (Int, List[T], Fn(...), Record ref, effect sets) | depends on syntax AST only for type-expression conversion |
| `lang/format/` | Canonical formatter; comment/blank-line preservation | |
| `lang/modules/` | `project.py` (manifest/lockfile), `loader.py` (module graph, init cycles), `resolver.py` (scopes, bindings, captures, definite assignment), `autoimport.py` | |
| `lang/check/` | Gradual static checker split by concern: `types.py`, `expr.py`, `effects.py`, `exhaustive.py`, `contracts.py`, `resources.py`, `concurrency.py`, `protocols.py`, `modes.py` | does not import runtime |
| `lang/runtime/values.py` | Runtime value classes (frozen/mutable records, collections, variants, closures, handles) | |
| `lang/runtime/equality.py` | Structural equality, typed hash keys, ordering, display | no Python `==` leakage (1 == 1.0, True == 1) |
| `lang/runtime/signals.py` | Exit taxonomy as distinct internal signals: Return/Break/Continue, `Thrown` (recoverable), `Cancelled`, `Abandoned`, `HardTermination` | not one hierarchy (V3 7.2.3) |
| `lang/runtime/errors.py` | Error values, categories, `AggregateException`, Result provenance | |
| `lang/runtime/rtypes.py` | Transient runtime type checks, protocol shape checks, conformance table | |
| `lang/runtime/contracts.py` | Contract/invariant evaluation, `old` snapshots, value capture for failures | |
| `lang/runtime/capture.py` | Bounded, cycle-safe, redacting value representation for diagnostics | never calls user code |
| `lang/runtime/coro.py`, `scheduler.py`, `clock.py` | Baton-passing coroutines, deterministic/seeded scheduler, real/virtual clock | IMPL-001/002 |
| `lang/runtime/cancellation.py` | Cancel requests, masking, delivery points | |
| `lang/runtime/tasks.py` | Task groups (4 modes), handles, observation, outcomes, reports | |
| `lang/runtime/isolation.py` | Sendability classification and graph copy | |
| `lang/runtime/channels.py` | Channels, ports, holder tracking, broadcast | |
| `lang/runtime/select.py` | Select arbitration, fairness cursors, ring buffer | |
| `lang/runtime/resources.py` | Use scopes, providers, borrows, release registration, cleanup combination | |
| `lang/runtime/interp/` | Evaluator: `core.py` (dispatch, env), `exprs.py`, `stmts.py`, `calls.py`, `patterns.py`, `exits.py` (defer/unwinding) | top of runtime |
| `lang/runtime/builtins/` | Native standard library: core, collections, strings, math, fs, json, time, cancel | |
| `lang/stdlib/*.lang` | Library code written in the language | |
| `lang/tooling/` | `cli.py`, `driver.py` (load→check→run), `testrunner.py`, `repl.py` | top |

## Allowed dependency directions

Lower layers never import higher layers. Enforced by `tests/unit/test_architecture.py`.

```
L0  source
L1  diagnostics            → L0
L2  syntax, typesys        → L0..L1
L3  format, modules        → L0..L2
L4  check                  → L0..L3          (never runtime)
L4  runtime                → L0..L3          (never check)
L5  tooling                → everything
```

Inside `runtime`: `values/equality/signals/errors/capture` → `rtypes/contracts/isolation`
→ `coro/scheduler/clock/cancellation` → `tasks/channels/resources` → `select` →
`interp` → `builtins` (builtins may import interp-facing helper protocols only via
`runtime/native.py`).

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
- Task groups × cancellation × cleanup (`tasks.py`, `interp/exits.py`).
- Select arbitration and channel commit protocol.
