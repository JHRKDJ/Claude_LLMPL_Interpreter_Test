# Channels and select

This file is an implementation contract derived from V3.
It has no authority over V3.
If this file conflicts with V3, V3 wins.

## 1. Relevant V3 commitments
- Typed channels with explicit capacity (rendezvous / buffered / unbounded), split
  send/receive ports, explicit closure, endpoint-loss detection, FIFO fairness,
  copy-at-commit isolation, broadcast of frozen values (5.13, 7.11).
- `select` over a closed selectable family with atomic registration/commitment,
  deterministic rotating fairness, explicit priority, `select now` with `none ready`,
  absolute deadlines, precomputed frozen Boolean guards, explicit closed branches,
  task-completion branches, bounded event ring buffer (5.14, 7.12).

## 2. Operational interpretation
- Controller `Channel[T].buffered(n)` → `.sender()`, `.receiver()`, `.close()`.
  `await tx.send(v)` waits for capacity (or a receiver for rendezvous), throws
  `ChannelClosed` after close or when no receivers remain; `await rx.receive()` throws
  `ChannelClosed` once closed and drained. `trySend`/`tryReceive` never wait.
- Endpoint holders (AMB-006/006b): tasks hold port capabilities; holdings end at task
  termination or `port.release()`.
- Waiters are FIFO; a value is graph-copied at commit; each commit has a sequence
  number used in diagnostics.
- `select` (`interp/selectx.py`): branch setup is evaluated once on entry (must be
  pure, `S.SELECT.IMPURE_SETUP`); guards are local Bool bindings
  (`S.SELECT.INVALID_GUARD`); ready branches are chosen by a per-site rotating cursor
  (default), source order (`priority`) or the seeded RNG in stress mode; claim and
  recheck before commit, so losing branches have no effect. A receive on a closed
  port without a `closed` branch throws `ChannelClosed`. `none ready` only (and
  always) in `select now` (`S.SELECT.NONE_READY_PLACEMENT`). Advisories:
  `W.SELECT.DEADLINE_RESET`, `W.SELECT.STARVATION`, `W.SELECT.CLOSED_LOOP`,
  `W.SELECT.BUSY_POLL`. Each task keeps a 32-entry ring of select events attached to
  failure diagnostics.

## 3. Specification-stage choices
SPEC-018 (channel API), SPEC-019 (select syntax, dynamic helpers).

## 4. Ambiguities
AMB-006, AMB-006b, AMB-002 (task branches observe child failures). Several deadline
branches are allowed; the earliest fires.

## 5. Interactions
Isolation (copy at commit), cancellation (select waits are cancellation points;
cancellation before commit leaves no effect), task groups.

## 6. Conformance tests
`tests/conformance/test_channels.py`, `tests/conformance/test_select.py`,
`tests/conformance/test_checker.py` (`select_*`).
