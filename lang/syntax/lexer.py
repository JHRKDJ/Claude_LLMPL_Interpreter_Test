"""Lexer.

Produces tokens with spans plus a side list of comments (trivia for the formatter).
Errors are reported as structured diagnostics; the lexer always makes progress.
"""
from __future__ import annotations

from ..diagnostics import Diagnostic, Fix, Label, Note, TextEdit, code
from ..source import SourceFile, Span
from .tokens import HARD_KEYWORDS, OPERATORS, Comment, StringPart, Token

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "{": "{", "}": "}", "'": "'"}


_NOT_AN_EXPRESSION = {"S.SYNTAX.INVALID_CHARACTER", "S.SYNTAX.UNTERMINATED_STRING", "S.SYNTAX.INVALID_ESCAPE"}


class Lexer:
    def __init__(self, file: SourceFile, start: int = 0, end: int | None = None):
        self.file = file
        self.text = file.text
        self.pos = start
        self.end = len(self.text) if end is None else end
        self.diagnostics: list[Diagnostic] = []
        self.comments: list[Comment] = []

    # ---------------------------------------------------------------- helpers
    def _span(self, start: int, end: int | None = None) -> Span:
        return Span(self.file, start, self.pos if end is None else end)

    def _error(self, stable: str, msg: str, start: int, end: int | None = None, label: str = "",
               help: str | None = None, fix: Fix | None = None) -> Diagnostic:
        d = Diagnostic(code(stable), msg, primary=Label(self._span(start, end), label))
        if help:
            d.help.append(help)
        if fix:
            d.fixes.append(fix)
        self.diagnostics.append(d)
        return d

    def _peek(self, k: int = 0) -> str:
        i = self.pos + k
        return self.text[i] if i < self.end else ""

    # ---------------------------------------------------------------- main loop
    def tokenize(self, interpolation: bool = False) -> list[Token]:
        """Lex until EOF (or, inside an interpolation, an unmatched '}' or ':' spec)."""
        tokens: list[Token] = []
        depth = 0
        while True:
            self._skip_space_and_comments(tokens)
            if self.pos >= self.end:
                tokens.append(Token("EOF", None, self._span(self.pos, self.pos)))
                return tokens
            ch = self.text[self.pos]
            start = self.pos
            if interpolation:
                if ch == "}" and depth == 0:
                    tokens.append(Token("EOF", None, self._span(self.pos, self.pos)))
                    return tokens
                if ch == ":" and depth == 0:
                    tokens.append(Token("EOF", None, self._span(self.pos, self.pos)))
                    return tokens
                if ch == '"' and depth == 0:
                    eol = self.text.find("\n", self.pos, self.end)
                    eol = self.end if eol < 0 else eol
                    rest = self.text[self.pos + 1:eol]
                    q1 = rest.find('"')
                    br = rest.find("}", q1 + 1) if q1 >= 0 else -1
                    if q1 < 0 or br < 0 or rest.find('"', br + 1) < 0:
                        # a nested string could never be followed by the interpolation's `}`:
                        # this quote ends the enclosing string, so the interpolation is unclosed
                        self._error("S.SYNTAX.INTERPOLATION",
                                    "string interpolation is missing its closing `}` before the end of the string",
                                    start, start + 1, label="string ends here",
                                    help="close the interpolation with `}` or write a literal brace as `\\{`")
                        tokens.append(Token("EOF", None, self._span(self.pos, self.pos)))
                        return tokens
                if ch == "\n":
                    self._error("S.SYNTAX.INTERPOLATION", "string interpolation is not closed on this line",
                                start, start + 1, help="close the interpolation with `}` or escape the brace as `\\{`")
                    tokens.append(Token("EOF", None, self._span(self.pos, self.pos)))
                    return tokens
            if ch == "\n":
                self.pos += 1
                tokens.append(Token("NEWLINE", "\n", self._span(start)))
                continue
            if ch.isalpha() or ch == "_":
                tokens.append(self._ident())
                continue
            if ch.isdigit():
                tokens.append(self._number())
                continue
            if ch == '"':
                tokens.append(self._string())
                continue
            if ch == "'":
                # Single-quoted strings are not part of the language; lex for recovery.
                tok = self._string(quote="'")
                self._error("S.SYNTAX.UNSUPPORTED_SYNTAX", "single-quoted strings are not supported",
                            tok.span.start, tok.span.end, help='use double quotes: "..."')
                tokens.append(tok)
                continue
            op = self._operator()
            if op is not None:
                if interpolation:
                    if op in ("(", "[", "{"):
                        depth += 1
                    elif op in (")", "]", "}"):
                        depth -= 1
                tokens.append(Token(op, op, self._span(start)))
                continue
            self.pos += 1
            self._error("S.SYNTAX.INVALID_CHARACTER", f"unexpected character {ch!r}", start, self.pos)

    def _skip_space_and_comments(self, tokens: list[Token]) -> None:
        while self.pos < self.end:
            ch = self.text[self.pos]
            if ch in " \t\r\f﻿":
                self.pos += 1
            elif ch == "/" and self._peek(1) == "/":
                start = self.pos
                while self.pos < self.end and self.text[self.pos] != "\n":
                    self.pos += 1
                self.comments.append(Comment(self._span(start), self.text[start:self.pos], self._own_line(start)))
            elif ch == "/" and self._peek(1) == "*":
                start = self.pos
                close = self.text.find("*/", self.pos + 2, self.end)
                if close < 0:
                    self.pos = self.end
                    self._error("S.SYNTAX.UNTERMINATED_COMMENT", "block comment is never closed", start, start + 2)
                else:
                    self.pos = close + 2
                self.comments.append(Comment(self._span(start), self.text[start:self.pos], self._own_line(start)))
            elif ch == "\\" and self._peek(1) == "\n":
                start = self.pos
                self.pos += 2
                self._error("S.SYNTAX.UNSUPPORTED_SYNTAX", "backslash line continuation is not supported", start,
                            start + 1, help="break lines after an operator, comma or opening bracket instead")
            else:
                return

    def _own_line(self, start: int) -> bool:
        i = start - 1
        while i >= 0 and self.text[i] in " \t\r":
            i -= 1
        return i < 0 or self.text[i] == "\n"

    def _ident(self) -> Token:
        start = self.pos
        while self.pos < self.end and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        word = self.text[start:self.pos]
        kind = word if word in HARD_KEYWORDS else "IDENT"
        return Token(kind, word, self._span(start))

    def _number(self) -> Token:
        start = self.pos
        text = self.text
        if text[self.pos] == "0" and self._peek(1) in ("x", "X", "b", "B", "o", "O"):
            base = {"x": 16, "b": 2, "o": 8}[self._peek(1).lower()]
            self.pos += 2
            digits_start = self.pos
            while self.pos < self.end and (text[self.pos].isalnum() or text[self.pos] == "_"):
                self.pos += 1
            raw = text[digits_start:self.pos].replace("_", "")
            try:
                value = int(raw, base)
            except ValueError:
                self._error("S.SYNTAX.INVALID_NUMBER", f"invalid base-{base} literal", start, self.pos)
                value = 0
            return Token("INT", value, self._span(start))
        while self.pos < self.end and (text[self.pos].isdigit() or text[self.pos] == "_"):
            self.pos += 1
        is_float = False
        if self._peek() == "." and self._peek(1).isdigit():
            is_float = True
            self.pos += 1
            while self.pos < self.end and (text[self.pos].isdigit() or text[self.pos] == "_"):
                self.pos += 1
        if self._peek() in ("e", "E") and (self._peek(1).isdigit() or
                                          (self._peek(1) in "+-" and self._peek(2).isdigit())):
            is_float = True
            self.pos += 2
            while self.pos < self.end and text[self.pos].isdigit():
                self.pos += 1
        raw = text[start:self.pos].replace("_", "")
        if self.pos < self.end and (text[self.pos].isalpha() or text[self.pos] == "_"):
            bad_start = self.pos
            while self.pos < self.end and (text[self.pos].isalnum() or text[self.pos] == "_"):
                self.pos += 1
            self._error("S.SYNTAX.INVALID_NUMBER", f"invalid numeric literal {text[start:self.pos]!r}",
                        start, self.pos, help="identifiers cannot start with a digit")
            del bad_start
        if is_float:
            return Token("FLOAT", float(raw), self._span(start))
        return Token("INT", int(raw), self._span(start))

    def _operator(self) -> str | None:
        for op in OPERATORS:
            if self.text.startswith(op, self.pos) and self.pos + len(op) <= self.end:
                self.pos += len(op)
                return op
        return None

    # ---------------------------------------------------------------- strings
    def _string(self, quote: str = '"') -> Token:
        start = self.pos
        triple = quote == '"' and self.text.startswith('"""', self.pos)
        self.pos += 3 if triple else 1
        parts: list[StringPart] = []
        buf: list[str] = []
        buf_start = self.pos
        closed = False
        literal_braces = False  # set after an unparseable `{`: later braces are reported once
        while self.pos < self.end:
            ch = self.text[self.pos]
            if triple and self.text.startswith('"""', self.pos):
                self.pos += 3
                closed = True
                break
            if not triple and ch == quote:
                self.pos += 1
                closed = True
                break
            if ch == "\n" and not triple:
                break
            if ch == "\\":
                esc_start = self.pos
                nxt = self._peek(1)
                if nxt == "u" and self._peek(2) == "{":
                    close = self.text.find("}", self.pos + 3, self.end)
                    hexdigits = self.text[self.pos + 3:close] if close > 0 else ""
                    try:
                        buf.append(chr(int(hexdigits, 16)))
                        self.pos = close + 1
                    except (ValueError, OverflowError):
                        self.pos += 2
                        self._error("S.SYNTAX.INVALID_ESCAPE", "invalid unicode escape", esc_start, self.pos,
                                    help="write \\u{1F600} with 1-6 hex digits")
                    continue
                if nxt in _ESCAPES:
                    buf.append(_ESCAPES[nxt])
                    self.pos += 2
                    continue
                self.pos += 2 if nxt else 1
                self._error("S.SYNTAX.INVALID_ESCAPE", f"unknown escape sequence '\\{nxt}'", esc_start, self.pos,
                            help="valid escapes: \\n \\t \\r \\0 \\\\ \\\" \\{ \\} \\u{HEX}")
                continue
            if ch == "{" and quote == '"':
                if buf:
                    parts.append(StringPart(text="".join(buf), span=self._span(buf_start)))
                    buf = []
                interp_start = self.pos
                self.pos += 1
                sub = Lexer(self.file, self.pos, self.end)
                toks = sub.tokenize(interpolation=True)
                if any(d.stable_code in _NOT_AN_EXPRESSION for d in sub.diagnostics):
                    # the brace does not start an expression (typically JSON or other
                    # brace-heavy text): report once, keep the brace literal, keep lexing
                    first = sub.diagnostics[0]
                    d = self._error("S.SYNTAX.INTERPOLATION", "`{` in a string starts an interpolation, but what "
                                    "follows is not an expression", interp_start, interp_start + 1,
                                    label="interpolation starts here",
                                    help="write a literal brace as `\\{` (and `\\}`), e.g. \"\\{\\\"port\\\": 80\\}\"")
                    if d is not None:
                        d.notes.append(Note(f"inside the interpolation: {first.message}"))
                    literal_braces = True
                    buf_start = interp_start if not buf else buf_start
                    buf.append("{")
                    continue
                self.diagnostics.extend(sub.diagnostics)
                self.comments.extend(sub.comments)
                self.pos = sub.pos
                spec = None
                if self._peek() == ":":
                    spec_start = self.pos + 1
                    close = self.pos
                    while close < self.end and self.text[close] not in '}"\n':
                        close += 1
                    spec = self.text[spec_start:close]
                    self.pos = close
                if self._peek() == "}":
                    self.pos += 1
                elif not sub.diagnostics:
                    self._error("S.SYNTAX.INTERPOLATION", "string interpolation is missing its closing `}`",
                                interp_start, self.pos, help="write a literal brace as `\\{`")
                if len(toks) == 1:  # only EOF
                    self._error("S.SYNTAX.INTERPOLATION", "empty interpolation `{}` in string",
                                interp_start, self.pos, help="write a literal brace as `\\{` or `\\}`")
                parts.append(StringPart(tokens=toks, spec=spec, span=self._span(interp_start)))
                buf_start = self.pos
                continue
            if ch == "}" and quote == '"':
                if not literal_braces:
                    self._error("S.SYNTAX.INTERPOLATION", "unmatched `}` in string literal", self.pos, self.pos + 1,
                                help="write a literal closing brace as `\\}`")
                buf.append("}")
                self.pos += 1
                continue
            buf.append(ch)
            self.pos += 1
        if not closed:
            self._error("S.SYNTAX.UNTERMINATED_STRING", "string literal is not terminated", start,
                        self.pos, help='close the string with `"`' + (' (use """ for multi-line strings)' if not triple else ''))
        if buf or not parts:
            parts.append(StringPart(text="".join(buf), span=self._span(buf_start)))
        value = "".join(p.text for p in parts if p.text is not None) if all(p.tokens is None for p in parts) else None
        if triple and value is not None:
            value = dedent_triple(value)
            parts = [StringPart(text=value, span=parts[0].span)]
        elif triple:
            parts = dedent_triple_parts(parts)
        return Token("STRING", value, self._span(start), parts=parts, triple=triple)


def dedent_triple(text: str) -> str:
    """Triple-quoted strings drop a leading newline and common indentation."""
    if text.startswith("\n"):
        text = text[1:]
    lines = text.split("\n")
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    common = min(indents) if indents else 0
    lines = [l[common:] if len(l) >= common else l.lstrip(" ") for l in lines]
    if lines and lines[-1].strip() == "":
        lines[-1] = ""
    return "\n".join(lines)


def dedent_triple_parts(parts: list[StringPart]) -> list[StringPart]:
    # Compute indentation on the literal segments only (interpolations count as text).
    joined = "".join(p.text if p.text is not None else "\x00" for p in parts)
    if joined.startswith("\n"):
        first = parts[0]
        if first.text is not None:
            first.text = first.text[1:]
        joined = joined[1:]
    lines = joined.split("\n")
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    common = min(indents) if indents else 0
    if common == 0:
        return parts
    out = []
    at_line_start = True
    for p in parts:
        if p.text is None:
            out.append(p)
            at_line_start = False
            continue
        segs = p.text.split("\n")
        new = []
        for i, s in enumerate(segs):
            if i > 0:
                at_line_start = True
            if at_line_start:
                s = s[common:] if len(s) - len(s.lstrip(" ")) >= common else s.lstrip(" ")
            new.append(s)
            at_line_start = False if s else at_line_start
        out.append(StringPart(text="\n".join(new), span=p.span))
    return out


def tokenize(file: SourceFile) -> tuple[list[Token], list[Comment], list[Diagnostic]]:
    lx = Lexer(file)
    toks = lx.tokenize()
    return toks, lx.comments, lx.diagnostics
