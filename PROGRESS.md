# PROGRESS

## Current state
- Phase: audits and final report. Implementation, LocalFlow and the first full V3
  coverage reread (RUN0 §U) are complete.
- Language suite: `python -m pytest tests -q` → 2115 passed (unit, conformance,
  negative, interactions, regressions, fuzz/property, tooling).
- LocalFlow: `python -m pytest examples/localflow -q` → 216 passed (30 acceptance
  scenarios vs the Python oracle, FIFO + seeds 1-3, 12 adversarial cases, regressions,
  source gates). LocalFlow passes `lang check --mode=verified` with zero errors and its
  manifest selects verified mode.
- Required-feature coverage: FEATURE_MATRIX.md — 178 rows COMPLETE, 6 DEFERRED (V3
  9.4 or semantics-neutral optimisation TYP-14), 1 OUT_OF_SCOPE (STD-06, IMPL-007).
  Evidence references are validated by tests/unit/test_feature_matrix.py.
- Work items: 236/239 DONE (`python tools/workitems.py summary`); open: AUDIT-002,
  AUDIT-003, FINAL-001.
- Open regression bugs: 0 (BUG-0001..0015 fixed, each with a regression test that
  failed first; LF-001..003 and ORACLE-001 in examples/localflow/regressions).

## First coverage sweep (RUN0 §U) — outcome
Gaps found by rereading V3 and closed with implementation + tests:
- Standard library (6.14/7.15): std.regex, std.datetime, std.chan, std.order.
- Defects: BUG-0011 (type parameters in value position), BUG-0012 (unknown-method
  code), BUG-0013 (effect variables in returned fn types), BUG-0014 (parser crash on
  `let ()`), BUG-0015 (named imports typed Dyn — 10 false verified errors in
  LocalFlow).
- Diagnostics: every live runtime code now tested; dead codes removed; flattened
  quiet view and cancellation summaries (7.13.6); render budget (7.13.5); seeded
  scheduling history (7.14.5); capacity-liveness note (7.11.3); large-copy root
  detail (7.10.10); S.EFFECT.BROAD_CATCH.
- Evidence added for waiter FIFO, after-commit cancellation, task-result
  classification, release failure during abandonment, failure ordering, absence
  of every rejected/deferred feature, and property/fuzz suites (schedule
  interleavings, graph copy, exhaustiveness vs brute force).

## Blockers / ambiguities
- None blocking. AMB-001..010 resolved narrowly (DECISIONS.md), to be listed in
  FINAL_REPORT.md.

## Next actions
1. Second independent coverage/correctness audit (AUDIT-002, subagent).
2. LocalFlow final adversarial review (AUDIT-003).
3. FINAL_REPORT.md (FINAL-001) and final green run of both suites.
