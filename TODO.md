# TODO — authoritative remaining-work queue

Ordered roughly by dependency. Newly discovered work is appended, never hidden.
`[x]` = implemented and covered by tests; details in FEATURE_MATRIX.md.

## Front end
- [x] Source/spans; diagnostics model + renderers (text, JSON)
- [x] Lexer (tokens, strings/interpolation, trivia)
- [x] Parser: full grammar, continuation rules, recovery (BUG-0004..0007 fixed)
- [x] Formatter (canonical, comments, idempotent, self-verifying) + format CLI

## Core runtime
- [x] Values, equality/hash/display, collections, strings, numerics
- [x] Bindings/scopes/closures/nonlocal; modules/imports/exports/manifest
- [x] Functions, methods, lambdas, control flow, patterns/match
- [x] Errors: throw/try/catch/else/capture/propagate/orThrow, effects runtime, aggregates
- [x] Contracts, predicates, old, invariants, exit ordering
- [x] Types: runtime boundary checks, transient checks (IMPL-004), as/type patterns, generics
- [x] Protocols: shape checks, conformance table, inherited contracts
- [x] Resources: providers, use, borrow, escape rules, release table, onAbandon, defer
- [x] Scheduler/coroutines/clock; async/await
- [x] Task groups (4 modes), handles, cancellation, within, quiescence, reports
- [x] Isolation/sendability/graph copy
- [x] Channels (+broadcast), select (+helpers, fairness, ring buffer)

## Static checker / modes
- [x] Name resolution diagnostics, definite assignment, auto-import (`check --fix`)
- [x] Gradual static types, effects/try, exhaustiveness, contract language rules
- [x] Resource/borrow escape, async/spawn rules, sendability, select purity, advisories
- [x] Draft/verified severity policy; release requires verified

## Tooling
- [x] CLI run/check/format/test/repl; JSON/quiet/deep; schedule random; exit codes
- [x] Test runner with seeded stress; REPL with explicit reload
- [x] docs/LANGUAGE_GUIDE.md (examples executed by tests/unit/test_language_guide.py)

## Tests
- [x] Unit (lexer, parser, architecture, docs consistency, runtime annotations)
- [x] Conformance, negative, mode interactions, regressions, fuzz (formatter, parser)
- [x] Interaction suite TEST-INT-001..030 (tests/interactions/test_interactions_{a,b,c}.py)

## LocalFlow
- [ ] PROGRAM_SPEC.md, TEST_PLAN.md, fixtures, Python oracle, black-box harness
- [ ] Implementation in the language; acceptance suite green; adversarial cases

## Audits / final
- [ ] First V3 coverage sweep; second independent audit; LocalFlow adversarial review
- [ ] WORK_ITEMS.json / FEATURE_MATRIX.md status reconciliation
- [ ] FINAL_REPORT.md; final green run

## Known limitations (recorded, not hidden)
- Checker: disagreeing branch types (if/match arms, try handlers) join to `Dyn` (no
  union types), so such mismatches are caught only at runtime boundaries
  (TEST-INT-001).
- Checker: method calls on `Dyn` receivers are `S.TYPE.DYNAMIC_CALL` errors in
  verified mode; narrowing with `as` is the remedy.
