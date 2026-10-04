"""BUG-0001: while a `use` body runs inside a provider's `yield`, the logical frame
stack must show the *scope owner's* frame, not the suspended provider's frame."""
from tests.helpers import ok, run


def test_nested_provider_yield_inside_inner_use_body():
    r = ok("""
mutable record Conn { id: Int }
resource fn connect(id: Int) yields Conn { yield Conn(id: id)
 print("release {id}") }
resource fn pooled() yields Conn {
    use inner = connect(9) {
        yield inner
        print("pool cleanup")
    }
}
fn main() { use c = pooled() { print("using {c.id}") } }""")
    assert r.lines == ["using 9", "pool cleanup", "release 9"]


def test_body_frame_is_scope_owner_for_async_and_spawn():
    # The body of a `use` in an async function may await and spawn even when the
    # provider itself is a synchronous function. (Derived data crosses; the borrow
    # itself may not — see test_borrow_cannot_cross_task.)
    r = ok("""
resource fn token() yields Int { yield 1 }
async fn main() {
    use t = token() {
        let v = parallel {
            let h = spawn work(t + 0)
            await h
        }
        print("got {v}")
    }
}
fn work(n: Int) -> Int { return n + 1 }""")
    assert r.lines == ["got 2"]


def test_borrow_cannot_cross_task():
    r = run("""
resource fn token() yields Int { yield 1 }
async fn main() { use t = token() { parallel { spawn work(t) } } }
fn work(n: Int) -> Int { return n }""")
    assert r.codes == ["A.TASK.NOT_SENDABLE"]
