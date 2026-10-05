"""BUG-0017 (second independent audit, F2): `return` inside a `use` body crashed the
interpreter (H.RUNTIME.INTERNAL_ERROR), and `break`/`continue` inside a `use` body
skipped normal release, leaking the resource (V3 5.5.9, 5.6.1)."""
from tests.helpers import run

PROVIDER = """
resource fn r(n: Int) yields Int {
    print("acquire", n)
    let e = yield n
    print("release", n, e)
}
"""


def test_return_inside_use_releases_then_returns():
    r = run(PROVIDER + """
fn f() -> Int {
    use x = r(1) { return x + 4 }
    return 0
}
fn main() { print(f()) }""")
    assert r.exit_code == 0, r.text()
    assert r.lines == ["acquire 1", "release 1 ScopeExit.Normal", "5"]


def test_break_and_continue_inside_use_release():
    r = run(PROVIDER + """
fn main() {
    for i in 0..3 {
        use c = r(i) {
            if i == 0 { continue }
            break
        }
    }
    print("end")
}""")
    assert r.lines == ["acquire 0", "release 0 ScopeExit.Normal", "acquire 1", "release 1 ScopeExit.Normal", "end"]


def test_return_inside_native_and_async_use():
    r = run("""
async resource fn ar() yields Int {
    let e = yield 3
    await sleep(1.millis)
    print("async release", e)
}
async fn f() -> Int {
    use x = await ar() { return x + 1 }
    return 0
}
async fn main() { print(await f()) }""")
    assert r.lines == ["async release ScopeExit.Normal", "4"], r.text()


def test_release_failure_on_return_is_outward():
    r = run("""
error RelFail { }
resource fn bad() yields Int throws RelFail {
    let e = yield 1
    throw RelFail()
}
fn f() -> Int throws RelFail {
    use x = try bad() { return 9 }
    return 0
}
fn main() { print(try f() catch RelFail => -1) }""")
    assert r.lines == ["-1"]
