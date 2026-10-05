"""BUG-0035 (second audit, C13/F13): verified mode let several sendability violations
through that only the runtime caught: a closure with mutable or reassigned captures
passed to `spawn` or sent on a channel, a `Broadcast` of a mutable element type, and a
task handle escaping its group inside a closure (V3 5.15.5: verified requires
sendability; 5.11)."""
from tests.helpers import check


def errs(src):
    return check(src, "verified").check_errors


def test_closure_with_mutable_capture_passed_to_spawn():
    assert "S.TASK.NOT_SENDABLE" in errs("""
async fn run(f: fn() -> Int) -> Int { return f() }
pub async fn main() -> Int {
    let c = MutableList[Int]()
    let f = fn() -> Int { c.push(1)
        return c.length }
    return parallel { let h = spawn run(f)
        await h }
}""")


def test_closure_with_mutable_capture_sent_on_channel():
    assert "S.TASK.NOT_SENDABLE" in errs("""
pub async fn main() throws ChannelClosed {
    let ch = Channel[fn() -> Int].unbounded()
    let c = MutableList[Int]()
    let f = fn() -> Int { return c.length }
    try await ch.sender().send(f)
}""")


def test_mutable_broadcast_element_type():
    assert "S.CHANNEL.BROADCAST_MUTABLE" in errs("pub fn f() { let b = Broadcast[MutableList[Int]].buffered(1) }")


def test_handle_escaping_inside_closure():
    assert "S.TASK.HANDLE_ESCAPE" in errs("""
async fn w() -> Int { return 1 }
pub async fn main() -> Int {
    let g: fn() -> Dyn = fn() => 0
    parallel { let h = spawn w()
        g = fn() => h
        await h }
    return 0
}""")


def test_frozen_captures_still_sendable():
    assert errs("""
async fn run(f: fn() -> Int) -> Int { return f() }
pub async fn main() -> Int {
    let k = 3
    let f = fn() -> Int { return k * 2 }
    return parallel { let h = spawn run(f)
        await h }
}""") == []
