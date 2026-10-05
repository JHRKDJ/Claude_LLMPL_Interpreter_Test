"""Negative tests: every program here is wrong. Each case pins the stable code, the
source text under the primary label, and that the diagnostic carries a usable fix
hint (help text or a suggestion) where the contract requires one (V3 7.13)."""
import pytest

from lang.syntax.parser import parse_text
from tests.helpers import check

SYNTAX = [
    ("unexpected_token", "fn f() { let = 1 }", "S.SYNTAX.UNEXPECTED_TOKEN", "="),
    ("expected_pattern", "fn f(x: Int) -> Int { return match x { => 1 } }", "S.SYNTAX.EXPECTED_PATTERN", "=>"),
    ("unterminated_string", 'fn f() { let s = "abc\n }', "S.SYNTAX.UNTERMINATED_STRING", None),
    ("unterminated_comment", "fn f() { }\n/* never closed", "S.SYNTAX.UNTERMINATED_COMMENT", None),
    ("invalid_escape", r'fn f() { let s = "a\qb" }', "S.SYNTAX.INVALID_ESCAPE", r"\q"),
    ("invalid_number", "fn f() { let n = 12abc }", "S.SYNTAX.INVALID_NUMBER", None),
    ("invalid_character", "fn f() { let n = 1 $ 2 }", "S.SYNTAX.INVALID_CHARACTER", "$"),
    ("unclosed_delimiter", "fn f() { let xs = [1, 2 }", "S.SYNTAX.MISMATCHED_DELIMITER", None),
    ("unclosed_brace", "fn f() { let x = 1", "S.SYNTAX.UNCLOSED_DELIMITER", None),
    ("leading_operator", "fn f() -> Int { let x = 1\n + 2\n return x }", "S.SYNTAX.LEADING_OPERATOR", None),
    ("expected_expression", "fn f() { let x = }", "S.SYNTAX.EXPECTED_EXPRESSION", None),
    ("expected_type", "fn f(x: ) { }", "S.SYNTAX.EXPECTED_TYPE", None),
    ("expected_block", "fn f() return 1", "S.SYNTAX.EXPECTED_BLOCK", None),
    ("missing_separator", "fn f() { let x = 1 let y = 2 }", "S.SYNTAX.MISSING_SEPARATOR", None),
    ("invalid_assignment_target", "fn f() { 1 = 2 }", "S.SYNTAX.INVALID_ASSIGNMENT_TARGET", None),
    ("python_def", "def f():\n    return 1", "S.SYNTAX.UNSUPPORTED_SYNTAX", None),
    ("ternary", "fn f(c: Bool) -> Int { return c ? 1 : 2 }", "S.SYNTAX.UNSUPPORTED_SYNTAX", None),
    ("increment", "fn f() { let i = 0\n i++ }", "S.SYNTAX.UNSUPPORTED_SYNTAX", None),
    ("unclosed_interpolation", 'fn f() { let s = "a {1 + 2" }', "S.SYNTAX.INTERPOLATION", None),
    ("empty_interpolation", 'fn f() { let s = "a {} b" }', "S.SYNTAX.INTERPOLATION", None),
    ("bad_interpolation_expr", 'fn f() { let s = "a {1 + }" }', "S.SYNTAX.EXPECTED_EXPRESSION", None),
]


@pytest.mark.parametrize("name,src,code,text", SYNTAX, ids=[c[0] for c in SYNTAX])
def test_syntax_diagnostics(name, src, code, text):
    r = parse_text(src)
    codes = [d.stable_code for d in r.diagnostics]
    assert codes and codes[0] == code, codes
    d = r.diagnostics[0]
    assert d.primary is not None and d.primary.span is not None
    if text is not None:
        assert d.primary.span.text == text


def test_unescaped_json_in_string_is_one_diagnostic():
    r = parse_text('fn f() { let s = "{\\"port\\": 80}" }')
    assert [d.stable_code for d in r.diagnostics] == ["S.SYNTAX.INTERPOLATION"]
    assert "\\{" in " ".join(r.diagnostics[0].help)


def test_syntax_errors_are_recovered_and_reported_per_statement():
    r = parse_text("fn f() {\n let = 1\n let y = 2\n let = 3\n}\nfn g() { return }")
    codes = [d.stable_code for d in r.diagnostics]
    assert codes == ["S.SYNTAX.UNEXPECTED_TOKEN", "S.SYNTAX.UNEXPECTED_TOKEN"]


def test_misplaced_construct_protocol_body():
    r = parse_text("protocol P { fn f(self) -> Int { return 1 } }")
    assert [d.stable_code for d in r.diagnostics] == ["S.SYNTAX.MISPLACED_CONSTRUCT"]


STATIC = [
    ("unresolved_name", "fn f() -> Int { return lenght }", "S.NAME.UNRESOLVED", "lenght"),
    ("unresolved_suggests_import", "fn f() -> Str { return fs.readText(\"x\") }", "S.NAME.UNRESOLVED", "fs"),
    ("duplicate_decl", "fn f() { }\nfn f() { }", "S.NAME.DUPLICATE", None),
    ("duplicate_local", "fn f() { let x = 1\n let x = 2 }", "S.NAME.DUPLICATE", None),
    ("const_reassign", "fn f() { const x = 1\n x = 2 }", "S.NAME.CONST_REASSIGN", None),
    ("captured_reassign", "fn f() { let n = 0\n let g = fn() { n = n + 1 } }", "S.NAME.CAPTURED_REASSIGN", None),
    ("nonlocal_invalid", "fn f() { nonlocal q }", "S.NAME.NONLOCAL_INVALID", None),
    ("not_a_type", "fn f() { }\nfn g(x: f) { }", "S.NAME.NOT_A_TYPE", "f"),
    ("mutable_global", "const xs = MutableList[Int]()", "S.MODULE.MUTABLE_GLOBAL", None),
    ("stdlib_module_not_found", "import std.nosuch\nfn f() { }", "S.MODULE.NOT_FOUND", None),
    ("unknown_dependency", "import nowhere.things\nfn f() { }", "S.MODULE.UNKNOWN_DEPENDENCY", None),
    ("invalid_pattern", "fn f(x: Int?) -> Int { return match x { Ok(v) => v, _ => 0 } }",
     "S.MATCH.INVALID_PATTERN", None),
    ("missing_field", "record P { x: Int, y: Int }\nfn f() -> P { return P(x: 1) }", "S.TYPE.MISSING_FIELD", None),
    ("not_callable", "fn f() -> Int { let n = 1\n return n(2) }", "S.TYPE.NOT_CALLABLE", None),
    ("invalid_with", "mutable record M { n: Int }\nfn f(m: M) -> M { return m with { n: 2 } }",
     "S.TYPE.INVALID_WITH", None),
    ("always_false_equality", 'fn f() -> Bool { return 1 == "1" }', "S.TYPE.ALWAYS_FALSE_EQUALITY", None),
    ("propagate_context", "error Bad { }\nfn r() -> Result[Int, Bad] { return Ok(1) }\n"
     "fn f() -> Int { return propagate r() }", "S.EFFECT.PROPAGATE_CONTEXT", None),
    ("old_outside_ensures", "fn f(x: Int) -> Int requires old(x) > 0 { return x }",
     "S.CONTRACT.OLD_OUTSIDE_ENSURES", "old(x)"),
    ("result_outside_ensures", "fn f(x: Int) -> Int requires result > 0 { return x }",
     "S.CONTRACT.RESULT_OUTSIDE_ENSURES", None),
]


@pytest.mark.parametrize("name,src,code,text", STATIC, ids=[c[0] for c in STATIC])
def test_static_diagnostics(name, src, code, text):
    r = check(src, "verified")
    assert code in r.check_errors, r.text()
    d = next(d for d in r.check if d.stable_code == code)
    assert d.primary is not None and d.primary.span is not None
    if text is not None:
        assert d.primary.span.text == text


def test_unresolved_name_suggests_close_match():
    r = check("fn f(length: Int) -> Int { return lenght }")
    d = next(d for d in r.check if d.stable_code == "S.NAME.UNRESOLVED")
    assert "length" in " ".join(d.help) + " ".join(str(s) for s in getattr(d, "suggestions", []))


def test_unresolved_stdlib_module_suggests_import():
    r = check('fn f() -> Str { return fs.readText("x") }')
    d = next(d for d in r.check if d.stable_code == "S.NAME.UNRESOLVED")
    text = " ".join(d.help) + " ".join(str(s) for s in getattr(d, "suggestions", []))
    assert "import std.fs" in text


def test_private_name_across_modules():
    r = check("import lib.util\nfn f() -> Int { return util.secret() }",
              files={"lib/util.lang": "fn secret() -> Int { return 1 }\npub fn open() -> Int { return 2 }"})
    assert "S.NAME.PRIVATE" in r.check_errors


def test_unknown_dependency_is_never_installed():
    r = check("import vendorpkg.thing\nfn f() { }",
              files={"lang.toml": '[project]\nname = "app"\nmode = "draft"\n'})
    d = next(d for d in r.check if d.stable_code == "S.MODULE.UNKNOWN_DEPENDENCY")
    assert "lang.toml" in " ".join(d.help)


def test_static_errors_block_run():
    from tests.helpers import run
    r = run("fn main() { print(nope) }")
    assert r.exit_code is None and r.check_errors == ["S.NAME.UNRESOLVED"]


def test_statement_in_expression_position_suggests_a_block():
    from lang.syntax.parser import parse_text
    for stmt in ("throw Bad()", "return 1", "continue"):
        r = parse_text("error Bad { }\nfn f(x: Int?) -> Int { for i in 0..1 { let v = match x { Some(n) => n, None => " + stmt + " } }\n return 0 }")
        d = r.diagnostics[0]
        assert d.stable_code == "S.SYNTAX.EXPECTED_EXPRESSION"
        assert any("wrap it in a block" in h for h in d.help), d.help
