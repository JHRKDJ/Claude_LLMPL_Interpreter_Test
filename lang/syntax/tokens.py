"""Token definitions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..source import Span

# interpolation format spec: `[<|>|^][0]width[.precision]` (SPEC-009, SPEC-010)
FORMAT_SPEC = re.compile(r"^([<>^])?(0)?(\d+)?(?:\.(\d+))?$")

HARD_KEYWORDS = frozenset("""
fn async await let const return if else while for in break continue match mutable
throws throw try catch capture propagate as is use yield borrow defer parallel spawn
select within import pub assert true false null nonlocal self
""".split())

# Contextual keywords are lexed as IDENT; the parser recognises them by value.
CONTEXTUAL_KEYWORDS = frozenset("""
record enum error category protocol predicate test resource requires ensures invariant
sensitive satisfies yields collect race firstSuccess now priority receive send from to
task completed at after when closed none ready onAbandon old result
""".split())

# Longest first.
OPERATORS = [
    "..=", "...", "==", "!=", "<=", ">=", "&&", "||", "->", "=>", "+=", "-=", "*=", "/=",
    "%=", "..", "::",
    "+", "-", "*", "/", "%", "<", ">", "=", "!", ".", ",", ":", ";", "(", ")", "[", "]",
    "{", "}", "?", "|", "&", "@", "#",
]

BINARY_OPERATORS = frozenset(["||", "&&", "==", "!=", "<", "<=", ">", ">=", "+", "-", "*",
                              "/", "%", "..", "..="])


@dataclass
class StringPart:
    """A piece of a string literal: literal text, or an interpolated expression."""

    text: str | None = None  # literal text (escapes processed)
    tokens: list["Token"] | None = None  # interpolation tokens (ends with EOF)
    spec: str | None = None  # format spec after ':'
    span: Span | None = None


@dataclass
class Token:
    kind: str  # IDENT, INT, FLOAT, STRING, NEWLINE, EOF, a keyword, or an operator
    value: Any
    span: Span
    parts: list[StringPart] = field(default_factory=list)  # for STRING
    triple: bool = False

    def is_(self, kind: str, value: Any = None) -> bool:
        if self.kind != kind:
            return False
        return value is None or self.value == value

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r})"


@dataclass
class Comment:
    span: Span
    text: str
    own_line: bool  # comment is the first non-blank thing on its line
