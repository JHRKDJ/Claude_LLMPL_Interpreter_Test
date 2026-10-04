# Diagnostics: representation and rendering

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Diagnostics are structured objects with stable hierarchical codes, source spans,
  expected/found, values, provenance, task and channel context, fixes (7.13).
- Rendering modes: default, quiet, deep, JSON (7.13.3, 7.14.2). Captured values are
  bounded, cycle-safe and redact `sensitive` fields; capture never runs user code.
- Every failure identifies the boundary, the relied-upon annotation and the use site
  where applicable (5.3.12).

## 2. Operational interpretation
- Model (`lang/diagnostics/model.py`): `Diagnostic(code, message, severity, primary,
  secondary[], notes[], help[], expected, found, values{}, fixes[], propagation[],
  task, channel, select_events[], children[], extra{})`.
- Codes (`codes.py`): `<outcome>.<DOMAIN>.<REASON>`; outcomes `S` static, `W`
  warning/advisory, `A` abandonment, `R` recoverable, `C` cancellation, `H` hard
  termination. Every emitted code is registered; JSON exposes `outcome`, `domain`,
  `reason`, `stable_code` separately.
- Text rendering (`render_text.py`): header `kind[CODE]: message`, `--> file:line:col`,
  source excerpt with labels, expected/found, values, notes, help, fixes, task path,
  stack with frame variables, children (aggregates, task groups).
- Exit codes: 0 ok, 1 unhandled recoverable error, 2 static errors, 3 abandonment,
  4 hard termination, 130 cancelled; an `Int` returned by `main` is the exit code.

## 3. Specification-stage choices
SPEC-022 (code display and JSON fields).

## 4. Ambiguities
None.

## 5. Interactions
All subsystems produce diagnostics; spans of composite expressions include
parentheses (BUG-0005).

## 6. Conformance tests
`tests/tooling/test_cli.py::test_check_json_is_machine_readable`,
`tests/negative/test_static_errors.py`, diagnostic-content assertions across
`tests/conformance/`, `tests/conformance/test_transient_checks.py`.
