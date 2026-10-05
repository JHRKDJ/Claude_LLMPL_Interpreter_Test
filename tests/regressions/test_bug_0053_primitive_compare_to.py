"""BUG-0053 (found while verifying the `lang test` CLI in the final green run): `Str`
had a `compareTo` method, so strings structurally satisfied `std.order.Comparable`,
but `Int`, `Float`, `Duration` and `Instant` did not. `order.sort([3, 1, 2])` was a
static mismatch (an error in verified mode) and abandoned at run time, while
`order.sort(["b", "a"])` worked. The ordered primitives now share one `compareTo`
that is exactly the `<` operator's ordering (so NaN and mixed Int/Float still abandon)."""
from tests.helpers import check, run

PRELUDE = "import std.order\n\n"


def test_ints_and_floats_sort_through_the_protocol():
    src = PRELUDE + ("fn main() {\n    print(order.sort([3, 1, 2]))\n    print(order.max([1.5, -2.0]))\n"
                     "    print(order.sort([2.seconds, 5.millis]))\n}\n")
    c = check(src, "verified")
    assert not c.check_errors, c.text()
    r = run(src)
    assert r.lines == ["[1, 2, 3]", "Some(1.5)", "[5ms, 2s]"], r.text()


def test_compare_to_matches_the_operator():
    r = run("fn main() {\n    print(1.compareTo(2), 2.compareTo(2), 3.compareTo(2), (-0.5).compareTo(0.5))\n}\n")
    assert r.lines == ["-1 0 1 -1"], r.text()


def test_nan_has_no_ordering_through_compare_to_either():
    r = run("fn main() {\n    let n = 0.0 / 0.0\n    print(n.compareTo(1.0))\n}\n")
    assert r.codes == ["A.TYPE.OPERAND_MISMATCH"], r.text()
