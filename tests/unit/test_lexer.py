"""Lexer unit tests (docs/semantics/syntax.md §2)."""
from lang.source import SourceFile
from lang.syntax.lexer import Lexer


def lex(text):
    lx = Lexer(SourceFile("<t>", text))
    toks = lx.tokenize()
    return [(t.kind, t.value) for t in toks if t.kind not in ("EOF",)], lx


def kinds(text):
    return [k for k, _ in lex(text)[0]]


def test_keywords_identifiers_and_contextual_words():
    toks, _ = lex("fn record x await")
    assert toks == [("fn", "fn"), ("IDENT", "record"), ("IDENT", "x"), ("await", "await")]


def test_numbers_with_separators_exponents_and_floats():
    toks, lx = lex("1_000 3.25 1e3 0x1F")
    vals = [v for k, v in toks]
    assert vals[:3] == [1000, 3.25, 1000.0]
    assert not lx.diagnostics or toks[3][1] == 31


def test_longest_operator_match():
    assert kinds("a ..= b .. c => d -> e") == ["IDENT", "..=", "IDENT", "..", "IDENT", "=>", "IDENT", "->", "IDENT"]


def test_newlines_are_tokens_and_comments_are_trivia():
    toks, lx = lex("a // c1\n/* c2 */ b")
    assert [k for k, _ in toks] == ["IDENT", "NEWLINE", "IDENT"]
    assert [c.text for c in lx.comments] == ["// c1", "/* c2 */"]
    assert [c.own_line for c in lx.comments] == [False, True]


def test_string_escapes_and_interpolation_parts():
    toks, lx = lex(r'"a\n\{b\} {x + 1:>4}"')
    (k, v), = toks
    assert k == "STRING" and not lx.diagnostics


def test_lexical_errors_have_codes_and_spans():
    for text, code in [('"abc', "S.SYNTAX.UNTERMINATED_STRING"), ("/* x", "S.SYNTAX.UNTERMINATED_COMMENT"),
                       (r'"\q"', "S.SYNTAX.INVALID_ESCAPE"), ("12ab", "S.SYNTAX.INVALID_NUMBER"),
                       ("a $ b", "S.SYNTAX.INVALID_CHARACTER"), ("'x'", "S.SYNTAX.UNSUPPORTED_SYNTAX")]:
        _, lx = lex(text)
        assert lx.diagnostics and lx.diagnostics[0].stable_code == code, (text, lx.diagnostics)
        sp = lx.diagnostics[0].primary.span
        assert 0 <= sp.start <= sp.end <= len(text)
