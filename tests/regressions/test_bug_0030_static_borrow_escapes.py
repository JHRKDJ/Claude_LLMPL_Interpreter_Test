"""BUG-0030 (second audit, C08/F8): verified mode missed borrow escapes the runtime
catches: wrapping in `Some(c)` or a tuple `(c, 1)`, and storing a borrow parameter into
a mutable record field inside a helper (V3 5.15.5: verified requires resource
correctness; 7.9.4: the checker tracks lexical escape)."""
from tests.helpers import check

PROV = """
resource fn connect(n: Int) yields Int {
    let e = yield n
}
mutable record Holder { c: Dyn }
"""


def test_option_and_tuple_wrapping():
    for expr in ("Some(c)", "(c, 1)"):
        src = PROV + "fn main() { let v = use c = connect(1) { " + expr + " }\n print(v) }"
        assert "S.RESOURCE.ESCAPE" in check(src, "verified").check_errors, expr


def test_helper_field_write():
    src = PROV + """
fn keep(h: Holder, c: borrow Int) { h.c = c }
fn main() { let h = Holder(c: 0)
  use c = connect(1) { keep(h, c) } }"""
    assert "S.RESOURCE.ESCAPE" in check(src, "verified").check_errors
