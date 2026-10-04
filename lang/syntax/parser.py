"""Recursive-descent parser with newline-context handling and error recovery.

See docs/semantics/syntax.md for the grammar and continuation rules.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

from ..diagnostics import Diagnostic, Fix, Label, TextEdit, code
from ..source import SourceFile, Span
from . import ast as A
from .lexer import Lexer
from .tokens import BINARY_OPERATORS, Comment, Token


class ParseError(Exception):
    pass


DECL_KEYWORDS_CTX = {"record", "enum", "error", "category", "protocol", "predicate", "test", "resource"}
HEADER_CONT = {"->", "throws", "{"}
HEADER_CONT_CTX = {"requires", "ensures", "yields"}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}
LEADING_OP_TOKENS = {"||", "&&", "==", "!=", "<", "<=", ">", ">=", "+", "*", "/", "%", "..", "..=", "|", "&"}
CORE_CASES = {"Some", "None", "Ok", "Err"}


CLOSERS = (")", "]", "}")


class Parser:
    def __init__(self, file: SourceFile, tokens: list[Token], comments: list[Comment] | None = None,
                 allow_toplevel_statements: bool = False):
        self.file = file
        self.toks = tokens
        self.i = 0
        self.diags: list[Diagnostic] = []
        self.comments = comments or []
        self.nl: list[bool] = [False]  # True => newlines insignificant in this context
        self.allow_toplevel_statements = allow_toplevel_statements
        self.unclosed_root: Optional[Diagnostic] = None
        self._stmt_had_error = False
        self.toplevel_statements: list[A.Stmt] = []

    # ------------------------------------------------------------ token access
    def raw(self, k: int = 0) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def peek(self) -> Token:
        if self.nl[-1]:
            while self.toks[self.i].kind == "NEWLINE":
                self.i += 1
        return self.toks[self.i]

    def peek_past_newlines(self, k: int = 0) -> Token:
        j = self.i
        seen = 0
        while True:
            while self.toks[j].kind == "NEWLINE":
                j += 1
            if seen == k or self.toks[j].kind == "EOF":
                return self.toks[j]
            j += 1
            seen += 1

    def peek2(self) -> Token:
        """Token after the current one (respecting newline context)."""
        self.peek()
        j = self.i + 1
        if self.nl[-1]:
            while self.toks[j].kind == "NEWLINE":
                j += 1
        return self.toks[min(j, len(self.toks) - 1)]

    def advance(self) -> Token:
        t = self.peek()
        if t.kind != "EOF":
            self.i += 1
        return t

    def at(self, kind: str) -> bool:
        return self.peek().kind == kind

    def at_ctx(self, word: str) -> bool:
        t = self.peek()
        return t.kind == "IDENT" and t.value == word

    def eat(self, kind: str) -> Optional[Token]:
        if self.peek().kind == kind:
            return self.advance()
        return None

    def eat_ctx(self, word: str) -> Optional[Token]:
        if self.at_ctx(word):
            return self.advance()
        return None

    def skip_newlines(self) -> None:
        while self.toks[self.i].kind == "NEWLINE":
            self.i += 1

    def skip_newlines_if_followed_by(self, kinds: set[str], ctx: set[str] = frozenset()) -> None:
        t = self.peek_past_newlines()
        if t.kind in kinds or (t.kind == "IDENT" and t.value in ctx):
            self.skip_newlines()

    @contextmanager
    def nl_ctx(self, insensitive: bool):
        self.nl.append(insensitive)
        try:
            yield
        finally:
            self.nl.pop()

    # ------------------------------------------------------------ errors
    def error(self, stable: str, msg: str, span: Span, label: str = "", help: str | None = None,
              fix: Fix | None = None, secondary: list[Label] | None = None) -> ParseError:
        d = Diagnostic(code(stable), msg, primary=Label(span, label))
        if help:
            d.help.append(help)
        if fix:
            d.fixes.append(fix)
        if secondary:
            d.secondary.extend(secondary)
        if self.unclosed_root is not None and d is not self.unclosed_root:
            d.likely_cascade = True
            d.notes.append(A_note("probably caused by the unclosed delimiter reported earlier",
                                  self.unclosed_root.span))
        if not self._stmt_had_error:
            self.diags.append(d)
        self._stmt_had_error = True
        return ParseError()

    def expect(self, kind: str, what: str | None = None) -> Token:
        t = self.peek()
        if t.kind == kind:
            return self.advance()
        what = what or f"`{kind}`"
        found = describe(t)
        if kind in CLOSERS and t.kind in CLOSERS:
            raise self.error("S.SYNTAX.MISMATCHED_DELIMITER", f"expected {what}, found `{t.kind}`", t.span,
                             f"expected `{kind}` here",
                             help=f"close the innermost open delimiter with `{kind}` before `{t.kind}`")
        raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", f"expected {what}, found {found}", t.span,
                         f"expected {what}")

    def expect_ident(self, what: str = "a name") -> Token:
        t = self.peek()
        if t.kind == "IDENT":
            return self.advance()
        found = describe(t)
        if t.kind in KEYWORD_KINDS:
            raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", f"expected {what}, found keyword `{t.value}`",
                             t.span, f"`{t.value}` is a reserved keyword",
                             help=f"rename it, e.g. `{t.value}_`")
        raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", f"expected {what}, found {found}", t.span, f"expected {what}")

    def expect_member_name(self) -> Token:
        t = self.peek()
        if t.kind == "IDENT" or t.kind in KEYWORD_KINDS or t.kind == "INT":
            return self.advance()
        raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", f"expected a field or method name, found {describe(t)}",
                         t.span, "expected a name")

    def expect_ctx(self, word: str) -> Token:
        t = self.peek()
        if t.kind == "IDENT" and t.value == word:
            return self.advance()
        raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", f"expected `{word}`, found {describe(t)}", t.span,
                         f"expected `{word}`")

    # ------------------------------------------------------------ recovery
    def sync_stmt(self) -> None:
        start = self.i
        depth = 0
        while True:
            t = self.toks[self.i]
            if t.kind == "EOF":
                return
            if depth == 0 and t.kind in ("NEWLINE", ";"):
                self.i += 1
                return
            if depth == 0 and t.kind == "}":
                return
            if t.kind in ("(", "[", "{"):
                depth += 1
            elif t.kind in (")", "]", "}"):
                depth -= 1
                if depth < 0:
                    if self.i == start and t.kind != "}":
                        self.i += 1  # always make progress past a stray closer (BUG-0007)
                    return
            self.i += 1

    def sync_toplevel(self) -> None:
        depth = 0
        while True:
            t = self.toks[self.i]
            if t.kind == "EOF":
                return
            if t.kind in ("(", "[", "{"):
                depth += 1
            elif t.kind in (")", "]", "}"):
                depth = max(0, depth - 1)
            elif t.kind == "NEWLINE" and depth == 0:
                nxt = self.toks[self.i + 1]
                if nxt.kind in ("fn", "pub", "async", "import", "const") or (
                        nxt.kind == "IDENT" and nxt.value in DECL_KEYWORDS_CTX) or nxt.kind == "mutable":
                    self.i += 1
                    return
            self.i += 1

    def end_stmt(self) -> None:
        t = self.toks[self.i]
        if t.kind in ("NEWLINE", ";"):
            self.i += 1
            return
        if t.kind in ("}", "EOF"):
            return
        raise self.error("S.SYNTAX.MISSING_SEPARATOR",
                         f"expected end of statement, found {describe(t)}", t.span,
                         "start a new line here", help="put each statement on its own line")

    # ------------------------------------------------------------ module
    def parse_module(self) -> A.Module:
        start = self.peek().span
        imports: list[A.Import] = []
        decls: list[A.Decl] = []
        while True:
            self.skip_newlines()
            t = self.toks[self.i]
            if t.kind == "EOF":
                break
            self._stmt_had_error = False
            try:
                if t.kind == "import":
                    imports.append(self.parse_import())
                else:
                    d = self.parse_decl()
                    if d is not None:
                        decls.append(d)
                self.end_stmt()
            except ParseError:
                self.sync_toplevel()
        end = self.toks[self.i].span
        mod = A.Module(span=start.to(end), imports=imports, decls=decls, comments=self.comments)
        return mod

    def parse_import(self) -> A.Import:
        kw = self.advance()
        path = [self.expect_ident("a module path").value]
        names = None
        while self.at("."):
            self.advance()
            if self.at("{"):
                self.advance()
                names = []
                with self.nl_ctx(True):
                    while not self.at("}"):
                        n = self.expect_ident("an imported name")
                        names.append((n.value, n.span))
                        if not self.eat(","):
                            break
                    self.expect("}", "`}` closing the import list")
                break
            path.append(self.expect_ident("a module path segment").value)
        alias = None
        if self.eat("as"):
            alias = self.expect_ident("an alias").value
        return A.Import(span=kw.span.to(self.toks[self.i - 1].span), path=path, names=names, alias=alias)

    def parse_decl(self) -> Optional[A.Decl]:
        t = self.peek()
        start = t.span
        is_pub = False
        if t.kind == "pub":
            self.advance()
            is_pub = True
            t = self.peek()
        if t.kind == "fn" or t.kind == "async" or (t.kind == "IDENT" and t.value == "resource"):
            return self.parse_fn(is_pub, start)
        if t.kind == "mutable":
            self.advance()
            self.expect_ctx("record")
            return self.parse_record(is_pub, start, mutable=True)
        if t.kind == "IDENT":
            if t.value == "record":
                self.advance()
                return self.parse_record(is_pub, start)
            if t.value == "enum":
                self.advance()
                return self.parse_enum(is_pub, start, is_error=False)
            if t.value == "error":
                self.advance()
                if self.at_ctx("enum"):
                    self.advance()
                    return self.parse_enum(is_pub, start, is_error=True)
                return self.parse_record(is_pub, start, kind="error")
            if t.value == "category":
                self.advance()
                n = self.expect_ident("a category name")
                return A.CategoryDecl(span=start.to(n.span), name=n.value, is_pub=is_pub)
            if t.value == "protocol":
                self.advance()
                return self.parse_protocol(is_pub, start)
            if t.value == "predicate":
                self.advance()
                return self.parse_predicate(is_pub, start)
            if t.value == "test" and self.peek2().kind == "STRING":
                self.advance()
                name_tok = self.advance()
                body = self.parse_block()
                td = A.TestDecl(span=start.to(body.span), name=name_tok.value or "", body=body)
                td.ann["name_src"] = name_tok.span.text  # literal as written (formatter)
                return td
        if t.kind == "const":
            self.advance()
            n = self.expect_ident("a constant name")
            ty = None
            if self.eat(":"):
                ty = self.parse_type()
            self.expect("=", "`=` and an initial value")
            self.skip_newlines()
            val = self.parse_expr()
            return A.ConstDecl(span=start.to(val.span), name=n.value, is_pub=is_pub, type=ty, value=val)
        if self.allow_toplevel_statements:
            st = self.parse_stmt()
            self.toplevel_statements.append(st)
            return None
        if t.kind == "let":
            raise self.error("S.MODULE.MUTABLE_GLOBAL",
                             "module-level `let` would create mutable global state",
                             t.span, "not allowed at module level",
                             help="use `const NAME = value` for a frozen module constant, or create state in main and pass it explicitly")
        if t.kind in ("class", ) or (t.kind == "IDENT" and t.value in ("class", "struct", "interface", "trait", "def", "func", "function")):
            raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", f"`{t.value}` is not a declaration keyword in this language",
                             t.span, help="use `fn`, `record`, `mutable record`, `enum` or `protocol`")
        raise self.error("S.SYNTAX.MISPLACED_CONSTRUCT", f"expected a declaration, found {describe(t)}", t.span,
                         "statements are not allowed at module level",
                         help="put executable code inside `fn main() { ... }`")

    def parse_type_params(self) -> list[str]:
        out = []
        if self.at("["):
            self.advance()
            with self.nl_ctx(True):
                while not self.at("]"):
                    out.append(self.expect_ident("a type parameter").value)
                    if not self.eat(","):
                        break
                self.expect("]", "`]` closing type parameters")
        return out

    def parse_fn(self, is_pub: bool, start: Span, owner: str | None = None, allow_no_body: bool = False) -> A.FnDecl:
        is_async = bool(self.eat("async"))
        is_resource = bool(self.eat_ctx("resource"))
        if not is_async and self.at("async"):
            raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", "write `async resource fn`, not `resource async fn`",
                             self.peek().span)
        self.expect("fn", "`fn`")
        name_tok = self.expect_ident("a function name")
        tps = self.parse_type_params()
        params = self.parse_params()
        ret = yields = throws = None
        requires: list[A.Expr] = []
        ensures: list[A.Expr] = []
        self.skip_newlines_if_followed_by(HEADER_CONT, HEADER_CONT_CTX)
        if self.eat("->"):
            ret = self.parse_type()
            self.skip_newlines_if_followed_by(HEADER_CONT, HEADER_CONT_CTX)
        elif self.eat_ctx("yields"):
            yields = self.parse_type()
            self.skip_newlines_if_followed_by(HEADER_CONT, HEADER_CONT_CTX)
        if self.eat("throws"):
            throws = self.parse_throws_list(decl=True)
            self.skip_newlines_if_followed_by(HEADER_CONT, HEADER_CONT_CTX)
        while self.at_ctx("requires") or self.at_ctx("ensures"):
            kw = self.advance()
            with self.nl_ctx(False):
                e = self.parse_expr()
            (requires if kw.value == "requires" else ensures).append(e)
            self.skip_newlines_if_followed_by(HEADER_CONT, HEADER_CONT_CTX)
        body = None
        if self.at("{"):
            body = self.parse_block()
        elif not allow_no_body:
            t = self.peek()
            if t.kind == "=>" or t.kind == "=":
                raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", "function bodies must be braced blocks", t.span,
                                 help="write `{ return expr }`")
            raise self.error("S.SYNTAX.EXPECTED_BLOCK", f"expected `{{` to start the body of `{name_tok.value}`, found {describe(t)}",
                             t.span, "function body expected")
        end = body.span if body else self.toks[self.i - 1].span
        return A.FnDecl(span=start.to(end), name=name_tok.value, is_pub=is_pub, type_params=tps, params=params,
                        ret=ret, yields=yields, throws=throws, requires=requires, ensures=ensures, body=body,
                        is_async=is_async, is_resource=is_resource, owner=owner, name_span=name_tok.span)

    def parse_params(self) -> list[A.Param]:
        self.expect("(", "`(` starting the parameter list")
        params: list[A.Param] = []
        with self.nl_ctx(True):
            while not self.at(")"):
                t = self.peek()
                if t.kind == "self":
                    self.advance()
                    params.append(A.Param(span=t.span, name="self", is_self=True))
                else:
                    n = self.expect_ident("a parameter name")
                    ty = None
                    borrow = False
                    if self.eat(":"):
                        if self.eat("borrow"):
                            borrow = True
                        ty = self.parse_type()
                    default = None
                    if self.eat("="):
                        default = self.parse_expr()
                    end = (default or ty or n).span
                    params.append(A.Param(span=n.span.to(end), name=n.value, type=ty, default=default, borrow=borrow))
                if not self.eat(","):
                    break
            self.expect(")", "`)` closing the parameter list")
        return params

    def parse_throws_list(self, decl: bool) -> list[A.TypeExpr]:
        out = [self.parse_type_atom()]
        while self.at("|") or (decl and self.at(",")):
            self.advance()
            out.append(self.parse_type_atom())
        return out

    def parse_record(self, is_pub: bool, start: Span, kind: str = "record", mutable: bool = False) -> A.RecordDecl:
        name_tok = self.expect_ident("a record name")
        tps = self.parse_type_params()
        category = None
        satisfies: list[A.TypeExpr] = []
        if kind == "error" and self.eat_ctx("category"):
            category = self.expect_ident("a category name").value
        if self.eat_ctx("satisfies"):
            satisfies.append(self.parse_type())
            while self.eat(","):
                satisfies.append(self.parse_type())
        rec = A.RecordDecl(span=start, name=name_tok.value, is_pub=is_pub, kind=kind, mutable=mutable,
                           type_params=tps, satisfies=satisfies, category=category, name_span=name_tok.span)
        if kind == "error" and not self.at("{"):
            rec.span = start.to(self.toks[self.i - 1].span)
            return rec
        self.parse_member_block(rec, name_tok.value)
        rec.span = start.to(self.toks[self.i - 1].span)
        return rec

    def parse_member_block(self, rec, owner: str) -> None:
        open_tok = self.expect("{", "`{` starting the declaration body")
        with self.nl_ctx(False):
            while True:
                self.skip_newlines()
                t = self.toks[self.i]
                if t.kind == "}":
                    self.i += 1
                    return
                if t.kind == "EOF":
                    raise self.unclosed(open_tok)
                self._stmt_had_error = False
                try:
                    self.parse_member(rec, owner)
                    t2 = self.toks[self.i]
                    if t2.kind == ",":
                        self.i += 1  # `,` separates items like a newline (BUG-0004)
                    else:
                        self.end_stmt()
                except ParseError:
                    self.sync_stmt()

    def parse_member(self, rec, owner: str) -> None:
        t = self.peek()
        start = t.span
        is_pub = bool(self.eat("pub"))
        t = self.peek()
        if t.kind in ("fn", "async") or (t.kind == "IDENT" and t.value == "resource"):
            fn = self.parse_fn(is_pub, start, owner=owner)
            rec.methods.append(fn)
            return
        if isinstance(rec, A.RecordDecl) and t.kind == "IDENT" and t.value == "invariant":
            self.advance()
            rec.invariants.append(self.parse_expr())
            return
        if isinstance(rec, A.EnumDecl):
            n = self.expect_ident("a case name")
            fields = None
            if self.at("("):
                fields = []
                self.advance()
                with self.nl_ctx(True):
                    while not self.at(")"):
                        fn_ = self.expect_ident("a payload field name")
                        if not self.at(":"):
                            raise self.error("S.SYNTAX.UNEXPECTED_TOKEN",
                                             f"enum payload fields must be named: `{fn_.value}: Type`",
                                             fn_.span, help=f"write `value: {fn_.value}` (fields need names)")
                        self.advance()
                        fty = self.parse_type()
                        fields.append(A.FieldDecl(span=fn_.span.to(fty.span), name=fn_.value, type=fty))
                        if not self.eat(","):
                            break
                    self.expect(")", "`)` closing the case payload")
            rec.cases.append(A.CaseDecl(span=n.span.to(self.toks[self.i - 1].span), name=n.value, fields=fields))
            return
        sensitive = bool(self.eat_ctx("sensitive")) if self.peek2().kind == "IDENT" else False
        n = self.expect_ident("a field name")
        self.expect(":", "`:` and a field type")
        fty = self.parse_type()
        default = None
        if self.eat("="):
            default = self.parse_expr()
        rec.fields.append(A.FieldDecl(span=n.span.to((default or fty).span), name=n.value, type=fty, default=default,
                                      sensitive=sensitive))

    def parse_enum(self, is_pub: bool, start: Span, is_error: bool) -> A.EnumDecl:
        name_tok = self.expect_ident("an enum name")
        tps = self.parse_type_params()
        category = None
        satisfies: list[A.TypeExpr] = []
        if is_error and self.eat_ctx("category"):
            category = self.expect_ident("a category name").value
        if self.eat_ctx("satisfies"):
            satisfies.append(self.parse_type())
            while self.eat(","):
                satisfies.append(self.parse_type())
        en = A.EnumDecl(span=start, name=name_tok.value, is_pub=is_pub, is_error=is_error, type_params=tps,
                        satisfies=satisfies, category=category, name_span=name_tok.span)
        self.parse_member_block(en, name_tok.value)
        en.span = start.to(self.toks[self.i - 1].span)
        return en

    def parse_protocol(self, is_pub: bool, start: Span) -> A.ProtocolDecl:
        name_tok = self.expect_ident("a protocol name")
        tps = self.parse_type_params()
        proto = A.ProtocolDecl(span=start, name=name_tok.value, is_pub=is_pub, type_params=tps)
        open_tok = self.expect("{", "`{` starting the protocol body")
        with self.nl_ctx(False):
            while True:
                self.skip_newlines()
                t = self.toks[self.i]
                if t.kind == "}":
                    self.i += 1
                    break
                if t.kind == "EOF":
                    raise self.unclosed(open_tok)
                self._stmt_had_error = False
                try:
                    m_start = self.peek().span
                    fn = self.parse_fn(False, m_start, owner=name_tok.value, allow_no_body=True)
                    if fn.body is not None:
                        self.error("S.SYNTAX.MISPLACED_CONSTRUCT", "protocol methods cannot have bodies",
                                   fn.body.span, help="protocols declare signatures and contracts only")
                    proto.methods.append(fn)
                    self.end_stmt()
                except ParseError:
                    self.sync_stmt()
        proto.span = start.to(self.toks[self.i - 1].span)
        return proto

    def parse_predicate(self, is_pub: bool, start: Span) -> A.PredicateDecl:
        name_tok = self.expect_ident("a predicate name")
        params = self.parse_params()
        if self.at("->"):
            self.advance()
            self.parse_type()  # must be Bool; checked later
        body = self.parse_block()
        return A.PredicateDecl(span=start.to(body.span), name=name_tok.value, is_pub=is_pub, params=params, body=body)

    def unclosed(self, open_tok: Token) -> ParseError:
        err = self.error("S.SYNTAX.UNCLOSED_DELIMITER", f"`{open_tok.kind}` is never closed", open_tok.span,
                         "opened here", help=f"add the matching closing delimiter")
        if self.diags and self.unclosed_root is None:
            self.unclosed_root = self.diags[-1]
        return err

    # ------------------------------------------------------------ types
    def parse_type(self) -> A.TypeExpr:
        t = self.parse_type_atom()
        while self.peek().kind == "?":
            q = self.advance()
            t = A.OptionalType(span=t.span.to(q.span), inner=t)
        return t

    def parse_type_atom(self) -> A.TypeExpr:
        t = self.peek()
        if t.kind == "fn" or (t.kind == "async" and self.peek2().kind == "fn"):
            is_async = bool(self.eat("async"))
            start = self.advance().span
            self.expect("(", "`(` in function type")
            params = []
            with self.nl_ctx(True):
                while not self.at(")"):
                    if self.at("IDENT") and self.peek2().kind == ":":
                        self.advance()
                        self.advance()
                    params.append(self.parse_type())
                    if not self.eat(","):
                        break
                close = self.expect(")", "`)` in function type")
            ret = None
            throws = None
            end = close.span
            if self.eat("->"):
                ret = self.parse_type()
                end = ret.span
            if self.at("throws"):
                self.advance()
                throws = self.parse_throws_list(decl=False)
                end = throws[-1].span
            return A.FnType(span=start.to(end), params=params, ret=ret, throws=throws, is_async=is_async)
        if t.kind == "(":
            open_ = self.advance()
            items = []
            with self.nl_ctx(True):
                while not self.at(")"):
                    items.append(self.parse_type())
                    if not self.eat(","):
                        break
                close = self.expect(")", "`)` closing tuple type")
            if len(items) == 0:
                return A.TypeName(span=open_.span.to(close.span), path=["Unit"])
            if len(items) == 1:
                return items[0]
            return A.TupleType(span=open_.span.to(close.span), items=items)
        if t.kind == "IDENT":
            first = self.advance()
            path = [first.value]
            end = first.span
            while self.peek().kind == "." and self.peek2().kind == "IDENT":
                self.advance()
                n = self.advance()
                path.append(n.value)
                end = n.span
            args = []
            if self.peek().kind == "[":
                self.advance()
                with self.nl_ctx(True):
                    while not self.at("]"):
                        args.append(self.parse_type())
                        if not self.eat(","):
                            break
                    close = self.expect("]", "`]` closing type arguments")
                end = close.span
            return A.TypeName(span=first.span.to(end), path=path, args=args)
        if t.kind == "null":
            self.advance()
            raise self.error("S.SYNTAX.EXPECTED_TYPE", "`null` is not a type", t.span,
                             help="use `T?` (Option[T]) for a value that may be absent")
        raise self.error("S.SYNTAX.EXPECTED_TYPE", f"expected a type, found {describe(t)}", t.span, "type expected")

    # ------------------------------------------------------------ blocks / statements
    def parse_block(self) -> A.Block:
        open_tok = self.peek()
        if open_tok.kind != "{":
            raise self.error("S.SYNTAX.EXPECTED_BLOCK", f"expected `{{`, found {describe(open_tok)}",
                             open_tok.span, "block expected")
        self.advance()
        stmts: list[A.Stmt] = []
        with self.nl_ctx(False):
            while True:
                self.skip_newlines()
                t = self.toks[self.i]
                if t.kind == "}":
                    self.i += 1
                    return A.Block(span=open_tok.span.to(t.span), stmts=stmts, end_span=t.span)
                if t.kind == "EOF":
                    raise self.unclosed(open_tok)
                if t.kind in (")", "]"):
                    self.i += 1
                    raise self.error("S.SYNTAX.MISMATCHED_DELIMITER", f"unexpected `{t.kind}` inside a block",
                                     t.span, help="check for a missing opening delimiter",
                                     secondary=[Label(open_tok.span, "block opened here")])
                saved = self._stmt_had_error
                self._stmt_had_error = False
                try:
                    stmts.append(self.parse_stmt())
                    self.end_stmt()
                except ParseError:
                    self.sync_stmt()
                self._stmt_had_error = saved and False

    def parse_stmt(self) -> A.Stmt:
        t = self.peek()
        k = t.kind
        if k == "let" or k == "const":
            return self.parse_let()
        if k == "return":
            self.advance()
            nxt = self.toks[self.i]
            if nxt.kind in ("NEWLINE", "}", ";", "EOF"):
                return A.ReturnStmt(span=t.span, value=None)
            v = self.parse_expr()
            return A.ReturnStmt(span=t.span.to(v.span), value=v)
        if k == "break":
            self.advance()
            return A.BreakStmt(span=t.span)
        if k == "continue":
            self.advance()
            return A.ContinueStmt(span=t.span)
        if k == "throw":
            self.advance()
            v = self.parse_expr()
            return A.ThrowStmt(span=t.span.to(v.span), value=v)
        if k == "defer":
            self.advance()
            if self.at("{"):
                b = self.parse_block()
                return A.DeferStmt(span=t.span.to(b.span), body=b)
            inner = self.parse_stmt()
            if isinstance(inner, A.ExprStmt):
                return A.DeferStmt(span=t.span.to(inner.span), body=inner.expr)
            if not isinstance(inner, A.AssignStmt):
                raise self.error("S.SYNTAX.MISPLACED_CONSTRUCT", "`defer` takes an expression, an assignment or a block",
                                 inner.span, help="wrap it in braces: `defer { ... }`")
            return A.DeferStmt(span=t.span.to(inner.span), body=A.Block(span=inner.span, stmts=[inner]))
        if k == "IDENT" and t.value == "onAbandon" and self.peek2().kind in ("IDENT", "self"):
            self.advance()
            e = self.parse_expr()
            return A.OnAbandonStmt(span=t.span.to(e.span), call=e)
        if k == "nonlocal":
            self.advance()
            names = [self.expect_ident("a captured binding name").value]
            while self.eat(","):
                names.append(self.expect_ident("a captured binding name").value)
            return A.NonlocalStmt(span=t.span.to(self.toks[self.i - 1].span), names=names)
        if k == "assert":
            self.advance()
            c = self.parse_expr()
            msg = None
            if self.eat(","):
                msg = self.parse_expr()
            return A.AssertStmt(span=t.span.to((msg or c).span), cond=c, message=msg)
        if k == "while":
            self.advance()
            c = self.parse_cond()
            b = self.parse_block()
            return A.WhileStmt(span=t.span.to(b.span), cond=c, body=b)
        if k == "for":
            self.advance()
            is_await = bool(self.eat("await"))
            pat = self.parse_pattern()
            self.expect("in", "`in`")
            it = self.parse_cond()
            b = self.parse_block()
            return A.ForStmt(span=t.span.to(b.span), pattern=pat, iterable=it, body=b, is_await=is_await)
        if k in LEADING_OP_TOKENS:
            prev = self._prev_line_end()
            fix = None
            if prev is not None:
                fix = Fix(f"move `{t.value}` to the end of the previous line",
                          [TextEdit(Span(self.file, prev, prev), f" {t.value}"), TextEdit(t.span, "")])
            raise self.error("S.SYNTAX.LEADING_OPERATOR",
                             f"line starts with binary operator `{t.value}`; it does not continue the previous line",
                             t.span, "operator at start of line",
                             help="put the operator at the end of the previous line to continue an expression",
                             fix=fix)
        if k == "{":
            raise self.error("S.SYNTAX.MISPLACED_CONSTRUCT", "bare blocks are not statements", t.span,
                             help="remove the braces, or use `if`/`while`/a helper function for a nested scope")
        if k == "IDENT" and t.value in ("elif", "elsif"):
            raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", f"`{t.value}` is not a keyword", t.span,
                             help="write `else if`")
        # a `-` that starts a line right after a line ending an expression is suspicious
        # (it does not continue that expression); a block's first statement is not (BUG-0006)
        prev_ends_expr = self._prev_line_expr_end() if t.kind == "-" else None
        e = self.parse_expr()
        nt = self.peek()
        if nt.kind in ASSIGN_OPS:
            op = self.advance()
            self.skip_newlines()
            if not isinstance(e, (A.Name, A.Field, A.Index)):
                raise self.error("S.SYNTAX.INVALID_ASSIGNMENT_TARGET", "this expression cannot be assigned to",
                                 e.span, help="assign to a binding, a field (`obj.f = v`) or an element (`xs[i] = v`)")
            v = self.parse_expr()
            return A.AssignStmt(span=e.span.to(v.span), target=e, op=op.kind, value=v)
        if isinstance(e, A.Unary) and e.op == "-" and t.kind == "-" and prev_ends_expr is not None:
            prev = prev_ends_expr
            raise self.error("S.SYNTAX.LEADING_OPERATOR",
                             "line starts with `-`; this is a separate statement, not a continuation",
                             t.span, help="put the `-` at the end of the previous line to continue the expression",
                             fix=Fix("move `-` to the end of the previous line",
                                     [TextEdit(Span(self.file, prev, prev), " -"), TextEdit(t.span, "")]) if prev is not None else None)
        return A.ExprStmt(span=e.span, expr=e)

    def _prev_line_expr_end(self) -> Optional[int]:
        """End offset of the previous line's last token if it could end an expression
        and a line break separates it from the current token; else None."""
        j = self.i - 1
        if j < 0 or self.toks[j].kind != "NEWLINE":
            return None
        while j >= 0 and self.toks[j].kind == "NEWLINE":
            j -= 1
        if j < 0:
            return None
        pt = self.toks[j]
        if pt.kind in ("IDENT", "INT", "FLOAT", "STRING", ")", "]") or \
                (pt.kind in ("true", "false", "null")):
            return pt.span.end
        return None

    def _prev_line_end(self) -> Optional[int]:
        j = self.i - 1
        while j >= 0 and self.toks[j].kind == "NEWLINE":
            j -= 1
        if j < 0:
            return None
        return self.toks[j].span.end

    def parse_let(self) -> A.LetStmt:
        kw = self.advance()
        is_const = kw.kind == "const"
        names: list[tuple[str, Span]] = []
        destructure = False
        if self.at("("):
            destructure = True
            self.advance()
            with self.nl_ctx(True):
                while not self.at(")"):
                    n = self.expect_ident("a binding name")
                    names.append((n.value, n.span))
                    if not self.eat(","):
                        break
                self.expect(")", "`)`")
        else:
            n = self.peek()
            if n.kind == "mutable" or (n.kind == "IDENT" and n.value == "mut"):
                self.advance()
                raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", f"`let {n.value}` is not needed",
                                 n.span, help="`let` bindings are already reassignable; mutability of objects comes from their type (e.g. `mutable record`, `MutableList`)")
            n = self.expect_ident("a binding name")
            names.append((n.value, n.span))
        ty = None
        if self.eat(":"):
            ty = self.parse_type()
        val = None
        if self.eat("="):
            self.skip_newlines()
            val = self.parse_expr()
        elif is_const:
            raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", "`const` requires an initial value",
                             self.peek().span, help="write `const NAME = value`")
        end = (val or ty).span if (val or ty) else names[-1][1]
        return A.LetStmt(span=kw.span.to(end), names=names, destructure=destructure, type=ty, value=val,
                         is_const=is_const)

    def parse_cond(self) -> A.Expr:
        return self.parse_expr()

    # ------------------------------------------------------------ expressions
    def parse_expr(self) -> A.Expr:
        t = self.peek()
        if t.kind == "try":
            return self.parse_try()
        if t.kind == "capture":
            self.advance()
            e = self.parse_or()
            return A.Capture(span=t.span.to(e.span), expr=e)
        if t.kind == "yield":
            self.advance()
            e = self.parse_or()
            return A.Yield(span=t.span.to(e.span), value=e)
        return self.parse_or()

    def parse_try(self) -> A.Try:
        kw = self.advance()
        e = self.parse_or()
        node = A.Try(span=kw.span.to(e.span), expr=e)
        while True:
            nxt = self.peek_past_newlines()
            if nxt.kind == "catch":
                self.skip_newlines()
                ck = self.advance()
                is_cat = bool(self.eat_ctx("category"))
                first = self.expect_ident("an error type or category name")
                path = [first.value]
                while self.peek().kind == "." and self.peek2().kind == "IDENT":
                    self.advance()
                    path.append(self.advance().value)
                binding = None
                if self.eat("as"):
                    binding = self.expect_ident("a binding name").value
                if self.at("{") and not self.at("=>"):
                    handler = self.parse_block()
                else:
                    self.expect("=>", "`=>` before the handler")
                    handler = self.parse_arm_body()
                node.catches.append(A.CatchClause(span=ck.span.to(handler.span), path=path, is_category=is_cat,
                                                  binding=binding, handler=handler))
                node.span = node.span.to(handler.span)
                continue
            if nxt.kind == "else" and node.catches:
                self.skip_newlines()
                el = self.peek()
                raise self.error("S.SYNTAX.MISPLACED_CONSTRUCT",
                                 "an unqualified `else` fallback cannot follow `catch` clauses", el.span,
                                 help="name the remaining error type with another `catch Type => ...` clause")
            if nxt.kind == "else" and not node.catches and self._else_is_fallback():
                self.skip_newlines()
                self.advance()
                if self.at_ctx("on"):
                    on = self.advance()
                    raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", "typed fallbacks are written with `catch`",
                                     on.span, help="write `try e catch ErrorType => fallback`")
                fb = self.parse_or() if not self.at("{") else self.parse_block_expr()
                node.fallback = fb
                node.span = node.span.to(fb.span)
            break
        return node

    def _else_is_fallback(self) -> bool:
        return True

    def parse_block_expr(self) -> A.Expr:
        b = self.parse_block()
        node = A.If(span=b.span, cond=A.Literal(span=b.span, value=True, kind="bool"), then=b, else_=None)
        node.ann["block_expr"] = True  # a bare `{ ... }` in expression position (formatter prints it as a block)
        return node

    def parse_arm_body(self):
        if self.at("{"):
            return self.parse_block()
        self.skip_newlines()
        return self.parse_expr()

    def _binary_rhs_skip(self):
        # after a binary operator, newlines continue the expression
        self.skip_newlines()

    def parse_or(self) -> A.Expr:
        left = self.parse_and()
        while self.at("||"):
            self.advance()
            self._binary_rhs_skip()
            right = self.parse_and()
            left = A.Binary(span=self.sp(left).to(self.sp(right)), op="||", left=left, right=right)
        t = self.peek()
        if t.kind == "IDENT" and t.value in ("and", "or"):
            op = "&&" if t.value == "and" else "||"
            raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", f"`{t.value}` is not an operator in this language",
                             t.span, help=f"use `{op}` (operands must be Bool)",
                             fix=Fix(f"replace `{t.value}` with `{op}`", [TextEdit(t.span, op)]))
        return left

    def parse_and(self) -> A.Expr:
        left = self.parse_cmp()
        while self.at("&&"):
            self.advance()
            self._binary_rhs_skip()
            right = self.parse_cmp()
            left = A.Binary(span=self.sp(left).to(self.sp(right)), op="&&", left=left, right=right)
        return left

    def parse_cmp(self) -> A.Expr:
        left = self.parse_rel()
        if self.at("==") or self.at("!="):
            op = self.advance()
            self._binary_rhs_skip()
            right = self.parse_rel()
            left = A.Binary(span=self.sp(left).to(self.sp(right)), op=op.kind, left=left, right=right)
            if self.at("==") or self.at("!="):
                t = self.peek()
                raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", "comparison operators do not chain", t.span,
                                 help="combine comparisons with `&&` and parentheses")
        return left

    def parse_rel(self) -> A.Expr:
        left = self.parse_is()
        if self.peek().kind in ("<", "<=", ">", ">="):
            op = self.advance()
            self._binary_rhs_skip()
            right = self.parse_is()
            left = A.Binary(span=self.sp(left).to(self.sp(right)), op=op.kind, left=left, right=right)
            if self.peek().kind in ("<", "<=", ">", ">="):
                t = self.peek()
                raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", "comparison operators do not chain", t.span,
                                 help="write `a < b && b < c`")
        return left

    def parse_is(self) -> A.Expr:
        left = self.parse_range()
        while True:
            if self.at("is"):
                self.advance()
                pat = self.parse_pattern(allow_or=False)
                left = A.Is(span=self.sp(left).to(pat.span), expr=left, pattern=pat)
                continue
            if self.at("as"):
                self.advance()
                ty = self.parse_type()
                left = A.As(span=self.sp(left).to(ty.span), expr=left, type=ty)
                continue
            return left

    def parse_range(self) -> A.Expr:
        left = self.parse_add()
        if self.at("..") or self.at("..="):
            op = self.advance()
            self._binary_rhs_skip()
            right = self.parse_add()
            return A.Range(span=self.sp(left).to(self.sp(right)), lo=left, hi=right, inclusive=op.kind == "..=")
        return left

    def parse_add(self) -> A.Expr:
        left = self.parse_mul()
        while self.peek().kind in ("+", "-"):
            op = self.advance()
            nxt = self.peek()
            if nxt.kind == op.kind and nxt.span.start == op.span.end:
                after = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else nxt
                if after.kind in ("NEWLINE", ";", "}", ")", "EOF"):
                    target = left.span.text
                    raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX",
                                     f"`{op.kind}{op.kind}` is not an operator in this language", op.span.to(nxt.span),
                                     help=f"write `{target} {op.kind}= 1`")
            self._binary_rhs_skip()
            right = self.parse_mul()
            left = A.Binary(span=self.sp(left).to(self.sp(right)), op=op.kind, left=left, right=right)
        return left

    def parse_mul(self) -> A.Expr:
        left = self.parse_unary()
        while self.peek().kind in ("*", "/", "%"):
            op = self.advance()
            self._binary_rhs_skip()
            right = self.parse_unary()
            left = A.Binary(span=self.sp(left).to(self.sp(right)), op=op.kind, left=left, right=right)
        return left

    def parse_unary(self) -> A.Expr:
        t = self.peek()
        if t.kind in ("-", "!"):
            self.advance()
            e = self.parse_unary()
            if t.kind == "-" and isinstance(e, A.Literal) and e.kind in ("int", "float") and \
                    e.span.start == t.span.end:  # fold only `-<number>`, never `-(<number>)` (BUG-0005)
                return A.Literal(span=t.span.to(self.sp(e)), value=-e.value, kind=e.kind)
            return A.Unary(span=t.span.to(self.sp(e)), op=t.kind, operand=e)
        if t.kind == "await":
            self.advance()
            e = self.parse_unary()
            return A.Await(span=t.span.to(self.sp(e)), expr=e)
        if t.kind == "propagate":
            self.advance()
            e = self.parse_unary()
            return A.Propagate(span=t.span.to(self.sp(e)), expr=e)
        if t.kind == "try":
            raise self.error("S.SYNTAX.MISPLACED_CONSTRUCT", "`try` must begin the expression it marks",
                             t.span, help="move `try` to the start of the whole expression, e.g. `try a + f()`")
        if t.kind == "IDENT" and t.value == "not":
            raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", "`not` is not an operator", t.span, help="use `!`")
        return self.parse_postfix(self.parse_primary())

    def parse_postfix(self, e: A.Expr) -> A.Expr:
        while True:
            t = self.peek()
            if t.kind == "(":
                e = self.parse_call(e)
                continue
            if t.kind == "[":
                self.advance()
                idx = []
                with self.nl_ctx(True):
                    while not self.at("]"):
                        idx.append(self.parse_expr())
                        if not self.eat(","):
                            break
                    close = self.expect("]", "`]` closing the index")
                e = A.Index(span=self.sp(e).to(close.span), obj=e, indices=idx)
                continue
            if t.kind == "." or (t.kind == "NEWLINE" and self.peek_past_newlines().kind == "."):
                self.skip_newlines()
                self.advance()
                n = self.expect_member_name()
                name = str(n.value)
                e = A.Field(span=self.sp(e).to(n.span), obj=e, name=name, name_span=n.span)
                continue
            if t.kind == "IDENT" and t.value == "with" and self.peek2().kind == "{":
                self.advance()
                self.advance()
                fields = []
                with self.nl_ctx(True):
                    while not self.at("}"):
                        fn_ = self.expect_ident("a field name")
                        self.expect(":", "`:` after the field name")
                        v = self.parse_expr()
                        fields.append((fn_.value, v, fn_.span))
                        if not self.eat(","):
                            break
                    close = self.expect("}", "`}` closing the update")
                e = A.WithUpdate(span=self.sp(e).to(close.span), obj=e, fields=fields)
                continue
            if t.kind == "?" :
                raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", "postfix `?` is not an operator in this language",
                                 t.span, help="use `try expr` to propagate errors, or `propagate r` for Results")
            return e

    def parse_call(self, callee: A.Expr) -> A.Call:
        self.advance()
        args: list[A.Arg] = []
        with self.nl_ctx(True):
            while not self.at(")"):
                t = self.peek()
                if t.kind == "IDENT" and self.peek2().kind == ":":
                    self.advance()
                    self.advance()
                    v = self.parse_expr()
                    args.append(A.Arg(t.value, v, t.span.to(self.sp(v))))
                elif t.kind == "IDENT" and self.peek2().kind == "=" :
                    raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", "named arguments use `name: value`",
                                     self.peek2().span, help=f"write `{t.value}: ...`")
                else:
                    v = self.parse_expr()
                    args.append(A.Arg(None, v, v.span))
                if not self.eat(","):
                    break
            close = self.expect(")", "`)` closing the argument list")
        return A.Call(span=self.sp(callee).to(close.span), callee=callee, args=args)

    def parse_primary(self) -> A.Expr:
        t = self.peek()
        k = t.kind
        if k == "INT":
            self.advance()
            return A.Literal(span=t.span, value=t.value, kind="int")
        if k == "FLOAT":
            self.advance()
            return A.Literal(span=t.span, value=t.value, kind="float")
        if k == "STRING":
            self.advance()
            return self.string_literal(t)
        if k == "true" or k == "false":
            self.advance()
            return A.Literal(span=t.span, value=(k == "true"), kind="bool")
        if k == "null":
            self.advance()
            return A.Literal(span=t.span, value=None, kind="null")
        if k == "IDENT":
            self.advance()
            if t.value in ("None", "nil", "undefined") and t.value != "None":
                pass
            return A.Name(span=t.span, name=t.value)
        if k == "self":
            self.advance()
            return A.Name(span=t.span, name="self")
        if k == "(":
            return self.parse_paren()
        if k == "[":
            self.advance()
            items = []
            with self.nl_ctx(True):
                while not self.at("]"):
                    items.append(self.parse_expr())
                    if not self.eat(","):
                        break
                close = self.expect("]", "`]` closing the list")
            return A.ListLit(span=t.span.to(close.span), items=items)
        if k == "{":
            self.advance()
            entries = []
            with self.nl_ctx(True):
                while not self.at("}"):
                    key = self.parse_expr()
                    self.expect(":", "`:` between map key and value")
                    val = self.parse_expr()
                    entries.append((key, val))
                    if not self.eat(","):
                        break
                close = self.expect("}", "`}` closing the map literal")
            return A.MapLit(span=t.span.to(close.span), entries=entries)
        if k == "fn" or (k == "async" and self.peek2().kind == "fn"):
            return self.parse_lambda()
        if k == "if":
            return self.parse_if()
        if k == "match":
            return self.parse_match()
        if k == "use":
            return self.parse_use()
        if k == "parallel":
            self.advance()
            mode = "failfast"
            if self.at_ctx("collect") or self.at_ctx("race") or self.at_ctx("firstSuccess"):
                mode = self.advance().value
            elif self.at("."):
                dot = self.advance()
                raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", "task-group modes are written `parallel collect { ... }`",
                                 dot.span, help="use `parallel`, `parallel collect`, `parallel race` or `parallel firstSuccess` followed by a block of spawns")
            body = self.parse_block()
            return A.Parallel(span=t.span.to(body.span), mode=mode, body=body)
        if k == "spawn":
            self.advance()
            if self.at("{"):
                b = self.parse_block()
                return A.Spawn(span=t.span.to(b.span), call=None, block=b)
            e = self.parse_postfix(self.parse_primary())
            if not isinstance(e, A.Call):
                raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", "`spawn` takes a function call or a block",
                                 e.span, help="write `spawn work(args)` or `spawn { ... }`")
            return A.Spawn(span=t.span.to(e.span), call=e, block=None)
        if k == "select":
            return self.parse_select()
        if k == "within":
            self.advance()
            d = self.parse_or()
            body = self.parse_block()
            return A.Within(span=t.span.to(body.span), deadline=d, body=body)
        if k == "await":
            return self.parse_unary()
        if k in ("NEWLINE", "EOF", "}"):
            raise self.error("S.SYNTAX.EXPECTED_EXPRESSION", "expected an expression", t.span, "expression expected")
        raise self.error("S.SYNTAX.EXPECTED_EXPRESSION", f"expected an expression, found {describe(t)}", t.span,
                         "expression expected")

    def parse_paren(self) -> A.Expr:
        open_ = self.advance()
        with self.nl_ctx(True):
            if self.at(")"):
                close = self.advance()
                return A.Literal(span=open_.span.to(close.span), value=None, kind="unit")
            first = self.parse_expr()
            if self.at(","):
                items = [first]
                while self.eat(","):
                    if self.at(")"):
                        break
                    items.append(self.parse_expr())
                close = self.expect(")", "`)` closing the tuple")
                return A.TupleLit(span=open_.span.to(close.span), items=items)
            close = self.expect(")", "`)`")
        first.span = open_.span.to(close.span) if isinstance(first, (A.Binary,)) else first.span
        first.ann["outer_span"] = open_.span.to(close.span)  # includes the parentheses (BUG-0005)
        return first

    @staticmethod
    def sp(e) -> Span:
        """Source extent of an operand including any enclosing parentheses."""
        return e.ann.get("outer_span", e.span)

    def string_literal(self, t: Token) -> A.StringLit:
        parts: list = []
        for p in t.parts:
            if p.tokens is None:
                parts.append(p.text or "")
            else:
                sub = Parser(self.file, p.tokens)
                sub.nl = [True]
                try:
                    if sub.peek().kind == "EOF":
                        expr = A.Literal(span=p.span, value="", kind="str")
                    else:
                        expr = sub.parse_expr()
                        if sub.peek().kind != "EOF":
                            bad = sub.peek()
                            sub.error("S.SYNTAX.INTERPOLATION", f"unexpected {describe(bad)} in interpolation",
                                      bad.span)
                except ParseError:
                    expr = A.Literal(span=p.span, value="", kind="str")
                self.diags.extend(sub.diags)
                parts.append(A.InterpPart(expr=expr, spec=p.spec, span=p.span))
        return A.StringLit(span=t.span, parts=parts, triple=t.triple)

    def parse_lambda(self) -> A.Lambda:
        start = self.peek().span
        is_async = bool(self.eat("async"))
        self.expect("fn")
        params = self.parse_params()
        ret = None
        throws = None
        if self.eat("->"):
            ret = self.parse_type()
        if self.eat("throws"):
            throws = self.parse_throws_list(decl=False)
        if self.at("{"):
            body = self.parse_block()
            return A.Lambda(span=start.to(body.span), params=params, ret=ret, throws=throws, body=body,
                            is_async=is_async, is_block=True)
        self.expect("=>", "`=>` or a block for the lambda body")
        if self.at("{"):
            body = self.parse_block()
            return A.Lambda(span=start.to(body.span), params=params, ret=ret, throws=throws, body=body,
                            is_async=is_async, is_block=True)
        self.skip_newlines()
        e = self.parse_expr()
        return A.Lambda(span=start.to(e.span), params=params, ret=ret, throws=throws, body=e, is_async=is_async,
                        is_block=False)

    def parse_if(self) -> A.If:
        kw = self.advance()
        cond = self.parse_cond()
        then = self.parse_block()
        node = A.If(span=kw.span.to(then.span), cond=cond, then=then)
        nxt = self.peek_past_newlines()
        if nxt.kind == "else":
            self.skip_newlines()
            self.advance()
            if self.at("if"):
                node.else_ = self.parse_if()
            else:
                node.else_ = self.parse_block()
            node.span = node.span.to(node.else_.span)
        elif nxt.kind == "IDENT" and nxt.value in ("elif", "elsif"):
            self.skip_newlines()
            raise self.error("S.SYNTAX.UNSUPPORTED_SYNTAX", f"`{nxt.value}` is not a keyword", nxt.span,
                             help="write `else if`")
        return node

    def parse_match(self) -> A.Match:
        kw = self.advance()
        scrut = self.parse_expr()
        open_tok = self.expect("{", "`{` starting the match arms")
        arms: list[A.MatchArm] = []
        with self.nl_ctx(False):
            while True:
                self.skip_newlines()
                t = self.toks[self.i]
                if t.kind == "}":
                    self.i += 1
                    break
                if t.kind == "EOF":
                    raise self.unclosed(open_tok)
                self._stmt_had_error = False
                try:
                    pat = self.parse_pattern()
                    guard = None
                    if self.eat("if"):
                        guard = self.parse_expr()
                    if self.at(":") or self.at("->"):
                        bad = self.peek()
                        raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", f"match arms use `=>`, found `{bad.kind}`",
                                         bad.span, help="write `pattern => result`")
                    self.expect("=>", "`=>` after the pattern")
                    body = self.parse_arm_body()
                    arms.append(A.MatchArm(span=pat.span.to(body.span), pattern=pat, guard=guard, body=body))
                    if self.toks[self.i].kind == ",":
                        self.i += 1  # `,` separates items like a newline (BUG-0004)
                    else:
                        self.end_stmt()
                except ParseError:
                    self.sync_stmt()
        return A.Match(span=kw.span.to(self.toks[self.i - 1].span), scrutinee=scrut, arms=arms)

    def parse_use(self) -> A.Use:
        kw = self.advance()
        n = self.expect_ident("a resource binding name")
        self.expect("=", "`=` and a resource provider call")
        init = self.parse_expr()
        body = self.parse_block()
        return A.Use(span=kw.span.to(body.span), name=n.value, init=init, body=body, name_span=n.span)

    def parse_select(self) -> A.Select:
        kw = self.advance()
        mode = "normal"
        if self.at_ctx("now"):
            self.advance()
            mode = "now"
        elif self.at_ctx("priority"):
            self.advance()
            mode = "priority"
        open_tok = self.expect("{", "`{` starting the select branches")
        branches: list[A.SelectBranch] = []
        with self.nl_ctx(False):
            while True:
                self.skip_newlines()
                t = self.toks[self.i]
                if t.kind == "}":
                    self.i += 1
                    break
                if t.kind == "EOF":
                    raise self.unclosed(open_tok)
                self._stmt_had_error = False
                try:
                    branches.append(self.parse_select_branch())
                    if self.toks[self.i].kind == ",":
                        self.i += 1  # `,` separates items like a newline (BUG-0004)
                    else:
                        self.end_stmt()
                except ParseError:
                    self.sync_stmt()
        return A.Select(span=kw.span.to(self.toks[self.i - 1].span), mode=mode, branches=branches)

    def parse_select_branch(self) -> A.SelectBranch:
        start = self.peek().span
        guard = None
        guard_span = None
        if self.at_ctx("when"):
            self.advance()
            g = self.peek()
            if g.kind not in ("IDENT", "true", "false"):
                raise self.error("S.SELECT.INVALID_GUARD", "a select guard must be a precomputed local Bool name",
                                 g.span, help="compute the condition first: `let canSend = ...` then `when canSend:`")
            self.advance()
            guard = g.value if g.kind == "IDENT" else g.kind
            guard_span = g.span
            if not self.at(":"):
                bad = self.peek()
                raise self.error("S.SELECT.INVALID_GUARD", "a select guard must be a single local Bool name followed by `:`",
                                 bad.span, help="compute the condition first: `let canSend = ...` then `when canSend:`")
            self.advance()
            self.skip_newlines()
        t = self.peek()
        word = t.value if t.kind == "IDENT" else None
        binding = target = value = None
        if word == "receive":
            self.advance()
            b = self.peek()
            if b.kind == "IDENT":
                binding = self.advance().value
            else:
                raise self.error("S.SYNTAX.UNEXPECTED_TOKEN", "expected a binding name after `receive`", b.span)
            self.expect_ctx("from")
            target = self.parse_or()
            kind = "receive"
        elif word == "closed":
            self.advance()
            target = self.parse_or()
            kind = "closed"
        elif word == "send":
            self.advance()
            value = self.parse_or()
            self.expect_ctx("to")
            target = self.parse_or()
            kind = "send"
        elif word == "task":
            self.advance()
            target = self.parse_postfix(self.parse_primary())
            self.expect_ctx("completed")
            self.expect("as", "`as` and a binding name")
            binding = self.expect_ident("a binding for the task result").value
            kind = "task"
        elif word == "at":
            self.advance()
            target = self.parse_or()
            kind = "at"
        elif word == "after":
            self.advance()
            target = self.parse_or()
            kind = "after"
        elif word == "none":
            self.advance()
            self.expect_ctx("ready")
            kind = "none"
        elif t.kind == "else" or (t.kind == "IDENT" and t.value == "default"):
            raise self.error("S.SELECT.NONE_READY_PLACEMENT", "blocking select has no default branch", t.span,
                             help="use `select now { ...; none ready => ... }` for a non-blocking check")
        else:
            raise self.error("S.SYNTAX.UNEXPECTED_TOKEN",
                             f"expected a select branch (receive/closed/send/task/at/after/none ready), found {describe(t)}",
                             t.span)
        self.expect("=>", "`=>` before the branch handler")
        body = self.parse_arm_body()
        return A.SelectBranch(span=start.to(body.span), kind=kind, guard=guard, guard_span=guard_span,
                              binding=binding, target=target, value=value, body=body)

    # ------------------------------------------------------------ patterns
    def parse_pattern(self, allow_or: bool = True) -> A.Pattern:
        p = self.parse_alt_pattern()
        if not allow_or:
            return p
        alts = [p]
        while self.at("|"):
            self.advance()
            self.skip_newlines()
            alts.append(self.parse_alt_pattern())
        if len(alts) == 1:
            return p
        return A.OrPat(span=alts[0].span.to(alts[-1].span), alts=alts)

    def parse_alt_pattern(self) -> A.Pattern:
        t = self.peek()
        k = t.kind
        if k == "IDENT" and t.value == "_":
            self.advance()
            return A.WildcardPat(span=t.span)
        if k == "INT":
            self.advance()
            return A.LiteralPat(span=t.span, value=t.value, kind="int")
        if k == "FLOAT":
            self.advance()
            return A.LiteralPat(span=t.span, value=t.value, kind="float")
        if k == "-" and self.peek2().kind in ("INT", "FLOAT"):
            self.advance()
            n = self.advance()
            return A.LiteralPat(span=t.span.to(n.span), value=-n.value, kind="int" if n.kind == "INT" else "float")
        if k == "STRING":
            self.advance()
            if t.value is None:
                raise self.error("S.SYNTAX.EXPECTED_PATTERN", "string patterns cannot contain interpolation", t.span)
            return A.LiteralPat(span=t.span, value=t.value, kind="str")
        if k in ("true", "false"):
            self.advance()
            return A.LiteralPat(span=t.span, value=(k == "true"), kind="bool")
        if k == "null":
            self.advance()
            return A.CasePat(span=t.span, path=["None"], args=None)
        if k == "(":
            open_ = self.advance()
            items = []
            with self.nl_ctx(True):
                while not self.at(")"):
                    items.append(self.parse_pattern())
                    if not self.eat(","):
                        break
                close = self.expect(")", "`)` closing the tuple pattern")
            if len(items) == 1:
                return items[0]
            return A.TuplePat(span=open_.span.to(close.span), items=items)
        if k == "IDENT" or k == "self":
            first = self.advance()
            path = [first.value]
            end = first.span
            while self.peek().kind == "." and self.peek2().kind == "IDENT":
                self.advance()
                n = self.advance()
                path.append(n.value)
                end = n.span
            if self.peek().kind == "(":
                self.advance()
                args: list = []
                with self.nl_ctx(True):
                    while not self.at(")"):
                        a = self.peek()
                        if a.kind == "IDENT" and self.peek2().kind == ":":
                            self.advance()
                            self.advance()
                            args.append((a.value, self.parse_pattern()))
                        else:
                            args.append((None, self.parse_pattern()))
                        if not self.eat(","):
                            break
                    close = self.expect(")", "`)` closing the pattern")
                return A.CasePat(span=first.span.to(close.span), path=path, args=args)
            if len(path) > 1 or path[0] in CORE_CASES:
                return A.CasePat(span=first.span.to(end), path=path, args=None)
            if self.peek().kind == ":":
                self.advance()
                ty = self.parse_type()
                return A.BindPat(span=first.span.to(ty.span), name=path[0], type=ty)
            return A.BindPat(span=first.span, name=path[0])
        raise self.error("S.SYNTAX.EXPECTED_PATTERN", f"expected a pattern, found {describe(t)}", t.span,
                         "pattern expected")


def A_note(msg: str, span: Optional[Span]):
    from ..diagnostics.model import Note
    return Note(msg, span)


KEYWORD_KINDS = frozenset("""
fn async await let const return if else while for in break continue match mutable throws throw try catch
capture propagate as is use yield borrow defer parallel spawn select within import pub assert true false null
nonlocal self
""".split())


def describe(t: Token) -> str:
    if t.kind == "EOF":
        return "end of file"
    if t.kind == "NEWLINE":
        return "end of line"
    if t.kind == "IDENT":
        return f"`{t.value}`"
    if t.kind in ("INT", "FLOAT"):
        return f"number `{t.value}`"
    if t.kind == "STRING":
        return "a string literal"
    return f"`{t.kind}`"


class ParseResult:
    def __init__(self, module: A.Module, diagnostics: list[Diagnostic], comments: list[Comment],
                 statements: list[A.Stmt]):
        self.module = module
        self.diagnostics = diagnostics
        self.comments = comments
        self.statements = statements

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def parse_source(file: SourceFile, allow_toplevel_statements: bool = False) -> ParseResult:
    lx = Lexer(file)
    toks = lx.tokenize()
    p = Parser(file, toks, lx.comments, allow_toplevel_statements=allow_toplevel_statements)
    mod = p.parse_module()
    diags = lx.diagnostics + p.diags
    # Order by position; lexer errors first at equal positions.
    diags.sort(key=lambda d: (d.span.start if d.span else 0))
    return ParseResult(mod, diags, lx.comments, p.toplevel_statements)


def parse_text(text: str, path: str = "<input>", allow_toplevel_statements: bool = False) -> ParseResult:
    return parse_source(SourceFile(path, text), allow_toplevel_statements)
