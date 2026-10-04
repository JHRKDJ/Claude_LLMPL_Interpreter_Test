# Draft and verified modes

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Draft permits absent annotations and incomplete static proof, reports missing
  markers without blocking happy-path execution; written annotations, contracts,
  resources, isolation, abandonment and cancellation stay active (5.15.1-4, 7.6.4).
- Verified requires explicit propagation/handling, type consistency, exhaustive
  matching, resource correctness, sendability, effect compatibility; reports async
  regions without cancellation points (5.15.5-6).
- Release builds require verified acceptance; the modes are acceptance standards, not
  two languages (5.15.7-8).

## 2. Operational interpretation
- The checker emits three kinds of findings (`docs/semantics/typing_and_effects.md`
  §3): legality rules (errors in both modes), verified obligations (warnings in
  draft, errors in verified) and advisories (warnings in both).
- `lang run` refuses (exit 2) only on errors; runtime behaviour is identical in both
  modes. `lang run --release` forces verified; `--release --mode draft` is
  `S.MODE.RELEASE_REQUIRES_VERIFIED`.
- The project default comes from `lang.toml` (`[project] mode`), else draft.

## 3. Specification-stage choices
Severity table in `typing_and_effects.md` §3; SPEC-023 (await), AMB-010.

## 4. Ambiguities
AMB-005 (draft absence of `throws`).

## 5. Interactions
Every subsystem's static rules are classified by this table.

## 6. Conformance tests
`tests/interactions/test_modes.py`, `tests/conformance/test_checker.py::test_obligation_policy`.
