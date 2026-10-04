# Values, bindings, equality and numerics

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Frozen by default; mutable records/collections are explicit and identity-bearing
  (5.1.1-7); module globals are frozen constants only (5.2).
- No automatic cross-type coercion (5.3.4); no truthiness (2.7, 4.2).
- `T?` = `Option[T]`, `null` = `None`; uninitialised is a binding state (5.4).
- Strings are code-point sequences; interpolation never calls user code (7.1.5, 7.3.3).

## 2. Operational interpretation
- Runtime values (`lang/runtime/values.py`): `int`, `float`, `bool`, `str` carry the
  language primitives; `FrozenList/FrozenMap/FrozenSet`, `MutableList/MutableMap/
  MutableSet`, `FrozenRecord/MutableRecord`, `VariantValue` (enum cases, Option,
  Result), `TupleValue`, `Closure`, `Duration`, `Instant`, `UNIT`.
- Equality (`lang/runtime/equality.py`): structural for frozen values, identity for
  mutable records and collections; different runtime types are unequal, except
  Int vs Float which abandons (`A.TYPE.OPERAND_MISMATCH`). Python `==` is never used
  on language values (`True == 1`, `1 == 1.0` do not leak).
- Hash keys: Map keys/Set elements must be frozen (`A.TYPE.UNHASHABLE`); NaN keys
  abandon (`A.NUMERIC.NAN_KEY`). Iteration order is insertion order.
- Arithmetic: Int×Int→Int, Float×Float→Float, `Int / Int` → Float, `a.div(b)` floor
  division, `%` floored modulo, division by zero abandons, `checkedDiv` → `Int?`.
  `&& || !` take and return Bool.
- Bindings: `let` reassignable, `const` not, `let x: T` uninitialised until assigned
  (`A.BINDING.UNINITIALISED` on early read). Closures capture bindings; reassigning a
  captured binding needs `nonlocal`.
- Freezing: `.freeze()` deep-copies into frozen values; `.mutableCopy()` the reverse.

## 3. Specification-stage choices
SPEC-002 (bindings), SPEC-003 (capture), SPEC-005 (`Dyn`), SPEC-008 (collections),
SPEC-009 (strings), SPEC-010 (operators, numerics, provisional NaN policy).

## 4. Ambiguities
- AMB-007: identity equality of mutable values with `W.TYPE.IDENTITY_EQUALITY` advice.
- NaN policy is provisional (IEEE propagation, visible at structural boundaries).

## 5. Interactions
- Frozen record fields must have transitively frozen types (`S.TYPE.FROZEN_FIELD_TYPE`).
- Task/channel isolation shares frozen values and graph-copies mutable ones
  (`isolation.md`).
- `old()` snapshots only frozen/primitive results (`contracts.md`).

## 6. Conformance tests
`tests/conformance/test_values.py`, `test_functions_records.py` (records, `with`,
module constants), `tests/regressions/test_bug_0005_negative_literal_span.py`.
