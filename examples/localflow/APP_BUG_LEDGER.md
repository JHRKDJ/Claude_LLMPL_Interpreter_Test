# LocalFlow application bug ledger

Defects in the LocalFlow program (written in the language), in the Python oracle, or
in PROGRAM_SPEC.md. They are kept apart from interpreter defects (`BUG_LEDGER.md`) so
that application bugs and language/implementation bugs can be told apart (RUN0 bug
isolation). Every entry has a permanent fixture under `fixtures/regressions/` (checked
against the oracle by `blackbox_tests/test_regressions.py`) or names the test that pins it.

Classes: `LF-` LocalFlow wrong, oracle right · `ORACLE-` oracle wrong, LocalFlow
right · `SPEC-LF-` the spec was ambiguous or silent; resolved in PROGRAM_SPEC.md.

```
ID
Origin / Symptom / Fixture / Failed before fix / Fix / Interpreter involved?
```

LF-001
Origin: acceptance testing (s30c)
Symptom: a cancellation request due at time 0 was evaluated only after the first wait,
  so the initially ready jobs started and were then cancelled instead of being NOT_RUN
  (§5.2: the request is handled in step 1, before starts).
Fixture: fixtures/regressions/r02_cancel_at_zero_dag.json (r01 is a guard written
  while isolating it)
Failed before fix: yes
Fix: engine.lang checks the due request at the top of each step.
Interpreter involved: no

LF-002
Origin: schedule-independence testing (`--schedule=random`, s21 seed 1, s28 seed 2)
Symptom: the engine's same-instant barrier (`sleep(0)` then drain) relied on FIFO task
  order; random schedules split one instant's completions into two batches.
Fixture: every fixture via blackbox_tests/test_schedule_independence.py
Failed before fix: yes
Fix: absolute millisecond deadlines, an explicit timeout-boundary rule, mirror
  tie-break offsets, adaptive barrier (engine.lang, jobs.lang).
Interpreter involved: no (the random scheduler exposed it, as V3 7.14.5 intends)

LF-003
Origin: acceptance testing (nested zero-time chains)
Symptom: a nested run's zero-time chain could settle after the parent's barrier
  closed, so the parent recorded the sub-workflow one step late.
Fixture: fixtures/regressions/r03_nested_zero_chain_tie.json
Failed before fix: yes
Fix: nested runs send heartbeat events and use a shorter barrier than their parent.
Interpreter involved: no

LF-004
Origin: final adversarial review (AUDIT-003, D1)
Symptom: a sub-workflow job's timeout cancelled its nested run with `within`, so nested
  completions due exactly at `timeoutMs` were reported CANCELLED instead of being
  recorded first (§4.7 makes the timeout a §5.5 cancellation request).
Fixture: fixtures/regressions/r04_sub_timeout_at_nested_completion.json,
  r06_nested_zero_after_completion_at_timeout.json (r05 passes before the fix and pins
  the nested-transform variant)
Failed before fix: yes (r04, r06)
Fix: jobs.lang passes the timeout to the nested engine as its cancellation time and
  reports `timeout` only if that request took effect.
Interpreter involved: no

SPEC-LF-001
Origin: final adversarial review (AUDIT-003, D2)
Symptom: a nested run finishing exactly at `timeoutMs`: §5.3 ("finishing at timeoutMs
  is a timeout") and §4.7 + §5.5 ("the request has no effect when every job is final")
  disagreed. The oracle followed §4.7/§5.5; LocalFlow followed §5.3.
Fixture: fixtures/regressions/r07_sub_timeout_equals_finish.json, r08_..._retry.json
Failed before fix: yes
Fix: PROGRAM_SPEC.md §4.7 states that for `subworkflow` jobs the §5.5 reading wins;
  LocalFlow follows after the LF-004 fix.
Interpreter involved: no

ORACLE-001
Origin: adversarial case a10
Symptom: the oracle simulated a sub-workflow completely when the job started and wrote
  nested transform outputs immediately, so a nested transform interrupted by the
  parent's cancellation still produced its file. LocalFlow was correct.
Fixture: fixtures/adversarial/a10_cancel_while_sub_and_transform.json
Failed before fix: yes (oracle side)
Fix: effects are recorded with absolute logical times and applied only if the
  producing job completed before any cancellation (reference_model/localflow_ref.py).
Interpreter involved: no
