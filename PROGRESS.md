# PROGRESS

## Current state
- Phase: complete. All RUN0 phases are done: implementation, LocalFlow, first coverage
  sweep (§U), second independent audit (§V), LocalFlow final adversarial review (§W),
  final green run (§X), FINAL_REPORT.md (§Y).
- Language suite: `python -m pytest tests -q` → 2387 passed.

  | suite | tests |
  |---|---|
  | unit | 47 |
  | conformance | 334 |
  | negative | 64 |
  | interactions | 72 |
  | regressions | 180 |
  | fuzz/property | 1670 |
  | tooling | 20 |

  Eight consecutive full runs on a quiet tree were all green. The single unexplained
  failure seen mid-run came from a background loop running against a tree that was
  being edited; it never reproduced.
- LocalFlow: `python -m pytest examples/localflow -q` → 446 passed, compared with the
  Python oracle byte for byte: file bytes, stdout, directories with modes, and report
  layout. The total includes:
  - 30 acceptance scenarios (FIFO and seeds 1-3);
  - 12 adversarial cases;
  - 17 regression fixtures;
  - 87 independent-review fixtures (FIFO and seed 5);
  - source gates.

  LocalFlow passes `lang check --mode=verified` with 0 errors and 11 advisories.
- Required-feature coverage (FEATURE_MATRIX.md): 178 COMPLETE, 6 DEFERRED (V3 9.4, or
  the semantics-neutral optimisation TYP-14), 1 OUT_OF_SCOPE (STD-06, IMPL-007).
- Work items: 290/290 DONE (`python tools/workitems.py summary`).
- Open regression bugs: 0.
  - Interpreter: BUG-0001..0053, each with a regression test that failed first.
  - Application: LF-001..007, ORACLE-001..003 and SPEC-LF-001..004 in
    `examples/localflow/APP_BUG_LEDGER.md`.

## Audit outcomes
- First coverage sweep (§U): stdlib gaps (std.regex, std.datetime, std.chan,
  std.order); BUG-0011..0015; diagnostics coverage.
- Second independent audit (§V, two subagent auditors: concurrency and types):
  BUG-0016..0050. AMB-002's timing dependence and the "creator holds sender" friction
  were reviewed and kept, with rationale in DECISIONS.md.
- LocalFlow final review (§W): sub-workflow timeout at the nested completion instant
  (LF-004); four spec repairs (text rules, output paths, nested timeout, D9-D12
  clarifications); two oracle fixes; a byte-level harness. It also found two
  interpreter defects: atomic-write file mode (BUG-0051) and firstSuccess under
  external cancellation (BUG-0052, V3 ambiguity AMB-013).
- Final green run: CLI verification found BUG-0053 (`compareTo` only on `Str`, so
  `std.order` could not sort Ints); fixed with a regression test.

## Blockers / ambiguities
- None blocking. AMB-001..013 are resolved in DECISIONS.md and discussed in
  FINAL_REPORT.md §4-§5.

## Next actions
- None required by RUN0. FINAL_REPORT.md §14 proposes one next experiment: a
  cold-start agent implementing LocalFlow from the guide and spec only.
