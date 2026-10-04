"""BUG-0005: the parser folded `-` applied to a *parenthesised* numeric literal into a
single literal whose span stopped before the closing parenthesis (`-(-7` for
`-(-7)`), so diagnostics and the formatter saw a truncated source range. Only a
minus sign immediately followed by a number literal may be folded."""
from lang.syntax import ast as A
from lang.syntax.parser import parse_text
from tests.helpers import ok


def _ret_expr(src):
    m = parse_text(src).module
    return m.decls[0].body.stmts[0].value


def test_negated_parenthesised_literal_span_is_complete():
    e = _ret_expr("fn f() -> Int { return -(-7) }")
    assert e.span.text == "-(-7)"


def test_adjacent_negative_literal_still_folds():
    e = _ret_expr("fn f() -> Int { return -7 }")
    assert isinstance(e, A.Literal) and e.value == -7 and e.span.text == "-7"


def test_value_semantics_unchanged():
    r = ok("fn main() { print(-(-7), -(3), (-7).abs(), -7.abs()) }")
    assert r.lines == ["7 -3 7 -7"]
