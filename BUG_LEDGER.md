# BUG LEDGER

Meaningful interpreter/toolchain defects discovered during development. Each entry
has a permanent regression test that failed before the fix. LocalFlow application
defects are recorded separately in `examples/localflow/APP_BUG_LEDGER.md`.

Format:

```
BUG-NNNN
Origin: where it was found (unit/conformance/LocalFlow scenario/audit)
Subsystems: ...
Symptom: ...
Minimal reproduction: tests/regressions/...
Regression test failed before fix: yes/no
Fix: ...
Commit: ...
Status: open/fixed
```

---

BUG-0001
Origin: conformance test `test_composed_provider_scoped_delegation` (resources)
Subsystems: resources × call frames (× async/spawn/select frame state)
Symptom: a provider that yields from inside its own `use` scope abandoned with
  A.RESOURCE.MULTIPLE_YIELD; more generally, while a `use` body ran inside a
  provider's `yield`, the logical frame stack still had the suspended provider
  frame on top, so frame-scoped state (provider context, async-ness, spawn groups,
  select fairness cursors, invariant `self` rule) was taken from the wrong activation.
Minimal reproduction: tests/regressions/test_bug_0001_provider_frames.py
Regression test failed before fix: yes (both cases)
Fix: eval_Yield hides the suspended provider frames (restores call depth) while the
  scope body runs and restores them for normal release (lang/runtime/interp/res.py).
Commit: (this commit)
Status: fixed

BUG-0002
Origin: conformance test `test_external_cancellation_plus_group_failure_preserved`
Subsystems: task groups × external cancellation
Symptom: a fail-fast (or collect) group whose children were cancelled by an
  enclosing scope's cancellation returned normally (fail-fast returned the body
  value; collect returned a report) instead of propagating cancellation after
  quiescence.
Minimal reproduction: tests/regressions/test_bug_0002_group_external_cancel.py
Regression test failed before fix: yes (2 of 3 cases; the third pins the
  "unaffected group returns, cancellation stays pending" behaviour)
Fix: group_outcome re-raises cancellation after quiescence when cancellation is
  pending for the owner and any child ended cancelled (lang/runtime/interp/conc.py).
Commit: (this commit)
Status: fixed
