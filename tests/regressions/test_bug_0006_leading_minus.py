"""BUG-0006: the leading-operator rule for `-` (a line starting with `-` after a line
that ends an expression is a separate statement, not a continuation) fired for
*every* statement beginning with unary minus, rejecting valid block values such
as `if c { 1 } else { -v }` (found by the formatter fuzzer)."""
from lang.syntax.parser import parse_text
from tests.helpers import ok


def _codes(src):
    return [d.stable_code for d in parse_text(src).diagnostics]


def test_block_value_starting_with_minus_on_same_line():
    assert _codes("fn f(c: Bool, v: Int) -> Int { return if c { 1 } else { -v } }") == []


def test_block_value_starting_with_minus_on_own_line():
    assert _codes("fn f(c: Bool, v: Int) -> Int {\n return if c {\n 1\n } else {\n -v\n }\n}") == []


def test_minus_after_statement_ending_with_block_is_allowed():
    assert _codes("fn f(c: Bool, v: Int) -> Int {\n let r = if c {\n  if c { print(1) }\n  -v\n } else { v }\n return r\n}") == []


def test_genuine_leading_minus_still_reported_with_fix():
    r = parse_text("fn f(a: Int, b: Int) -> Int {\n let x = a\n  - b\n return x\n}")
    assert [d.stable_code for d in r.diagnostics] == ["S.SYNTAX.LEADING_OPERATOR"]
    assert r.diagnostics[0].fixes


def test_runs():
    r = ok("fn pick(c: Bool, v: Int) -> Int { return if c { 1 } else { -v } }\nfn main() { print(pick(false, 4)) }")
    assert r.lines == ["-4"]
