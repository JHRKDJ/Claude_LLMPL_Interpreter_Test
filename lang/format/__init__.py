"""Canonical formatter (V3 4.8, 7.14.3; contract: docs/semantics/formatter.md).

An AST pretty-printer: one canonical layout per construct, 4-space indentation,
braces on the opening line, one statement per line, at most one preserved blank line
between statements/members, comments preserved (own-line comments before the item
that follows them, trailing comments after the item they share a line with).
String and numeric literals are reproduced from source so escapes and digit
separators survive. The formatter refuses source with syntax errors.

Idempotence (`format(format(x)) == format(x)`) and parse/format/parse equivalence
are tested by tests/fuzz/test_formatter_fuzz.py.
"""
from __future__ import annotations

from typing import Optional

from ..source import SourceFile
from ..syntax import ast as A
from ..syntax.parser import parse_source

INDENT = "    "
WIDTH = 100

# binding strength (higher binds tighter); see docs/semantics/syntax.md §3
PREC = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4,
        "+": 7, "-": 7, "*": 8, "/": 8, "%": 8}
NONASSOC = {"==", "!=", "<", "<=", ">", ">="}
P_IS, P_RANGE, P_UNARY, P_POSTFIX, P_LOW = 5, 6, 9, 10, 0


class FormatError(ValueError):
    pass


def format_source(text: str, path: str = "<input>") -> str:
    sf = SourceFile(path, text)
    res = parse_source(sf)
    if not res.ok:
        first = next(d for d in res.diagnostics if d.severity == "error")
        loc = ""
        if first.primary is not None and first.primary.span is not None:
            line, col = first.primary.span.start_line_col
            loc = f" at {line}:{col}"
        raise FormatError(f"source has syntax errors ({first.stable_code}{loc}: {first.message})")
    out = Formatter(sf, res.module, res.comments).run()
    # safety net: the canonical form must parse to the same program
    check = parse_source(SourceFile(path, out))
    if not check.ok:
        raise FormatError("internal formatter error: output does not parse "
                          f"({next(d for d in check.diagnostics if d.severity == 'error').message})")
    from .equiv import ast_equal
    diff = ast_equal(res.module, check.module, "module")
    if diff is not None:
        raise FormatError(f"internal formatter error: output changes the program ({diff})")
    if len([c for c in check.comments if not _in_string(c, check.module)]) != \
            len([c for c in res.comments if not _in_string(c, res.module)]):
        raise FormatError("internal formatter error: a comment was lost")
    return out


def _in_string(c, mod) -> bool:
    return any(isinstance(n, A.StringLit) and n.span.start <= c.span.start < n.span.end for n in A.walk(mod))


def prec(e) -> int:
    c = e.__class__
    if c is A.Binary:
        return PREC[e.op]
    if c in (A.Is, A.As):
        return P_IS
    if c is A.Range:
        return P_RANGE
    if c in (A.Unary, A.Await, A.Propagate):
        return P_UNARY
    if c in (A.Try, A.Capture, A.Yield):
        return P_LOW
    if c is A.Lambda and not e.is_block:
        return P_LOW
    if c is A.Literal and e.kind in ("int", "float") and e.span.text.lstrip().startswith("-"):
        return P_UNARY  # a folded negative literal behaves like a prefix minus
    return P_POSTFIX


class Out:
    def __init__(self):
        self.lines: list[str] = []

    def line(self, indent: int, text: str) -> None:
        self.lines.append((INDENT * indent + text) if text else "")

    def blank(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def append_to_last(self, text: str) -> None:
        self.lines[-1] += text


class Formatter:
    def __init__(self, sf: SourceFile, mod: A.Module, comments):
        self.sf = sf
        self.mod = mod
        strings = [n.span for n in A.walk(mod) if isinstance(n, A.StringLit)]
        self.comments = sorted((c for c in comments
                                if not any(s.start <= c.span.start < s.end for s in strings)),
                               key=lambda c: c.span.start)
        self.ci = 0
        self.out = Out()
        self.prev_end_line: Optional[int] = None
        self.block_start = False

    # ------------------------------------------------------------ positions
    def line_of(self, pos: int) -> int:
        return self.sf.line_col(pos)[0]

    def gap_before(self, pos: int) -> None:
        """Preserve (at most) one blank line before the item starting at `pos`
        (never directly after an opening brace)."""
        if self.block_start:
            self.block_start = False
            return
        if self.prev_end_line is not None and self.line_of(pos) - self.prev_end_line > 1:
            self.out.blank()

    # ------------------------------------------------------------ comments
    def leading_comments(self, pos: int, indent: int) -> None:
        while self.ci < len(self.comments) and self.comments[self.ci].span.start < pos:
            c = self.comments[self.ci]
            self.ci += 1
            if not c.own_line and self.out.lines and self.prev_end_line is not None and \
                    self.line_of(c.span.start) == self.prev_end_line:
                self.out.append_to_last("  " + c.text.rstrip())
                continue
            self.gap_before(c.span.start)
            text_lines = c.text.rstrip().split("\n")
            self.out.line(indent, text_lines[0])
            for extra in text_lines[1:]:
                self.out.lines.append(extra.rstrip())
            self.prev_end_line = self.line_of(c.span.start) + len(text_lines) - 1

    def trailing_comment(self, end: int) -> None:
        """Attach a comment that shares the source line where an item ends."""
        end_line = self.line_of(max(end - 1, 0))
        self.prev_end_line = end_line
        if self.ci < len(self.comments):
            c = self.comments[self.ci]
            if c.span.start >= end - 1 and not c.own_line and self.line_of(c.span.start) == end_line \
                    and "\n" not in c.text:
                self.out.append_to_last("  " + c.text.rstrip())
                self.ci += 1

    def flush_comments(self, pos: int, indent: int) -> None:
        self.leading_comments(pos, indent)

    # ------------------------------------------------------------ module
    def run(self) -> str:
        m = self.mod
        for imp in m.imports:
            self.leading_comments(imp.span.start, 0)
            self.gap_before(imp.span.start)
            self.out.line(0, self.import_(imp))
            self.trailing_comment(imp.span.end)
        first = True
        for d in m.decls:
            self.leading_comments(d.span.start, 0)
            if m.imports or not first:
                if isinstance(d, A.ConstDecl) and self._prev_decl_const and not self._source_gap(d):
                    pass
                else:
                    self.out.blank()
            self.decl(d, 0)
            self.trailing_comment(d.span.end)
            self._prev_decl_const = isinstance(d, A.ConstDecl)
            first = False
        self.leading_comments(len(self.sf.text) + 1, 0)
        while self.out.lines and self.out.lines[-1] == "":
            self.out.lines.pop()
        return "\n".join(self.out.lines) + "\n" if self.out.lines else ""

    _prev_decl_const = False

    def _source_gap(self, d) -> bool:
        return self.prev_end_line is not None and self.line_of(d.span.start) - self.prev_end_line > 1

    def import_(self, imp: A.Import) -> str:
        s = "import " + ".".join(imp.path)
        if imp.names is not None:
            s += ".{" + ", ".join(n for n, _ in imp.names) + "}"
        if imp.alias:
            s += " as " + imp.alias
        return s

    # ------------------------------------------------------------ declarations
    def decl(self, d, ind: int) -> None:
        pub = "pub " if getattr(d, "is_pub", False) else ""
        c = d.__class__
        if c is A.FnDecl:
            self.fn_decl(d, ind)
        elif c is A.RecordDecl:
            kw = "error" if d.kind == "error" else ("mutable record" if d.mutable else "record")
            head = f"{pub}{kw} {d.name}{self.tparams(d.type_params)}"
            if d.category:
                head += f" category {d.category}"
            if d.satisfies:
                head += " satisfies " + ", ".join(self.type_(t) for t in d.satisfies)
            members = [(f.span.start, "field", f) for f in d.fields] + \
                      [(e.span.start, "inv", e) for e in d.invariants] + \
                      [(m.span.start, "method", m) for m in d.methods]
            self.member_block(head, sorted(members, key=lambda x: x[0]), ind, d.span.end)
        elif c is A.EnumDecl:
            kw = "error enum" if d.is_error else "enum"
            head = f"{pub}{kw} {d.name}{self.tparams(d.type_params)}"
            if d.category:
                head += f" category {d.category}"
            if d.satisfies:
                head += " satisfies " + ", ".join(self.type_(t) for t in d.satisfies)
            members = [(cs.span.start, "case", cs) for cs in d.cases] + \
                      [(m.span.start, "method", m) for m in d.methods]
            self.member_block(head, sorted(members, key=lambda x: x[0]), ind, d.span.end)
        elif c is A.ProtocolDecl:
            head = f"{pub}protocol {d.name}{self.tparams(d.type_params)}"
            self.member_block(head, [(m.span.start, "method", m) for m in d.methods], ind, d.span.end)
        elif c is A.CategoryDecl:
            self.out.line(ind, f"{pub}category {d.name}")
        elif c is A.PredicateDecl:
            head = f"{pub}predicate {d.name}({self.params(d.params)})"
            self.block_after(head, d.body, ind)
        elif c is A.ConstDecl:
            t = f": {self.type_(d.type)}" if d.type is not None else ""
            self.expr_line(ind, f"{pub}const {d.name}{t} = ", d.value, "")
        elif c is A.TestDecl:
            self.block_after(f"test {d.ann.get('name_src') or chr(34) + d.name + chr(34)}", d.body, ind)
        else:  # pragma: no cover - parser produces no other declarations
            raise FormatError(f"cannot format {c.__name__}")

    def member_block(self, head: str, members, ind: int, end: int) -> None:
        if not members and not self._comments_before(end):
            self.out.line(ind, head + " {}")
            return
        self.out.line(ind, head + " {")
        self.block_start = True
        prev_kind = None
        for pos, kind, m in members:
            self.leading_comments(pos, ind + 1)
            if prev_kind is not None and (kind == "method" or prev_kind == "method" or kind != prev_kind):
                self.out.blank()
                self.block_start = False
            else:
                self.gap_before(pos)
            if kind == "field":
                self.field(m, ind + 1)
            elif kind == "inv":
                self.expr_line(ind + 1, "invariant ", m, "")
            elif kind == "case":
                self.case(m, ind + 1)
            else:
                self.fn_decl(m, ind + 1)
            self.trailing_comment(m.span.end)
            prev_kind = kind
        self.leading_comments(end - 1, ind + 1)
        self.out.line(ind, "}")

    def _comments_before(self, end: int) -> bool:
        return self.ci < len(self.comments) and self.comments[self.ci].span.start < end

    def field(self, f: A.FieldDecl, ind: int) -> None:
        s = ("sensitive " if f.sensitive else "") + f"{f.name}: {self.type_(f.type)}"
        if f.default is not None:
            self.expr_line(ind, s + " = ", f.default, "")
        else:
            self.out.line(ind, s)

    def case(self, c: A.CaseDecl, ind: int) -> None:
        if c.fields is None:
            self.out.line(ind, c.name)
        else:
            self.out.line(ind, c.name + "(" + ", ".join(f"{f.name}: {self.type_(f.type)}" for f in c.fields) + ")")

    def fn_header(self, d: A.FnDecl) -> str:
        s = "pub " if d.is_pub else ""
        if d.is_async:
            s += "async "
        if d.is_resource:
            s += "resource "
        s += f"fn {d.name}{self.tparams(d.type_params)}({self.params(d.params)})"
        if d.yields is not None:
            s += f" yields {self.type_(d.yields)}"
        elif d.ret is not None:
            s += f" -> {self.type_(d.ret)}"
        if d.throws is not None:
            s += " throws " + ", ".join(self.type_(t) for t in d.throws)
        return s

    def fn_decl(self, d: A.FnDecl, ind: int) -> None:
        head = self.fn_header(d)
        contracts = [("requires", e) for e in d.requires] + [("ensures", e) for e in d.ensures]
        if not contracts:
            if d.body is None:
                self.out.line(ind, head)
            else:
                self.block_after(head, d.body, ind)
            return
        self.out.line(ind, head)
        for kw, e in contracts:
            self.out.line(ind + 1, f"{kw} {self.expr(e, ind + 1)}")
        if d.body is not None:
            self.block_lines("{", d.body, ind)

    def tparams(self, tps) -> str:
        return "[" + ", ".join(tps) + "]" if tps else ""

    def params(self, ps) -> str:
        return ", ".join(self.param(p) for p in ps)

    def param(self, p: A.Param) -> str:
        if p.is_self:
            return "self"
        s = p.name
        if p.type is not None:
            s += ": " + ("borrow " if p.borrow else "") + self.type_(p.type)
        if p.default is not None:
            s += " = " + self.expr(p.default, 0)
        return s

    # ------------------------------------------------------------ types
    def type_(self, t) -> str:
        c = t.__class__
        if c is A.TypeName:
            s = ".".join(t.path)
            if t.args:
                s += "[" + ", ".join(self.type_(a) for a in t.args) + "]"
            return s
        if c is A.OptionalType:
            inner = self.type_(t.inner)
            if isinstance(t.inner, A.FnType):
                inner = f"({inner})"
            return inner + "?"
        if c is A.TupleType:
            return "(" + ", ".join(self.type_(i) for i in t.items) + ")"
        if c is A.FnType:
            s = ("async " if t.is_async else "") + "fn(" + ", ".join(self.type_(p) for p in t.params) + ")"
            if t.ret is not None:
                s += " -> " + self.type_(t.ret)
            if t.throws:
                s += " throws " + " | ".join(self.type_(x) for x in t.throws)
            return s
        if c is A.BorrowType:
            return "borrow " + self.type_(t.inner)
        raise FormatError(f"cannot format type {c.__name__}")

    # ------------------------------------------------------------ blocks and statements
    def block_after(self, head: str, b: Optional[A.Block], ind: int) -> None:
        """`head {` ... `}` with the body at ind+1."""
        if b is None:
            self.out.line(ind, head)
            return
        self.block_lines(head + " {" if head else "{", b, ind)

    def block_lines(self, open_text: str, b: A.Block, ind: int, close_suffix: str = "") -> None:
        end = b.span.end
        if not b.stmts and not self._comments_before(end):
            self.out.line(ind, open_text + "}" + close_suffix if open_text.endswith("{") else open_text)
            return
        self.out.line(ind, open_text)
        self.prev_end_line = self.line_of(b.span.start)
        self.block_start = True
        self.stmts(b.stmts, ind + 1)
        self.leading_comments(end - 1, ind + 1)
        self.out.line(ind, "}" + close_suffix)

    def stmts(self, stmts, ind: int) -> None:
        for st in stmts:
            self.leading_comments(st.span.start, ind)
            self.gap_before(st.span.start)
            self.stmt(st, ind)
            self.trailing_comment(st.span.end)

    def stmt(self, st, ind: int) -> None:
        c = st.__class__
        if c is A.ExprStmt:
            self.expr_line(ind, "", st.expr, "")
        elif c is A.LetStmt:
            kw = "const" if st.is_const else "let"
            if st.destructure:
                target = "(" + ", ".join(n for n, _ in st.names) + ")"
            else:
                target = st.names[0][0]
            t = f": {self.type_(st.type)}" if st.type is not None else ""
            if st.value is None:
                self.out.line(ind, f"{kw} {target}{t}")
            else:
                self.expr_line(ind, f"{kw} {target}{t} = ", st.value, "")
        elif c is A.AssignStmt:
            self.expr_line(ind, f"{self.expr(st.target, ind)} {st.op} ", st.value, "")
        elif c is A.ReturnStmt:
            if st.value is None:
                self.out.line(ind, "return")
            else:
                self.expr_line(ind, "return ", st.value, "")
        elif c is A.BreakStmt:
            self.out.line(ind, "break")
        elif c is A.ContinueStmt:
            self.out.line(ind, "continue")
        elif c is A.ThrowStmt:
            self.expr_line(ind, "throw ", st.value, "")
        elif c is A.DeferStmt:
            if isinstance(st.body, A.Block):
                self.block_after("defer", st.body, ind)
            else:
                self.expr_line(ind, "defer ", st.body, "")
        elif c is A.OnAbandonStmt:
            self.expr_line(ind, "onAbandon ", st.call, "")
        elif c is A.NonlocalStmt:
            self.out.line(ind, "nonlocal " + ", ".join(st.names))
        elif c is A.AssertStmt:
            s = "assert " + self.expr(st.cond, ind)
            if st.message is not None:
                s += ", " + self.expr(st.message, ind)
            self.out.line(ind, s)
        elif c is A.WhileStmt:
            self.block_after("while " + self.expr(st.cond, ind), st.body, ind)
        elif c is A.ForStmt:
            kw = "for await " if st.is_await else "for "
            self.block_after(f"{kw}{self.pattern(st.pattern)} in {self.expr(st.iterable, ind)}", st.body, ind)
        else:  # pragma: no cover
            raise FormatError(f"cannot format statement {c.__name__}")

    # ------------------------------------------------------------ expressions (multi-line aware)
    def expr_line(self, ind: int, prefix: str, e, suffix: str) -> None:
        """Emit `prefix <e> suffix` starting a new line, laying out block-bearing
        expressions (if/match/use/parallel/...) across lines."""
        lines = self.expr_lines(e, ind)
        if len(lines) == 1:
            self.out.line(ind, prefix + lines[0] + suffix)
            return
        self.out.line(ind, prefix + lines[0])
        for ln in lines[1:-1]:
            self.out.lines.append(ln)
        self.out.lines.append(lines[-1] + suffix)

    def expr_lines(self, e, ind: int) -> list[str]:
        """Render `e` whose first line continues the current line at indent `ind`.
        Subsequent lines are returned fully indented."""
        text = self.expr(e, ind)
        return text.split("\n")

    def sub_block(self, b: A.Block, ind: int) -> str:
        """`{` + body lines at ind+1 + `}` at ind, as text (first line continues)."""
        if not b.stmts and not self._comments_before(b.span.end):
            return "{}"
        saved_out, saved_prev = self.out, self.prev_end_line
        self.out = Out()
        self.prev_end_line = self.line_of(b.span.start)
        self.block_start = True
        self.stmts(b.stmts, ind + 1)
        self.leading_comments(b.span.end - 1, ind + 1)
        body = self.out.lines
        self.out = saved_out
        self.prev_end_line = saved_prev if saved_prev is not None else self.prev_end_line
        return "{\n" + "\n".join(body) + "\n" + INDENT * ind + "}"

    def expr(self, e, ind: int) -> str:
        m = getattr(self, "e_" + e.__class__.__name__, None)
        if m is None:  # pragma: no cover
            raise FormatError(f"cannot format expression {e.__class__.__name__}")
        return m(e, ind)

    def wrap(self, e, ind: int, need: int) -> str:
        s = self.expr(e, ind)
        return f"({s})" if prec(e) < need else s

    def e_Literal(self, e, ind):
        if e.kind in ("int", "float"):
            return e.span.text
        if e.kind == "bool":
            return "true" if e.value else "false"
        if e.kind == "null":
            return "null"
        if e.kind == "unit":
            return "()"
        return e.span.text

    def e_StringLit(self, e, ind):
        return e.span.text

    def e_Name(self, e, ind):
        return e.name

    def _seq(self, opener: str, items: list[str], closer: str, ind: int) -> str:
        flat = opener + ", ".join(items) + closer
        if len(INDENT * ind) + len(flat) <= WIDTH or len(items) < 2 or any("\n" in i for i in items):
            return flat
        inner = INDENT * (ind + 1)
        return opener + "\n" + "".join(inner + i + ",\n" for i in items) + INDENT * ind + closer

    def e_ListLit(self, e, ind):
        return self._seq("[", [self.expr(i, ind + 1) for i in e.items], "]", ind)

    def e_MapLit(self, e, ind):
        if not e.entries:
            return "{}"
        return self._seq("{", [f"{self.expr(k, ind + 1)}: {self.expr(v, ind + 1)}" for k, v in e.entries], "}", ind)

    def e_TupleLit(self, e, ind):
        return "(" + ", ".join(self.expr(i, ind) for i in e.items) + ")"

    def e_Unary(self, e, ind):
        inner = self.wrap(e.operand, ind, P_UNARY)
        if e.op == "-" and inner.startswith("-"):
            inner = f"({inner})"
        return e.op + inner

    def e_Binary(self, e, ind):
        p = PREC[e.op]
        lneed = p + 1 if e.op in NONASSOC else p
        rneed = p + 1
        left = self.wrap(e.left, ind, lneed)
        right = self.wrap(e.right, ind, rneed)
        if isinstance(e.left, (A.Await, A.Propagate)):
            left = f"({left})"
        if isinstance(e.right, (A.Await, A.Propagate)):
            right = f"({right})"
        return f"{left} {e.op} {right}"

    def e_Range(self, e, ind):
        op = "..=" if e.inclusive else ".."
        return f"{self.wrap(e.lo, ind, P_RANGE + 1)}{op}{self.wrap(e.hi, ind, P_RANGE + 1)}"

    def e_Call(self, e, ind):
        callee = self.wrap(e.callee, ind, P_POSTFIX)
        args = [(f"{a.name}: " if a.name else "") + self.expr(a.value, ind + 1) for a in e.args]
        return callee + self._seq("(", args, ")", ind)

    def e_Index(self, e, ind):
        return self.wrap(e.obj, ind, P_POSTFIX) + "[" + ", ".join(self.expr(i, ind) for i in e.indices) + "]"

    def e_Field(self, e, ind):
        return self.wrap(e.obj, ind, P_POSTFIX) + "." + e.name

    def e_WithUpdate(self, e, ind):
        fields = ", ".join(f"{n}: {self.expr(v, ind)}" for n, v, _ in e.fields)
        return self.wrap(e.obj, ind, P_POSTFIX) + " with { " + fields + " }"

    def e_Lambda(self, e, ind):
        s = ("async " if e.is_async else "") + "fn(" + self.params(e.params) + ")"
        if e.ret is not None:
            s += " -> " + self.type_(e.ret)
        if e.throws is not None:
            s += " throws " + " | ".join(self.type_(t) for t in e.throws)
        if e.is_block:
            return s + " " + self.sub_block(e.body, ind)
        return s + " => " + self.expr(e.body, ind)

    def e_If(self, e, ind):
        if e.ann.get("block_expr"):
            return self.sub_block(e.then, ind)
        s = "if " + self.expr(e.cond, ind) + " " + self.sub_block(e.then, ind)
        if e.else_ is not None:
            if isinstance(e.else_, A.If):
                s += " else " + self.e_If(e.else_, ind)
            else:
                s += " else " + self.sub_block(e.else_, ind)
        return s

    def arm_body(self, body, ind) -> str:
        if isinstance(body, A.Block):
            return self.sub_block(body, ind)
        return self.expr(body, ind)

    def e_Match(self, e, ind):
        lines = ["match " + self.expr(e.scrutinee, ind) + " {"]
        saved_out = self.out
        for arm in e.arms:
            self.out = Out()
            self.leading_comments(arm.span.start, ind + 1)
            pre = self.out.lines
            self.out = saved_out
            lines.extend(pre)
            g = f" if {self.expr(arm.guard, ind + 1)}" if arm.guard is not None else ""
            lines.append(INDENT * (ind + 1) + f"{self.pattern(arm.pattern)}{g} => {self.arm_body(arm.body, ind + 1)}")
        lines.append(INDENT * ind + "}")
        return "\n".join(lines)

    def e_Is(self, e, ind):
        return f"{self.wrap(e.expr, ind, P_IS + 1)} is {self.pattern(e.pattern)}"

    def e_As(self, e, ind):
        return f"{self.wrap(e.expr, ind, P_IS + 1)} as {self.type_(e.type)}"

    def e_Try(self, e, ind):
        inner = self.expr(e.expr, ind)
        if isinstance(e.expr, A.Try) and (e.expr.catches or e.expr.fallback is not None):
            inner = f"({inner})"
        parts = []
        for cl in e.catches:
            s = "catch " + ("category " if cl.is_category else "") + ".".join(cl.path)
            if cl.binding:
                s += " as " + cl.binding
            parts.append((s + " => ", cl.handler))
        if e.fallback is not None:
            parts.append(("else ", e.fallback))
        if not parts:
            return "try " + inner
        flat_parts = [p + (self.arm_body(h, ind) if isinstance(h, A.Block) else self.expr(h, ind)) for p, h in parts]
        flat = "try " + inner + " " + " ".join(flat_parts)
        if "\n" not in flat and len(INDENT * ind) + len(flat) <= WIDTH:
            return flat
        out = "try " + inner
        for p, h in parts:
            out += "\n" + INDENT * (ind + 1) + p + self.arm_body(h, ind + 1)
        return out

    def e_Capture(self, e, ind):
        return "capture " + self.expr(e.expr, ind)

    def e_Propagate(self, e, ind):
        return "propagate " + self.wrap(e.expr, ind, P_UNARY)

    def e_Await(self, e, ind):
        return "await " + self.wrap(e.expr, ind, P_UNARY)

    def e_Yield(self, e, ind):
        return "yield " + self.expr(e.value, ind)

    def e_Use(self, e, ind):
        return f"use {e.name} = {self.expr(e.init, ind)} " + self.sub_block(e.body, ind)

    def e_Parallel(self, e, ind):
        mode = "" if e.mode == "failfast" else e.mode + " "
        return f"parallel {mode}" + self.sub_block(e.body, ind)

    def e_Spawn(self, e, ind):
        if e.call is not None:
            return "spawn " + self.expr(e.call, ind)
        return "spawn " + self.sub_block(e.block, ind)

    def e_Within(self, e, ind):
        return f"within {self.expr(e.deadline, ind)} " + self.sub_block(e.body, ind)

    def e_Select(self, e, ind):
        mode = "" if e.mode == "normal" else e.mode + " "
        lines = [f"select {mode}{{"]
        saved_out = self.out
        for b in e.branches:
            self.out = Out()
            self.leading_comments(b.span.start, ind + 1)
            lines.extend(self.out.lines)
            self.out = saved_out
            g = f"when {b.guard}: " if b.guard else ""
            k = b.kind
            if k == "receive":
                head = f"receive {b.binding or '_'} from {self.expr(b.target, ind + 1)}"
            elif k == "closed":
                head = f"closed {self.expr(b.target, ind + 1)}"
            elif k == "send":
                head = f"send {self.expr(b.value, ind + 1)} to {self.expr(b.target, ind + 1)}"
            elif k == "task":
                head = f"task {self.expr(b.target, ind + 1)} completed as {b.binding}"
            elif k == "at":
                head = f"at {self.expr(b.target, ind + 1)}"
            elif k == "after":
                head = f"after {self.expr(b.target, ind + 1)}"
            else:
                head = "none ready"
            lines.append(INDENT * (ind + 1) + f"{g}{head} => {self.arm_body(b.body, ind + 1)}")
        lines.append(INDENT * ind + "}")
        return "\n".join(lines)

    # ------------------------------------------------------------ patterns
    def pattern(self, p) -> str:
        c = p.__class__
        if c is A.WildcardPat:
            return "_"
        if c is A.BindPat:
            return p.name + (f": {self.type_(p.type)}" if p.type is not None else "")
        if c is A.LiteralPat:
            return p.span.text
        if c is A.CasePat:
            s = ".".join(p.path)
            if p.args is not None:
                s += "(" + ", ".join((f"{n}: " if n else "") + self.pattern(sp) for n, sp in p.args) + ")"
            return s
        if c is A.TuplePat:
            return "(" + ", ".join(self.pattern(i) for i in p.items) + ")"
        if c is A.OrPat:
            return " | ".join(self.pattern(a) for a in p.alts)
        raise FormatError(f"cannot format pattern {c.__name__}")
