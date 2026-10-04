"""Channel selection (V3 5.14, 6.10, 7.12, 8.13-8.17)."""
from tests.helpers import ok, run


def test_select_receive_from_ready_channel():
    r = ok("""
async fn main() {
    let a = Channel[Str].unbounded()
    let b = Channel[Str].unbounded()
    let ra = a.receiver()
    let rb = b.receiver()
    try await b.sender().send("from b") catch ChannelClosed => ()
    let v = select {
        receive x from ra => "a: {x}"
        receive y from rb => "b: {y}"
    }
    print(v)
}""")
    assert r.lines == ["b: from b"]


def test_losing_branches_have_no_effect():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let b = Channel[Int].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    try await ta.send(1) catch ChannelClosed => ()
    try await tb.send(2) catch ChannelClosed => ()
    let first = select { receive x from ra => x
 receive y from rb => y }
    print(first, ra.tryReceive(), rb.tryReceive())
}""")
    assert r.lines == ["1 TryReceive.WouldBlock TryReceive.Message(value: 2)"]


def test_rotating_fairness_no_starvation():
    r = ok("""
async fn main() {
    let a = Channel[Str].unbounded()
    let b = Channel[Str].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    for i in 0..3 { try await ta.send("a") catch ChannelClosed => ()
 try await tb.send("b") catch ChannelClosed => () }
    let order = MutableList[Str]()
    for i in 0..6 {
        order.push(select { receive x from ra => x
 receive y from rb => y })
    }
    print(order.freeze().join(""))
}""")
    assert r.lines == ["ababab"]


def test_priority_select_prefers_source_order():
    r = ok("""
async fn main() {
    let a = Channel[Str].unbounded()
    let b = Channel[Str].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    for i in 0..2 { try await ta.send("a") catch ChannelClosed => ()
 try await tb.send("b") catch ChannelClosed => () }
    let order = MutableList[Str]()
    for i in 0..4 {
        order.push(select priority { receive x from ra => x
 receive y from rb => y })
    }
    print(order.freeze().join(""))
}""")
    assert r.lines == ["aabb"]


def test_fairness_cursor_is_per_activation():
    r = ok("""
async fn pick(ra: ReceivePort[Str], rb: ReceivePort[Str]) -> Str {
    return select { receive x from ra => x
 receive y from rb => y }
}
async fn main() {
    let a = Channel[Str].unbounded()
    let b = Channel[Str].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    for i in 0..2 { try await ta.send("a") catch ChannelClosed => ()
 try await tb.send("b") catch ChannelClosed => () }
    print(await pick(ra, rb), await pick(ra, rb))
}""")
    assert r.lines == ["a a"]


def test_select_now_none_ready():
    r = ok("""
fn main() {
    let a = Channel[Int].unbounded()
    let ra = a.receiver()
    let tx = a.sender()
    let v = select now { receive x from ra => "got {x}"
 none ready => "nothing" }
    print(v)
}""")
    assert r.lines == ["nothing"]


def test_blocking_select_has_no_default_branch():
    r = run("""
async fn main() { let a = Channel[Int].unbounded()
 let ra = a.receiver()
 select { receive x from ra => x
 none ready => 0 } }""")
    assert "S.SELECT.NONE_READY_PLACEMENT" in r.check_errors or r.codes == ["A.RUNTIME.INVALID_ARGUMENT"]


def test_select_deadline_after_and_at():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let ra = a.receiver()
    let tx = a.sender()
    let v = select { receive x from ra => "msg"
 after 20.millis => "timeout" }
    let deadline = time.now() + 5.millis
    let w = select { receive x from ra => "msg"
 at deadline => "deadline" }
    print(v, w)
}""")
    assert r.lines == ["timeout deadline"]


def test_guards_disable_branches():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let b = Channel[Int].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    try await ta.send(1) catch ChannelClosed => ()
    try await tb.send(2) catch ChannelClosed => ()
    let wantA = false
    let wantB = true
    let v = select { when wantA: receive x from ra => x
 when wantB: receive y from rb => y }
    print(v)
}""")
    assert r.lines == ["2"]


def test_closed_branch_explicit_outcome():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let ra = a.receiver()
    let tx = a.sender()
    try await tx.send(1) catch ChannelClosed => ()
    a.close()
    let out = MutableList[Str]()
    for i in 0..2 {
        out.push(select { receive x from ra => "msg {x}"
 closed ra => "closed" })
    }
    print(out)
}""")
    assert r.lines == ['MutableList["msg 1", "closed"]']


def test_closed_receive_without_closed_branch_throws():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let ra = a.receiver()
    a.close()
    let v = try select { receive x from ra => x } catch ChannelClosed as e => -1
    print(v)
}""")
    assert r.lines == ["-1"]


def test_send_branch_commits_once():
    r = ok("""
async fn main() {
    let a = Channel[Int].buffered(1)
    let b = Channel[Int].buffered(1)
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    let v = 42
    let which = select { send v to ta => "a"
 send v to tb => "b" }
    print(which, ra.tryReceive(), rb.tryReceive())
}""")
    assert r.lines == ["a TryReceive.Message(value: 42) TryReceive.WouldBlock"]


def test_task_completion_branch_does_not_cancel_other_tasks():
    r = ok("""
async fn quick() -> Int { await sleep(1.millis)
 return 1 }
async fn slow() -> Int { await sleep(30.millis)
 print("slow finished")
 return 2 }
async fn main() {
    parallel {
        let q = spawn quick()
        let s = spawn slow()
        let first = select { task q completed as r => "quick {r}"
 task s completed as r => "slow {r}" }
        print(first)
    }
}""")
    assert r.lines == ["quick Ok(1)", "slow finished"]


def test_task_branch_failure_is_observed_result():
    r = ok("""
error E { }
async fn bad() -> Int throws E { throw E() }
async fn main() {
    parallel {
        let h = spawn bad()
        let v = select { task h completed as r => r.isErr() }
        print(v)
    }
}""")
    assert r.lines == ["true"]


def test_select_waits_until_peer_commits():
    r = ok("""
async fn later(tx: SendPort[Str]) throws ChannelClosed { await sleep(10.millis)
 try await tx.send("late") }
async fn main() throws AggregateException {
    let a = Channel[Str].rendezvous()
    let ra = a.receiver()
    parallel {
        spawn later(a.sender())
        let v = select { receive m from ra => m
 after 1.seconds => "timeout" }
        print(v)
    }
}""")
    assert r.lines == ["late"]


def test_select_cancellation_before_commit_consumes_nothing():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let ra = a.receiver()
    let tx = a.sender()
    let r = try within 5.millis { select { receive x from ra => x } } catch DeadlineExceeded => -1
    try await tx.send(9) catch ChannelClosed => ()
    print(r, ra.tryReceive())
}""")
    assert r.lines == ["-1 TryReceive.Message(value: 9)"]


def test_select_ring_buffer_recorded_in_diagnostics():
    r = run("""
async fn main() {
    let a = Channel[Int].unbounded()
    let ra = a.receiver()
    let tx = a.sender()
    try await tx.send(1) catch ChannelClosed => ()
    let v = select { receive x from ra => x }
    assert v == 2
}""")
    assert r.codes == ["A.ASSERT.FAILED"]
    ev = r.diag.select_events[-1]
    assert ev["chosen"] == 0 and ev["ready"] == [0]


def test_dynamic_select_receive():
    r = ok("""
async fn main() {
    let a = Channel[Int].unbounded()
    let b = Channel[Int].unbounded()
    let tb = b.sender()
    try await tb.send(5) catch ChannelClosed => ()
    a.close()
    let ports = [a.receiver(), b.receiver()]
    let s1 = await selectReceive(ports)
    print(s1.index, s1.outcome)
}""")
    assert r.lines[0] in ('0 Received.Closed(reason: "ControllerClosed")', "1 Received.Message(value: 5)")


def test_dynamic_select_task():
    r = ok("""
async fn w(n: Int) -> Int { await sleep(n.millis)
 return n }
async fn main() {
    parallel {
        let hs = [spawn w(20), spawn w(5)]
        let s = await selectTask(hs)
        print(s.index, s.result)
    }
}""")
    assert r.lines == ["1 Ok(5)"]


def test_seeded_random_tie_breaking():
    src = """
async fn main() {
    let a = Channel[Str].unbounded()
    let b = Channel[Str].unbounded()
    let ta = a.sender()
    let tb = b.sender()
    let ra = a.receiver()
    let rb = b.receiver()
    for i in 0..5 { try await ta.send("a") catch ChannelClosed => ()
 try await tb.send("b") catch ChannelClosed => () }
    let out = MutableList[Str]()
    for i in 0..10 { out.push(select { receive x from ra => x
 receive y from rb => y }) }
    print(out.freeze().join(""))
}"""
    x = ok(src, schedule="random", seed=1)
    y = ok(src, schedule="random", seed=1)
    assert x.lines == y.lines and x.lines[0].count("a") == 5
