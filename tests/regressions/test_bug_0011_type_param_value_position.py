"""BUG-0011 (found writing the std.chan library): a generic function could not name
its own type parameter as a type argument in value position — `MutableList[T]()`,
`Channel[A].rendezvous()` — the resolver reported `S.NAME.UNRESOLVED` for `T`,
although `T` is in scope for the whole body (it already worked in `let x: T`)."""
from tests.helpers import check, run


SRC = """
fn collect[T](xs: List[T]) -> List[T] {
    let out = MutableList[T]()
    for x in xs { out.push(x) }
    return out.freeze()
}
async fn relay[A](v: A) -> A {
    let ch = Channel[A].buffered(1)
    try await ch.sender().send(v) catch ChannelClosed => ()
    return try await ch.receiver().receive() catch ChannelClosed => v
}
async fn main() {
    print(collect([1, 2, 3]))
    print(await relay("x"))
}"""


def test_type_parameter_usable_as_value_position_type_argument():
    r = check(SRC, "verified")
    assert "S.NAME.UNRESOLVED" not in r.check_codes, r.text()


def test_program_runs():
    r = run(SRC)
    assert r.stdout.splitlines() == ["[1, 2, 3]", "x"], r.diags
