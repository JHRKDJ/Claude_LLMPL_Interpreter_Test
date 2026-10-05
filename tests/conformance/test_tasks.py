"""Structured concurrency: groups, handles, observation, cancellation (V3 5.12, 6.8, 7.10, 8.10, 8.11)."""
from tests.helpers import ok, run

ERR = """
error Boom { n: Int }
error Other { }
"""


def test_parallel_runs_children_and_returns_body_value():
    r = ok("""
async fn work(n: Int) -> Int { await sleep(n.millis)
 return n * 10 }
async fn main() {
    let total = parallel {
        let a = spawn work(3)
        let b = spawn work(1)
        (await a) + (await b)
    }
    print(total)
}""")
    assert r.lines == ["40"]


def test_children_interleave_cooperatively_in_virtual_time():
    r = ok("""
async fn tick(name: Str, n: Int) {
    for i in 0..n { print("{name}{i}")
 await sleep(10.millis) }
}
async fn main() { parallel { spawn tick("a", 2)
 spawn tick("b", 2) } }""")
    assert r.lines == ["a0", "b0", "a1", "b1"]


def test_failfast_one_child_failure_is_aggregate_and_cancels_siblings():
    r = run(ERR + """
async fn bad() -> Int throws Boom { await sleep(5.millis)
 throw Boom(n: 1) }
async fn slow() -> Int {
    defer print("slow cleanup")
    await sleep(1000.millis)
    print("slow finished")
    return 1
}
async fn main() throws AggregateException {
    parallel { spawn bad()
 spawn slow() }
}""")
    assert r.lines == ["slow cleanup"]
    assert r.outcome == "threw"
    d = r.diag
    assert "AggregateException" in d.message
    assert len(d.children) == 1 and "Boom" in d.children[0].message
    assert d.children[0].task.path.endswith("1:bad")


def test_awaited_and_caught_child_failure_is_observed():
    r = ok(ERR + """
async fn bad() -> Int throws Boom { throw Boom(n: 2) }
async fn main() {
    let v = parallel {
        let h = spawn bad()
        try await h catch Boom as e => e.n * 100
    }
    print(v)
}""")
    assert r.lines == ["200"]


def test_awaited_and_captured_child_failure_is_observed():
    r = ok(ERR + """
async fn bad() -> Int throws Boom { throw Boom(n: 3) }
async fn main() {
    let r = parallel { let h = spawn bad()
 capture await h }
    print(r)
}""")
    assert r.lines == ["Err(Boom(n: 3))"]


def test_awaited_uncaught_failure_reported_once():
    r = run(ERR + """
async fn bad() -> Int throws Boom { throw Boom(n: 4) }
async fn main() throws AggregateException {
    parallel { let h = spawn bad()
 let x = try await h }
}""")
    assert r.outcome == "threw"
    assert len(r.diag.children) == 1


def test_unawaited_failure_appears_at_boundary():
    r = run(ERR + """
async fn bad() -> Int throws Boom { throw Boom(n: 5) }
async fn main() throws AggregateException {
    parallel { spawn bad() }
    print("not reached")
}""")
    assert r.outcome == "threw" and r.stdout == ""
    assert len(r.diag.children) == 1


def test_two_failures_one_handled():
    r = run(ERR + """
async fn bad(n: Int) -> Int throws Boom { await sleep(n.millis)
 throw Boom(n: n) }
async fn main() throws AggregateException {
    parallel {
        let a = spawn bad(1)
        let b = spawn bad(1)
        let x = try await a catch Boom => 0
    }
}""")
    assert r.outcome == "threw"
    msgs = [c.message for c in r.diag.children]
    assert len(msgs) == 1


def test_child_abandonment_dominates_and_abandons_parent():
    r = run(ERR + """
async fn crash() { assert false, "child bug" }
async fn bad() throws Boom { throw Boom(n: 1) }
async fn main() throws AggregateException {
    parallel { spawn bad()
 spawn crash() }
}""")
    assert r.outcome == "abandoned"
    assert r.codes == ["A.TASK.GROUP_FAILURE"]
    kinds = sorted(c.stable_code for c in r.diag.children)
    assert "A.ASSERT.FAILED" in kinds and "R.ERROR.UNHANDLED" in kinds


def test_collect_returns_report_with_abandonment_as_data():
    r = ok(ERR + """
async fn good() -> Int { return 1 }
async fn bad() -> Int throws Boom { throw Boom(n: 2) }
async fn crash() -> Int { assert false
 return 0 }
async fn main() {
    let report = parallel collect { spawn good()
 spawn bad()
 spawn crash() }
    for o in report.outcomes {
        print(match o {
            TaskOutcome.Succeeded(taskPath: p, value: v) => "ok {v}"
            TaskOutcome.ThrewException(taskPath: p, exception: e) => "threw"
            TaskOutcome.Abandoned(taskPath: p, report: rep) => "abandoned {rep.code}"
            TaskOutcome.Cancelled(taskPath: p, reason: why) => "cancelled"
            TaskOutcome.NestedGroup(taskPath: p, report: rep) => "nested"
        })
    }
    print("parent continues")
}""")
    assert r.lines == ["ok 1", "threw", "abandoned A.ASSERT.FAILED", "parent continues"]


def test_race_winner_cancels_losers():
    r = ok("""
async fn fast() -> Str { await sleep(10.millis)
 return "fast" }
async fn slow() -> Str { defer print("slow cancelled cleanly")
 await sleep(500.millis)
 return "slow" }
async fn main() { let w = parallel race { spawn slow()
 spawn fast() }
 print(w) }""")
    assert r.lines == ["slow cancelled cleanly", "fast"]


def test_race_winning_failure_is_aggregate():
    r = run(ERR + """
async fn fails() -> Int throws Boom { throw Boom(n: 1) }
async fn slow() -> Int { await sleep(100.millis)
 return 1 }
async fn main() throws AggregateException { let w = parallel race { spawn fails()
 spawn slow() } }""")
    assert r.outcome == "threw" and "AggregateException" in r.diag.message


def test_first_success_tolerates_failures():
    r = ok(ERR + """
async fn fail(n: Int) -> Str throws Boom { await sleep(n.millis)
 throw Boom(n: n) }
async fn succeed() -> Str { await sleep(20.millis)
 return "ok" }
async fn main() { let v = parallel firstSuccess { spawn fail(1)
 spawn succeed()
 spawn fail(2) }
 print(v) }""")
    assert r.lines == ["ok"]


def test_first_success_all_fail_aggregates_all():
    r = run(ERR + """
async fn fail(n: Int) -> Str throws Boom { throw Boom(n: n) }
async fn main() throws AggregateException { let v = parallel firstSuccess { spawn fail(1)
 spawn fail(2) } }""")
    assert r.outcome == "threw" and len(r.diag.children) == 2


def test_spawn_outside_parallel_rejected():
    r = run("""async fn w() { }
async fn main() { spawn w() }""")
    assert "S.TASK.SPAWN_OUTSIDE_GROUP" in r.check_errors


def test_await_outside_async_rejected():
    r = run("""async fn w() { }
fn main() { await w() }""")
    assert "S.ASYNC.AWAIT_OUTSIDE_ASYNC" in r.check_errors


def test_sync_function_cannot_suspend_at_runtime():
    r = run("""fn main() { let f: Dyn = sleep
 f(1.millis) }""")
    assert r.codes == ["A.ASYNC.SYNC_CONTEXT"]


def test_task_isolation_copies_mutable_arguments():
    r = ok("""
mutable record Box { n: Int }
async fn mutate(b: Box) -> Int { b.n = 99
 return b.n }
async fn main() {
    let b = Box(n: 1)
    let v = parallel { let h = spawn mutate(b)
 await h }
    print(v, b.n)
}""")
    assert r.lines == ["99 1"]


def test_graph_copy_preserves_cycles_and_aliases():
    r = ok("""
mutable record Node { label: Str
 next: Dyn }
async fn check(a: Node, b: Node) -> Bool {
    return a.next == b && b.next == a && a.next.next == a
}
async fn main() {
    let a = Node(label: "a", next: null)
    let b = Node(label: "b", next: a)
    a.next = b
    let ok = parallel { let h = spawn check(a, b)
 await h }
    print(ok)
}""")
    assert r.lines == ["true"]


def test_spawn_block_rejects_mutable_capture():
    r = run("""
async fn main() {
    let xs = MutableList.of(1)
    parallel { spawn { xs.push(2) } }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]


def test_spawn_block_rejects_reassigned_capture():
    r = run("""
async fn main() {
    let n = 1
    n = 2
    parallel { spawn { print(n) } }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]


def test_spawn_block_frozen_capture_ok():
    r = ok("""
async fn main() {
    let cfg = {"k": 1}
    let v = parallel { let h = spawn { cfg["k"] + 1 }
 await h }
    print(v)
}""")
    assert r.lines == ["2"]


def test_closure_with_mutable_capture_not_sendable():
    r = run("""
async fn call(f: fn() -> Int) -> Int { return f() }
async fn main() {
    let xs = MutableList.of(1)
    let f = fn() => xs.length
    parallel { spawn call(f) }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]


def test_cancel_check_in_cpu_loop():
    r = ok("""
error Boom { }
async fn spin() -> Int {
    let i = 0
    while true { cancel.check()
 i += 1
 if i % 1000 == 0 { await sleep(1.millis) } }
    return i
}
async fn boom() throws Boom { await sleep(5.millis)
 throw Boom() }
async fn main() {
    let r = capture parallel { spawn spin()
 spawn boom() }
    print(r.isErr())
}""")
    assert r.lines == ["true"]


def test_within_deadline_throws_deadline_exceeded():
    r = ok("""
async fn slow() -> Int { defer print("cleanup")
 await sleep(1.seconds)
 return 1 }
async fn main() {
    let v = try within 50.millis { await slow() } catch DeadlineExceeded => -1
    print(v)
}""")
    assert r.lines == ["cleanup", "-1"]


def test_within_completes_in_time():
    r = ok("""
async fn main() { let v = try within 1.seconds { await sleep(10.millis)
 7 } catch DeadlineExceeded => -1
 print(v) }""")
    assert r.lines == ["7"]


def test_cancellation_not_catchable_and_masked_cleanup_can_await():
    r = ok("""
async fn worker() {
    defer {
        await sleep(5.millis)
        print("async cleanup finished")
    }
    await sleep(1.seconds)
}
async fn main() {
    let r = try within 20.millis { await worker() } catch DeadlineExceeded => "timed out"
    print(r)
}""")
    assert r.lines == ["async cleanup finished", "timed out"]


def test_quiescence_before_exit():
    r = ok("""
async fn child(n: Int) { await sleep((n * 10).millis)
 print("child {n} done") }
async fn main() {
    parallel { spawn child(3)
 spawn child(1)
 spawn child(2) }
    print("after group")
}""")
    assert r.lines == ["child 1 done", "child 2 done", "child 3 done", "after group"]


def test_nested_groups_and_task_paths():
    r = run("""
error E { }
async fn leaf() throws E { throw E() }
async fn mid() throws AggregateException { parallel { spawn leaf() } }
async fn main() throws AggregateException { parallel { spawn mid() } }""")
    assert r.outcome == "threw"
    outer = r.diag
    inner = outer.children[0]
    assert "mid" in inner.task.path
    assert inner.children and "leaf" in inner.children[0].task.path


def test_external_cancellation_plus_group_failure_preserved():
    r = run("""
error E { }
async fn fail() throws E { await sleep(5.millis)
 throw E() }
async fn sleeper() { await sleep(1.seconds) }
async fn outer() throws AggregateException {
    parallel { spawn fail()
 spawn sleeper() }
}
async fn main() {
    let r = try within 5.millis {
        let x = try await outer() catch AggregateException => "group failed"
        print(x)
        await sleep(100.millis)
        "not reached"
    } catch DeadlineExceeded => "deadline"
    print(r)
}""")
    assert r.lines in (["group failed", "deadline"], ["deadline"])


def test_deadlock_detected():
    r = run("""
async fn main() {
    let ch = Channel[Int].rendezvous()
    let rx = ch.receiver()
    let tx = ch.sender()
    let v = try await rx.receive() catch ChannelClosed => -1
}""")
    assert r.codes == ["A.CONCURRENCY.DEADLOCK"]
    assert r.diag.channel is not None


def test_seeded_random_schedule_is_reproducible():
    src = """
async fn w(n: Int) { await sleep(0.millis)
 print(n) }
async fn main() { parallel { for i in 0..6 { spawn w(i) } } }"""
    a = ok(src, schedule="random", seed=7)
    b = ok(src, schedule="random", seed=7)
    assert a.lines == b.lines and sorted(a.lines) == [str(i) for i in range(6)]


def test_task_result_is_classified_at_the_boundary():
    """V3 5.11: task results cross the boundary too; a closure with mutable captures
    cannot be a task result."""
    r = run("""
async fn leak() -> fn() -> Int {
    let xs = MutableList[Int]()
    return fn() => xs.length
}
async fn main() {
    let f = parallel { let h = spawn leak()
        await h }
    print(f())
}""")
    assert r.codes == ["A.TASK.GROUP_FAILURE"]
    assert r.diag.children[0].stable_code == "A.TASK.NOT_SENDABLE"
    assert "task result" in r.diag.children[0].message


def test_mutable_task_result_is_copied_not_aliased():
    r = ok("""
async fn make() -> MutableList[Int] { let xs = MutableList[Int]()
 xs.push(1)
 return xs }
async fn main() {
    let a = parallel { let h = spawn make()
        await h }
    a.push(2)
    print(a)
}""")
    assert r.lines == ["MutableList[1, 2]"]
