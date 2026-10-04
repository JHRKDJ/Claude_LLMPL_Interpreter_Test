"""Cross-feature interactions TEST-INT-011..020 (RUN0 §J; V3 Part VIII)."""
from tests.helpers import check, ok, run

ERR = "error Bad { n: Int }\nerror Other { }\n"

PROV = ERR + """
resource fn conn(id: Int, failRelease: Bool = false) yields Int throws Bad {
    let exit = yield id
    if failRelease { throw Bad(n: 100 + id) }
}
"""


# TEST-INT-011 cleanup x cleanup failure (V3 7.9.5) ------------------------------------
def test_int011_release_failure_after_normal_body_is_the_outcome():
    r = ok(PROV + """
fn main() {
    let r = try use c = conn(1, failRelease: true) { c * 10 } catch Bad as e => e.n
    print(r)
}""")
    assert r.lines == ["101"]


def test_int011_body_and_release_failures_aggregate_body_first():
    r = ok(PROV + """
fn main() {
    let r = try use c = conn(2, failRelease: true) { throw Other() }
        catch AggregateException as agg => agg.entries.length
    print(r)
}""")
    assert r.lines == ["2"]


def test_int011_defer_failures_aggregate():
    r = ok(ERR + """
fn boom(n: Int) throws Bad { throw Bad(n: n) }
fn work() throws Bad, AggregateException {
    defer try boom(1)
    defer try boom(2)
    print("body")
}
fn main() { let r = try work() catch AggregateException as a => a.entries.length
 print(r) }""")
    assert r.lines == ["body", "2"]


# TEST-INT-012 tasks x errors/abandonment/cancellation --------------------------------
def test_int012_child_error_aggregates_and_siblings_cancelled():
    r = ok(ERR + """
async fn bad() -> Int throws Bad { await sleep(1.millis)
 throw Bad(n: 1) }
async fn slow() -> Int { defer print("slow cleaned up")
 await sleep(10.seconds)
 return 2 }
async fn main() {
    let r = try parallel { spawn bad()
     spawn slow()
     0 } catch AggregateException as a => a.entries.length
    print(r)
}""")
    assert r.lines == ["slow cleaned up", "1"]


def test_int012_child_abandonment_abandons_parent_with_group_failure():
    r = run("""
async fn crash() -> Int { let xs = [1]
 return xs[9] }
async fn main() { parallel { spawn crash() } }""")
    assert r.codes == ["A.TASK.GROUP_FAILURE"]
    assert r.diag.children and r.diag.children[0].stable_code == "A.INDEX.OUT_OF_RANGE"


def test_int012_external_cancellation_reaches_children():
    r = ok("""
async fn child(n: Int) { defer print("child", n, "released")
 await sleep(1.seconds) }
async fn main() {
    let r = try within 5.millis { parallel { spawn child(1)
     spawn child(2) }
     "finished" } catch DeadlineExceeded => "deadline"
    print(r)
}""")
    assert sorted(r.lines[:2]) == ["child 1 released", "child 2 released"] and r.lines[2] == "deadline"


# TEST-INT-013 isolation x frozen/mutable/resources (V3 8.2) ---------------------------
def test_int013_cyclic_mutable_graph_is_copied_with_cycle_preserved():
    r = ok("""
mutable record Node { v: Int, next: Node? }
async fn walk(n: Node) -> Int { n.v = 99
 return match n.next { Some(m) => match m.next { Some(k) => k.v, None => -1 }, None => -1 } }
async fn main() {
    let a = Node(v: 1, next: null)
    let b = Node(v: 2, next: Some(a))
    a.next = Some(b)
    let seen = parallel { let h = spawn walk(a)
     await h }
    print(seen, a.v)
}""")
    assert r.lines == ["99 1"]  # child saw its own copy's cycle; parent's value untouched


def test_int013_resource_deep_in_argument_graph_rejected_before_child_starts():
    r = run("""
resource fn tok() yields Int { yield 1 }
async fn child(xs: Dyn) { print("child started") }
async fn main() {
    use t = tok() {
        let holder = MutableList[Dyn]()
        holder.push(MutableList.of(t))
        parallel { spawn child(holder) }
    }
}""")
    assert r.lines == [] and r.codes and r.codes[0] in ("A.TASK.NOT_SENDABLE", "A.RESOURCE.ESCAPE")


def test_int013_closure_with_mutable_capture_not_sendable():
    r = run("""
async fn apply(f: Dyn) -> Int { return f() }
async fn main() {
    let n = 0
    let bump = fn() { nonlocal n
     n = n + 1
     return n }
    parallel { spawn apply(bump) }
}""")
    assert "A.TASK.NOT_SENDABLE" in r.codes or "S.TASK.CAPTURE_MUTABLE" in r.check_codes


def test_int013_frozen_values_shared():
    r = ok("""
record Cfg { name: Str, limits: List[Int] }
async fn total(c: Cfg) -> Int { return c.limits.length }
async fn main() { let c = Cfg(name: "x", limits: [1, 2, 3])
 print(parallel { let h = spawn total(c)
  await h }) }""")
    assert r.lines == ["3"]


# TEST-INT-014 channels x task lifetime/cancellation ---------------------------------
def test_int014_receiver_task_exit_releases_port_so_send_fails():
    r = ok("""
async fn consumer(rx: ReceivePort[Int]) -> Int { return try await rx.receive() catch ChannelClosed => -1 }
async fn main() {
    let ch = Channel[Int].buffered(1)
    let tx = ch.sender()
    let rx = ch.receiver()
    let got = parallel { let h = spawn consumer(rx)
     rx.release()  // main created the port, so it holds it too (AMB-006) until released
     try await tx.send(5) catch ChannelClosed => ()
     await h }
    let r = try await tx.send(6) catch ChannelClosed => "closed: no receivers"
    print(got, r)
}""")
    assert r.lines == ["5 closed: no receivers"]


def test_int014_blocked_send_is_cancellable_without_commit():
    r = ok("""
async fn main() {
    let ch = Channel[Int].rendezvous()
    let tx = ch.sender()
    let rx = ch.receiver()
    let r = try within 5.millis { try await tx.send(1) catch ChannelClosed => ()
     "sent" } catch DeadlineExceeded => "timed out"
    let after = rx.tryReceive()
    print(r, after)
}""")
    assert r.lines == ["timed out TryReceive.WouldBlock"]  # nothing was committed


# TEST-INT-015 select x channels/cancellation/readiness/failure ----------------------
def test_int015_simultaneous_readiness_rotates_and_cancellation_before_commit():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let b = Channel[Int].unbounded()
    let ra = a.receiver()
    let rb = b.receiver()
    let ta = a.sender()
    let tb = b.sender()
    for i in 0..4 { try await ta.send(i) catch ChannelClosed => ()
     try await tb.send(10 + i) catch ChannelClosed => () }
    let picks = MutableList[Int]()
    for i in 0..4 {
        let v = try select { receive x from ra => x
         receive y from rb => y } catch ChannelClosed => -1
        picks.push(v)
    }
    print(picks)
    let empty = Channel[Int].unbounded()
    let re = empty.receiver()
    let keep = empty.sender()
    let r = try within 2.millis { try select { receive x from re => x } catch ChannelClosed => -1 }
        catch DeadlineExceeded => -2
    print(r, re.tryReceive())
}""")
    assert r.lines[0] == "MutableList[0, 10, 1, 11]"
    assert r.lines[1].startswith("-2")


def test_int015_task_branch_observes_failure_as_result():
    r = ok(ERR + """
async fn bad() -> Int throws Bad { throw Bad(n: 4) }
async fn main() {
    let v = parallel { let h = spawn bad()
     select { task h completed as res => match res { Ok(x) => x, Err(e) => e.n * 10 } } }
    print(v)
}""")
    assert r.lines == ["40"]


# TEST-INT-016 concurrent failures x aggregation x diagnostics (V3 8.10, 8.11) -------
def test_int016_two_failures_one_handled_no_duplicates():
    r = run(ERR + """
async fn bad(n: Int) -> Int throws Bad { await sleep(n.millis)
 throw Bad(n: n) }
async fn main() throws AggregateException {
    parallel {
        let h1 = spawn bad(1)
        let h2 = spawn bad(2)
        let x = try await h1 catch Bad => 0
        await h2
    }
}""")
    assert r.codes == ["R.ERROR.UNHANDLED"]
    d = r.diag
    assert d.extra.get("error_type") == "AggregateException"
    paths = [c.task.path for c in d.children if c.task]
    assert len(paths) == len(set(paths)) == 1


def test_int016_external_cancellation_and_group_failure_both_reported():
    r = ok(ERR + """
async fn bad() -> Int throws Bad { await sleep(1.millis)
 throw Bad(n: 1) }
async fn slow() { await sleep(1.seconds) }
async fn outer() throws AggregateException { parallel { spawn bad()
 spawn slow() } }
async fn main() {
    let r = try within 1.millis { try await outer() catch AggregateException => "group failed"
     "after" } catch DeadlineExceeded => "deadline still delivered"
    print(r)
}""")
    assert r.lines == ["deadline still delivered"]


# TEST-INT-017 error effects x higher-order functions (V3 8.3) -----------------------
def test_int017_effect_variable_inferred_from_callback():
    src = ERR + """
fn apply[E](f: fn(Int) -> Int throws E, x: Int) -> Int throws E { return try f(x) }
fn risky(x: Int) -> Int throws Bad { if x > 1 { throw Bad(n: x) }
 return x }
fn safe(x: Int) -> Int { return x + 1 }
pub fn quiet() -> Int { return apply(safe, 1) }
pub fn loud() -> Int { return try apply(risky, 5) catch Bad as e => e.n }
fn main() { print(quiet(), loud()) }"""
    assert check(src, "verified").check == []
    assert ok(src).lines == ["2 5"]


def test_int017_unhandled_callback_effect_reported_at_call_site():
    r = check(ERR + """
fn apply[E](f: fn(Int) -> Int throws E, x: Int) -> Int throws E { return try f(x) }
fn risky(x: Int) -> Int throws Bad { throw Bad(n: x) }
pub fn loud() -> Int { return apply(risky, 5) }""")
    assert "S.EFFECT.MISSING_TRY" in r.check_errors and "S.EFFECT.UNDECLARED_THROWS" in r.check_errors


def test_int017_result_function_captures_throwing_callback():
    r = ok(ERR + """
fn collect(f: fn(Int) -> Int throws Bad, xs: List[Int]) -> Result[List[Int], Bad] {
    let out = MutableList[Int]()
    for x in xs { out.push(propagate (capture f(x))) }
    return Ok(out.freeze())
}
fn risky(x: Int) -> Int throws Bad { if x == 2 { throw Bad(n: x) }
 return x * 10 }
fn main() { print(collect(risky, [1, 3]), collect(risky, [1, 2, 3])) }""")
    assert r.lines == ["Ok([10, 30]) Err(Bad(n: 2))"]


# TEST-INT-018 exceptions x Results x channels (V3 8.4) ------------------------------
def test_int018_err_payload_is_data_and_send_failure_is_separate():
    r = ok(ERR + """
async fn main() {
    let ch = Channel[Result[Int, Bad]].buffered(4)
    let tx = ch.sender()
    let rx = ch.receiver()
    try await tx.send(Err(Bad(n: 3))) catch ChannelClosed => print("closed?")
    let m = try await rx.receive() catch ChannelClosed => Ok(-1)
    print(m)
    ch.close()
    let s = try await tx.send(Ok(1)) catch ChannelClosed => "send failed: closed"
    print(s)
}""")
    assert r.lines == ["Err(Bad(n: 3))", "send failed: closed"]


# TEST-INT-019 resources x async suspension (V3 8.5) ---------------------------------
def test_int019_borrow_crosses_await_in_same_task_and_cancellation_releases():
    r = ok("""
resource fn tok() yields Int { defer print("released")
 yield 7 }
async fn use_after_wait(t: borrow Int) -> Int { await sleep(1.millis)
 return t + 1 }
async fn main() {
    let v = use t = tok() { await use_after_wait(t) }
    print(v)
    let r = try within 1.millis { use t = tok() { await sleep(1.seconds)
     0 } } catch DeadlineExceeded => -1
    print(r)
}""")
    assert r.lines == ["released", "8", "released", "-1"]


def test_int019_borrow_cannot_be_spawned():
    r = check("""
resource fn tok() yields Int { yield 7 }
async fn child(t: borrow Int) -> Int { return t }
async fn f() -> Int { return use t = tok() { parallel { let h = spawn child(t)
 await h } } }""")
    assert "S.TASK.NOT_SENDABLE" in r.check_errors


# TEST-INT-020 resources x expression blocks x contracts (V3 8.7) --------------------
def test_int020_body_value_saved_release_then_postcondition():
    r = ok("""
mutable record Trace { steps: MutableList[Str] }
resource fn file(tr: Trace) yields Int { tr.steps.push("open")
 yield 5
 tr.steps.push("release") }
fn analyse(tr: Trace) -> Int ensures result == 10 {
    let report = use f = file(tr) { tr.steps.push("body")
     f * 2 }
    tr.steps.push("bind " + "{report}")
    return report
}
fn main() { let tr = Trace(steps: MutableList[Str]())
 print(analyse(tr))
 print(tr.steps) }""")
    assert r.lines == ["10", 'MutableList["open", "body", "release", "bind 10"]']
