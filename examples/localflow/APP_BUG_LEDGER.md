# LocalFlow application bug ledger

Defects in the LocalFlow program (written in the language), in the Python oracle, or
in PROGRAM_SPEC.md. They are kept apart from interpreter defects (`BUG_LEDGER.md`) so
that application bugs and language/implementation bugs can be told apart (RUN0 bug
isolation). Every entry has a permanent fixture under `fixtures/regressions/` (checked
against the oracle by `blackbox_tests/test_regressions.py`) or names the test that pins it.

Classes: `LF-` LocalFlow wrong, oracle right · `ORACLE-` oracle wrong, LocalFlow
right · `SPEC-LF-` the spec was ambiguous or silent; resolved in PROGRAM_SPEC.md.

```
ID
Origin / Symptom / Fixture / Failed before fix / Fix / Interpreter involved?
```

LF-001
Origin: acceptance testing (s30c)
Symptom: a cancellation request due at time 0 was evaluated only after the first wait,
  so the initially ready jobs started and were then cancelled instead of being NOT_RUN
  (§5.2: the request is handled in step 1, before starts).
Fixture: fixtures/regressions/r02_cancel_at_zero_dag.json (r01 is a guard written
  while isolating it)
Failed before fix: yes
Fix: engine.lang checks the due request at the top of each step.
Interpreter involved: no

LF-002
Origin: schedule-independence testing (`--schedule=random`, s21 seed 1, s28 seed 2)
Symptom: the engine's same-instant barrier (`sleep(0)` then drain) relied on FIFO task
  order; random schedules split one instant's completions into two batches.
Fixture: every fixture via blackbox_tests/test_schedule_independence.py
Failed before fix: yes
Fix: absolute millisecond deadlines, an explicit timeout-boundary rule, mirror
  tie-break offsets, adaptive barrier (engine.lang, jobs.lang).
Interpreter involved: no (the random scheduler exposed it, as V3 7.14.5 intends)

LF-003
Origin: acceptance testing (nested zero-time chains)
Symptom: a nested run's zero-time chain could settle after the parent's barrier
  closed, so the parent recorded the sub-workflow one step late.
Fixture: fixtures/regressions/r03_nested_zero_chain_tie.json
Failed before fix: yes
Fix: nested runs send heartbeat events and use a shorter barrier than their parent.
Interpreter involved: no

LF-004
Origin: final adversarial review (AUDIT-003, D1)
Symptom: a sub-workflow job's timeout cancelled its nested run with `within`, so nested
  completions due exactly at `timeoutMs` were reported CANCELLED instead of being
  recorded first (§4.7 makes the timeout a §5.5 cancellation request).
Fixture: fixtures/regressions/r04_sub_timeout_at_nested_completion.json,
  r06_nested_zero_after_completion_at_timeout.json (r05 passes before the fix and pins
  the nested-transform variant)
Failed before fix: yes (r04, r06)
Fix: jobs.lang passes the timeout to the nested engine as its cancellation time and
  reports `timeout` only if that request took effect.
Interpreter involved: no

SPEC-LF-001
Origin: final adversarial review (AUDIT-003, D2)
Symptom: a nested run finishing exactly at `timeoutMs`: §5.3 ("finishing at timeoutMs
  is a timeout") and §4.7 + §5.5 ("the request has no effect when every job is final")
  disagreed. The oracle followed §4.7/§5.5; LocalFlow followed §5.3.
Fixture: fixtures/regressions/r07_sub_timeout_equals_finish.json, r08_..._retry.json
Failed before fix: yes
Fix: PROGRAM_SPEC.md §4.7 states that for `subworkflow` jobs the §5.5 reading wins;
  LocalFlow follows after the LF-004 fix.
Interpreter involved: no

ORACLE-001
Origin: adversarial case a10
Symptom: the oracle simulated a sub-workflow completely when the job started and wrote
  nested transform outputs immediately, so a nested transform interrupted by the
  parent's cancellation still produced its file. LocalFlow was correct.
Fixture: fixtures/adversarial/a10_cancel_while_sub_and_transform.json
Failed before fix: yes (oracle side)
Fix: effects are recorded with absolute logical times and applied only if the
  producing job completed before any cancellation (reference_model/localflow_ref.py).
Interpreter involved: no

LF-005
Origin: final adversarial review (AUDIT-003, D3)
Symptom: `number` on an empty file produced `"1: "` (the empty text was one line).
Fixture: fixtures/regressions/r11_number_empty_file.json
Failed before fix: yes
Fix: an empty text has no lines (jobs.lang transformText; SPEC-LF-002).
Interpreter involved: no

LF-006
Origin: final adversarial review (harness: leftover `.scratch` directories)
Symptom: LocalFlow left an empty `OUTDIR/.scratch` (and empty nested output
  directories); the oracle creates directories only for files it writes. The old
  harness compared regular files only, so this was invisible.
Fixture: every fixture with a transform (harness `tree` comparison), e.g. r01, r11
Failed before fix: yes (once the harness compared directories)
Fix: main.lang prunes empty directories after the run; the spec states that OUTDIR
  holds only the report, succeeded outputs and their directories. A sub-workflow's
  output directory is now created only by the nested transforms that write into it,
  so an internal-defect stop (exit 3, no pruning) leaves no empty `OUTDIR/JOBID`
  (review fixture f29).
Interpreter involved: no

SPEC-LF-002
Origin: final adversarial review (D3, D4, D5)
Symptom: the spec did not define lines, newline handling, CSV cells or integer cells;
  the two implementations relied on host-language defaults (Python `read_text`
  translates CRLF; `split("\n")` on an empty text gives one empty line).
Fixture: r11, r12, r13
Fix: PROGRAM_SPEC.md §4.3 "Text rules": exact UTF-8, `\n` the only terminator, an
  empty text has no lines, csvSum drops one trailing `\r`, integer cell grammar.
Interpreter involved: no (BUG-0045 had already made `toInt` strict, which is why
  `+5` was handled identically once the rule was written down)

ORACLE-002
Origin: final adversarial review (D6)
Symptom: the oracle accepted `NaN`, `Infinity` and `-Infinity` (Python json default);
  they are not JSON and LocalFlow reported `malformed`.
Fixture: r09_infinity_literal.json, r10_nan_literal.json
Failed before fix: yes
Fix: `json.loads(..., parse_constant=...)` rejects them.
Interpreter involved: no

ORACLE-003
Origin: final adversarial review (D3, D5)
Symptom: the oracle read inputs with newline translation (CRLF → LF) and turned an
  empty file into `"\n"` under `number`; undecodable input crashed it.
Fixture: r11, r12, r14
Failed before fix: yes
Fix: exact reads/writes (`newline=""`), empty text special case, `UnicodeDecodeError`
  is `io`.
Interpreter involved: no

LF-007
Origin: final adversarial review (D7, fixture g14)
Symptom: an `output` naming a subdirectory (`d/x.txt`) failed with class `io` in
  LocalFlow (the atomic write needs an existing directory) while the oracle created it.
Fixture: fixtures/regressions/r15_output_subdirectory.json
Failed before fix: yes
Fix: transform creates the output's parent directories (jobs.lang); SPEC-LF-003.
Interpreter involved: no

SPEC-LF-003
Origin: final adversarial review (D7, D8, fixture g14)
Symptom: `output: "../escape.txt"` wrote outside OUTDIR in *both* implementations (and
  an absolute output would have too); the spec said only "file name, relative to
  OUTDIR". Subdirectories were unspecified.
Fixture: fixtures/regressions/r16_output_path_invalid.json, r15
Failed before fix: r15 yes; r16 no (both sides agreed on the unsafe behaviour; it pins
  the new rule)
Fix: §4.3: `output` is `/`-separated non-empty segments, none `.` or `..`, not
  `report.json`, not inside `.scratch`, else `malformed`; subdirectories are created.
  `input` may be absolute or use `..` (reading is the author's choice).
Interpreter involved: no

SPEC-LF-004
Origin: final adversarial review (D9-D12; both implementations already agreed)
Symptom: unclear spec text — whether a backoff ending at the cancellation instant
  starts an attempt (D9); duplicate or dangling deps and `3.0` as an integer (D10); a
  dead "excluding skipped dependencies" clause in reduce (D11); whether nested outputs
  survive a failed/cancelled sub-workflow job (D12).
Fixture: review fixtures g03, g04, f15, f18 (D9); f03, f04, f24 and
  regressions/r17_integers_and_deps (D10); f20, f47 (D11); f34, f49, g13 (D12)
Failed before fix: no (agreed behaviour, documented and pinned)
Fix: spec text states the agreed behaviour (§2 integers, §3 deps, §4.5, §4.7, §5.3).
Interpreter involved: no
