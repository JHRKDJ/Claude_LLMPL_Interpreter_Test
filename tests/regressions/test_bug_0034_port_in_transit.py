"""BUG-0034 (second audit, C12/F12): a receive port travelling inside a buffered message
(sent on another channel, not yet received) had no holder, so the data channel reported
`NoReceivers` and refused sends although the receiver would be delivered and still worked
(V3 5.13.5: ports are capabilities; 5.13.11: sends fail only when no receivers remain)."""
from tests.helpers import run

SRC = """
async fn fwd(rx: ReceivePort[Int], mtx: SendPort[ReceivePort[Int]]) throws ChannelClosed {
    try await mtx.send(rx)
}
async fn main() throws ChannelClosed, AggregateException {
    let data = Channel[Int].unbounded()
    let dtx = data.sender()
    let meta = Channel[ReceivePort[Int]].unbounded()
    let mtx = meta.sender()
    let mrx = meta.receiver()
    let rx = data.receiver()
    parallel {
        spawn fwd(rx, mtx)
        rx.release()
    }
    let r = try await dtx.send(5) catch ChannelClosed as e => print("send failed:", e.reason)
    let rx2 = try await mrx.receive()
    print("got port back; tryReceive:", rx2.tryReceive())
}"""


def test_port_in_transit_still_counts_as_receiver():
    r = run(SRC)
    assert r.lines == ["got port back; tryReceive: TryReceive.Message(value: 5)"], r.text()


def test_in_transit_hold_released_when_carrier_cannot_deliver():
    r = run("""
async fn main() throws ChannelClosed {
    let data = Channel[Int].unbounded()
    let dtx = data.sender()
    let meta = Channel[ReceivePort[Int]].unbounded()
    let mtx = meta.sender()
    let mrx = meta.receiver()
    let rx = data.receiver()
    try await mtx.send(rx)
    rx.release()
    mrx.release()
    let r = try await dtx.send(5) catch ChannelClosed as e => print("send failed:", e.reason)
}""")
    assert r.lines == ["send failed: NoReceivers"], r.text()
