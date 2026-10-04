# TODO — authoritative remaining-work queue

Ordered roughly by dependency. Newly discovered work is appended, never hidden.

## Front end
- [ ] Source/spans; diagnostics model + renderers (text, JSON)
- [ ] Lexer (tokens, strings/interpolation, trivia)
- [ ] Parser: full grammar, continuation rules, recovery
- [ ] Formatter (canonical, comments, idempotent) + format CLI

## Core runtime
- [ ] Values, equality/hash/display, collections, strings, numerics
- [ ] Bindings/scopes/closures/nonlocal; modules/imports/exports/manifest
- [ ] Functions, methods, lambdas, control flow, patterns/match
- [ ] Errors: throw/try/catch/else/capture/propagate/orThrow, effects runtime, aggregates
- [ ] Contracts, predicates, old, invariants, exit ordering
- [ ] Types: runtime boundary checks, transient checks, as/type patterns, generics
- [ ] Protocols: shape checks, conformance table, inherited contracts
- [ ] Resources: providers, use, borrow, escape rules, release table, onAbandon, defer
- [ ] Scheduler/coroutines/clock; async/await
- [ ] Task groups (4 modes), handles, cancellation, within, quiescence, reports
- [ ] Isolation/sendability/graph copy
- [ ] Channels (+broadcast), select (+helpers, fairness, ring buffer)

## Static checker / modes
- [ ] Name resolution diagnostics, definite assignment, auto-import
- [ ] Gradual static types, effects/try, exhaustiveness, contract language rules
- [ ] Resource/borrow escape, async/spawn rules, sendability, select purity, advisories
- [ ] Draft/verified severity policy; release requires verified

## Tooling
- [ ] CLI run/check/format/test/repl; JSON/quiet/deep; schedule random; exit codes
- [ ] Diagnostics: bounded capture/redaction, abandonment frames, task trees, channel/select provenance

## Tests
- [ ] Unit, conformance, negative, interaction (TEST-INT-001..030), regression, fuzz

## LocalFlow
- [ ] PROGRAM_SPEC.md, TEST_PLAN.md, fixtures, Python oracle, black-box harness
- [ ] Implementation in the language; acceptance suite green; adversarial cases

## Audits / final
- [ ] First V3 coverage sweep; second independent audit; LocalFlow adversarial review
- [ ] FINAL_REPORT.md; final green run
