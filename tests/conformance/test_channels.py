"""Channels (V3 5.13, 6.9, 7.11, 8.4, 8.12)."""
from tests.helpers import ok, run


def test_rendezvous_send_receive():
    r = ok("""
async fn producer(tx: SendPort[Int]) throws ChannelClosed { for i in 0..3 { try await tx.send(i) } }
async fn main() throws ChannelClosed, AggregateException {
    let ch = Channel[Int].rendezvous()
    parallel {
        spawn producer(ch.sender())
        let rx = ch.receiver()
        for _ in 0..3 { print(try await rx.receive()) }
    }
}""")
    assert r.lines == ["0", "1", "2"]


def test_buffered_capacity_and_backpressure():
    r = ok("""
async fn producer(tx: SendPort[Int]) throws ChannelClosed {
    for i in 0..4 { try await tx.send(i)
 print("sent {i}") }
}
async fn main() throws ChannelClosed, AggregateException {
    let ch = Channel[Int].buffered(2)
    parallel {
        spawn producer(ch.sender())
        let rx = ch.receiver()
        await sleep(10.millis)
        print("consumer starts")
        for _ in 0..4 { print("got {try await rx.receive()}") }
    }
}""")
    assert r.lines[:3] == ["sent 0", "sent 1", "consumer starts"]
    assert r.lines.count("got 0") == 1 and r.lines[-1] in ("got 3", "sent 3")


def test_close_drains_buffer_then_reports_closure():
    r = ok("""
async fn main() {
    let ch = Channel[Str].buffered(4)
    let tx = ch.sender()
    let rx = ch.receiver()
    try await tx.send("a") catch ChannelClosed => ()
    try await tx.send("b") catch ChannelClosed => ()
    ch.close()
    for await msg in rx { print(msg) }
    let r = try await rx.receive() catch ChannelClosed as e => "closed: {e.reason}"
    print(r)
    let s = try await tx.send("c") catch ChannelClosed as e => print("send failed: {e.reason}")
}""")
    assert r.lines == ["a", "b", "closed: ControllerClosed", "send failed: ControllerClosed"]


def test_closure_is_permanent():
    r = ok("""
async fn main() {
    let ch = Channel[Int].unbounded()
    ch.close()
    ch.close()
    print(ch.isClosed())
}""")
    assert r.lines == ["true"]


def test_no_receivers_remain_send_fails():
    r = ok("""
async fn consumer(rx: ReceivePort[Int]) throws ChannelClosed { print("got {try await rx.receive()}") }
async fn main() throws AggregateException {
    let ch = Channel[Int].buffered(1)
    let tx = ch.sender()
    parallel {
        let rx = ch.receiver()
        spawn consumer(rx)
        rx.release()
        try await tx.send(1) catch ChannelClosed as e => print("unexpected {e.reason}")
    }
    try await tx.send(2) catch ChannelClosed as e => print("send failed: {e.reason}")
}""")
    assert r.lines == ["got 1", "send failed: NoReceivers"]


def test_no_senders_remain_receiver_sees_closure():
    r = ok("""
async fn producer(tx: SendPort[Int]) throws ChannelClosed { try await tx.send(7) }
async fn main() throws AggregateException {
    let ch = Channel[Int].buffered(4)
    let rx = ch.receiver()
    parallel {
        let tx = ch.sender()
        spawn producer(tx)
        tx.release()
    }
    for await v in rx { print(v) }
    print("closed because no senders remain")
}""")
    assert r.lines == ["7", "closed because no senders remain"]


def test_competing_consumers_each_message_once():
    r = ok("""
async fn worker(name: Str, rx: ReceivePort[Int], out: SendPort[Str]) throws ChannelClosed {
    for await n in rx { try await out.send("{name}:{n}") }
}
async fn main() throws ChannelClosed, AggregateException {
    let jobs = Channel[Int].buffered(10)
    let results = Channel[Str].unbounded()
    let tx = jobs.sender()
    let rx = results.receiver()
    parallel {
        spawn worker("a", jobs.receiver(), results.sender())
        spawn worker("b", jobs.receiver(), results.sender())
        for i in 0..6 { try await tx.send(i) }
        jobs.close()
        let seen = MutableList[Int]()
        for _ in 0..6 {
            let s = try await rx.receive()
            seen.push(s.split(":")[1].toInt().unwrap())
        }
        print(seen.freeze().sorted())
    }
}""")
    assert r.lines == ["[0, 1, 2, 3, 4, 5]"]


def test_same_task_order_preserved():
    r = ok("""
async fn main() {
    let ch = Channel[Int].unbounded()
    let tx = ch.sender()
    let rx = ch.receiver()
    for i in 0..5 { try await tx.send(i) catch ChannelClosed => () }
    ch.close()
    let got = MutableList[Int]()
    for await v in rx { got.push(v) }
    print(got)
}""")
    assert r.lines == ["MutableList[0, 1, 2, 3, 4]"]


def test_mutable_messages_are_copied():
    r = ok("""
mutable record Msg { n: Int }
async fn main() {
    let ch = Channel[Msg].unbounded()
    let tx = ch.sender()
    let rx = ch.receiver()
    let m = Msg(n: 1)
    try await tx.send(m) catch ChannelClosed => ()
    m.n = 2
    let got = try await rx.receive() catch ChannelClosed => Msg(n: -1)
    print(got.n, m.n, got == m)
}""")
    assert r.lines == ["1 2 false"]


def test_message_type_checked():
    r = run("""
async fn main() {
    let ch = Channel[Int].unbounded()
    let tx = ch.sender()
    try await tx.send("x") catch ChannelClosed => ()
}""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]


def test_resource_cannot_be_sent():
    r = run("""
resource fn tok() yields Int { yield 1 }
async fn main() {
    let ch = Channel[Dyn].unbounded()
    let tx = ch.sender()
    use t = tok() { try await tx.send(t) catch ChannelClosed => () }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]


def test_controller_not_sendable_ports_are():
    r = run("""
async fn use_ch(c: Dyn) { }
async fn main() {
    let ch = Channel[Int].unbounded()
    parallel { spawn use_ch(ch) }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]
    assert "controller" in r.diag.message


def test_try_send_try_receive():
    r = ok("""
fn main() {
    let ch = Channel[Int].buffered(1)
    let tx = ch.sender()
    let rx = ch.receiver()
    print(rx.tryReceive(), tx.trySend(1), tx.trySend(2), rx.tryReceive())
    ch.close()
    print(tx.trySend(3), rx.tryReceive())
}""")
    assert r.lines == ["TryReceive.WouldBlock TrySend.Sent TrySend.WouldBlock TryReceive.Message(value: 1)",
                       'TrySend.Closed(reason: "ControllerClosed") TryReceive.Closed(reason: "ControllerClosed")']


def test_result_message_is_data_not_thrown():
    r = ok("""
error ValidationError { row: Int }
async fn main() {
    let ch = Channel[Result[Int, ValidationError]].unbounded()
    let tx = ch.sender()
    let rx = ch.receiver()
    try await tx.send(Err(ValidationError(row: 3))) catch ChannelClosed => ()
    let m = try await rx.receive() catch ChannelClosed => Ok(0)
    print(match m { Ok(v) => "ok"
 Err(e) => "row {e.row}" })
}""")
    assert r.lines == ["row 3"]


def test_cancellation_before_commit_sends_nothing():
    r = ok("""
async fn main() {
    let ch = Channel[Int].rendezvous()
    let tx = ch.sender()
    let rx = ch.receiver()
    let r = try within 10.millis { try await tx.send(1) catch ChannelClosed => () } catch DeadlineExceeded => "timed out"
    print(r, rx.tryReceive())
}""")
    assert r.lines == ["timed out TryReceive.WouldBlock"]


def test_broadcast_every_subscriber_gets_every_message():
    r = ok("""
async fn listen(name: Str, rx: ReceivePort[Str]) { for await m in rx { print("{name} {m}") } }
async fn main() throws AggregateException {
    let b = Broadcast[Str].buffered(4)
    let publisher = b.publisher()
    parallel {
        spawn listen("x", b.subscribe())
        spawn listen("y", b.subscribe())
        try await publisher.send("hello") catch ChannelClosed => ()
        try await publisher.send("bye") catch ChannelClosed => ()
        b.close()
    }
}""")
    assert sorted(r.lines) == ["x bye", "x hello", "y bye", "y hello"]


def test_broadcast_rejects_mutable_messages():
    r = run("""
async fn main() {
    let b = Broadcast[Dyn].buffered(1)
    let publisher = b.publisher()
    let s = b.subscribe()
    try await publisher.send(MutableList.of(1)) catch ChannelClosed => ()
}""")
    assert r.codes == ["A.CHANNEL.BROADCAST_MUTABLE"]


def test_channel_events_in_deadlock_diagnostic():
    r = run("""
async fn main() {
    let ch = Channel[Int].rendezvous()
    let tx = ch.sender()
    let rx = ch.receiver()
    try await tx.send(5) catch ChannelClosed => ()
}""")
    assert r.codes == ["A.CONCURRENCY.DEADLOCK"]
    assert r.diag.channel.channel_id >= 1


def test_waiter_queue_fifo_cancellation_removes_and_reregistration_joins_back():
    """V3 5.14.18: endpoint waiters are served FIFO; a cancelled waiter is removed and
    a re-registration joins the back of the queue."""
    src = """
async fn recv(name: Str, rx: ReceivePort[Int], log: SendPort[Str]) throws ChannelClosed {
    let v = try await rx.receive()
    try await log.send("{name}:{v}")
}
async fn impatient(rx: ReceivePort[Int], log: SendPort[Str]) throws ChannelClosed {
    let first = try within 3.millis { try await rx.receive() } catch DeadlineExceeded => -1
    try await log.send("b-timeout:{first}")
    let v = try await rx.receive()
    try await log.send("b:{v}")
}
async fn main() throws ChannelClosed, AggregateException {
    let ch = Channel[Int].rendezvous()
    let logc = Channel[Str].unbounded()
    let tx = ch.sender()
    parallel {
        spawn recv("a", ch.receiver(), logc.sender())
        await sleep(1.millis)
        spawn impatient(ch.receiver(), logc.sender())
        await sleep(1.millis)
        spawn recv("c", ch.receiver(), logc.sender())
        await sleep(3.millis)
        for i in 0..3 { try await tx.send(i) }
    }
    logc.close()
    for await m in logc.receiver() { print(m) }
}"""
    for kw in ({}, {"schedule": "random", "seed": 5}, {"schedule": "random", "seed": 9}):
        # which waiter received which message is fixed by the FIFO queue; the order in
        # which the receivers then log it is schedule-dependent
        assert sorted(ok(src, **kw).lines) == ["a:0", "b-timeout:-1", "b:2", "c:1"]


def test_cancellation_after_commit_keeps_the_committed_message():
    """V3 5.13.13: the race winner's send commits to the waiting receiver; the receiver
    is then cancelled, but obtains the committed value first (nothing is lost) and the
    cancellation is delivered at its next cancellation point."""
    r = ok("""
async fn waiter(rx: ReceivePort[Int]) -> Int throws ChannelClosed {
    let v = try await rx.receive()
    print("got {v}")
    await sleep(1.millis)
    print("not reached")
    return v
}
async fn sender(tx: SendPort[Int]) -> Int throws ChannelClosed {
    try await tx.send(7)
    return 0
}
async fn main() throws AggregateException, ChannelClosed {
    let ch = Channel[Int].rendezvous()
    let w = parallel race { spawn waiter(ch.receiver())
        spawn sender(ch.sender()) }
    print("winner {w}")
}""")
    assert r.lines == ["got 7", "winner 0"]


def test_deadlock_on_full_buffer_notes_capacity_dependence():
    r = run("""
async fn main() {
    let ch = Channel[Int].buffered(2)
    let tx = ch.sender()
    let rx = ch.receiver()
    for i in 0..3 { try await tx.send(i) catch ChannelClosed => () }
}""")
    assert r.codes == ["A.CONCURRENCY.DEADLOCK"]
    assert any("is full (2/2)" in n.message and "capacity" in n.message for n in r.diag.notes)
