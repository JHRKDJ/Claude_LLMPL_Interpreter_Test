"""The exit taxonomy (V3 5.6, 7.2.3) as distinct internal signals.

Language control transfers derive from `Signal(BaseException)` so that no generic
`except Exception` in interpreter code can swallow them. The four failure classes —
`Thrown` (recoverable), `Cancelled`, `Abandoned`, `HardTermination` — do not share a
catchable base: language `catch` only ever handles `Thrown`.

`Fault` is an ordinary Python exception used *inside* runtime helpers to report an
abandonment condition without knowing the source span; the evaluator converts it
into `Abandoned` at the span of the operation that faulted.
"""
from __future__ import annotations

from typing import Any, Optional


class Fault(Exception):
    def __init__(self, stable: str, message: str, help: Optional[str] = None, notes: Optional[list] = None,
                 expected: Optional[str] = None, found: Optional[str] = None, secondary: Optional[list] = None,
                 values: Optional[dict] = None, extra: Optional[dict] = None):
        super().__init__(message)
        self.stable = stable
        self.message = message
        self.help = help
        self.notes = notes or []
        self.expected = expected
        self.found = found
        self.secondary = secondary or []
        self.values = values or {}
        self.extra = extra or {}


class Signal(BaseException):
    """Base for language-level control transfer. Never caught generically."""


class ReturnSignal(Signal):
    __slots__ = ("value", "span")

    def __init__(self, value, span=None):
        self.value = value
        self.span = span


class BreakSignal(Signal):
    pass


class ContinueSignal(Signal):
    pass


class ErrorProvenance:
    """Lightweight provenance carried by recoverable errors and Err values (V3 7.7.8)."""

    __slots__ = ("created_at", "chain", "task_path", "context", "unmarked", "parts", "cancel_pending")

    def __init__(self, created_at, task_path: Optional[str]):
        self.created_at = created_at  # Span
        self.chain: list = []  # propagation sites (Span), in order
        self.task_path = task_path
        self.context: list[tuple[str, str]] = []  # bounded explicit context
        self.unmarked: list = []  # propagation sites lacking a `try` marker (draft)
        # For AggregateException: (source, task_path, error, prov) per entry, in order.
        self.parts: list = []
        self.cancel_pending = False

    def copy(self) -> "ErrorProvenance":
        p = ErrorProvenance(self.created_at, self.task_path)
        p.chain = list(self.chain)
        p.context = list(self.context)
        p.unmarked = list(self.unmarked)
        p.parts = list(self.parts)
        p.cancel_pending = self.cancel_pending
        return p


class ChildOrigin:
    """Marks a recoverable error that came out of a child task via await."""

    __slots__ = ("task", "observed")

    def __init__(self, task):
        self.task = task
        self.observed = False


class Thrown(Signal):
    """A recoverable exception in flight. `error` is the language error value."""

    def __init__(self, error: Any, prov: ErrorProvenance, origin: Optional[ChildOrigin] = None):
        self.error = error
        self.prov = prov
        self.origin = origin


class Cancelled(Signal):
    """Cooperative cancellation unwinding. Boundaries consult scope flags to decide
    whether the cancellation is theirs to resolve."""

    def __init__(self, reason: str = "cancelled", span=None):
        self.reason = reason
        self.span = span
        self.cleanup_failures: list = []


class Abandoned(Signal):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic


class HardTermination(Signal):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
