# Recoverable errors, Result, abandonment and top-level failure

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Failure taxonomy: recoverable exceptions, abandonment, cancellation, hard
  termination are distinct (7.2.3, 7.7.1); abandonment is never catchable.
- Finite declared error sets; visible propagation markers at call sites in verified
  code; draft may omit markers and the exception still propagates (5.7, 7.7.3).
- Catches name types or categories; no catch-all; an unqualified fallback only for
  one statically known concrete error type (5.7.5, 7.7.3).
- A function exposes either `throws` or `Result`, not both (7.7.4).
- Effect polymorphism with error-set variables (5.8, 7.7.5); `Dyn` callables must be
  narrowed in verified code (7.7.6).
- Top-level unhandled failure is reported with provenance; cleanup still runs (7.7.9).

## 2. Operational interpretation
- Signals (`runtime/signals.py`): `Thrown(error, provenance)`, `Abandoned(diagnostic)`,
  `Cancelled`, `HardTermination` share no catchable base; `catch` only sees `Thrown`.
- `throw v` requires a declared error value (`S.EFFECT.NOT_AN_ERROR` /
  `A.TYPE.OPERAND_MISMATCH`). Provenance records creation site, propagation chain,
  task path, context entries, unmarked hops (draft) and aggregated parts.
- `try e` marks/propagates; `try e catch T as x => h …` handles named types, enum
  cases (catching every case of an error enum handles the type) and categories;
  `try e else f` handles exactly the checker-proved type (`fallback_qual`);
  `catch … else …` together is a syntax error. Catch-all spellings from other
  languages (`catch _`, `catch e`, `catch Exception`/`Error`/`Throwable`) are
  `S.EFFECT.BROAD_CATCH` with a fix hint; an unqualified `else` over several types
  is `S.EFFECT.BROAD_FALLBACK` (tests/negative/test_rejected_and_deferred.py).
- `capture e` → `Result`; `propagate r` returns `Err` early from a Result-returning
  function (`S.EFFECT.PROPAGATE_CONTEXT` elsewhere); `r.orThrow()`; `.context(k, v)`.
- Written `throws` is enforced at runtime (AMB-005): an undeclared escaping error
  abandons with `A.EFFECT.UNDECLARED_EXCEPTION`.
- Static effects (`lang/check/walk.py`, `callcheck.py`): collectors per scope;
  handlers filter; unannotated functions get inferred sets (fixpoint);
  `AggregateException` contributions from cleanup combination and task groups;
  advisories `S.EFFECT.CATCH_UNREACHABLE`, `W.EFFECT.USELESS_TRY`.
- Top level: unhandled error → exit 1 with `R.ERROR.UNHANDLED`; abandonment → exit 3;
  cancellation → 130; hard termination → 4.

## 3. Specification-stage choices
SPEC-011 (declarations, categories, catches), SPEC-012 (capture/propagate/orThrow),
SPEC-013 (effect variables, unions).

## 4. Ambiguities
AMB-005 (draft absence of `throws`); IMPL-005 (inferred effects are static-only).

## 5. Interactions
Cleanup-failure combination (`resources.md`), aggregate outcomes of task groups
(`tasks_and_cancellation.md`), select's `ChannelClosed` (`channels_and_select.md`).

## 6. Conformance tests
`tests/conformance/test_errors.py`, `tests/conformance/test_checker.py` (effect
rows), `tests/unit/test_runtime_annotations.py`, `tests/interactions/test_modes.py`.
