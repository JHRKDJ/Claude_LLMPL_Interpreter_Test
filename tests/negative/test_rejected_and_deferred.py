"""Rejected and deferred V3 features stay absent (V3 9.4, 9.5; FEATURE_MATRIX §18).
Each test pins one absence so that a later change cannot reintroduce it silently."""
from tests.helpers import check, run


def codes(src, mode="draft"):
    r = run(src, mode=mode)
    return r.check_codes + r.codes


def test_no_class_inheritance():
    assert "S.SYNTAX.UNSUPPORTED_SYNTAX" in codes("class A extends B { }\nfn main() { }")
    assert codes("record A : B { x: Int }\nfn main() { }") == ["S.SYNTAX.UNEXPECTED_TOKEN"]


def test_no_structural_closeable_raii():
    """A record with close() is not closed automatically at scope exit (9.5)."""
    r = run("""
mutable record Conn { open: Bool
    fn close(self) { self.open = false
        print("closed") } }
fn main() {
    let c = Conn(open: true)
    if true { let d = c }
    print(c.open)
}""")
    assert r.lines == ["true"]


def test_no_automatic_coercion():
    assert run('fn main() { print("1" + 1) }').codes == ["A.TYPE.OPERAND_MISMATCH"]
    assert codes("fn main() { if 1 { print(1) } }") == ["S.TYPE.STATIC_MISMATCH", "A.TYPE.NON_BOOL_CONDITION"]


def test_no_broad_untyped_catch():
    r = check("""
error A { }
error B { }
fn f(x: Int) -> Int throws A, B { if x > 0 { throw A() }
 throw B() }
pub fn g() -> Int { return try f(1) catch _ => 0 }""", "verified")
    assert r.check_errors == ["S.EFFECT.BROAD_CATCH"], r.text()
    for spelling in ("e", "Exception", "Error", "Throwable"):
        r = check(f"""error A {{ }}
fn f() -> Int throws A {{ throw A() }}
pub fn g() -> Int {{ return try f() catch {spelling} => 0 }}""", "verified")
        assert r.check_errors == ["S.EFFECT.BROAD_CATCH"], (spelling, r.text())


def test_no_throw_and_result_in_one_signature():
    r = check("""
error E { }
pub fn f() -> Result[Int, E] throws E { return Ok(1) }""", "verified")
    assert "S.EFFECT.THROWS_AND_RESULT" in r.check_errors


def test_no_recoverable_abandonment():
    """Abandonment cannot be caught in the failed task (9.5 `try_recover`)."""
    r = run("""
fn main() {
    let xs = [1]
    let v = try xs[3] catch Data => 0
    print("continued", v)
}""")
    assert r.codes == ["A.INDEX.OUT_OF_RANGE"] and r.outcome == "abandoned" and "continued" not in r.stdout
    assert r.check_codes == ["S.EFFECT.CATCH_UNREACHABLE"]  # nothing recoverable can be caught there


def test_no_mutable_globals():
    assert codes("let counter = 0\nfn main() { }") == ["S.MODULE.MUTABLE_GLOBAL"]
    assert codes("const items = MutableList[Int]()\nfn main() { }") == ["S.MODULE.MUTABLE_GLOBAL"]


def test_no_locks_or_shared_mutable_state_between_tasks():
    r = run("""
mutable record Counter { n: Int }
async fn bump(c: Counter) { c.n = c.n + 1 }
async fn main() {
    let c = Counter(n: 0)
    parallel { spawn bump(c)
        spawn bump(c) }
    print(c.n)
}""")
    assert r.lines == ["0"]  # each child mutated its own copy


def test_channels_cannot_reopen_and_have_no_default_mode_switch():
    r = run("""
async fn main() { let ch = Channel[Int].unbounded()
    ch.close()
    ch.reopen() }""")
    assert (r.check_codes, r.codes) == (["S.TYPE.UNKNOWN_METHOD"], ["A.TYPE.UNKNOWN_METHOD"])
    r = run("fn main() { let ch = Channel[Int]() }")  # capacity is always written explicitly
    assert (r.check_codes, r.codes) == (["S.TYPE.NOT_CALLABLE"], ["A.TYPE.NOT_CALLABLE"])


def test_channel_event_history_is_not_observable_by_programs():
    r = run("""
async fn main() { let ch = Channel[Int].unbounded()
    print(ch.history()) }""")
    assert (r.check_codes, r.codes) == (["S.TYPE.UNKNOWN_METHOD"], ["A.TYPE.UNKNOWN_METHOD"])


def test_no_default_branch_in_blocking_select_and_no_arbitrary_async_branch():
    assert codes("""
async fn main() { let ch = Channel[Int].unbounded()
    let rx = ch.receiver()
    select { receive v from rx => print(v)
        default => print("none") } }""") == ["S.SELECT.NONE_READY_PLACEMENT"]
    assert codes("""
async fn f() -> Int { return 1 }
async fn main() { select { await f() => print(1) } }""") == ["S.SYNTAX.UNEXPECTED_TOKEN"]


def test_no_numeric_priorities_or_dynamic_heterogeneous_select():
    assert codes("""
async fn main() { let ch = Channel[Int].unbounded()
    let rx = ch.receiver()
    select priority 3 { receive v from rx => print(v) } }""") == ["S.SYNTAX.UNEXPECTED_TOKEN"]
    r = run("""
async fn main() { let a = Channel[Int].unbounded()
    let b = Channel[Str].unbounded()
    await selectAny([a.receiver(), b.sender()]) }""")
    assert r.check_codes == ["S.NAME.UNRESOLVED"]  # only homogeneous selectReceive/selectTask exist


def test_no_mutable_broadcast():
    r = run("""
async fn main() { let b = Broadcast[Dyn].buffered(1)
    let p = b.publisher()
    let s = b.subscribe()
    try await p.send(MutableList[Int]()) catch ChannelClosed => () }""")
    assert r.codes == ["A.CHANNEL.BROADCAST_MUTABLE"]


def test_no_operator_overloading_or_reflection():
    assert codes("""
record V { x: Int
    fn plus(self, o: V) -> V { return V(x: self.x + o.x) } }
fn main() { print(V(x: 1) + V(x: 2)) }""") == ["S.TYPE.INVALID_OPERATOR", "A.TYPE.OPERAND_MISMATCH"]
    r = run("record P { x: Int }\nfn main() { print(P(x: 1).fields()) }")
    assert (r.check_codes, r.codes) == (["S.TYPE.UNKNOWN_METHOD"], ["A.TYPE.UNKNOWN_METHOD"])


def test_no_fixed_width_integers_or_silent_dependency_installation():
    r = run("fn main() { let x: Int32 = 1 }")
    assert r.check_codes == ["S.NAME.UNRESOLVED"]
    assert "S.MODULE.UNKNOWN_DEPENDENCY" in codes("import requests\nfn main() { }")
