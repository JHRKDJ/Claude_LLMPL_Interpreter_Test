"""BUG-0004: the syntax contract (docs/semantics/syntax.md §3, SPEC-006/007) allows
match arms and record/enum members to be separated by `,` as well as by newlines,
but after consuming the comma the parser still demanded a newline, so one-line forms
such as `match x { 1 => 10, _ => 0 }` and `enum Color { Red, Green, Blue }` were
rejected with S.SYNTAX.MISSING_SEPARATOR."""
from lang.syntax.parser import parse_text
from tests.helpers import ok


def _codes(src):
    return [d.stable_code for d in parse_text(src).diagnostics]


def test_match_arms_comma_separated_on_one_line():
    assert _codes("fn f(x: Int) -> Int { return match x { 1 => 10, 2 => 20, _ => 0 } }") == []


def test_enum_cases_comma_separated():
    assert _codes("enum Color { Red, Green, Blue }") == []
    assert _codes("enum Shape { Circle(radius: Float), Rect(w: Float, h: Float), Empty }") == []


def test_record_fields_comma_separated():
    assert _codes("record P { x: Int, y: Int }") == []


def test_one_line_forms_run():
    r = ok("""
enum Color { Red, Green, Blue }
record P { x: Int, y: Int }
fn name(c: Color) -> Str { return match c { Color.Red => "r", Color.Green => "g", Color.Blue => "b" } }
fn main() { let p = P(x: 1, y: 2)
 print("{name(Color.Green)} {p.x + p.y}") }""")
    assert r.lines == ["g 3"]


def test_missing_separator_still_reported_without_comma():
    assert _codes("record P { x: Int y: Int }") == ["S.SYNTAX.MISSING_SEPARATOR"]
