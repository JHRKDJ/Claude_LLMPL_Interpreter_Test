# FINAL REPORT — RUN0: a reference implementation of V3 and LocalFlow

Scope: one autonomous run executing `RUN0_GOAL.md` against
`design/LLM_NATIVE_DESIGN_V3.md` (V3). Everything under "observed" below can be
checked against the repository: `BUG_LEDGER.md` (interpreter), 
`examples/localflow/APP_BUG_LEDGER.md` (application/oracle/spec), `DECISIONS.md`,
`FEATURE_MATRIX.md`, `examples/localflow/notes/LANGUAGE_EXPERIENCE.md` and the test
suites. Numbers are from the final green run (§X) unless stated.

A caveat applies to the whole report. One agent wrote both the language
implementation and the application, and it had the full design document in context
throughout. So "learnability" evidence comes from an agent that knew the design but had
never *written* the language. It is not evidence about an agent seeing V3 cold, and it
is not evidence about humans.

---

## 1. Executive result

- **A coherent implementation emerged.** It is a modular Python 3.11 tree-walking
  interpreter with:
  - a gradual static checker with draft and verified modes;
  - structured diagnostics (text and JSON from one data model);
  - a canonical formatter, a test runner with seeded schedule stress, a REPL and a CLI
    (`run`, `check`, `format`, `test`, `repl`);
  - a small standard library, partly written in the language itself.
- **Coverage.** Of the 185 V3 features in FEATURE_MATRIX.md (derived from a full read
  of V3), 178 are COMPLETE with tests:
  - 6 are DEFERRED, either by V3 itself (§9.4: resource-owning records, multiple
    category membership, mutable broadcast, dynamic heterogeneous select, numeric
    priorities) or as a semantics-neutral optimisation (TYP-14);
  - 1 is OUT_OF_SCOPE: network, HTTP, process and database providers (IMPL-007).
- **The language runs substantial programs.** LocalFlow is a deterministic workflow
  engine: about 2,000 lines of the language in 7 modules. It covers retries, timeouts,
  fail-fast, cancellation, resource-backed transforms, fan-out, sub-workflows and
  seeded schedule independence. It passes `lang check --mode=verified` with 0 errors
  (11 advisory warnings), and its manifest selects verified mode.
- **LocalFlow passes its full suite: 446 black-box tests, byte-level comparison
  against an independent Python oracle.** This includes:
  - the 30 original acceptance scenarios (FIFO and seeds 1-3);
  - 12 adversarial cases;
  - 17 application regression fixtures;
  - 87 fixtures written by an independent final reviewer (FIFO and seed 5);
  - source-quality gates (verified mode, formatter).
- **Language/toolchain suite: 2,387 tests pass.**

  | suite | tests |
  |---|---|
  | unit | 47 |
  | conformance | 334 |
  | negative | 64 |
  | interaction (TEST-INT-001..030) | 72 |
  | regression | 180 |
  | fuzz/property | 1,670 |
  | tooling | 20 |

- **Defects.** 53 interpreter/toolchain defects were found and fixed. Each has a
  regression test that was confirmed to fail before its fix, and none remain open.
  The application side recorded 7 LocalFlow defects, 3 oracle defects and 4 spec
  repairs.

The headline qualitative result is the gap between the first sweep and the second
audit. After the first full coverage reread, I judged the implementation complete. A
second, independent audit then found 35 further genuine defects (BUG-0016..0050), and
the final application review found 2 more (BUG-0051/0052). Verifying the CLI in the
final green run found one more (BUG-0053). Most were cross-feature interactions.
Self-assessed completeness was therefore unreliable here, and the independent passes
were the most productive single activity late in the run (§7).

## 2. Implemented architecture

`ARCHITECTURE.md` has the module map. In summary:

| layer | modules | notes |
|---|---|---|
| source & syntax | `source.py`, `syntax/` (lexer, parser, AST, tokens) | Hand-written recursive descent with V3's newline/continuation rules and error recovery. The parser (~1.6k lines) is the largest single file, mostly because of recovery and precise diagnostics. |
| modules | `modules/loader.py` | manifest (`lang.toml`), import graph, native vs language std modules |
| static checker | `check/`: `resolve` (names, definite assignment, captures, init cycles), `typecheck`/`expr`/`callcheck`/`walk` (gradual types, effects, resources, async/spawn, sendability), `selectcheck`, `exhaustive`, `contracts_check`, `yieldflow` (provider yield paths), `advisories` | Severity policy (`legal` / `oblig` / `advise`) implements draft vs verified in one place. The checker annotates the AST with transient runtime checks (IMPL-004) and typed-call boundaries. |
| runtime | `runtime/interp/` (calls, exprs, stmts, patterns, res, conc, chan, selectx, link, core), `scheduler`, `tasks`, `channels`, `isolation`, `frozen`, `rtypes`, `equality`, `capture`, `values`, `builtins/` | Mixin interpreter. Baton-passing cooperative scheduler (one language task runs at a time) with FIFO or seeded random choice and a real or virtual clock (IMPL-001/002). |
| diagnostics | `diagnostics/` (model, codes, render_text, render_json) | One `Diagnostic` tree. Stable codes (`S.*` static, `A.*` abandonment, `R.*` unhandled recoverable, `W.*` advisory, `I.*` info). Render budget, quiet/deep views, redaction. |
| tooling | `format/` (canonical formatter + equivalence check), `tooling/` (CLI, REPL, test runner, `--fix`) | The formatter refuses to write output that does not re-parse to an equivalent tree with the same comments. |
| std | `runtime/builtins/*` (fs, json, math, regex, datetime, …), `stdlib/*.lang` (chan, order) | |

Large or complex components, by conceptual weight rather than size:
1. **The task-group/cancellation core** (`interp/conc.py`, `tasks.py`, `scheduler.py`).
   It covers four group modes, quiescence, external versus internal cancellation,
   masking floors, deadlines, and outcome tables.
2. **Resource scopes** (`interp/res.py`). Exit classification, release under
   cancellation masking, borrow escape and `onAbandon`.
3. **The gradual checker's call typing** (`check/callcheck.py`). Generic
   instantiation, effect variables, typed-call boundary annotations and builtin
   signatures parsed from strings.
4. **Channels with port-holder tracking** (`interp/chan.py`, `channels.py`). This
   tracking is how "no receivers remain" is decided without GC finalisation
   (AMB-006).

## 3. V3 coverage

Summary by subsystem (full detail and test references in FEATURE_MATRIX.md, whose
references are validated by `tests/unit/test_feature_matrix.py`):

| V3 subsystem | status | important tests | real unresolved concern |
|---|---|---|---|
| Syntax/source (4.x, 6.1, 7.1) | 9/9 | `tests/unit/test_parser.py`, parser and formatter fuzz | `{}` empty map vs empty block in statement position (§5) |
| Values/data model (5.1, 7.3) | 15/15 | `c/test_values.py`, `r/0019,0020,0045,0046` | Numerics policy (half-away rounding, strict parsing, Int/Float never equal) is SPEC-010, not V3 |
| Bindings/closures (5.2, 6.3, 7.4) | 6/6 | `c/test_functions_records.py`, `r/0018,0050` | — |
| Types (5.3, 6.4, 7.6) | 13/13 (+1 deferred) | `c/test_checker.py`, `c/test_transient_checks.py`, `r/0024-0026,0048`, `i/test_int001_*` | No union types: disagreeing branches join to `Dyn`, so some mismatches surface only at run-time boundaries |
| Functions/protocols/contracts (5.10, 6.5, 7.5, 7.8) | 14/14 | `c/test_contracts.py`, `c/test_checker.py`, `r/0028,0041` | AMB-001: a protocol added in another module adds postconditions to existing types' methods |
| Errors/Results/effects (5.7-5.9, 7.7) | 15/15 (+1 deferred) | `c/test_errors.py`, `r/0013,0027,0043` | — |
| Resources/cleanup (5.5, 5.6, 7.9) | 12/12 (+1 deferred) | `c/test_resources.py`, `r/0001,0017,0022,0029,0031` | — |
| Structured concurrency (5.12, 7.10) | 20/20 | `c/test_tasks.py`, `r/0002,0016,0023,0033,0038,0052` | AMB-002 timing dependence; AMB-013 |
| Isolation (5.11, 7.10.10) | 8/8 | `c/test_tasks.py`, `i/test_int013_*`, `r/0021,0035,0037`, graph-copy property test | — |
| Channels (5.13, 7.11) | 12/12 (+1 deferred) | `c/test_channels.py`, `r/0034` | "Creator holds sender" friction (§5) |
| Select (5.14, 7.12) | 17/17 (+2 deferred) | `c/test_select.py`, `i/test_int022_*` | — |
| Draft/verified (5.15) | 7/7 | `tests/negative`, `i/test_modes.py` | Verified mode on `Dyn`-heavy code needs explicit narrowing (§10) |
| Modules (5.16, 6.11, 7.4.1) | 8/8 | `c/test_functions_records.py`, `n/test_static_errors.py`, `i/test_int027_*`, `r/0015,0042` | — |
| Diagnostics (6.12, 7.13) | 11/11 | `c/test_runtime_diagnostics.py`, `r/0044,0048` | Credential redaction is heuristic (bounded regexes plus a registry). It is not a guarantee. |
| Toolchain (6.13, 7.14) | 6/6 | `tests/tooling`, `r/0049`, formatter fuzz | Formatter wraps long headers but not long expressions |
| Core/std boundary (6.14, 7.15) | 5/5 (+1 out of scope) | `c/test_stdlib.py` | `std.regex` uses Python `re` pattern syntax (documented leakage, IMPL-007) |

Implementation limits that do not change semantics:
- Call depth is capped at 2,500. Exceeding it is a clean abandonment,
  `A.RUNTIME.STACK_OVERFLOW` (IMPL-008).
- Generic type parameters are erased at run time (IMPL-006). Runtime checks cover
  values, not type arguments, except at checker-inserted boundaries.

## 4. V3 ambiguities

All resolutions are in DECISIONS.md. They are classified here as RUN0 asks.

**Genuine ambiguities (V3 under-determines behaviour that programs can observe):**
- **AMB-001 — inherited protocol contracts under global structural conformance.**
  Resolved by narrowing: a method that adds `requires` does not conform. Concern: there
  is action at a distance across modules.
- **AMB-002 — fail-fast and catching an awaited child failure.** Whether
  `try await h catch` sees the failure depends on whether the body reaches the `await`
  before the failure cancels it. V3 7.10.4 permits schedule-dependent first-failure
  identity, so this stands. It is pinned by a test that demonstrates the timing
  dependence. Deterministic handling needs `parallel collect` or conversion inside
  the child.
- **AMB-003 — awaiting a cancelled or abandoned child.** Resolved: the awaiting task
  abandons, or receives the cancellation if it is itself being cancelled.
- **AMB-004 — what is a cancellation point.** An operation that commits immediately
  is not one.
- **AMB-006/006b — "no receivers remain" without finalisation.** Explicit port-holder
  sets per task, and loss only after an endpoint has existed.
- **AMB-013 — first-success under external cancellation after a tolerated failure.**
  V3 5.12.11/8.11 ("preserve both; process the group failure") conflict with 7.10.7
  ("AggregateException only if all children fail; cancellation remains pending").
  I first implemented the general rule (BUG-0023). The LocalFlow review then showed
  why the mode-specific rule is right: a timeout should not become "permanent
  failure" because one redundant provider failed first. Resolved for 7.10.7, with
  BUG-0052 and a corrected test expectation. This is the clearest case in the run of
  an application exposing a real ambiguity in the design text.

**Specification-stage decisions (V3 leaves them explicitly to the specification):**
SPEC-001..025, covering:
- concrete syntax and the keyword set;
- record update;
- collection literals;
- the numerics policy (SPEC-010, extended after Python-leakage findings);
- error categories;
- effect-variable syntax;
- the contract language;
- `defer`;
- channel and select syntax;
- the manifest;
- REPL and test-runner models.

AMB-005 (draft-mode absence of `throws`), AMB-007 (identity equality of mutable
values), AMB-008 (`spawn` only lexically inside `parallel`), AMB-009 (contracts may
read mutable fields), AMB-010 (unresolved names block in draft too), AMB-011 (reports
hold frozen values) and AMB-012 (handles unsendable) are in this class. V3 points in
a direction and the choice is mechanical.

**Implementation-only decisions:**
- IMPL-001/002: baton-passing scheduler, virtual clock.
- IMPL-003: the provider body runs inside `yield`.
- IMPL-004: transient checks.
- IMPL-005: inferred effects are metadata.
- IMPL-006: erasure.
- IMPL-007: stdlib scope.
- IMPL-008: call depth.

## 5. Design conflicts and interactions

Places where two V3 ideas interacted badly or were hard to satisfy together:

1. **Structured cancellation × "a failure is never lost" (AMB-002, AMB-013).**
   Fail-fast cancels the body, so whether a failure is *observed* or *aggregated*
   depends on scheduling. V3 accepts this, but programs can observe it. It is the one
   place where V3's determinism story leaks.
2. **Control flow × scope boundaries.** `return`, `break` and `continue` crossing a
   `parallel` body or a resource scope (BUG-0016, 0017) were missing from the
   exit-classification tables in my first implementation. V3's tables are written in
   terms of normal, throw, cancel and abandon. Control-flow exits are a fifth class
   that every boundary must handle.
3. **Closures × everything that restricts values.** Closures capturing:
   - mutable state broke sendability (0018, 0035) and frozenness (0050);
   - borrows broke resource escape (0029);
   - bound methods of mutable receivers broke isolation (0037).

   Each restriction (isolation, freezing, borrow escape) needs its own closure-capture
   analysis. Closures were the most frequent carrier of cross-feature bugs.
4. **Gradual typing × verified mode.** `Dyn` is the escape hatch, but in verified mode
   a method call on `Dyn` is an error (V3 5.3.10/7.7.6: its effect is unknown). JSON
   handling therefore needs explicit `as` narrowing everywhere. Lambda parameters
   without annotations are `Dyn` (experience entry 19). The rule is principled, but it
   concentrates friction exactly where data enters the program.
5. **Channels' endpoint liveness × structured ownership.** "No receivers remain"
   requires knowing who holds a port. The creator holds both ends until it releases
   them, so a common producer/consumer shape deadlocks or waits unless the creator
   calls `release()`. This "creator holds sender" friction was raised in the second
   audit (C17) and kept: the alternatives reintroduce GC-like finalisation, which V3
   rejects.
6. **Brace syntax × map literals.** `{}` in statement position is a block, so an empty
   map in a branch needs `Map.empty()` (entry 2). This is small, but it is a
   surface-syntax collision V3 did not anticipate.
7. **Logical-time batching × no scheduler introspection.** Collecting "all
   completions at one instant" in a concurrent program needed a hand-built barrier
   protocol (LF-002/003). V3 deliberately has no "wait until all other tasks are
   blocked" primitive. That is right, but it makes instant-level semantics expensive
   to express.

## 6. Implementation complexity

| mechanism | code | debugging/bugs | tests | conceptual / integration |
|---|---|---|---|---|
| Task groups + cancellation + masking | medium (~1.0k lines across conc/tasks/scheduler) | highest: BUG-0002, 0016, 0022, 0023, 0033, 0038, 0052 | conformance + interactions + schedule fuzz | Highest. The outcome tables multiply by exit class, mode and external cancellation. |
| Static checker (gradual types/effects) | largest (~4.9k) | 17+ bugs, mostly false negatives found by audit | negative + checker conformance | High. Every runtime rule needs a static twin with the same edge cases. |
| Resources | small–medium | 0001, 0017, 0022, 0029, 0031 | conformance + yield-path tests | Medium. The release table is crisp; the interactions are not. |
| Parser + formatter | ~2.4k | 0004–0007, 0014, 0036, 0040 (mostly fuzz-found) | 1.6k fuzz cases | Low conceptually, high in volume |
| Diagnostics (capture, budget, redaction) | ~0.9k | 0012, 0044, 0048; one quadratic-regex slowdown | runtime-diagnostic suite | Medium. Privacy and boundedness requirements interact with performance. |
| Channels/select | ~1.1k | 0034 only | conformance + interactions | Medium. Endpoint tracking was the only subtle part. |

The cross-subsystem integration that cost the most was **keeping checker and runtime
consistent**. Several bugs were one side enforcing a rule the other did not:
- BUG-0046: Int/Float lookups;
- BUG-0047: duplicate keys;
- BUG-0049: format specs;
- BUG-0050: frozen closures.

## 7. Regression bug evidence

53 interpreter/toolchain defects (`BUG_LEDGER.md`). Counts are small and the
categories overlap, so this is descriptive only.

**By where they were found:**

| discovery route | bugs | count |
|---|---|---|
| Own conformance/unit/interaction tests and integration review | 0001–0004, 0008 | 5 |
| Fuzzing (parser/formatter) | 0005–0007, 0014 | 4 |
| Writing LocalFlow or the standard library in the language | 0009, 0010, 0011 | 3 |
| First V3 coverage reread | 0012, 0013, 0015 | 3 |
| Second independent audit (subagents) | 0016–0050 | 35 |
| LocalFlow final adversarial review | 0051, 0052 | 2 |
| Final green run (CLI verification) | 0053 | 1 |

Notes on the table:
- 0015 surfaced when LocalFlow was re-checked in verified mode.
- 0045 was found jointly by the audit and the LocalFlow review.
- **Found only through LocalFlow:** 0009, 0010, 0015, 0051 and 0052 (5), plus 0011
  through the stdlib. The remainder came from tests and audits.

**By subsystem (approximate; a bug can have two):**

| subsystem | approx. count |
|---|---|
| static checker | ~17 |
| concurrency/cancellation/isolation | ~11 |
| parser/formatter | 7 |
| Python leakage in values/numerics/equality | 4 |
| resources | 4 |
| diagnostics/privacy | 3 |
| one each: contracts, modules, protocols, effects runtime, tooling, std.fs, std ordering | 7 |

**Recurring patterns:**
1. **Cross-feature interactions, which the audit found and my own tests did not.** My
   tests checked each feature against its own section of V3. The audit instead
   combined features: return inside parallel, closures in frozen lists, cancellation
   during release.
2. **Host-language leakage.** Python's rounding, `int()`, float display, `mkstemp`
   modes and `read_text` newline translation (the last on the oracle side) leaked
   into behaviour that V3 says must be language-defined (V3 2.7). This happened in
   *both* the interpreter and the Python oracle.
3. **Checker false negatives masked by runtime checks.** Programs were never
   *unsafe*, because the runtime abandons. But verified mode accepted programs it
   should have rejected (0024–0026, 0050). The gradual design makes such gaps silent
   until audited.
4. **Fuzzing found only parser bugs (4).** The property tests for schedule
   interleavings, graph copy and exhaustiveness found none.

## 8. LocalFlow experience

**Natural architecture.** The program falls into separate modules:
- `load` validates into frozen records;
- `graph` resolves dependencies;
- `engine` runs a scheduling loop over a mutable `RunState`;
- `jobs` holds one function per kind, plus the attempt/retry loop;
- `report` and `main` build and write the result.

Frozen records for configuration and mutable records for run state matched V3's
split. `W.STATE.LARGE_MUTABLE_RECORD` pushed a useful refactor (entry 7).

**Features used naturally:**
- `parallel` + `spawn` for running jobs;
- `within` for per-attempt timeouts;
- `parallel firstSuccess` for mirrors;
- resource providers (`resource fn workspace`) and `use` with atomic writes, so
  transform cleanup on timeout or cancel was correct the first time;
- `capture` to turn failures into data in the retry loop;
- `defer` + non-blocking `trySend` to report from cancelled tasks (entry 11);
- fail-fast by throwing from the group body (entry 12).

**Where V3 improved local reasoning.** Every suspension is a visible `await`, every
task is created inside a visible `parallel`, and every cleanup is a visible
`use`/`defer`. In the timeout and cancellation bugs found by the reviewers (LF-004),
the code path responsible was found by reading two adjacent functions, because
cancellation could only enter at marked points.

**Awkward architecture and bookkeeping:**
- Instant-level batching needed a barrier protocol with heartbeats and nanosecond
  tie-break offsets (LF-002/003, entry 10). This was the hardest part of the
  application.
- A `Progress` sink threaded through five calls, because a cancelled nested run cannot
  return a value. `W.STATE.PASS_THROUGH` flagged it as a false positive (entry 8).
- JSON-shaped configuration is `Map[Str, Dyn]` with many `cfgInt`/`cfgStr` narrowing
  helpers.

**Features not naturally used:**
- channels beyond one event stream per run;
- `select` (one use);
- contracts (light use; the spec's invariants are mostly validation);
- protocols (none needed).

**Difficult interactions:**
- the sub-workflow timeout as a nested cancellation request (LF-004);
- the first-success/cancellation outcome (BUG-0052);
- ordering same-instant completions under random schedules (LF-002).

**Draft vs verified.** LocalFlow was written in draft mode and moved to verified
afterwards. The move initially showed 10 errors. All were a checker defect (BUG-0015),
not the program. After the fix it was verified-clean. Of the 11 remaining advisories:
- 8 are `W.CANCEL.NO_CANCELLATION_POINT` on bounded loops, which is noise (entry 17);
- 3 are `PASS_THROUGH`.

## 9. Diagnostic experience

- **Root-cause localisation: good.** Abandonment diagnostics carry the primary span at
  the failing operation, propagation history for recoverable errors
  (`= propagated through:`), the task path, and bounded local values. Typed-boundary
  mismatches name the boundary where the assumption became active (V3 7.6.5;
  improved by BUG-0048).
- **Source spans: accurate**, including inside interpolations and formatter output.
- **Concurrent provenance.** Task-group failures render as a tree with task paths,
  cancellation summaries and a seeded 32-entry scheduling-decision ring, so a
  random-schedule failure can be replayed by seed. This is what made LF-002
  reproducible.
- **Structured output is real, not formatted strings.** `--json` emits the same tree
  (codes, spans, labels, notes, children), and tests assert on codes and fields.
- **Weak spots:**
  - syntax errors for statements in expression position initially lacked the "use
    braces" suggestion (fixed for match arms);
  - the `Dyn` method-call error suggests `as` narrowing when annotating a lambda
    parameter is the better fix (entry 19);
  - a file with an unresolved name is not type-checked until the name is fixed. This
    is deliberate cascade control, but it means one extra round-trip when both kinds
    of error are present;
  - render budgets truncate deep traces in large programs. LocalFlow's f29 defect stop
    printed "truncated to the render budget", and the essential frame was still
    present.
- **Usefulness for agent repair: high, on the evidence of this run.** In nearly every
  diagnosed failure I acted on the first diagnostic without needing to add prints:
  - my test-writing mistakes;
  - LocalFlow development errors;
  - audit reproductions.

  The exceptions were logical-time ordering bugs, which needed the seed and the
  decision ring rather than a span.

## 10. Agent learnability

Writing about 2,000 lines of correct LocalFlow plus about 190 lines of standard
library took no extended period of fighting the language. Most first drafts of
functions checked cleanly or failed with one or two diagnostics.

**Documentation actually needed:** the V3 document itself was too large to consult
while coding. Its decisions are spread over sections 5–8. What I actually used:
- `docs/LANGUAGE_GUIDE.md`, written early as a compact reference whose examples are
  executed by tests;
- the code tables in `diagnostics/codes.py`.

That suggests a learnability-critical artifact is a 300-line guide, not the design
document.

**Repeated misunderstandings (from my own errors, tests and the experience log):**
- **Statements versus expressions.** These errors recurred throughout the run:
  - `None => return x` and `None => throw E()` in match arms (entries 1 and 16);
  - `let` in arm position;
  - `try` placement inside `&&` (entry 20).

  Python and Rust habits pull in opposite directions. This was the most frequent
  error class in the experience log and in my own test-writing mistakes.
- **Python habits:**
  - `list.pop()` returning the element rather than `T?` (entry 4);
  - `/` on Ints (entry 6);
  - `"".split("\n")` producing one line.
- **An expectation the library failed to meet:** while verifying the test CLI at
  the very end, I wrote `order.sort([3, 1, 2])`, which failed because only `Str` had
  `compareTo`. The expectation was reasonable and the library was wrong (BUG-0053).
- **Syntax I invented without checking:**
  - `MutableList.length()` written as a method (it is a property);
  - `use` without a block;
  - `channel[...]()` constructors;
  - `type X = {...}` records.

  These came up in this final session, while writing test programs quickly. Each cost
  one diagnostic round-trip, and each diagnostic was precise.
- **Semantics I got wrong in the implementation itself** (the more important
  category): the cross-feature cases in §7. These were not misunderstandings of
  V3's *intent*. They were failures to enumerate how features combine.

## 11. Repair behaviour

These are observed examples of how V3's constraints shaped repairs.

**Constructive, correct repairs:**
- `W.STATE.LARGE_MUTABLE_RECORD` led to splitting the run state into per-job
  `JobState` and a small `RunState` (entry 7).
- Verified mode's `S.TYPE.DYNAMIC_CALL` in a CSV transform was fixed by annotating
  `fn(r: Str)` and extracting a named helper `withoutCr` (entry 19). The repair made
  the code clearer.
- An `Int` boundary mismatch on `n * (n + 1) / 2` was repaired to `.div(2)`, which
  is the correct fix (entry 6).

**Useful localisation:** the abandonment for a mutable closure stored in a frozen list
named the field, the capture and the reason. It led directly to a static rule
(BUG-0050), and the fix was a typed analysis, not a workaround.

**Broad or lazy workarounds avoided, and one tempting one recorded:**
- `W.CANCEL.NO_CANCELLATION_POINT` could be silenced with `cancel.check()` calls that
  add no safety. I did not add them, and the advisory noise remains (8 warnings).
- `W.STATE.PASS_THROUGH` could be "fixed" by a global. It was left as recorded noise
  instead.
- The advisories are the place where an agent under pressure to reach zero warnings
  would plausibly make the program worse.

**Removal of functionality:** not observed. No feature was removed to satisfy the
checker.

**Excessive annotation:** moderate, concentrated in `Dyn` narrowing of JSON data
(`cfgInt`/`cfgStr` helpers; `as Map[Str, Dyn]`). It was not observed elsewhere.

**Test corrections versus test weakening:** three times a test written earlier was
corrected because a later reading of V3 showed its expectation was wrong:
- `test_use_after_release_through_escaped_closure`;
- the init-cycle codes;
- the first-success expectation of BUG-0023 under AMB-013.

Each correction is recorded in the ledger with its reason. None loosened an
assertion to make a failing implementation pass.

## 12. Interpreter vs application bug isolation

- **How often LocalFlow revealed interpreter defects:** 5 of the 53 came only through
  LocalFlow (§7), plus 1 through stdlib code written in the language. On the
  application side, 7 defects were LocalFlow's own, 3 were the oracle's and 4 were
  spec gaps. LocalFlow was therefore a minor source of interpreter bugs by count. But
  the ones it found were ones the conformance suite structurally could not reach:
  - verified-mode behaviour on a large real program (0015);
  - file permissions under a byte-level harness (0051);
  - a group-mode ambiguity that only matters when a timeout meets a redundant
    provider (0052).
- **Minimal reproductions were easy.** Each LocalFlow-revealed interpreter bug reduced
  to a 10–25 line program within one or two steps. For example, BUG-0052 went from the
  f42 fixture to `within` + `parallel firstSuccess { spawn hang(); spawn bad() }`.
  Two properties made this fast:
  - the diagnostic named the construct;
  - the virtual clock made the reproduction deterministic.
- **Attribution.** These features made it straightforward:
  - the separate ledgers (`BUG_LEDGER.md` and `APP_BUG_LEDGER.md`);
  - an independent oracle;
  - schedule seeds.

  The main attribution risk was the opposite direction: oracle bugs that look like
  LocalFlow bugs (ORACLE-001..003). Two of those were Python defaults in the oracle
  (NaN JSON literals, CRLF translation), not reasoning errors. A byte-level harness
  was needed before either side's host leakage became visible.

## 13. Evidence about continuing the project

### OBSERVED IN THIS RUN
1. **V3 is implementable as a coherent whole.** Every non-deferred feature was
   implemented and tested by one agent in one run. No V3 requirement turned out to be
   contradictory in a way that blocked implementation. Ambiguities were resolvable
   locally (§4), the hardest being AMB-002 and AMB-013.
2. **The structured concurrency + resources + cancellation core earned its
   complexity in the application.** Timeout and cancellation cleanup in LocalFlow
   (scratch markers, atomic writes, nested runs) was correct on the first attempt in
   most paths. When it was wrong (LF-004), the fix was local. This is the strongest
   positive evidence in the run.
3. **The same core produced the most interpreter defects** (§6, §7) and the two
   hardest interpretation problems: the accepted timing dependence AMB-002 and the
   one real textual conflict AMB-013. The complexity is real and
   concentrated there.
4. **Diagnostics were useful for repair.** Structured codes, propagation history, task
   trees and seeded replay localised essentially every failure in this run.
5. **Verified mode was valuable but its friction concentrates at data boundaries**
   (`Dyn` narrowing). Some advisory heuristics (cancellation points, pass-through)
   had low precision on a real program: 11 of 11 warnings in LocalFlow were not
   actionable.
6. **Self-assessment was unreliable.** Independent audits found 37 defects after I
   believed the implementation complete, mostly interactions, and the final green
   run surfaced one more (BUG-0053). Any claim about V3's correctness from a single
   author's tests should be discounted accordingly.
7. **Host-language leakage happened on both sides** (interpreter and oracle), despite
   V3 2.7 warning against it. Only strict language-level defaults and a byte-exact
   harness exposed it.
8. **Performance: this interpreter is far outside V3's comfort zone on CPU-bound
   code.** Measured on this machine, startup excluded:

   | workload | CPython | interpreter | ratio |
   |---|---|---|---|
   | recursive `fib(25)` | 0.018 s | 5.1 s | ≈280× |
   | trial-division `primeCount(60000)` | 0.075 s | 9.3 s | ≈125× |

   Verified mode costs about 0–10% over draft. V3 §2.1 treats ten times slower than
   Python as damaging to the feedback loop. The measurement cannot separate the cost
   of a tree-walker hosted in Python from the cost of V3's diagnostic substrate
   (spans, task lineage, bounded capture). It therefore does not test V3's 25% / 2×
   budgets (7.13.5), which are relative to an implementation of the same language
   without that substrate, and no such baseline exists here. LocalFlow was
   mostly unaffected because it is logical-time-bound. A typical fixture takes about
   0.4 s, of which about 0.36 s is loading and checking the program, against 0.04 s
   for the oracle. The large-scale scenario s28 takes about 13 s, where the CPU cost
   shows.

### SPECULATIVE DESIGN OPINION
- **V3 looks promising rather than overcomplicated, but its value is concentrated.**
  Probability about 0.65 that a smaller kernel keeps most of the observed value. That
  kernel would be:
  - explicit effects with `try`/`capture`;
  - frozen/mutable records;
  - structured task groups with cancellation and `within`;
  - resource scopes;
  - strict, language-defined primitives;
  - structured diagnostics with seeded schedules.

  Under that hypothesis, the following carry less weight per unit of complexity:
  - select (heavily specified: 17 features, used once);
  - broadcast;
  - contracts beyond simple pre/postconditions;
  - global structural protocols (AMB-001's action at a distance);
  - most advisories.

  The evidence is one application written by the implementer, so the estimate is
  weak. Channels and select may matter more for streaming programs than for a
  scheduler.
- **The four-mode group outcome tables are where I would expect future users and
  implementers to disagree.** I put about 0.7 on further mode × cancellation
  ambiguities existing beyond AMB-002 and AMB-013 that this run did not hit.
- **Draft→verified as a workflow seems right for agents.** Writing in draft then
  tightening matched how I worked. Its value depends on verified-mode precision,
  which suffered here from checker false negatives (§7, pattern 3) rather than from
  false positives.
- **Further experimentation is worthwhile. Major investment before a cold-start
  learnability test is not**, because the evidence that matters most is missing (see
  below).

**Most likely way these conclusions look wrong in hindsight:** the positive
LocalFlow experience is an artefact of authorship. I wrote the interpreter, so I knew
which constructs were solid, and an agent without that knowledge might find V3's
rules (statement/expression split, verified-mode narrowing, group outcome tables)
much harder.

**The single assumption most worth checking against what you know:** that an LLM
agent's learnability bottleneck is reading a compact guide plus diagnostics, rather
than prior exposure to the language. Everything favourable in §10–§11 rests on it.

## 14. Highest-information next experiment

**Run a cold-start agent experiment.** Give fresh agent sessions, with no access to
the interpreter source or V3, only:
- `docs/LANGUAGE_GUIDE.md`;
- the CLI;
- `examples/localflow/PROGRAM_SPEC.md` and the black-box harness.

Ask them to implement LocalFlow from scratch. In parallel, run a control arm that
implements the same spec in Python against the same harness.

**Measure:**
- acceptance-suite pass rate over time and repair iterations;
- the distribution of diagnostic codes hit;
- verified-mode error counts at first check;
- how often an agent "fixes" an advisory by degrading the program;
- defects found by the 87 review fixtures and the 17 regression fixtures, which act as
  a ready-made hidden test set.

This tests the assumption flagged above directly, reuses the existing infrastructure
unchanged, and distinguishes "V3 helps agents write correct concurrent code" from
"the implementer could write correct code in their own language."
