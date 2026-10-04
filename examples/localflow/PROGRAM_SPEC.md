# LocalFlow — program specification

LocalFlow is a deterministic local workflow/job execution engine. It loads a JSON
workflow definition, validates it, executes its jobs with dependency-aware, bounded
concurrent scheduling, handles retries, timeouts, failures, cancellation and
cleanup, and writes a deterministic machine-readable execution report.

This specification describes externally visible behaviour only. It is independent of
how LocalFlow is implemented. The Python oracle (`reference_model/`) and the
black-box tests (`blackbox_tests/`) are derived from this document.

## 1. Invocation

```
lang run --clock=virtual examples/localflow/src/main.lang WORKFLOW.json OUTDIR
```

- `WORKFLOW.json`: the workflow definition (§2). Relative input paths inside it are
  resolved against the directory containing `WORKFLOW.json`.
- `OUTDIR`: output directory; created if missing. LocalFlow writes
  `OUTDIR/report.json` (§6) and the files produced by `transform` jobs (§4.3).
- Time is *logical*: every duration below is in logical milliseconds; with
  `--clock=virtual` a run takes no wall-clock time and is fully deterministic.

Exit status:

| status | meaning |
|---|---|
| 0 | workflow `SUCCEEDED` |
| 10 | workflow `INVALID` (input or graph errors; no job ran) |
| 11 | workflow `FAILED` |
| 12 | workflow `CANCELLED` |
| 3 | a job hit an internal-defect check (§4.1 `assert`); LocalFlow stops at once and writes **no** report |

Standard output (informational; tests compare it only where stated): one line
`JOBID STATUS` per job in declaration order, then `workflow ID STATUS`. For an
invalid workflow: one line `error CODE JOB` per validation error, then
`workflow ID INVALID`.

## 2. Workflow definition

A JSON object:

| field | type | default | meaning |
|---|---|---|---|
| `workflow` | non-empty string | required | workflow id |
| `jobs` | array of job objects | required | jobs in *declaration order* |
| `maxConcurrency` | integer ≥ 1 | 4 | global limit on simultaneously running jobs |
| `groups` | object name → integer ≥ 1 | `{}` | per-group concurrency limits |
| `onFailure` | `"continue"` or `"failFast"` | `"continue"` | failure policy (§5.4) |
| `cancelAfterMs` | integer ≥ 0 | absent | simulated external cancellation request at that logical time (§5.5) |
| `workflows` | object name → workflow object | `{}` | reusable sub-workflows for `subworkflow` jobs; a sub-workflow may not itself contain `workflows`, `cancelAfterMs` or `subworkflow` jobs |

Job object:

| field | type | default | meaning |
|---|---|---|---|
| `id` | string matching `[A-Za-z0-9_.-]+` | required | stable job id |
| `kind` | one of `compute`, `external`, `transform`, `map`, `reduce`, `check`, `subworkflow` | required | §4 |
| `deps` | array of job ids | `[]` | jobs that must succeed (or be skipped, §5.2) first; duplicates not allowed |
| `when` | `{"job": ID, "equals": Bool}` | absent | run only if job `ID` (which must be in `deps` and be a `check` job) produced `equals` |
| `group` | string | absent | concurrency group; must be a key of `groups` |
| `retry` | `{"maxAttempts": ≥1, "backoffMs": ≥0, "multiplier": ≥1}` | `{1, 0, 1}` | retry policy (§5.3) |
| `timeoutMs` | integer ≥ 1 | absent | per-attempt timeout (§5.3) |
| `config` | object | `{}` | kind-specific configuration (§4) |

Unknown fields are ignored.

## 3. Validation

Validation happens before any job runs. If any error is found, the workflow is
`INVALID`: no job runs, the report has `status: "INVALID"`, every job has status
`NOT_RUN`, and `errors` lists **all** errors found, in this order:

1. JSON syntax error → one error `malformed`, job `null`, and nothing else is checked.
2. Top-level structure (`workflow`, `jobs`, `maxConcurrency`, `groups`,
   `onFailure`, `cancelAfterMs`, `workflows` types/values) → `malformed`, job `null`.
3. For each job in declaration order: field types/values, known `kind`, required
   `config` fields and their types (§4) → `malformed` with that job's id (or `null`
   if the id itself is invalid); a job whose `id` repeats an earlier job's id →
   `duplicate-id` with that id; each `deps` entry naming no job →
   `missing-dependency` (job = the referencing job); `when` naming a job that is not
   in `deps` or is not a `check` job → `malformed`; unknown `group` → `malformed`;
   a `hang` script step (§4.2) in a job with neither `timeoutMs` nor a workflow
   `cancelAfterMs` → `malformed`; a `subworkflow` naming an unknown workflow →
   `missing-workflow`.
4. Dependency cycles → one error `cycle`, job `null`, whose `jobs` field lists, in
   declaration order, every job that lies on a dependency cycle (a job depending on
   itself included).
5. Each sub-workflow in `workflows` is validated with rules 2–4; its errors are
   reported with `workflow` set to the sub-workflow's name.

Error objects: `{"code": CODE, "job": ID or null, "workflow": NAME or null,
"jobs": [IDS] (only for cycle), "message": text}`. Tests compare everything except
`message`.

## 4. Job kinds

Every job produces an *output* (a JSON value) on success. Durations below are
logical time the job occupies a concurrency slot. Failures have a *class* (§6).

### 4.1 `compute` — pure computation
`config`: `op` ∈ `fib`, `sumTo`, `primeCount`, `assert`; `n` integer ≥ 0 (for
`fib`/`sumTo`/`primeCount`); `costMs` integer ≥ 0 (default 0).
After `costMs`: `fib` → the n-th Fibonacci number (fib 0 = 0, fib 1 = 1); `sumTo` →
0 + 1 + … + n; `primeCount` → number of primes ≤ n.
`assert`: `config.value` and `config.expect` integers; if they differ the job has hit
an internal defect: LocalFlow stops immediately (exit 3, no report). If equal,
output is `value`.

### 4.2 `external` — simulated external operation
`config`: `latencyMs` ≥ 0 (default 10); `script`: non-empty array of steps (default
`["ok"]`); `value`: any JSON (default `null`); `mirrors`: optional non-empty array of
objects `{latencyMs, script, value}` with the same defaults.
Attempt `k` (1-based) uses step `script[k-1]`, or the last step if `k` exceeds the
script length. An attempt lasts `latencyMs`, then: `ok` → success with output
`value`; `retryable` → retryable failure; `permanent` → permanent failure; `hang` →
never finishes by itself (only a timeout or cancellation ends it).
With `mirrors`, each attempt queries every mirror concurrently (each using its own
script with the same attempt number). The attempt succeeds with the value of the
mirror that succeeds first (ties: the earliest mirror in the array) and ends at that
moment, cancelling the others. If every mirror fails, the attempt fails when the last
mirror fails: permanently if all mirrors failed permanently, otherwise retryably.

### 4.3 `transform` — local file transformation (resource-backed)
`config`: `input` (path, relative to the workflow file's directory), `output` (file
name, relative to `OUTDIR`), `op` ∈ `upper`, `number`, `csvSum`; `latencyMs` ≥ 0
(default 0); `failAfterWrite` Bool (default false); `failCleanup` Bool (default false).
An attempt:
1. creates the scratch marker file `OUTDIR/.scratch/JOBID` (the job's workspace);
2. reads `input` (missing/unreadable → failure class `io`);
3. computes the result: `upper` → the text upper-cased; `number` → each line prefixed
   with `N: ` (1-based); `csvSum` → the input is CSV with a header row; the output
   is the CSV `column,sum` followed by one row per column, in header order, whose
   sum is the sum of the column's integer values (any non-integer cell → failure
   class `bad-input`);
4. writes the result to `OUTDIR/output` *atomically*: the file appears only if the
   attempt succeeds; it waits `latencyMs` after writing and before committing;
5. if `failAfterWrite`, fails with class `transform` after waiting (so the write is
   rolled back);
6. on every outcome — success, failure, timeout, cancellation — removes the scratch
   marker. If `failCleanup`, removing the workspace fails (the marker is still
   removed): a cleanup failure after a successful body makes the job fail with class
   `cleanup`; after a body failure (`io`, `bad-input`, `transform`) the body's class
   is kept and `"cleanup"` is appended to the error's `details`; during a timeout or
   cancellation the cleanup failure does not change the job's error.
The read happens at the start of the attempt, so `io` and `bad-input` failures occur
0 ms after the attempt starts; the attempt otherwise lasts `latencyMs`.
Output: `{"file": output, "bytes": N}` (N = length of the written text in characters).
After any run no `OUTDIR/.scratch/*` marker remains and no output file exists for a
job that did not succeed.

### 4.4 `map` — fan-out
`config`: `items` (array of integers) or `from` (id of a dependency whose output is
an array of integers); `op` ∈ `square`, `inc`; `failOn`: array of integers (default
`[]`) — items equal to one of these fail; `itemLatencyMs` ≥ 0 (default 0);
`parallelism` ≥ 1 (default 4); `allowPartial` Bool (default false).
Items are processed in consecutive batches of `parallelism` items; the items of a
batch run concurrently and independently (one item failing does not stop the others);
each batch takes `itemLatencyMs`. Output: `{"results": [...], "failed": [...]}` where
`results` has one entry per item (the result, or `null` if it failed) and `failed`
lists the 0-based indices of failed items. If any item failed and `allowPartial` is
false, the job fails with class `partial` (the output is still reported).
`from` naming a job whose output is not an array of integers → class `bad-input`.

### 4.5 `reduce` — aggregation
`config`: `op` ∈ `sum`, `max`, `concat`, `count`. Inputs are the outputs of the job's
`deps` in `deps` order, excluding skipped dependencies. `sum`/`max` accept integers
and arrays of integers (arrays are flattened) and produce an integer (`max` of no
values → class `bad-input`); `concat` accepts arrays and produces their
concatenation; `count` produces the number of inputs. Any other input → `bad-input`.
Duration 0.

### 4.6 `check` — condition
`config`: `input` (a dependency id), `op` ∈ `gt`, `lt`, `eq`, `value` integer. Output
`true`/`false`: `input`'s output compared with `value`. A non-integer input →
`bad-input`. Duration 0. Jobs use the result through `when` (§5.2).

### 4.7 `subworkflow` — composition
`config`: `workflow` (a name in `workflows`). Runs that workflow with the same rules,
starting at the moment the job starts (its own `maxConcurrency`, `groups` and
`onFailure` apply inside it; it does not consume extra parent slots). Its transform
outputs go to `OUTDIR/JOBID/`. The `subreport` uses times relative to the nested
run's start. A timeout of the job acts on the nested run as a cancellation request at
`timeoutMs` (the subreport then has status `CANCELLED`); a retry runs the nested
workflow again and `subreport` describes the last attempt. Output: object mapping each nested job id that
succeeded to its output. Fails with class `subworkflow` unless the nested workflow
succeeded. The nested report appears as the job's `subreport`. Cancellation of the
parent job cancels the nested workflow.

## 5. Execution

### 5.1 Job states
`PENDING` → `RUNNING` → one of `SUCCEEDED`, `FAILED`, `CANCELLED`; or `PENDING` →
`BLOCKED`, `SKIPPED` or `NOT_RUN`. Final statuses: `SUCCEEDED`, `FAILED`,
`CANCELLED` (was running when the run was cancelled or aborted), `BLOCKED` (a
dependency did not succeed), `SKIPPED` (condition false or upstream skipped),
`NOT_RUN` (never started because the run ended first).

### 5.2 Scheduling algorithm (normative)
Logical time starts at 0. The engine repeats *steps*. In each step, at the current
time T:
1. **Record** every job completion that happens at T (all of them, regardless of the
   order in which they occur), and any cancellation request due at T (§5.5).
2. **Resolve** pending jobs until nothing changes, in declaration order: a pending job
   whose dependencies are all final becomes
   - `BLOCKED` if any dependency is `FAILED`, `BLOCKED`, `CANCELLED` or `NOT_RUN`;
     `blockedBy` = the first such dependency in `deps` order; `rootCause` = the
     sorted (declaration order) set of `FAILED`/`CANCELLED` jobs reachable through
     such dependencies;
   - otherwise `SKIPPED` with reason `upstream-skipped` if any dependency is `SKIPPED`;
   - otherwise `SKIPPED` with reason `condition` if its `when` condition is false;
   - otherwise *ready*.
3. **Start** ready jobs in declaration order: a ready job starts at T if fewer than
   `maxConcurrency` jobs are running and (if it has a group) fewer than the group's
   limit of that group's jobs are running; otherwise it waits (later jobs may still
   start).
4. Jobs that take 0 logical time and were started at T complete at T; the step repeats
   at T until a step records nothing new. Then T advances to the next moment at which
   something happens.
After step 1, before resolving: if a cancellation request is due at T and some job is
not final, the run is cancelled (§5.5); otherwise, under `failFast`, if any job
failed in this step the run aborts (§5.4). In both cases the run ends at T.
The run ends when every job is final. `durationMs` = T at that moment.

### 5.3 Attempts, retries and timeouts
A started job makes attempts. `attempts` in the report counts attempts started.
- A failure is *retryable* if its class is `retryable` or `timeout`; others are not.
- After a retryable failure of attempt k < `maxAttempts`, the job waits
  `backoffMs × multiplier^(k-1)` and starts attempt k+1. The job stays `RUNNING` and
  keeps its slot meanwhile.
- With `timeoutMs`, an attempt that has not finished `timeoutMs` after it started
  fails with class `timeout` at exactly that moment (an attempt that would finish at
  exactly `timeoutMs` times out).
- Final failure class: `permanent`, `timeout`, `retries-exhausted` (last failure was
  `retryable`), or the kind's own class (`io`, `bad-input`, `transform`, `partial`,
  `subworkflow`, `cleanup`). Non-retryable classes end the job after one attempt
  (a timeout of a non-external job is retryable like any timeout).

### 5.4 Failure policy
- `continue`: a failed job only affects its dependents (`BLOCKED`); independent jobs
  keep running and starting.
- `failFast`: in the step in which the first job fails — after all completions at
  that moment are recorded, so they keep their own results — every running job is
  cancelled (`CANCELLED`, `end` = T) and every other non-final job becomes
  `NOT_RUN` (`end` = T). The workflow is `FAILED`.

### 5.5 External cancellation
With `cancelAfterMs = C`, a cancellation request occurs at time C. Completions at C are
recorded first (§5.2 step 1); if every job is then final the request has no effect;
otherwise every running job is cancelled (`CANCELLED`, `end` = C) and every other
non-final job becomes `NOT_RUN` (`end` = C). Cancelled jobs release their resources
(transform scratch markers removed, partial outputs not committed). The workflow is
`CANCELLED` (even if some jobs failed earlier). If the workflow finished before C,
the request has no effect.

### 5.6 Workflow status
`INVALID` (validation failed) — else `CANCELLED` (cancellation request took effect)
— else `SUCCEEDED` if every job is `SUCCEEDED` or `SKIPPED` — else `FAILED`.

## 6. Report

`OUTDIR/report.json`, UTF-8 JSON with two-space indentation, keys in the order shown:

```
{
  "workflow": ID,
  "status": "SUCCEEDED" | "FAILED" | "CANCELLED" | "INVALID",
  "durationMs": T,
  "cancelled": Bool,
  "errors": [ validation error objects ],
  "summary": {"SUCCEEDED": n, "FAILED": n, "CANCELLED": n, "BLOCKED": n, "SKIPPED": n, "NOT_RUN": n},
  "jobs": [
    {
      "id": ID, "kind": KIND, "status": STATUS, "attempts": n,
      "start": T or null, "end": T or null,
      "output": JSON or null,
      "error": null or {"class": CLASS, "message": text, "details": [Str]},
      "blockedBy": ID or null, "rootCause": [IDS] or null, "skipReason": "condition" | "upstream-skipped" | null,
      "subreport": nested report or null
    }
  ]
}
```

- `jobs` are in declaration order; for `INVALID` reports all jobs are `NOT_RUN` with
  `attempts` 0 (jobs whose id is invalid are omitted).
- `output` is present for `SUCCEEDED` jobs and for `map` jobs that failed with class
  `partial`; otherwise `null`.
- `error` is present exactly for `FAILED` jobs, and for `CANCELLED` jobs as
  `{"class": "cancelled", ...}`.
- `end` is the time the job became final (for `BLOCKED`/`SKIPPED`/`NOT_RUN` the time
  that was decided; for `INVALID` reports `null`); `start` is the start of the first
  attempt, `null` for jobs that never started.
- `blockedBy`/`rootCause` are set only for `BLOCKED` jobs, `skipReason` only for
  `SKIPPED` jobs, `subreport` only for `subworkflow` jobs that started.
- Tests compare the whole report except `message` fields.

## 7. Non-goals
Persistence/restart from an earlier report, real network access, wall-clock timing,
and concurrency limits across sub-workflow boundaries are out of scope.
