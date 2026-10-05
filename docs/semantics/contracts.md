# Contracts, predicates and invariants

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- `requires`/`ensures` in signatures, a restricted total effect-free contract language,
  `old(expr)` snapshots of primitive/frozen results, non-recursive predicates
  (5.10.1-5, 7.8.1-3).
- Record invariants with controlled mutation of invariant fields; checked at public
  boundaries; broken invariants abandon, superseding cancellation (5.10.6-7, 8.8).
- Contract violations are abandonment with blame (7.8.4).

## 2. Operational interpretation
- Preconditions run before the body (blame: caller); `old` snapshots are taken at
  entry; postconditions after the body with `result` bound (blame: implementation).
  Failures: `A.CONTRACT.PRECONDITION_FAILED` / `POSTCONDITION_FAILED` with the clause
  as primary span and the evaluated sub-expression values.
- Restricted language (`lang/check/contracts_check.py`): literals, names, field reads,
  operators, `is`, `if`/`match` expressions, collection literals, ranges, predicate
  calls, `old` (ensures only), total read-only builtin queries (with inline lambdas
  for `all/any/count`). Prohibited: mutation, I/O, await/spawn/select/resources,
  try/capture/propagate, `xs[i]`, general calls (`S.CONTRACT.RESTRICTED`),
  `old` outside `ensures` (`S.CONTRACT.OLD_OUTSIDE_ENSURES`), `result` outside
  `ensures`, recursive predicates (`S.CONTRACT.RECURSIVE_PREDICATE`).
- `old(e)` with a statically mutable result is `S.CONTRACT.OLD_NOT_SNAPSHOTTABLE`;
  dynamically, `A.CONTRACT.EVALUATION_FAILED`.
- Invariants: checked after construction, after `with`, and at exit (normal,
  exception, cancellation — after cleanup) of each *outermost* method call on the
  object; writes to invariant fields outside the record's methods are
  `S.CONTRACT.INVARIANT_FIELD_WRITE` / `A.CONTRACT.INVARIANT_FIELD_WRITE`; an
  invariant field holding a mutable value cannot even be read outside those methods
  (or contracts) — `S.CONTRACT.INVARIANT_FIELD_ACCESS` / `A.CONTRACT.INVARIANT_FIELD_ACCESS`.
  `W.INVARIANT.ACROSS_AWAIT` warns when a method mutates an invariant field before a
  cancellation point (V3 8.8).

## 3. Specification-stage choices
SPEC-014 (syntax, outermost-call rule, field control).

## 4. Ambiguities
AMB-009 (contracts may read mutable fields), AMB-001 (inherited protocol contracts).

## 5. Interactions
Cancellation × invariants (abandonment supersedes); resources (postconditions cannot
touch released resources); protocols.

## 6. Conformance tests
`tests/conformance/test_contracts.py`, `tests/conformance/test_checker.py`
(`contract_*`, `old_*`, `recursive_predicate`, `invariant_*`),
`tests/negative/test_static_errors.py` (`old_outside_ensures`, `result_outside_ensures`).
