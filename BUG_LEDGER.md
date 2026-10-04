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
Commit: 3dcea3c
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
Commit: 3dcea3c
Status: fixed

BUG-0003
Origin: checker integration review (conformance test
  `test_on_abandon_restricted_to_builtin_primitives` asserted the wrong code)
Subsystems: resources × diagnostics
Symptom: the runtime's defence-in-depth check for `onAbandon` (only built-in
  abandonment-safe release primitives, V3 5.5.10-12) abandoned with the unrelated
  code A.RESOURCE.PROVIDER_OUTSIDE_USE, so tools and readers could not distinguish
  "provider used outside `use`" from "unsafe abandonment action".
Minimal reproduction: tests/regressions/test_bug_0003_on_abandon_code.py (runs the
  interpreter without the static checker, which now rejects this statically)
Regression test failed before fix: yes
Fix: exec_OnAbandonStmt reports A.RESOURCE.ON_ABANDON_RESTRICTED (new code in
  lang/diagnostics/codes.py); the conformance test asserts the static code
  S.RESOURCE.ON_ABANDON_RESTRICTED.
Commit: a67c865
Status: fixed

BUG-0004
Origin: writing checker conformance tests (one-line enum/match forms)
Subsystems: parser (match arms × record/enum members × select branches)
Symptom: after consuming a `,` separator the parser still required a newline, so
  `match x { 1 => 10, _ => 0 }`, `enum Color { Red, Green, Blue }` and
  `record P { x: Int, y: Int }` were rejected with S.SYNTAX.MISSING_SEPARATOR,
  contradicting the syntax contract.
Minimal reproduction: tests/regressions/test_bug_0004_comma_separators.py
Regression test failed before fix: yes (4 of 5 cases; the fifth pins that a missing
  separator without a comma is still reported)
Fix: a consumed `,` now ends the item exactly like a newline at all three sites in
  lang/syntax/parser.py; syntax.md grammar and SPEC-007 updated to state it.
Commit: be0d02c
Status: fixed
