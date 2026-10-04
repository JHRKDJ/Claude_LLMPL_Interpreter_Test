# FEATURE MATRIX (derived from a complete read of V3)

Columns: **V3** = V3 decision status; **§** = V3 section; **Impl** = implementation
location; **Tests** = conformance / negative / interaction test locations;
**State** ∈ NOT_STARTED, IN_PROGRESS, IMPLEMENTED, VERIFYING, COMPLETE,
BLOCKED_BY_REAL_DESIGN_CONFLICT; deferred/rejected rows are tracked so their
absence can be verified. Work items are in `WORK_ITEMS.json`.

Abbreviations: D = Decided, DD = Decided direction, P = Provisional, SS =
Specification-stage, OD = Open detail, DEF = Deferred, REJ = Rejected.

## 1. Syntax and source (V3 4.x, 6.1, 7.1)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| SYN-01 | Brace-delimited blocks; indentation not significant | D | 6.1, 7.1.1 | | | NOT_STARTED | |
| SYN-02 | Newline statements + continuation rules; clear diagnostics over aggressive continuation | DD | 7.1.2 | | | NOT_STARTED | SPEC-001 |
| SYN-03 | `fn`, explicit `self`, postfix optional return annotation | DD | 6.1, 7.1.4 | | | NOT_STARTED | SPEC-004 |
| SYN-04 | `async fn`; only async functions suspend | D | 6.1, 7.10.2 | | | NOT_STARTED | |
| SYN-05 | Unicode strings, brace interpolation, escaping, format modifiers, safe display | DD | 7.1.5 | | | NOT_STARTED | SPEC-009 |
| SYN-06 | Lambdas: expression + block forms, effect annotations | DD | 7.1.6 | | | NOT_STARTED | SPEC-004 |
| SYN-07 | Keyword priors (fn, spawn, await, match, try, pub, use, let, mutable record, requires/ensures) | SS | 7.1.3 | | | NOT_STARTED | DECISIONS §A |
| SYN-08 | Expression-oriented blocks (if/match/use/select) | DD | 7.2.1 | | | NOT_STARTED | SPEC-004 |
| SYN-09 | Left-to-right evaluation; args before call | DD | 7.2.2 | | | NOT_STARTED | |

## 2. Values and data model (V3 5.1, 6.2, 7.3)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| VAL-01 | Int arbitrary precision; Float binary64; Bool non-coercing; Str immutable Unicode; Unit | DD | 6.2, 7.3.3 | | | NOT_STARTED | |
| VAL-02 | NaN policy | SS/P | 7.3.3, 9.3#25 | | | NOT_STARTED | SPEC-010 provisional |
| VAL-03 | Frozen records transitively frozen, structural equality, no identity | D | 5.1.1-3, 7.3.1 | | | NOT_STARTED | |
| VAL-04 | Mutable records identity-bearing | D | 5.1.2, 7.3.1 | | | NOT_STARTED | AMB-007 |
| VAL-05 | Type-level mutability (no per-instance switch) | D | 5.1.4 | | | NOT_STARTED | |
| VAL-06 | Frozen updates produce new values (`with`) | D | 5.1.6, 7.3.1 | | | NOT_STARTED | SPEC-006 |
| VAL-07 | Frozen collections (persistent) + mutable collections; sequence/map/set | D sem | 7.3.2 | | | NOT_STARTED | SPEC-008 |
| VAL-08 | freeze() / mutableCopy() snapshot isolation | D | 5.1.7 | | | NOT_STARTED | |
| VAL-09 | Map/set iteration order specified | DD | 7.3.2 | | | NOT_STARTED | insertion order |
| VAL-10 | Structural equality and hashing incl. nested collections/variants | DD | 7.3.1 | | | NOT_STARTED | |
| VAL-11 | Closed nominal variants | D | 6.2, 3.3 | | | NOT_STARTED | SPEC-007 |
| VAL-12 | Option: `T?` = Option[T], `null` = None, no raw null | D | 5.4, 7.3.4 | | | NOT_STARTED | |
| VAL-13 | Result[T,E] core type | D | 7.3.4 | | | NOT_STARTED | |
| VAL-14 | Str indexing/normalisation defined | DD | 7.3.3 | | | NOT_STARTED | code points, no implicit normalisation |
| VAL-15 | No class inheritance | D | 2.2 | | | NOT_STARTED | verify absence |

## 3. Bindings, state, scope, closures (V3 5.1.5, 5.2, 6.3, 7.4)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| BND-01 | Reassignable bindings; rebinding distinct from mutation | D sem | 5.1.5 | | | NOT_STARTED | SPEC-002 |
| BND-02 | Optional constant binding | SS | 6.3 | | | NOT_STARTED | `const` |
| BND-03 | Frozen module constants; mutable module globals prohibited | D | 5.2, 7.4.2 | | | NOT_STARTED | |
| BND-04 | Uninitialised binding state; no use before initialisation | D/DD | 5.4.3, 6.3 | | | NOT_STARTED | |
| BND-05 | Closures capture lexical bindings; reassignment marker | DD/P | 7.4.3 | | | NOT_STARTED | SPEC-003 |
| BND-06 | State-horizon advisories | P | 7.3.5 | | | NOT_STARTED | heuristic |

## 4. Types and annotations (V3 5.3, 6.4, 7.6)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| TYP-01 | Dynamic default, strong, non-coercing | D | 5.3.1, 5.3.4 | | | NOT_STARTED | |
| TYP-02 | Written annotations runtime-enforced in both modes | D | 5.3.2-3 | | | NOT_STARTED | |
| TYP-03 | Concrete record annotation nominal | D | 5.3.5 | | | NOT_STARTED | |
| TYP-04 | Protocol annotation: immediate shallow shape/effect check | D | 5.3.6, 7.5.2 | | | NOT_STARTED | |
| TYP-05 | Transient checks of nested/generic contents at typed uses/writes | D | 5.3.7, 7.6.3 | | | NOT_STARTED | IMPL-004 |
| TYP-06 | Return values checked before leaving | D | 5.3.8 | | | NOT_STARTED | |
| TYP-07 | Dynamic mismatch = abandonment with boundary/annotation/origin diagnostics | D | 5.3.9, 5.3.12, 7.6.5 | | | NOT_STARTED | |
| TYP-08 | Dynamic callables narrowed before verified invocation | D | 5.3.10, 7.7.6 | | | NOT_STARTED | |
| TYP-09 | Dynamic values not sendable by default; inspection | D | 5.3.11, 7.6.6 | | | NOT_STARTED | |
| TYP-10 | Generics: collections, variants, Results, tasks, channels, effects | DD | 6.4 | | | NOT_STARTED | |
| TYP-11 | `Dyn` spelling | SS | 5.3.1 | | | NOT_STARTED | SPEC-005 |
| TYP-12 | Verified: static validation of resolvable annotations | D | 7.6.4 | | | NOT_STARTED | |
| TYP-13 | Exported interface annotations required | DD | 7.1.4 | | | NOT_STARTED | verified only |
| TYP-14 | Frozen verified values may skip repeated checks | P | 9.2 | | | NOT_STARTED | optimisation; may stay unimplemented with rationale |

## 5. Functions, protocols, contracts (V3 5.10, 6.5, 7.5, 7.8)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| FN-01 | Parameters; argument passing by value category | DD | 6.5, 7.2.2 | | | NOT_STARTED | |
| FN-02 | Methods with explicit self | DD | 6.5 | | | NOT_STARTED | |
| PRO-01 | Structural protocol conformance; optional `satisfies` | DD/P | 6.2, 7.5.1 | | | NOT_STARTED | AMB-001 |
| PRO-02 | Protocol contracts inherited, checked on every invocation | D | 5.10.8, 5.10.11 | | | NOT_STARTED | AMB-001 |
| PRO-03 | Implementations cannot add public preconditions | D | 5.10.9, 7.8.5 | | | NOT_STARTED | |
| PRO-04 | Implementation postconditions supplement | D | 5.10.10 | | | NOT_STARTED | |
| PRO-05 | Structural conformance does not imply sendability | D | 8.9 | | | NOT_STARTED | |
| CON-01 | requires/ensures in signatures, executable | D | 5.10.1-2 | | | NOT_STARTED | |
| CON-02 | Restricted contract-expression language | D | 5.10.3, 7.8.2 | | | NOT_STARTED | AMB-009 |
| CON-03 | Non-recursive predicates calling only predicates | D | 5.10.4 | | | NOT_STARTED | |
| CON-04 | old(expr) legality by captured result | D | 5.10.5, 7.8.3 | | | NOT_STARTED | |
| CON-05 | Record invariants; controlled mutation of invariant fields | DD/SS | 5.10.6-7, 7.8.4 | | | NOT_STARTED | SPEC-014 |
| CON-06 | Exit ordering: save, cleanup, post/invariants; invariant failure supersedes | D | 5.10.12-14, 7.8.6 | | | NOT_STARTED | |
| CON-07 | Violation always abandonment | D | 5.10.15 | | | NOT_STARTED | |

## 6. Errors, Results, effects (V3 5.7-5.9, 6.6, 7.7)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| ERR-01 | Distinct failure classes (recoverable, cancellation, abandonment, hard, catastrophic) | D | 5.6, 6.6, 7.2.3 | | | NOT_STARTED | |
| ERR-02 | Declared throws sets; try marker in verified; draft still propagates | D | 3.2, 5.15.3, 7.7.3 | | | NOT_STARTED | AMB-005 |
| ERR-03 | Concrete nominal errors; zero-or-one category; closed error enums | D | 5.9, 7.7.7 | | | NOT_STARTED | SPEC-011 |
| ERR-04 | Catch by type/category; no broad catch-all | D | 5.7.5, 7.7.3 | | | NOT_STARTED | |
| ERR-05 | Typed fallback; unqualified fallback only for one known type | D | 5.7.5 | | | NOT_STARTED | |
| ERR-06 | Result for stored failure; cannot both throw and return Result | D | 5.7.2-3, 7.7.4 | | | NOT_STARTED | |
| ERR-07 | Explicit throw↔Result conversion | SS | 5.7.4 | | | NOT_STARTED | SPEC-012 |
| ERR-08 | Err provenance: type, code, creation span, propagation chain, task lineage, bounded context | D | 7.7.8 | | | NOT_STARTED | |
| ERR-09 | Minimal effect polymorphism: error-set variables, unions, forwarding | D | 5.8, 7.7.5, 8.3 | | | NOT_STARTED | SPEC-013 |
| ERR-10 | Checked alternatives for expected branches | DD | 5.7.8, 7.7.2 | | | NOT_STARTED | |
| ERR-11 | Top-level unhandled exception: cleanup, diagnostic, failure exit, not abandonment | D | 5.7.10, 7.7.9 | | | NOT_STARTED | |
| ERR-12 | AggregateException: general non-empty aggregate with provenance | D | 5.6, 7.9.8 | | | NOT_STARTED | |
| ERR-13 | Abandonment uncatchable in failed task | D | 5.6.4, 6.6 | | | NOT_STARTED | |
| ERR-14 | Hard termination escalation | DD | 5.6.5, 7.10.11 | | | NOT_STARTED | |
| ERR-15 | Catching category does not make open set exhaustive | D | 5.9.6 | | | NOT_STARTED | |
| ERR-16 | Multiple category membership | DEF | 5.9.5 | — | — | DEFERRED | runtime stores categories as a tuple so later extension is not foreclosed |

## 7. Resources and cleanup (V3 5.5, 5.6, 6.7, 7.9)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| RES-01 | Resource providers: acquire, exactly one yield, release, abandonment registration | D | 5.5.3, 7.9.2 | | | NOT_STARTED | IMPL-003 |
| RES-02 | Providers callable only as scope initialisers | D | 5.5.4 | | | NOT_STARTED | |
| RES-03 | Resource values cannot be bound/returned/stored/captured/sent/passed to tasks | D | 5.5.5 | | | NOT_STARTED | |
| RES-04 | Expression-valued scopes; release can change outward outcome | D | 5.5.6, 7.9.5 | | | NOT_STARTED | |
| RES-05 | Borrows: non-escaping, same-task, may cross await | D | 5.5.7-8, 7.9.4 | | | NOT_STARTED | |
| RES-06 | Normal release on return/exception/cancellation; knows exit class; no suppression | D | 5.5.9 | | | NOT_STARTED | |
| RES-07 | Abandonment-safe release only, restricted actions/inputs | D | 5.5.10-12 | | | NOT_STARTED | |
| RES-08 | Release failure during abandonment appended diagnostically | D | 5.5.13 | | | NOT_STARTED | |
| RES-09 | `defer` non-resource cleanup, not on abandonment, LIFO, async under masking | D | 5.6, 7.9.6 | | | NOT_STARTED | SPEC-016 |
| RES-10 | Cleanup-failure combination table | D | 5.6 | | | NOT_STARTED | |
| RES-11 | Scope-width advisories | P | 7.9.7 | | | NOT_STARTED | best-effort |
| RES-12 | No structural Closeable/RAII | REJ | 6.14, 9.5 | — | | NOT_STARTED | verify absence |
| RES-13 | Resource-owning records | DEF | 5.5.14 | — | — | DEFERRED | |

## 8. Structured concurrency and cancellation (V3 5.12, 6.8, 7.10)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| TSK-01 | Structured task groups; no fire-and-forget | D | 6.8, 7.10.1 | | | NOT_STARTED | AMB-008 |
| TSK-02 | One substrate, four modes: fail-fast, collect-all, race, first-success | D | 5.12.1 | | | NOT_STARTED | SPEC-017 |
| TSK-03 | Quiescence before exit | D | 5.12.2, 7.10.3 | | | NOT_STARTED | |
| TSK-04 | Stable handles; await exposes concrete exception | D | 5.12.3, 7.10.9 | | | NOT_STARTED | |
| TSK-05 | Observation: caught/captured not re-reported; unhandled/unawaited aggregated once | D | 5.12.4-5, 8.10 | | | NOT_STARTED | AMB-002 |
| TSK-06 | Fail-fast: AggregateException even for one child | D | 7.10.4 | | | NOT_STARTED | |
| TSK-07 | Child abandonment dominates fail-fast/race/first-success; TaskGroupFailure | D | 5.12.6, 5.12.9 | | | NOT_STARTED | |
| TSK-08 | Collect-all returns TaskGroupReport including abandonment as data | D | 5.12.7-8, 7.10.5 | | | NOT_STARTED | |
| TSK-09 | Race | D | 7.10.6 | | | NOT_STARTED | |
| TSK-10 | First-success | D | 7.10.7 | | | NOT_STARTED | |
| TSK-11 | Lexical task tree preserved; flattened views | D | 5.12.10 | | | NOT_STARTED | |
| TSK-12 | External cancellation + child failure both preserved | D | 5.12.11, 8.11 | | | NOT_STARTED | |
| TSK-13 | Diagnostic ordering by task path, not arrival time | D | 7.10.3 | | | NOT_STARTED | |
| CAN-01 | Cooperative cancellation at visible points; `cancel.check()` | D | 7.10.2 | | | NOT_STARTED | AMB-004 |
| CAN-02 | Cancellation not catchable/discardable | D | 5.7.9, 7.10.11 | | | NOT_STARTED | |
| CAN-03 | Cleanup masking + redelivery | D | 6.8 | | | NOT_STARTED | |
| CAN-04 | Invariants checked before cancellation leaves operation | D | 6.8, 8.8 | | | NOT_STARTED | |
| CAN-05 | Stuck-cleanup diagnostic; hard-termination escalation | DD | 7.10.11 | | | NOT_STARTED | |
| CAN-06 | Verified reports async regions without cancellation points | D | 5.15.6 | | | NOT_STARTED | |
| CAN-07 | `within deadline` structured timeout | DD ("may") | 7.12.9 | | | NOT_STARTED | SPEC-017 |

## 9. Isolation / sendability (V3 5.11, 7.10.10)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| ISO-01 | Classification before child start/message commit | D | 5.11 | | | NOT_STARTED | |
| ISO-02 | Share frozen; graph-copy mutable; reject resources/borrows/unsafe | D | 5.11 | | | NOT_STARTED | |
| ISO-03 | Graph copy preserves cycles/aliases, no alias back | D | 5.11, 7.10.10 | | | NOT_STARTED | |
| ISO-04 | Closures: sendable captures share; mutable captures reject | D | 5.11, 7.4.3 | | | NOT_STARTED | SPEC-003 |
| ISO-05 | Ports share as frozen capabilities; controller retained; handles scoped | D/SS | 5.11 | | | NOT_STARTED | AMB-006 |
| ISO-06 | Dynamic values: runtime graph inspection | D | 5.11, 8.2 | | | NOT_STARTED | |
| ISO-07 | Large-copy advisories | DD | 5.11, 7.10.10 | | | NOT_STARTED | |
| ISO-08 | No user copy hooks | D/DEF | 7.10.10, 9.4 | — | | NOT_STARTED | verify absence |

## 10. Channels (V3 5.13, 6.9, 7.11)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| CHN-01 | MPMC competing-consumer, exactly-once delivery | D | 5.13.1-2 | | | NOT_STARTED | |
| CHN-02 | Controller + send/receive ports; ports frozen sendable duplicable | D sem | 5.13.4-5, 7.11.2 | | | NOT_STARTED | SPEC-018 |
| CHN-03 | Capacities: rendezvous (default), buffered(n), unbounded | D | 5.13.6-8 | | | NOT_STARTED | |
| CHN-04 | Closure permanent; endpoint loss distinctions | D | 5.13.9-11 | | | NOT_STARTED | AMB-006 |
| CHN-05 | Blocking ops cancellation points; commit atomicity | D | 5.13.12-13 | | | NOT_STARTED | |
| CHN-06 | Nonblocking try operations | DD | 6.9 | | | NOT_STARTED | |
| CHN-07 | Same-task order; global commit sequence | D | 5.13.14 | | | NOT_STARTED | |
| CHN-08 | Mutable messages copied once after reservation, before commit | D | 5.13.15, 7.11.8, 8.12 | | | NOT_STARTED | |
| CHN-09 | Diagnostic event history unavailable to program | DD | 5.13.16, 7.11.5 | | | NOT_STARTED | |
| CHN-10 | Broadcast, frozen-only | DD | 5.13.3 | | | NOT_STARTED | |
| CHN-11 | FIFO waiter queues; cancellation removes waiter | P | 5.14.18, 7.11.7 | | | NOT_STARTED | |
| CHN-12 | Unbounded growth advisories | DD | 5.13.8 | | | NOT_STARTED | |
| CHN-13 | Mutable broadcast | DEF | 9.4 | — | — | DEFERRED | |

## 11. Selection (V3 5.14, 6.10, 7.12)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| SEL-01 | Participants: send, receive, task completion, deadline, closure outcome | D | 5.14.1 | | | NOT_STARTED | |
| SEL-02 | No arbitrary async branches | D | 5.14.2 | | | NOT_STARTED | |
| SEL-03 | Static branch syntax, expression-valued | DD | 5.14.3 | | | NOT_STARTED | SPEC-019 |
| SEL-04 | Pure/precomputed branch setup | D | 5.14.4 | | | NOT_STARTED | |
| SEL-05 | Atomic single commit; losers no effect | D | 5.14.5-6 | | | NOT_STARTED | |
| SEL-06 | Rotating fairness cursor per site/activation; N-bound | DD/P | 5.14.7-8 | | | NOT_STARTED | |
| SEL-07 | Priority form + starvation diagnostics | D | 5.14.9 | | | NOT_STARTED | |
| SEL-08 | Seeded randomisation in stress mode only | D | 5.14.10 | | | NOT_STARTED | |
| SEL-09 | Select cancellation semantics | D | 5.14.11 | | | NOT_STARTED | |
| SEL-10 | Selecting a task doesn't cancel others | D | 5.14.12 | | | NOT_STARTED | |
| SEL-11 | No default branch; `select now` with none-ready | D | 5.14.13 | | | NOT_STARTED | |
| SEL-12 | Absolute deadlines; relative sugar; reset diagnostics | D | 5.14.14, 8.16 | | | NOT_STARTED | |
| SEL-13 | Guards: precomputed frozen booleans, read once | D | 5.14.15, 8.17 | | | NOT_STARTED | |
| SEL-14 | Closed outcomes explicit; loop warnings | D | 5.14.16, 8.13 | | | NOT_STARTED | |
| SEL-15 | Dynamic homogeneous helpers | DD | 5.14.17, 7.12.13 | | | NOT_STARTED | |
| SEL-16 | Endpoint FIFO waiter queues | P | 5.14.18 | | | NOT_STARTED | |
| SEL-17 | Bounded selection event ring buffer | DD | 5.14.19, 7.12.14 | | | NOT_STARTED | |
| SEL-18 | Dynamic heterogeneous selection | DEF | 9.4 | — | — | DEFERRED | |
| SEL-19 | Numeric priorities | DEF | 9.4 | — | — | DEFERRED | |

## 12. Draft/verified modes (V3 5.15, 7.6.4)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| MOD-01 | Manifest default mode + CLI override | D | 5.15.1 | | | NOT_STARTED | |
| MOD-02 | Draft accepts incomplete source; diagnoses obligations | D | 5.15.2 | | | NOT_STARTED | |
| MOD-03 | Unmarked throwing call still propagates in draft | D | 5.15.3 | | | NOT_STARTED | |
| MOD-04 | Runtime safety rules active in draft | D | 5.15.4 | | | NOT_STARTED | |
| MOD-05 | Verified static obligations | D | 5.15.5 | | | NOT_STARTED | |
| MOD-06 | Release requires verified | D | 5.15.7 | | | NOT_STARTED | |
| MOD-07 | Modes do not change meaning | D | 5.15.8 | | | NOT_STARTED | |

## 13. Modules and imports (V3 2.4, 5.16, 6.11, 7.4.1, 8.19)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| MDL-01 | One file one module; directory modules | D/SS | 6.11 | | | NOT_STARTED | SPEC-020 |
| MDL-02 | Exported + module-private only | DD | 6.11, 7.4.1 | | | NOT_STARTED | |
| MDL-03 | Absolute paths | D | 6.11 | | | NOT_STARTED | |
| MDL-04 | Unresolved names: diagnostic with candidates; visible auto-insert from known deps | D | 2.4, 7.4.1, 8.19 | | | NOT_STARTED | AMB-010 |
| MDL-05 | New dependencies only via explicit manifest/lockfile | D | 5.16.4 | | | NOT_STARTED | |
| MDL-06 | Runtime init cycles rejected with full trace | D | 6.11 | | | NOT_STARTED | |
| MDL-07 | Type/declaration cycle policy | OD/SS | 6.11 | | | NOT_STARTED | SPEC-020 |
| MDL-08 | Runtime loading for REPL/agents; explicit reload | D | 6.11, 7.14.4 | | | NOT_STARTED | |

## 14. Diagnostics (V3 6.12, 7.13)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| DGN-01 | Structured objects independent of rendering | D | 6.12, 7.13.3 | | | NOT_STARTED | |
| DGN-02 | Hierarchical codes; JSON outcome/domain/reason | DD | 7.13.2 | | | NOT_STARTED | SPEC-022 |
| DGN-03 | Multi-span, notes, help, task/resource/channel provenance | DD | 7.13.3, 7.13.6 | | | NOT_STARTED | |
| DGN-04 | Bounded, cycle-safe, side-effect-free, secret-aware local values | D | 7.13.4, 8.20 | | | NOT_STARTED | |
| DGN-05 | Result provenance | D | 7.7.8 | | | NOT_STARTED | |
| DGN-06 | Concurrent diagnostics: lexical tree + flattened leaves | D | 7.13.6 | | | NOT_STARTED | |
| DGN-07 | Channel/select diagnostics | DD | 6.12 | | | NOT_STARTED | |
| DGN-08 | Parser/checker multi-error recovery, root prominent, cascades noted | D | 7.13.7 | | | NOT_STARTED | |
| DGN-09 | Modes: default, quiet, deep, JSON | DD | 6.12 | | | NOT_STARTED | |
| DGN-10 | Performance/render budgets with explicit truncation | P | 7.13.5 | | | NOT_STARTED | |
| DGN-11 | Fix suggestions are visible patches | D | 7.13.7 | | | NOT_STARTED | |

## 15. Toolchain (V3 6.13, 7.14)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| TL-01 | CLI run/check/format/repl/test with mode & diagnostic options | DD | 7.14.2 | | | NOT_STARTED | |
| TL-02 | Formatter canonical, deterministic, idempotent; patches | D | 6.1, 7.14.3 | | | NOT_STARTED | |
| TL-03 | REPL first-class with runtime loading | D | 7.14.4 | | | NOT_STARTED | |
| TL-04 | Seeded schedule stress testing; seed recorded on failure | DD | 7.14.5 | | | NOT_STARTED | |
| TL-05 | Python differential oracle on declared domain | D | 5.16.5-8, 7.16.4 | | | NOT_STARTED | applied to LocalFlow |
| TL-06 | Test framework | SS | 9.3#22 | | | NOT_STARTED | SPEC-021 |

## 16. Core / standard library boundary (V3 6.14, 7.15)

| ID | Feature | V3 | § | Impl | Tests | State | Assumptions / concerns |
|---|---|---|---|---|---|---|---|
| STD-01 | File resource providers | std | 6.14 | | | NOT_STARTED | |
| STD-02 | JSON, math, datetime/time, regex, strings | std | 6.14 | | | NOT_STARTED | regex delegates to Python `re` (documented leakage boundary) |
| STD-03 | Ordinary protocols Comparable/Hashable/Iterable | std | 6.14 | | | NOT_STARTED | |
| STD-04 | Standard concrete errors and categories | std | 6.14 | | | NOT_STARTED | |
| STD-05 | Channel helpers: fan-in, receive-until-closed, request-response, homogeneous selection | std | 6.14, 7.11.9 | | | NOT_STARTED | |
| STD-06 | Network/HTTP/process/database providers | std | 6.14 | | | NOT_STARTED | environment has no services; lowest priority, decide during audit |

## 17. Interactions (V3 Part VIII) → TEST-INT-* work items

8.1 dynamic×protocols×contracts · 8.2 dynamic×tasks/channels · 8.3 effects×higher-order ·
8.4 exceptions×Results×channels · 8.5 resources×async · 8.6 resources×abandonment ·
8.7 resources×expression blocks×contracts · 8.8 mutable×invariants×cancellation ·
8.9 protocol contracts×mutable impls · 8.10 handles×aggregation · 8.11 external
cancellation×group failure · 8.12 channels×copy×backpressure · 8.13 closure×select loops ·
8.14 fairness×diagnostics · 8.15 select×task lifetimes · 8.16 relative timeout×loops ·
8.17 guards×mutable state · 8.18 modules×state×tasks · 8.19 auto-import×reproducibility ·
8.20 diagnostics×privacy · 8.21 Python differential testing (LocalFlow oracle).

## 18. Deferred / rejected (verify absence, do not implement)

Deferred (9.4): resource-owning records; multiple categories; module-state facility;
algebraic effects; dynamic heterogeneous select; mutable broadcast; numeric priorities;
general pure-function effect; user copy hooks; fixed-width ints; reflection/metaprogramming;
operator overloading beyond narrow core; FFI; deterministic replay across I/O.
Rejected (9.5): class inheritance; Closeable RAII; affine/move semantics; final-reference
cleanup; advisory-only annotations; guarded/proxy gradual typing; automatic coercion;
unchecked exceptions; Java-style checked exceptions without forwarding; Go-style error
values everywhere; throw+Result functions; recoverable abandonment; broad untyped
catch; structural error matching; theorem-proving contracts; general purity inference;
mutable globals; locks; channels as lifetime model; universal channel mode; implicit
unbounded default; reopenable channels; arbitrary async select; readiness-only select;
permanent source-order default; random default; opaque global round-robin; blocking
select default branch; reactive guards; silent removal of closed branches; dynamic
heterogeneous select; dual representations; silent dependency installation.
