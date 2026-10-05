"""BUG-0021 (second audit, C04/F4): a task handle (or other reject-policy capability)
nested inside a frozen collection crossed task and channel boundaries, because the
frozen-graph scan only looked for ports. V3 5.11: a task handle is "not an arbitrary
message value"; a bare handle was already rejected."""
from tests.helpers import run


def test_handle_in_frozen_list_task_argument_rejected():
    r = run("""
async fn work() -> Int { await sleep(1.millis)
   return 7 }
async fn child(hs: List[Dyn]) -> Int { return 0 }
async fn main() {
    parallel {
        let t = spawn work()
        spawn child([t])
    }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"], r.text()


def test_handle_in_frozen_list_message_rejected():
    r = run("""
async fn work() -> Int { await sleep(1.millis)
   return 7 }
async fn main() {
    let ch = Channel[List[Dyn]].unbounded()
    let tx = ch.sender()
    parallel {
        let t = spawn work()
        try await tx.send([t]) catch ChannelClosed => ()
    }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"], r.text()


def test_ports_in_frozen_list_still_shared():
    r = run("""
async fn use1(ps: List[SendPort[Int]]) throws ChannelClosed { try await ps[0].send(3) }
async fn main() throws ChannelClosed, AggregateException {
    let ch = Channel[Int].buffered(1)
    let rx = ch.receiver()
    parallel { spawn use1([ch.sender()]) }
    print(try await rx.receive())
}""")
    assert r.lines == ["3"], r.text()


def test_closure_capturing_a_handle_is_not_sendable():
    r = run("""
async fn work() -> Int { await sleep(1.millis)
   return 7 }
async fn child(f: fn() -> Dyn) -> Int { return 0 }
async fn main() {
    parallel {
        let t = spawn work()
        spawn child(fn() => t)
    }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"], r.text()
