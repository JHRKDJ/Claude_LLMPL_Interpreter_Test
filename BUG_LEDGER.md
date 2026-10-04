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
