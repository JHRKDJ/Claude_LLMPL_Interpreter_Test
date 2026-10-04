# Static checking, gradual types and effects — implementation contract

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
Dynamic, strong, non-coercing default (5.3.1, 5.3.4); written annotations are
runtime-enforced in both modes (5.3.2-3); transient checks (5.3.7, 7.6.2-3);
dynamic callables narrowed before verified invocation (5.3.10, 7.7.6); declared
finite throws sets, `try` at call sites in verified source (3.2, 7.7.3); minimal
effect polymorphism (5.8, 7.7.5, 8.3); exhaustive matching (3.3, 5.15.5); draft vs
verified are acceptance standards, not different languages (5.15, 7.6.4).

## 2. Operational interpretation
- Every expression gets a static type; anything unknown is `Dyn`. `Dyn` is consistent
  with everything. Otherwise types must be *consistent* structurally; nominal records
  /enums/errors by qualified name; a nominal type is consistent with a protocol iff it
  structurally satisfies it (same rules as the runtime shape check, AMB-001).
- `T` is **not** consistent with `T?` (no implicit wrapping: write `Some(x)`).
- Effects: each expression has an effect = set of nominal error types that may escape,
  or *unknown* (calls through `Dyn` callees / unannotated draft functions with unknown
  bodies). Function effects: the written `throws` set if present; otherwise inferred
  from the body (callers in the same program see the inferred set).
- Effect variables (type params in `throws` positions) are bound at call sites from the
  callback arguments' effects and substituted into the callee's effect.
- Cleanup aggregation: a block whose `defer`s may throw while its body may throw (or
  with several throwing defers), a `use` scope whose provider and body may both throw,
  and every `parallel` block that may observe a failure contribute `AggregateException`.

## 3. Obligation policy (DRAFT → severity, VERIFIED → severity)
| Rule | draft | verified |
|---|---|---|
| syntax, unresolved names, duplicates, placement (await/spawn/yield/onAbandon), restricted contract language, broad `else` fallback, throws+Result, provider outside `use`, `none ready` placement, impure select setup, frozen-record field types, invariant-field writes outside methods, `satisfies` violations | error | error |
| missing `try` / handler at a throwing call (`S.EFFECT.MISSING_TRY`) | warning | error |
| escaping error not declared (`S.EFFECT.UNDECLARED_THROWS`) | warning | error |
| static type mismatch, unknown field/method, arity on known callees | warning | error |
| non-exhaustive match on a closed type | warning | error |
| exported fn without parameter/return annotations | — | error |
| Dyn callable invoked (`S.TYPE.DYNAMIC_CALL`) | — | error |
| missing `await` on async call; `await` on non-async | warning | error |
| resource escape / borrow to non-`borrow` parameter | warning | error |
| unsendable spawn argument / capture | warning | error |
| provider not yielding exactly once on every path | warning | error |
| definite assignment | warning | error |
| advisories (select loops, scope width, state horizon, identity equality, useless `try`, unreachable catch/arm, invariant mutation before a cancellation point) | warning | warning |
| async loop without a cancellation point (`W.CANCEL.NO_CANCELLATION_POINT`): unconditional `while true` | warning | warning |
| … the same for any other `while`/`for` loop ("verified analysis reports", V3 7.10.2) | — | warning |
| task handle escaping its `parallel` block (`S.TASK.HANDLE_ESCAPE`), wrong generic arity | error | error |

Warnings never block execution; errors block `run` (exit status 2).

## 4. Transient checks inserted by the checker (IMPL-004)
Where typed code consumes a nested value whose type comes from an annotation that the
runtime did not check deeply, the checker records `ann["rt_check"] = T` (and the span
of the relied-upon annotation) on: index reads of `List[T]`/`Map[K,V]` elements,
`for` loop elements, and pattern bindings of `Option[T]`/`Result[T,E]` payloads. The
runtime checks those values; failures are `A.TYPE.DYNAMIC_MISMATCH` with the use site
primary and the annotation secondary (V3 7.6.5).

## 5. Conformance tests
`tests/conformance/test_checker.py`, `tests/negative/test_static_errors.py`,
`tests/interactions/test_modes.py`.
