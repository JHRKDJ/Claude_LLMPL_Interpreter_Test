# Structured tasks, cancellation and isolation

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Only `async fn` suspends; `await` is visible (7.10.2). Task creation is lexically
  visible and scoped; children quiesce before the group returns (5.12, 7.10.3).
- Group modes: fail-fast, collect-all, race, first-success with the outcome tables
  of 7.10.4-7.10.7; abandonment dominates; `AggregateException` even for one child.
- Cancellation is cooperative, delivered at cancellation points, maskable during
  cleanup, never catchable (5.6, 7.10.11). Deadlines are absolute (5.14.14, 7.12.9).
- Isolation: share frozen, graph-copy mutable (cycles and aliases preserved), reject
  resources/borrows/controllers/handles (5.11, 7.10.10). Deterministic scheduling;
  seeded randomisation only in test/stress mode (5.14.10, 7.14.5).

## 2. Operational interpretation
- Scheduler (IMPL-001/002): one language task runs at a time; FIFO or seeded random
  ready-queue choice; real or virtual clock.
- `parallel [collect|race|firstSuccess] { … spawn f(args) … }`; `spawn` only
  lexically inside the body (AMB-008, `S.TASK.SPAWN_OUTSIDE_GROUP`); handles are
  `Task[T, E]`, immutable, unsendable, unusable after the group (AMB-012,
  `S.TASK.HANDLE_ESCAPE`, `A.TASK.HANDLE_OUTSIDE_SCOPE`).
- Fail-fast observation rule (AMB-002); awaiting cancelled/abandoned children
  (AMB-003); external cancellation of children propagates after quiescence (BUG-0002).
- External cancellation × child failure (5.12.11/8.11): fail-fast and collect process
  the failure and keep the cancellation pending (BUG-0023); first-success aggregates
  only when every child failed, otherwise the cancellation propagates (AMB-013).
- Cancel scopes (task, group, `within`) cascade to nested groups and children.
  Cancellation points (AMB-004): `await`, `cancel.check()`, `sleep`, waits in
  `within`/select/channels. `W.CANCEL.NO_CANCELLATION_POINT` (unconditional loops in
  both modes; every loop in verified).
- Deadlock (every task blocked, no timer): leaves abandon with
  `A.CONCURRENCY.DEADLOCK` including blocked-task summary and channel provenance.
- Isolation (`runtime/isolation.py`): `Transfer` classifies and copies at spawn
  arguments, captures and channel commits; `A.TASK.NOT_SENDABLE` for rejections;
  `W.TASK.LARGE_COPY` above `large_copy_threshold`. Static: `S.TASK.NOT_SENDABLE`,
  `S.TASK.CAPTURE_MUTABLE`.

## 3. Specification-stage choices
SPEC-017 (syntax), SPEC-023 (await on async calls).

## 4. Ambiguities
AMB-002, AMB-003, AMB-004, AMB-008, AMB-011 (collect report holds frozen values),
AMB-012.

## 5. Interactions
Resources (borrows never cross tasks; release on cancellation), invariants
(abandonment supersedes cancellation), channels/select (cancellation before commit).

## 6. Conformance tests
`tests/conformance/test_tasks.py`, `tests/regressions/test_bug_0002_group_external_cancel.py`,
`tests/conformance/test_checker.py` (task rows), `tests/tooling/test_cli.py::test_test_command_and_seeded_stress`.
