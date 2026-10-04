# Formatter, CLI, test runner and REPL

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Canonical, deterministic, idempotent, authoritative formatter; tool edits are
  ordinary reviewable source edits; patches instead of silent mutation where wanted
  (4.8, 7.14.3).
- Command family `run`, `check`, `format`, `repl`, `test`; draft/verified,
  quiet/deep/JSON, seeded scheduling stress (7.14.2, 7.14.5).
- First-class REPL with runtime module loading and explicit reload (7.14.4).

## 2. Operational interpretation
- Formatter (`lang/format/`): see SPEC-025 for the layout. It refuses sources with
  syntax errors and refuses its own output unless it parses to a structurally equal
  AST (`equiv.py`, which identifies `-(n)` with the literal `-n`) with the same
  number of comments.
- CLI (`lang/tooling/cli.py`): `run [--mode] [--release] [--clock] [--schedule]
  [--seed] [--json|--quiet|--deep] file [args…]`; `check [--fix [--diff]] [--json]`;
  `format [--check|--diff]`; `test [--filter] [--repeat] [--schedule --seed]
  [--json]`; `repl`; `lock`.
- Test runner (`testrunner.py`): fresh interpreter per test, virtual clock by default,
  `W.TEST.SEED` reproduce diagnostics under random scheduling.
- REPL (`repl.py`): SPEC-024.

## 3. Specification-stage choices
SPEC-021 (tests), SPEC-024 (REPL), SPEC-025 (formatter/test runner).

## 4. Ambiguities
None.

## 5. Interactions
Diagnostics (all tools render the same objects), modules (`--fix` uses import
candidates), scheduler (stress mode).

## 6. Conformance tests
`tests/tooling/test_cli.py`, `tests/tooling/test_repl.py`,
`tests/fuzz/test_formatter_fuzz.py`.
