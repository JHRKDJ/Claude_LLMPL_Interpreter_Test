# LocalFlow application regression corpus

One fixture per LocalFlow defect found during acceptance testing and review (ledger:
`../../APP_BUG_LEDGER.md`) (kept separate from
interpreter regressions in `tests/regressions/`). Each is compared against the oracle
by `blackbox_tests/test_regressions.py`.

| fixture | defect |
|---|---|
| r02_cancel_at_zero_dag | LF-001: a cancellation request due at time 0 was evaluated only after the first wait, so the initial ready jobs were started and then cancelled instead of becoming NOT_RUN (spec §5.2: the request is handled in step 1, before starts) |
| r01_ready_at_cancel_time | guard written while isolating LF-001: jobs that become ready exactly at the cancellation instant must be NOT_RUN (passes; kept as a pin) |
| r04_sub_timeout_at_nested_completion, r06_nested_zero_after_completion_at_timeout (r05_sub_timeout_nested_transform_at_boundary: passing pin) | LF-004 (final review D1): a sub-workflow job's timeout cancelled its nested run with `within`, so nested completions (and nested transform outputs) due at exactly `timeoutMs` were reported `CANCELLED` instead of being recorded first (§4.7 makes the timeout a §5.5 cancellation request). The timeout is now passed to the nested engine as its cancellation time |
| r07_sub_timeout_equals_finish, r08_sub_timeout_equals_finish_retry | SPEC-LF-001 (final review D2): a nested run that finishes exactly at `timeoutMs` — the spec combined §5.3 ("finishing at `timeoutMs` times out") with §4.7/§5.5 ("a cancellation request has no effect if every job is final") ambiguously. §4.7 now states that for `subworkflow` jobs the §5.5 reading wins; the oracle already implemented it, LocalFlow followed after the LF-004 fix |
| (all fixtures, `test_schedule_independence.py`) | LF-002: the engine's same-instant barrier (`sleep(0)` then drain) relied on FIFO task order; under `--schedule=random` a batch of completions at one instant could be split, letting a job start in a slot the spec assigns differently (s21 seed 1, s28 seed 2) |

## Oracle corrections
| id | defect in the reference model |
|---|---|
| ORACLE-001 | Found by adversarial case a10: the oracle simulated a sub-workflow completely when the job started and wrote nested transform outputs immediately, so a nested transform that the parent's cancellation interrupted still produced its file. Effects are now recorded with absolute logical times and applied only if the producing job completed before any cancellation. LocalFlow was correct. |
