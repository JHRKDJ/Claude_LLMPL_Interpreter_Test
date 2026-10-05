"""BUG-0032 (second audit, C10/F10): a single throwing `defer` in a block whose other
statements cannot throw made the checker demand `AggregateException` (verified mode
rejected a correct program). V3 5.6: normal return + cleanup failure throws the cleanup
error; only body failure + cleanup failure aggregates."""
from tests.helpers import check, run

SRC = """
error DeferFailed { n: Int }
fn f() throws DeferFailed {
    defer { throw DeferFailed(n: 2) }
    print("body")
}
fn main() { print(capture f()) }"""


def test_single_throwing_defer_needs_no_aggregate():
    r = check(SRC, "verified")
    assert r.check == [], r.text()
    assert run(SRC, mode="verified").lines == ["body", "Err(DeferFailed(n: 2))"]


def test_body_and_defer_both_throwing_still_need_aggregate():
    r = check("""
error A { }
error B { }
fn g() throws A { throw A() }
fn f() throws A, B {
    defer { throw B() }
    try g()
}""", "verified")
    assert "S.EFFECT.UNDECLARED_THROWS" in r.check_errors and "AggregateException" in r.text()
