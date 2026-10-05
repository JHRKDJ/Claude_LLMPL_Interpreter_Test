"""BUG-0043 (second audit, T12): a variable bound by a category catch
(`catch IOish as e => e.path`) was typed Dyn, so field access passed verified mode and
abandoned at run time (A.TYPE.UNKNOWN_FIELD) when the concrete error lacked the field.
V3 5.9.3: categories affect catch matching only; they contribute no fields."""
from tests.helpers import check

PRE = """
category IOish
error NotFound category IOish { path: Str }
error Denied category IOish { }
fn op(n: Int) -> Str throws NotFound, Denied {
    if n == 0 { throw Denied() }
    throw NotFound(path: "p")
}
"""


def test_field_access_on_category_binding_rejected_in_verified():
    r = check(PRE + "pub fn f() -> Str { return try op(0) catch category IOish as e => e.path }", "verified")
    assert "S.TYPE.UNKNOWN_FIELD" in r.check_errors, r.text()


def test_narrowing_or_concrete_catch_is_fine():
    r = check(PRE + """
pub fn f() -> Str { return try op(0) catch NotFound as e => e.path catch Denied => "denied" }
pub fn g() -> Str { return try op(0) catch category IOish as e => typeName(e) }""", "verified")
    assert r.check_errors == [], r.text()
