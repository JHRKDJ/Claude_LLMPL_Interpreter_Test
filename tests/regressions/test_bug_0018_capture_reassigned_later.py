"""BUG-0018 (second independent audit, F3): a closure capturing a binding that the
enclosing scope reassigns *after* the closure was created was treated as sendable and
shared live across tasks (the child observed the parent's later assignments), and a
spawn block whose capture is reassigned after the spawn was silently snapshotted.
V3 5.11/7.4.3: closures whose captures are not effectively constant are rejected."""
from tests.helpers import run


def test_closure_over_later_reassigned_binding_is_not_sendable():
    r = run("""
async fn watch(get: fn() -> Int) -> Int {
    await sleep(2.millis)
    return get()
}
async fn main() {
    let x = 0
    let get = fn() -> Int { return x }
    parallel {
        spawn watch(get)
        await sleep(1.millis)
        x = 10
    }
}""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"], r.text()


def test_spawn_block_capture_reassigned_after_spawn_is_rejected():
    r = run("""
async fn main() {
    let x = 1
    parallel {
        spawn { await sleep(1.millis)
            print(x) }
        x = 2
    }
}""")
    assert "S.TASK.NOT_SENDABLE" in r.check_codes or r.codes == ["A.TASK.NOT_SENDABLE"], r.text()


def test_effectively_constant_capture_still_sendable():
    r = run("""
async fn watch(get: fn() -> Int) -> Int { return get() }
async fn main() {
    let x = 5
    let get = fn() -> Int { return x }
    let v = parallel { let h = spawn watch(get)
        await h }
    print(v)
}""")
    assert r.lines == ["5"]
