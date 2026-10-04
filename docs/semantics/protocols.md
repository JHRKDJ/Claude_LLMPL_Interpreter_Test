# Protocols and structural conformance

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Protocols are structural; a protocol annotation performs an immediate shallow
  shape check: methods, arities, declared recoverable effects, metadata (5.3.6).
- Protocol contracts apply whenever a conforming method is invoked; implementations
  may not add preconditions (5.10.8-11, 7.5.1).
- Conformance does not imply sendability (8.9).

## 2. Operational interpretation
- `protocol P { fn m(self, x: Int) -> Str throws E requires … ensures … }`.
- Static (`Checker.conformance`): every protocol method must exist with the same
  parameter count, async-ness, consistent parameter/return types, an effect within
  the protocol's (effect variables accept any), and no added `requires`.
  `satisfies P` on a declaration is checked eagerly (`S.PROTOCOL.NOT_SATISFIED`,
  `S.PROTOCOL.ADDED_PRECONDITION`).
- Runtime (`rtypes.protocol_shape`): the same shape check at typed boundaries;
  failure is `A.TYPE.DYNAMIC_MISMATCH` naming the missing/incompatible member.
- Inherited contracts (AMB-001): calling `m` on a value of type T runs the contracts
  of every protocol that T structurally satisfies and that declares `m`; blame
  names the protocol.

## 3. Specification-stage choices
Declaration syntax as above; `satisfies` is an optional, checked assertion.

## 4. Ambiguities
AMB-001 (global structural conformance; added preconditions make a type
non-conforming). Concern: a protocol in another module can add postconditions to an
existing type's method; recorded for the final report.

## 5. Interactions
Effects (written `throws` on protocol methods), contracts (`contracts.md`), builtin
kinds satisfy protocols by method-name tables.

## 6. Conformance tests
`tests/conformance/test_contracts.py` (protocol shape, arity, effects, added
precondition, inherited contracts), `tests/conformance/test_checker.py`
(`protocol_*` cases).
