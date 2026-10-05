"""BUG-0016 (second independent audit, F1): `return`, `break` or `continue` inside a
`parallel` body left the group without waiting for quiescence, so children outlived
their structured scope (V3 5.12.2, 6.8): they ran after the function returned, were
never run at all when the program ended, and their failures were lost."""
from tests.helpers import run


def test_return_inside_parallel_waits_for_children():
    r = run("""
async fn child() {
    defer print("child cleanup", time.now())
    print("child started", time.now())
    await sleep(10.millis)
    print("child finished", time.now()) }
async fn f() -> Int {
    parallel {
        spawn child()
        return 5
    }
    return 0
}
async fn main() {
    let v = await f()
    print("f returned", v, time.now())
}""")
    assert r.lines == ["child started Instant(0s)", "child finished Instant(10ms)", "child cleanup Instant(10ms)",
                       "f returned 5 Instant(10ms)"]


def test_break_and_continue_inside_parallel_wait_for_children():
    r = run("""
async fn child(i: Int) { await sleep(5.millis)
    print("child", i, "done") }
async fn main() {
    for i in 0..3 {
        parallel {
            spawn child(i)
            if i == 0 { continue }
            if i == 1 { break }
        }
    }
    print("end", time.now())
}""")
    assert r.lines == ["child 0 done", "child 1 done", "end Instant(10ms)"]


def test_child_failure_after_return_is_reported():
    r = run("""
error Boom { }
async fn child() throws Boom { await sleep(1.millis)
    throw Boom() }
async fn f() -> Int throws AggregateException {
    parallel {
        spawn child()
        return 5
    }
    return 0
}
async fn main() {
    let v = try await f() catch AggregateException as a => -a.entries.length
    print(v)
}""")
    assert r.lines == ["-1"]
