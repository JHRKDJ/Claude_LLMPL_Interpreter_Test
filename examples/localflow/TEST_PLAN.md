# LocalFlow — test plan

Black-box acceptance testing of LocalFlow against `PROGRAM_SPEC.md`.

## Method
For every fixture `fixtures/NAME.json` the harness (`blackbox_tests/`) runs

1. the **oracle** — `python reference_model/localflow_ref.py fixtures/NAME.json EXP/`
   (an independent discrete-event simulation of the spec), and
2. **LocalFlow** — `lang run --clock=virtual src/main.lang fixtures/NAME.json OUT/`
   through the interpreter, as a subprocess,

and requires identical externally observable results:

- exit status;
- `report.json`, compared as JSON with every `message` field removed;
- the set of files under the output directory and their exact contents
  (in particular: no `.scratch/*` marker survives; outputs exist only for
  succeeded transform jobs);
- standard output lines.

The harness never inspects interpreter internals. In addition, specific assertions
below pin the behaviour each scenario exists for, so that a shared misreading of the
spec by oracle and implementation is less likely to pass unnoticed.

## Scenario map (RUN0 §O)

| # | scenario | fixture(s) | pinned assertions |
|---|---|---|---|
| 1 | single successful job | s01_single | status SUCCEEDED, output fib(20)=6765, end=costMs |
| 2 | linear chain | s02_chain | each job starts at its dependency's end |
| 3 | diamond DAG | s03_diamond | join starts at max(left, right) end; sum of outputs |
| 4 | wide DAG | s04_wide | 30 independent jobs under maxConcurrency 8; final count 30 |
| 5 | bounded concurrency | s05_bounded | never more than 3 running, group `io` limit 1 |
| 6 | duplicate id | s06_duplicate | INVALID, `duplicate-id` x, exit 10, no job runs |
| 7 | missing dependency | s07_missing_dep | `missing-dependency` on y |
| 8 | cycle | s08_cycle | `cycle` listing a, b, c, d (not e) |
| 9 | retry succeeds | s09_retry_success | attempts 3, backoff 3 then 6, end 24 |
| 10 | retries exhausted | s10_retry_exhausted | class retries-exhausted, attempts 3, dependent BLOCKED |
| 11 | permanent not retried | s11_permanent | attempts 1 despite maxAttempts 5 |
| 12 | timeout | s12_timeout | timeout class; exact-boundary timeout; hang ended by timeout then retried |
| 13 | upstream failure | s13_upstream_failure | mid BLOCKED by src, leaf BLOCKED by mid with rootCause [src] |
| 14 | collect / continue | s14_collect_continue | independent branch completes after a failure |
| 15 | fail-fast cancellation | s15_failfast | running sibling CANCELLED, same-instant completion kept, rest NOT_RUN |
| 16 | cancellation during resource job | s16_cancel_resource | transform CANCELLED, no output, no scratch marker |
| 17 | cleanup after success | s17_resource_success | three outputs with exact contents; no markers |
| 18 | cleanup after recoverable failure | s18_resource_failure | io / bad-input / transform classes; no outputs; no markers |
| 19 | cleanup under cancellation | s19_cleanup_under_cancel | timeout and external cancel both release; failing cleanup during cancel does not change the error |
| 20 | cleanup fails after another failure | s20_cleanup_fails | primary class kept with details [cleanup]; cleanup-only failure class `cleanup` |
| 21 | concurrent failures keep provenance | s21_concurrent_failures | three failures at the same instant all reported with their own classes |
| 22 | fan-out | s22_fanout, s22b_fanout_from_list | batches, partial results, allowPartial, `from` dependency |
| 23 | reduce | s23_reduce | sum/max/concat; concat of a non-list → bad-input |
| 24 | conditional | s24_conditional | false branch SKIPPED(condition), its dependents SKIPPED(upstream-skipped) |
| 25 | sub-workflow | s25_subworkflow, s30g_sub_timeout_retry, s30h_cancel_subworkflow | nested report, nested outputs in OUTDIR/JOB/, failing nested run, timeout+retry, cancellation |
| 26 | deterministic repeat | s26_deterministic | two runs give byte-identical reports and stdout |
| 27 | malformed input | s27_malformed_types, s27b_malformed_json | every listed error, in order |
| 28 | large generated DAG | s28_large (gen_large.py) | 500 jobs, groups, retries, failures; oracle equality |
| 29 | mixed outcomes | s29_mixed | succeeded, failed, retried, blocked, skipped, cancelled and NOT_RUN in one run |
| 30 | adversarial extras | s30_mirrors_race, s30b_empty, s30c_cancel_at_zero, s30d_zero_time_chain, s30e_failfast_zero_time, s30f_assert_defect | first-success mirrors with ties; empty workflow; cancel at 0; zero-duration chains under limit 1; fail-fast triggered by a 0 ms job; internal-defect stop (exit 3, no report) |

## Regression corpus
Every LocalFlow defect found while testing gets a fixture under
`fixtures/regressions/` and an entry in the table above before it is fixed
(application regressions are kept separate from interpreter regressions in
`tests/regressions/`).

## Adversarial review
After the suite is green, `blackbox_tests/test_adversarial.py` adds cases written
by reviewing the spec for behaviours a plausible-but-wrong implementation could get
wrong (ordering of same-instant events, slot release on retry, group limits with
blocked heads, cancellation during backoff, etc.).
