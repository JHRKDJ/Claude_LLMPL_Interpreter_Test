# Writing LocalFlow in the language — experience log

Evidence recorded while implementing LocalFlow (input to FINAL_REPORT.md). Each
entry: what happened, whether it was a language/implementation problem or a
programmer error, and the diagnostic quality.

1. **Statements in match arms.** `None => return x` and `Some(s) => for ...` are
   syntax errors: arms take expressions; statements need `{ ... }`. Diagnostic:
   `S.SYNTAX.EXPECTED_EXPRESSION` at the keyword — accurate, but it does not suggest
   the braces. (Programmer error; diagnostic could be more helpful.)
2. **`{}` as an empty map inside a block.** `if c { m } else { {} }` parses the inner
   `{}` as a bare block (`S.SYNTAX.MISPLACED_CONSTRUCT: bare blocks are not
   statements`). `Map.empty()` works. This is a real ambiguity of brace syntax with
   brace map literals in statement position. (Language-design friction.)
3. **Leading `&&` on a continuation line** is rejected by design (V3 7.1.2 prefers
   explicit continuation). The `S.SYNTAX.EXPECTED_PATTERN` reported inside a match arm
   is less clear than the usual `S.SYNTAX.LEADING_OPERATOR`. (Programmer error;
   diagnostic quality issue in arm context.)
4. **`pop()` returns `T?`.** I wrote `let (v, i) = work.pop()`; the checker did not
   flag destructuring an Option — an interpreter (checker) defect, BUG-0009, fixed with
   a regression test. Root cause of my mistake: Python habit (`list.pop()` returns
   the element). The language's checked twin design (V3 7.7.2) is right; the gap was
   diagnostic.
5. **Tuple type arguments in value position** (`MutableList[(Str, Int)]()`) were
   typed as `Dyn`, giving a false non-exhaustiveness warning (BUG-0009).
6. **`Int / Int` is a Float.** I first wrote `n * (n + 1) / 2` for an integer sum;
   the language's true division (SPEC-010) would have produced a Float and abandoned
   at the `Int` boundary. `.div(2)` is explicit. Python/C habits collide here; the
   static checker reports the mismatch, which is the intended safety net.
7. **`W.STATE.LARGE_MUTABLE_RECORD` was useful.** The first engine state record had
   15 per-run maps; the advisory pointed at V3 3.1, and splitting it into a per-job
   `JobState` plus a small `RunState` made the transitions (and their contracts)
   simpler.
8. **`W.STATE.PASS_THROUGH` false positive.** A `Progress` sink is threaded
   `perform → attemptWithTimeout → attempt → subworkflow → engine.run` because a
   *cancelled* nested run cannot return its report as a value; only the last function
   uses it. This is explicit dependency passing of the kind V3 3.1 calls conforming;
   the heuristic cannot tell. Recorded, not "fixed" in the application.
9. **`import a.{X}` does not bind `a`.** Using both `a.f()` and `X` needs two imports.
   Clear `S.NAME.UNRESOLVED`; consistent with the module design.
10. **Deterministic logical time on a concurrent runtime was the hardest part.**
    The spec promises that all completions at one logical instant are processed as
    one batch. My first engine waited `sleep(0)` and drained the channel — correct
    under the default FIFO scheduler, but `lang test`-style randomised scheduling
    (`--schedule=random`) immediately exposed the hidden ordering assumption
    (LF-002): exactly the purpose V3 7.14.5 gives the stress mode. The fix needed
    (a) every duration expressed as an absolute deadline on the run's millisecond
    grid, (b) an explicit rule for the timeout boundary instead of relying on which
    of two simultaneous timers fires first, (c) a nanosecond-offset tie-break for
    first-success mirrors, and (d) an adaptive barrier plus heartbeat events from
    nested runs (LF-003). V3 has no "wait until every other task is blocked"
    primitive, and should not (it would leak scheduler internals), so a program that
    needs instant-level batching must build its own protocol. This is evidence that
    structured concurrency + virtual time makes such behaviour *testable*, but
    expressing "all simultaneous events" is not free.
11. **Cancellation reporting through `defer`.** A cancelled runner cannot return
    data, but its `defer` can `trySend` a final event (non-blocking commit is not a
    cancellation point, AMB-004) and a nested run's `defer` can write its partial
    report into a same-task sink. This worked first time and reads naturally.
12. **Fail-fast by failing the group body.** Aborting the run by throwing from the
    `parallel` body makes the language cancel all running jobs and wait for their
    cleanup (scratch markers removed, atomic writes rolled back) — the structured
    concurrency rules did exactly what the application spec needed.
13. **First real use of the formatter** (on LocalFlow) found two layout defects the
    fuzz corpus had not: a blank line was inserted between a declaration and its
    leading comment, and a short `if c { a } else { b }` argument was exploded over
    five lines. Both fixed in the formatter; its self-verification (re-parse and
    compare, including comment count) also caught a lost comment in the first fix
    attempt before it could reach any file.
