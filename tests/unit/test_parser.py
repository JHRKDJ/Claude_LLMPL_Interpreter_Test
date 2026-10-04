"""Parser unit tests: precedence, continuation contexts, spans, recovery."""
from lang.syntax import ast as A
from lang.syntax.parser import parse_text


def expr(src):
    r = parse_text(f"fn f() {{ return {src} }}")
    assert r.ok, [d.message for d in r.diagnostics]
    return r.module.decls[0].body.stmts[0].value


def shape(e):
    if isinstance(e, A.Binary):
        return f"({shape(e.left)} {e.op} {shape(e.right)})"
    if isinstance(e, A.Unary):
        return f"({e.op}{shape(e.operand)})"
    if isinstance(e, A.Name):
        return e.name
    if isinstance(e, A.Literal):
        return str(e.value)
    if isinstance(e, A.Await):
        return f"(await {shape(e.expr)})"
    if isinstance(e, A.Range):
        return f"({shape(e.lo)}..{shape(e.hi)})"
    return type(e).__name__


def test_precedence_ladder():
    assert shape(expr("a || b && c == d")) == "(a || (b && (c == d)))"
    assert shape(expr("a + b * c - d")) == "((a + (b * c)) - d)"
    assert shape(expr("-a * b")) == "((-a) * b)"
    assert shape(expr("a < b + 1")) == "(a < (b + 1))"
    assert shape(expr("0..n + 1")) == "(0..(n + 1))"
    assert shape(expr("await a + b")) == "((await a) + b)"


def test_comparisons_do_not_chain():
    r = parse_text("fn f() { return a < b < c }")
    assert [d.stable_code for d in r.diagnostics] == ["S.SYNTAX.UNEXPECTED_TOKEN"]


def test_continuation_after_operator_and_inside_brackets_and_method_chain():
    r = parse_text("fn f() {\n let x = 1 +\n  2\n let y = g(\n 1,\n 2)\n let z = xs\n  .map(fn(v) => v)\n  .length\n}")
    assert r.ok
    stmts = r.module.decls[0].body.stmts
    assert len(stmts) == 3 and isinstance(stmts[2].value, A.Field)


def test_try_covers_whole_operand_and_catch_on_next_line():
    r = parse_text("fn f() {\n let v = try a() + b()\n  catch E => 0\n}")
    assert r.ok
    t = r.module.decls[0].body.stmts[0].value
    assert isinstance(t, A.Try) and isinstance(t.expr, A.Binary) and len(t.catches) == 1


def test_spans_cover_source_text_including_parentheses():
    assert expr("(a + b) * c").span.text == "(a + b) * c"
    assert expr("f(x)[0].y").span.text == "f(x)[0].y"
    assert expr("-(x)").span.text == "-(x)"


def test_recovery_reports_each_bad_statement_once():
    r = parse_text("fn f() {\n let = 1\n let ok = 2\n let = 3\n}\nfn g() { }")
    assert len(r.diagnostics) == 2
    assert [d.name for d in r.module.decls] == ["f", "g"]


def test_unsupported_foreign_syntax_is_named():
    for src in ["def f(): pass", "fn f() { let x = c ? 1 : 2 }", "fn f() { x++ }", "fn f() { if a and b { } }"]:
        r = parse_text(src)
        assert r.diagnostics, src
        assert r.diagnostics[0].stable_code in ("S.SYNTAX.UNSUPPORTED_SYNTAX", "S.SYNTAX.UNEXPECTED_TOKEN",
                                                "S.SYNTAX.MISSING_SEPARATOR"), (src, r.diagnostics[0].stable_code)
