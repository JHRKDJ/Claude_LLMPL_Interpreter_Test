"""BUG-0014 (found by the parser fuzzer once the stdlib tests joined its corpus):
`let ()` — a destructuring pattern with no names — crashed the parser with an
IndexError instead of reporting a syntax diagnostic."""
from tests.helpers import check
from lang.syntax.parser import parse_text


def test_empty_destructuring_is_a_syntax_error_not_a_crash():
    r = parse_text("fn main() { let () }")
    assert [d.stable_code for d in r.diagnostics] == ["S.SYNTAX.UNEXPECTED_TOKEN"]
    assert "at least one name" in r.diagnostics[0].message


def test_fuzzer_input():
    r = parse_text('\nfn a() -> Int throws ParseError { throw ParseError(line: 1) }\nfn main() { let () }x = a')
    assert r.diagnostics and all(d.stable_code.startswith("S.") for d in r.diagnostics)


def test_empty_destructuring_with_value():
    r = check("fn main() { let () = (1, 2) }", "draft")
    assert "S.SYNTAX.UNEXPECTED_TOKEN" in r.check_errors
