# Functions, records, variants and pattern matching

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- One explicit function family (`fn`, `async fn`, lambdas) (6.1, 7.1.3-7.1.6).
- Nominal records; frozen by default; methods with explicit `self` (5.1, 6.5).
- Closed variants with exhaustive matching; runtime backstop in draft, static proof
  in verified (3.3, 5.15.5).
- Optional values are `Option`; no null distinct from `None` (5.4).

## 2. Operational interpretation
- Function bodies return Unit unless `return e` runs; `if`/`match`/`use`/`select`/
  `parallel`/`within` blocks yield their last expression (SPEC-004).
- Calls: positional then named arguments; defaults evaluated per call; arity and
  annotation checks at the boundary (`A.TYPE.ARITY`, `A.TYPE.DYNAMIC_MISMATCH`).
- Records: construction by named fields (`P(x: 1)`), positional only for single-field
  records; missing fields `S.TYPE.MISSING_FIELD`; field types checked shallowly at
  construction; `with` on frozen records only; mutable records via field assignment.
- Enums: cases always qualified (`Color.Red`) except core `Some/None/Ok/Err`.
  Payload fields are read only through patterns.
- Patterns: wildcard, binding (optionally typed: `x: Int` tests the runtime type),
  literals, qualified case/record patterns with positional or named sub-patterns,
  tuples, or-patterns (`a | b`), guards (`if`). `match` with no matching arm abandons
  (`A.MATCH.NO_ARM`).
- Exhaustiveness (`lang/check/exhaustive.py`): usefulness algorithm over Bool,
  Option, Result, enums, error enums, tuples and records; open types (Int, Str, …)
  require a catch-all; guarded arms never count; unreachable arms are advisories.

## 3. Specification-stage choices
SPEC-004 (functions/lambdas), SPEC-006 (records), SPEC-007 (variants, comma or
newline separators).

## 4. Ambiguities
None beyond the decisions above.

## 5. Interactions
- Methods of invariant-bearing records run under the outermost-call invariant rule
  (`contracts.md`).
- Payload bindings whose static type relies on an annotation get transient checks
  (IMPL-004, `typing_and_effects.md` §4).

## 6. Conformance tests
`tests/conformance/test_functions_records.py`, `tests/conformance/test_checker.py`
(`non_exhaustive_*`, `unreachable_arm`, `exhaustive_*`),
`tests/interactions/test_modes.py::test_exhaustiveness_runtime_in_draft_static_in_verified`,
`tests/regressions/test_bug_0004_comma_separators.py`.
