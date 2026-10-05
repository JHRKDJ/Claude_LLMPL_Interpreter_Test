"""BUG-0039 (second audit, C17/F17 minor findings):
(a) a loop whose only "suspension" was `select now` counted as having a cancellation
    point (V3 5.15.6: `select now` never waits);
(b) constructing a frozen record in a select send (`send P(x: n + 1) to tx`) was
    rejected as impure (V3 5.14.4 allows restricted pure expressions);
(c) `spawn connect(3)` of a resource provider produced a spurious
    S.ASYNC.AWAIT_NON_ASYNC about an `await` that was never written;
(d) a bare `TaskGroupReport` return annotation was a static mismatch against the report
    produced by `parallel collect`;
(e) printing a borrow showed `<borrow of p resource>` instead of the value."""
from tests.helpers import check, run


def test_select_now_is_not_a_cancellation_point():
    r = check("""
async fn f(rx: ReceivePort[Int]) {
    let n = 0
    while n < 10 {
        select now { receive v from rx => { n = n + v }
            none ready => { n = n + 1 } }
    }
}""", "verified")
    assert "W.CANCEL.NO_CANCELLATION_POINT" in r.check_codes, r.text()


def test_frozen_record_construction_is_pure_select_setup():
    r = check("""
record P { x: Int }
pub async fn f(tx: SendPort[P], n: Int) throws ChannelClosed {
    select { send P(x: n + 1) to tx => () }
}""", "verified")
    assert "S.SELECT.IMPURE_SETUP" not in r.check_codes, r.text()


def test_spawning_a_provider_reports_only_the_provider_rule():
    r = check("""
resource fn connect(id: Int) yields Int { let e = yield id }
pub async fn main() throws AggregateException { parallel { spawn connect(3) } }""", "verified")
    assert "S.RESOURCE.PROVIDER_OUTSIDE_USE" in r.check_codes
    assert "S.ASYNC.AWAIT_NON_ASYNC" not in r.check_codes, r.text()


def test_bare_task_group_report_annotation():
    r = check("""
async fn leaf(n: Int) -> Int { return n }
pub async fn mid() -> TaskGroupReport {
  return parallel collect { spawn leaf(1) }
}""", "verified")
    assert "S.TYPE.STATIC_MISMATCH" not in r.check_codes, r.text()


def test_borrow_displays_its_value():
    r = run("""
resource fn p() yields Int { let e = yield 41 }
fn main() { use x = p() { print(x, "{x}") } }""")
    assert r.lines == ["41 41"], r.text()


def test_nested_collect_report_is_a_nested_group_outcome():
    r = run("""
async fn leaf(n: Int) -> Int { return n }
async fn mid() -> TaskGroupReport { return parallel collect { spawn leaf(1) } }
async fn main() {
    let rep = parallel collect { spawn mid()
        spawn leaf(3) }
    print(rep.outcomes.map(fn(o) => match o { TaskOutcome.NestedGroup(p, r) => "nested", _ => "other" }))
}""")
    assert r.lines == ['["nested", "other"]'], r.text()


def test_select_ring_records_commit_sequence():
    r = run("""
async fn main() {
    let ch = Channel[Int].unbounded()
    let tx = ch.sender()
    let rx = ch.receiver()
    try await tx.send(1) catch ChannelClosed => ()
    select { receive v from rx => print(v) }
    let xs = [1]
    print(xs[5])
}""")
    assert r.diag.select_events and r.diag.select_events[-1].get("seq") == 1, r.diag.select_events
