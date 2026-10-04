"""AST node definitions.

Every node carries a source span and a unique integer id. Later passes attach
analysis results in side tables keyed by node id (resolver/checker) or in the
`ann` dict (transient runtime-check annotations, IMPL-004).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from ..source import Span

_ids = itertools.count(1)


@dataclass(eq=False)
class Node:
    span: Span
    id: int = field(default_factory=lambda: next(_ids), init=False, repr=False)
    ann: dict = field(default_factory=dict, init=False, repr=False)


# ------------------------------------------------------------------ types
@dataclass(eq=False)
class TypeExpr(Node):
    pass


@dataclass(eq=False)
class TypeName(TypeExpr):
    path: list[str]
    args: list[TypeExpr] = field(default_factory=list)

    @property
    def name(self) -> str:
        return ".".join(self.path)


@dataclass(eq=False)
class OptionalType(TypeExpr):
    inner: TypeExpr


@dataclass(eq=False)
class TupleType(TypeExpr):
    items: list[TypeExpr]


@dataclass(eq=False)
class FnType(TypeExpr):
    params: list[TypeExpr]
    ret: Optional[TypeExpr]
    throws: Optional[list[TypeExpr]]
    is_async: bool = False


@dataclass(eq=False)
class BorrowType(TypeExpr):
    inner: TypeExpr


# ------------------------------------------------------------------ patterns
@dataclass(eq=False)
class Pattern(Node):
    pass


@dataclass(eq=False)
class WildcardPat(Pattern):
    pass


@dataclass(eq=False)
class BindPat(Pattern):
    name: str
    type: Optional[TypeExpr] = None


@dataclass(eq=False)
class LiteralPat(Pattern):
    value: Any  # int, float, str, bool, None(for null), or "unit"
    kind: str  # int float str bool null


@dataclass(eq=False)
class CasePat(Pattern):
    path: list[str]  # e.g. ["Shape", "Circle"] or ["Some"]
    args: Optional[list[tuple[Optional[str], Pattern]]] = None  # None => no parens

    @property
    def name(self) -> str:
        return ".".join(self.path)


@dataclass(eq=False)
class TuplePat(Pattern):
    items: list[Pattern]


@dataclass(eq=False)
class OrPat(Pattern):
    alts: list[Pattern]


# ------------------------------------------------------------------ expressions
@dataclass(eq=False)
class Expr(Node):
    pass


@dataclass(eq=False)
class Literal(Expr):
    value: Any
    kind: str  # int float bool null unit


@dataclass(eq=False)
class InterpPart:
    expr: "Expr"
    spec: Optional[str]
    span: Span


@dataclass(eq=False)
class StringLit(Expr):
    parts: list[Union[str, InterpPart]]
    triple: bool = False


@dataclass(eq=False)
class Name(Expr):
    name: str


@dataclass(eq=False)
class ListLit(Expr):
    items: list[Expr]


@dataclass(eq=False)
class MapLit(Expr):
    entries: list[tuple[Expr, Expr]]


@dataclass(eq=False)
class TupleLit(Expr):
    items: list[Expr]


@dataclass(eq=False)
class Unary(Expr):
    op: str
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Range(Expr):
    lo: Expr
    hi: Expr
    inclusive: bool


@dataclass(eq=False)
class Arg:
    name: Optional[str]
    value: Expr
    span: Span


@dataclass(eq=False)
class Call(Expr):
    callee: Expr
    args: list[Arg]


@dataclass(eq=False)
class Index(Expr):
    obj: Expr
    indices: list[Expr]


@dataclass(eq=False)
class Field(Expr):
    obj: Expr
    name: str
    name_span: Optional[Span] = None


@dataclass(eq=False)
class WithUpdate(Expr):
    obj: Expr
    fields: list[tuple[str, Expr, Span]]


@dataclass(eq=False)
class Param(Node):
    name: str
    type: Optional[TypeExpr] = None
    default: Optional[Expr] = None
    borrow: bool = False
    is_self: bool = False


@dataclass(eq=False)
class Lambda(Expr):
    params: list[Param]
    ret: Optional[TypeExpr]
    throws: Optional[list[TypeExpr]]
    body: Union[Expr, "Block"]
    is_async: bool = False
    is_block: bool = False


@dataclass(eq=False)
class If(Expr):
    cond: Expr
    then: "Block"
    else_: Optional[Union["Block", "If"]] = None


@dataclass(eq=False)
class MatchArm(Node):
    pattern: Pattern
    guard: Optional[Expr]
    body: Union[Expr, "Block"]


@dataclass(eq=False)
class Match(Expr):
    scrutinee: Expr
    arms: list[MatchArm]


@dataclass(eq=False)
class Is(Expr):
    expr: Expr
    pattern: Pattern


@dataclass(eq=False)
class As(Expr):
    expr: Expr
    type: TypeExpr


@dataclass(eq=False)
class CatchClause(Node):
    path: list[str]  # error type, error-enum case or category name
    is_category: bool
    binding: Optional[str]
    handler: Union[Expr, "Block"]


@dataclass(eq=False)
class Try(Expr):
    expr: Expr
    catches: list[CatchClause] = field(default_factory=list)
    fallback: Optional[Expr] = None


@dataclass(eq=False)
class Capture(Expr):
    expr: Expr


@dataclass(eq=False)
class Propagate(Expr):
    expr: Expr


@dataclass(eq=False)
class Await(Expr):
    expr: Expr


@dataclass(eq=False)
class Yield(Expr):
    value: Expr


@dataclass(eq=False)
class Use(Expr):
    name: str
    init: Expr
    body: "Block"
    name_span: Optional[Span] = None


@dataclass(eq=False)
class Parallel(Expr):
    mode: str  # failfast collect race firstSuccess
    body: "Block"


@dataclass(eq=False)
class Spawn(Expr):
    call: Optional[Expr]  # a Call expression (explicit arguments)
    block: Optional["Block"]  # closure-capturing form


@dataclass(eq=False)
class Within(Expr):
    deadline: Expr
    body: "Block"


@dataclass(eq=False)
class SelectBranch(Node):
    kind: str  # receive closed send task at after none
    guard: Optional[str]
    guard_span: Optional[Span]
    binding: Optional[str]  # receive/task binding name
    target: Optional[Expr]  # port / handle / deadline / duration
    value: Optional[Expr]  # send value
    body: Union[Expr, "Block"]


@dataclass(eq=False)
class Select(Expr):
    mode: str  # normal now priority
    branches: list[SelectBranch]


# ------------------------------------------------------------------ statements
@dataclass(eq=False)
class Stmt(Node):
    pass


@dataclass(eq=False)
class Block(Node):
    stmts: list[Stmt]
    end_span: Optional[Span] = None


@dataclass(eq=False)
class LetStmt(Stmt):
    names: list[tuple[str, Span]]  # one name, or several for tuple destructuring
    destructure: bool
    type: Optional[TypeExpr]
    value: Optional[Expr]
    is_const: bool = False


@dataclass(eq=False)
class AssignStmt(Stmt):
    target: Expr
    op: str
    value: Expr


@dataclass(eq=False)
class ReturnStmt(Stmt):
    value: Optional[Expr]


@dataclass(eq=False)
class BreakStmt(Stmt):
    pass


@dataclass(eq=False)
class ContinueStmt(Stmt):
    pass


@dataclass(eq=False)
class ThrowStmt(Stmt):
    value: Expr


@dataclass(eq=False)
class DeferStmt(Stmt):
    body: Union[Expr, Block]


@dataclass(eq=False)
class OnAbandonStmt(Stmt):
    call: Expr


@dataclass(eq=False)
class NonlocalStmt(Stmt):
    names: list[str]


@dataclass(eq=False)
class AssertStmt(Stmt):
    cond: Expr
    message: Optional[Expr]


@dataclass(eq=False)
class WhileStmt(Stmt):
    cond: Expr
    body: Block


@dataclass(eq=False)
class ForStmt(Stmt):
    pattern: Pattern
    iterable: Expr
    body: Block
    is_await: bool = False


@dataclass(eq=False)
class ExprStmt(Stmt):
    expr: Expr


# ------------------------------------------------------------------ declarations
@dataclass(eq=False)
class Decl(Node):
    name: str
    is_pub: bool = False


@dataclass(eq=False)
class FnDecl(Decl):
    type_params: list[str] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    ret: Optional[TypeExpr] = None
    yields: Optional[TypeExpr] = None
    throws: Optional[list[TypeExpr]] = None
    requires: list[Expr] = field(default_factory=list)
    ensures: list[Expr] = field(default_factory=list)
    body: Optional[Block] = None
    is_async: bool = False
    is_resource: bool = False
    owner: Optional[str] = None  # record/enum/protocol name for members
    name_span: Optional[Span] = None

    @property
    def has_self(self) -> bool:
        return bool(self.params) and self.params[0].is_self


@dataclass(eq=False)
class FieldDecl(Node):
    name: str
    type: Optional[TypeExpr]
    default: Optional[Expr] = None
    sensitive: bool = False


@dataclass(eq=False)
class RecordDecl(Decl):
    kind: str = "record"  # record | error
    mutable: bool = False
    type_params: list[str] = field(default_factory=list)
    satisfies: list[TypeExpr] = field(default_factory=list)
    fields: list[FieldDecl] = field(default_factory=list)
    invariants: list[Expr] = field(default_factory=list)
    methods: list[FnDecl] = field(default_factory=list)
    category: Optional[str] = None
    name_span: Optional[Span] = None


@dataclass(eq=False)
class CaseDecl(Node):
    name: str
    fields: Optional[list[FieldDecl]]


@dataclass(eq=False)
class EnumDecl(Decl):
    is_error: bool = False
    type_params: list[str] = field(default_factory=list)
    satisfies: list[TypeExpr] = field(default_factory=list)
    cases: list[CaseDecl] = field(default_factory=list)
    methods: list[FnDecl] = field(default_factory=list)
    category: Optional[str] = None
    name_span: Optional[Span] = None


@dataclass(eq=False)
class CategoryDecl(Decl):
    pass


@dataclass(eq=False)
class ProtocolDecl(Decl):
    type_params: list[str] = field(default_factory=list)
    methods: list[FnDecl] = field(default_factory=list)


@dataclass(eq=False)
class PredicateDecl(Decl):
    params: list[Param] = field(default_factory=list)
    body: Optional[Block] = None


@dataclass(eq=False)
class ConstDecl(Decl):
    type: Optional[TypeExpr] = None
    value: Optional[Expr] = None


@dataclass(eq=False)
class TestDecl(Decl):
    body: Optional[Block] = None


@dataclass(eq=False)
class Import(Node):
    path: list[str]
    names: Optional[list[tuple[str, Span]]] = None
    alias: Optional[str] = None


@dataclass(eq=False)
class Module(Node):
    imports: list[Import] = field(default_factory=list)
    decls: list[Decl] = field(default_factory=list)
    comments: list = field(default_factory=list)


# ------------------------------------------------------------------ utilities
def iter_children(node: Any):
    """Yield direct child nodes (used by generic walkers)."""
    if isinstance(node, list):
        for x in node:
            yield from iter_children(x)
        return
    if isinstance(node, tuple):
        for x in node:
            yield from iter_children(x)
        return
    if isinstance(node, (Node, InterpPart, Arg)):
        for k, v in vars(node).items():
            if k in ("span", "id", "ann", "name_span", "end_span", "guard_span"):
                continue
            if isinstance(v, (Node, InterpPart, Arg)):
                yield v
            elif isinstance(v, (list, tuple)):
                for x in v:
                    if isinstance(x, (Node, InterpPart, Arg)):
                        yield x
                    elif isinstance(x, tuple):
                        for y in x:
                            if isinstance(y, (Node, InterpPart, Arg)):
                                yield y


def walk(node: Any):
    """Pre-order traversal over Nodes (and InterpPart/Arg wrappers)."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        children = list(iter_children(n))
        stack.extend(reversed(children))
