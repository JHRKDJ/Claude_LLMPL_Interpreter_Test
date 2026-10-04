# Resources, borrows, defer and cleanup

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Providers: acquisition, exactly one yield, normal release, abandonment-safe release
  registration; usable only as a `use` initialiser (5.5.1-4).
- Resources/borrows never escape: no binding, return, storage, capture by escaping
  closures, sending, or crossing tasks (5.5.5-8).
- Normal release runs on normal/exception/cancellation exits, knows the exit class,
  cannot suppress the pending outcome; abandonment runs only abandonment-safe
  primitives (5.5.9-13). `defer` is block-scoped LIFO cleanup (5.6, 7.9.6).
- Cleanup failure combination (7.9.5 table).

## 2. Operational interpretation
- `use x = try provider(args) { body }` is expression-valued. The provider runs until
  `yield v`; the body then runs *inside* the yield (IMPL-003) with the provider frames
  hidden (BUG-0001); `yield` returns a `ScopeExit` (`Normal`, `Failed`, `Cancelled`).
- `x` is a `Borrow` valid only while the scope is open and only in its task
  (`A.RESOURCE.USE_AFTER_RELEASE`, `A.RESOURCE.CROSS_TASK`). Helpers take
  `borrow T` parameters (`S.RESOURCE.BORROW_PARAM` otherwise).
- Static: `S.RESOURCE.PROVIDER_OUTSIDE_USE`, `S.RESOURCE.ESCAPE`,
  `S.RESOURCE.YIELD_COUNT` (exactly one yield on every path),
  `S.RESOURCE.YIELD_OUTSIDE_PROVIDER`, `S.RESOURCE.ON_ABANDON_RESTRICTED`,
  `W.RESOURCE.SCOPE_TOO_WIDE`. Runtime twins: `A.RESOURCE.*`
  (`ON_ABANDON_RESTRICTED`, BUG-0003).
- Cleanup combination: body ok + release fails → release error; body fails + release
  fails → `AggregateException` (body first); cancellation pending + release fails →
  release failure reported as `W.CLEANUP.FAILED_DURING_CANCELLATION` and
  cancellation continues; abandonment: release failures are secondary notes.
- `defer` runs LIFO at block exit with cancellation masked; several failing defers
  aggregate. A cleanup blocked while cancellation is pending gets
  `W.CLEANUP.STUCK` after `stuck_cleanup_after_ms` (10 s) or at deadlock.

## 3. Specification-stage choices
SPEC-015 (provider/use/borrow syntax, `ScopeExit`), SPEC-016 (`defer`).

## 4. Ambiguities
IMPL-003 (body inside yield). No language-level cleanup timeout (V3 7.10.11).

## 5. Interactions
Tasks (borrows never cross; release on cancellation), contracts (postconditions after
release), effects (`AggregateException` contributions).

## 6. Conformance tests
`tests/conformance/test_resources.py`, `tests/regressions/test_bug_0001_provider_frames.py`,
`tests/regressions/test_bug_0003_on_abandon_code.py`, `tests/conformance/test_checker.py`
(resource rows).
