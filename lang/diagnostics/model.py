"""Structured diagnostic model (V3 6.12, 7.13).

Diagnostics are data. Human-readable and JSON output are *rendered from* these
objects (render_text.py / render_json.py); producers never build display strings
for structure that the model can carry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..source import Span

OUTCOME_NAMES = {
    "A": "abandonment",
    "R": "recoverable",
    "S": "static",
    "W": "warning",
    "C": "cancellation",
    "H": "hard_termination",
    "I": "info",
}


@dataclass(frozen=True)
class Code:
    """Hierarchical stable code: outcome class, domain, leaf reason (V3 7.13.2)."""

    outcome: str  # one of OUTCOME_NAMES
    domain: str  # e.g. TYPE
    reason: str  # e.g. DYNAMIC_MISMATCH

    @property
    def stable_code(self) -> str:
        return f"{self.outcome}.{self.domain}.{self.reason}"

    def to_json(self) -> dict:
        return {
            "outcome": OUTCOME_NAMES[self.outcome],
            "domain": self.domain.lower(),
            "reason": self.reason.lower(),
            "stable_code": self.stable_code,
        }

    def __str__(self) -> str:
        return self.stable_code


@dataclass
class Label:
    span: Span
    message: str = ""


@dataclass
class Note:
    message: str
    span: Optional[Span] = None


@dataclass
class TextEdit:
    span: Span
    replacement: str

    def to_json(self) -> dict:
        return {"span": self.span.to_json(), "replacement": self.replacement}


@dataclass
class Fix:
    """A suggested *visible* source edit (V3 7.13.7: fixes are patches)."""

    description: str
    edits: list[TextEdit] = field(default_factory=list)


@dataclass
class Frame:
    function: str
    span: Optional[Span]
    locals: dict[str, str] = field(default_factory=dict)
    locals_truncated: bool = False


@dataclass
class TaskProvenance:
    path: str
    group_site: Optional[Span] = None
    group_mode: Optional[str] = None
    seed: Optional[int] = None


@dataclass
class ResourceProvenance:
    resource: str
    acquired_at: Optional[Span] = None
    scope: Optional[Span] = None
    release_phase: Optional[str] = None  # normal | abandonment
    exit_class: Optional[str] = None


@dataclass
class ChannelProvenance:
    channel_id: int
    operation: str
    created_at: Optional[Span] = None
    port_id: Optional[int] = None
    reason: Optional[str] = None
    message_type: Optional[str] = None
    sequence: Optional[int] = None
    events: list[dict] = field(default_factory=list)


@dataclass
class Diagnostic:
    code: Code
    message: str
    severity: str = "error"  # error | warning | info
    primary: Optional[Label] = None
    secondary: list[Label] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    help: list[str] = field(default_factory=list)
    expected: Optional[str] = None
    found: Optional[str] = None
    fixes: list[Fix] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)
    propagation: list[Span] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    task: Optional[TaskProvenance] = None
    resource: Optional[ResourceProvenance] = None
    channel: Optional[ChannelProvenance] = None
    select_events: list[dict] = field(default_factory=list)
    causes: list["Diagnostic"] = field(default_factory=list)
    children: list["Diagnostic"] = field(default_factory=list)
    likely_cascade: bool = False
    blocking: bool = True
    truncated: bool = False
    redacted: bool = False

    def is_redacted(self) -> bool:
        """True if any rendered part carries a redaction (the producer's flag, or a
        `<redacted>` placeholder in the message, values, notes or captured locals)."""
        if self.redacted:
            return True
        texts = [self.message] + [str(v) for v in self.values.values()] + [n.message for n in self.notes]
        for fr in self.frames:
            texts.extend(str(v) for v in getattr(fr, "locals", {}).values())
        return any("<redacted>" in t for t in texts if t)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def stable_code(self) -> str:
        return self.code.stable_code

    @property
    def span(self) -> Optional[Span]:
        return self.primary.span if self.primary else None

    def with_note(self, msg: str, span: Optional[Span] = None) -> "Diagnostic":
        self.notes.append(Note(msg, span))
        return self

    def __repr__(self) -> str:
        where = self.primary.span.describe() if self.primary else "?"
        return f"<Diagnostic {self.stable_code} at {where}: {self.message}>"


class DiagnosticBag:
    """Ordered collection of diagnostics produced by a pass."""

    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def add(self, d: Diagnostic) -> Diagnostic:
        self.items.append(d)
        return d

    def extend(self, ds) -> None:
        for d in ds:
            self.add(d)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "error"]

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.items)

    def codes(self) -> list[str]:
        return [d.stable_code for d in self.items]

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
