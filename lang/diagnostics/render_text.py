"""Human-readable rendering of structured diagnostics.

Rendering is a pure function of the Diagnostic object. Modes:
  default — full primary/secondary spans, notes, provenance, frames (bounded)
  quiet   — header line + primary location only
  deep    — like default plus select/channel event history and all frames

Rendering is bounded (V3 7.13.5): outside deep mode at most MAX_CHILDREN child
reports are shown per diagnostic, and a RenderBudget (default about thirty seconds)
stops rendering with an explicit truncation note. JSON output is never truncated.
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

from ..source import Span
from .model import Diagnostic, Label

MAX_CHILDREN = 20
DEFAULT_RENDER_BUDGET_S = 30.0


class RenderBudget:
    """Wall-clock budget shared by every diagnostic rendered for one report."""

    def __init__(self, seconds: float = DEFAULT_RENDER_BUDGET_S):
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds
        self.exhausted = False

    def over(self) -> bool:
        if not self.exhausted and time.monotonic() > self.deadline:
            self.exhausted = True
        return self.exhausted

    def note(self) -> str:
        return (f"note: the {self.seconds:g}s rendering budget was exhausted; the report is truncated "
                f"(use --json for the complete structured report)")


HEADER_WORD = {
    "A": "abandonment",
    "R": "error",
    "C": "cancelled",
    "H": "hard termination",
    "I": "info",
}


def header_word(d: Diagnostic) -> str:
    if d.code.outcome in ("S", "W"):
        return d.severity if d.severity != "info" else "info"
    return HEADER_WORD.get(d.code.outcome, d.severity)


def _snippet(span: Span, label: str, gutter: int) -> list[str]:
    sl, sc = span.start_line_col
    el, ec = span.end_line_col
    line_text = span.file.line_text(sl)
    if el == sl:
        width = max(1, ec - sc)
    else:
        width = max(1, len(line_text) - sc + 1)
    pad = " " * gutter
    caret_line = " " * (sc - 1) + "^" * width
    if label:
        caret_line += " " + label
    out = [f"{pad} |", f"{str(sl).rjust(gutter)} | {line_text}", f"{pad} | {caret_line}"]
    if el > sl:
        out.append(f"{pad} | ... (span continues to line {el})")
    return out


def _gutter(spans: Iterable[Span]) -> int:
    width = 1
    for s in spans:
        if s is not None and s.file.text:
            width = max(width, len(str(s.start_line_col[0])))
    return width


def render(d: Diagnostic, mode: str = "default", indent: str = "", max_frames: int = 8,
           budget: Optional[RenderBudget] = None) -> str:
    lines: list[str] = []
    word = header_word(d)
    cascade = " (likely cascade of an earlier error)" if d.likely_cascade else ""
    lines.append(f"{word}[{d.stable_code}]: {d.message}{cascade}")
    spans = [d.primary.span] if d.primary else []
    spans += [l.span for l in d.secondary]
    gutter = _gutter(spans)
    if d.primary is not None:
        lines.append(f"{' ' * gutter}--> {d.primary.span.describe()}")
        if mode != "quiet" and d.primary.span.file.text:
            lines += _snippet(d.primary.span, d.primary.message, gutter)
    if mode == "quiet":
        # human view: nested failures flattened to their leaves (V3 7.13.6)
        for leaf in leaves(d):
            where = f" ({leaf.task.path})" if leaf.task is not None else ""
            lines.append(f"  - {leaf.stable_code}{where}: {leaf.message}")
        return "\n".join(indent + l for l in lines)
    for lab in d.secondary:
        msg = lab.message or "related"
        lines.append(f"{' ' * gutter} = {msg}:")
        lines.append(f"{' ' * gutter}--> {lab.span.describe()}")
        if lab.span.file.text:
            lines += _snippet(lab.span, "", gutter)
    if d.expected is not None:
        lines.append(f"{' ' * gutter} = expected: {d.expected}")
    if d.found is not None:
        lines.append(f"{' ' * gutter} = found: {d.found}")
    for name, val in d.values.items():
        lines.append(f"{' ' * gutter} = value {name} = {val}")
    for note in d.notes:
        loc = f" ({note.span.describe()})" if note.span else ""
        lines.append(f"{' ' * gutter} = note: {note.message}{loc}")
    for h in d.help:
        lines.append(f"{' ' * gutter} = help: {h}")
    for fix in d.fixes:
        lines.append(f"{' ' * gutter} = suggested edit: {fix.description}")
        for e in fix.edits:
            lines.append(f"{' ' * gutter}     at {e.span.describe()}: insert/replace with {e.replacement!r}")
    if d.propagation:
        lines.append(f"{' ' * gutter} = propagated through:")
        for s in d.propagation:
            lines.append(f"{' ' * gutter}     {s.describe()}")
    if d.task is not None:
        t = d.task
        extra = f" (group {t.group_mode} at {t.group_site.describe()})" if t.group_site else ""
        lines.append(f"{' ' * gutter} = task: {t.path}{extra}")
        if t.seed is not None:
            lines.append(f"{' ' * gutter} = schedule seed: {t.seed}")
    if d.resource is not None:
        r = d.resource
        bits = [f"resource {r.resource}"]
        if r.acquired_at:
            bits.append(f"acquired at {r.acquired_at.describe()}")
        if r.scope:
            bits.append(f"scope at {r.scope.describe()}")
        if r.release_phase:
            bits.append(f"{r.release_phase} release")
        if r.exit_class:
            bits.append(f"exit {r.exit_class}")
        lines.append(f"{' ' * gutter} = " + ", ".join(bits))
    if d.channel is not None:
        c = d.channel
        bits = [f"channel #{c.channel_id}", f"operation {c.operation}"]
        if c.port_id is not None:
            bits.append(f"port #{c.port_id}")
        if c.reason:
            bits.append(f"reason {c.reason}")
        if c.message_type:
            bits.append(f"message type {c.message_type}")
        if c.created_at:
            bits.append(f"created at {c.created_at.describe()}")
        lines.append(f"{' ' * gutter} = " + ", ".join(bits))
        if mode == "deep":
            for ev in c.events:
                lines.append(f"{' ' * gutter}     event {ev}")
    if mode == "deep" and d.extra.get("schedule_decisions"):
        dec = d.extra["schedule_decisions"]
        lines.append(f"{' ' * gutter} = recent seeded scheduling decisions ({len(dec)}):")
        for x in dec:
            lines.append(f"{' ' * gutter}     #{x['switch']}: ran {x['ran']} (picked {x['pick']} of {x['ready']} ready)")
    if d.select_events and mode in ("default", "deep"):
        shown = d.select_events if mode == "deep" else d.select_events[-3:]
        lines.append(f"{' ' * gutter} = recent select events ({len(d.select_events)} recorded):")
        for ev in shown:
            lines.append(f"{' ' * gutter}     {ev}")
    if d.frames:
        frames = d.frames if mode == "deep" else d.frames[:max_frames]
        lines.append(f"{' ' * gutter} = stack (innermost first):")
        for fr in frames:
            where = fr.span.describe() if fr.span else "?"
            lines.append(f"{' ' * gutter}     {fr.function} at {where}")
            for k, v in fr.locals.items():
                lines.append(f"{' ' * gutter}         {k} = {v}")
            if fr.locals_truncated:
                lines.append(f"{' ' * gutter}         ... (locals truncated)")
        if len(d.frames) > len(frames):
            lines.append(f"{' ' * gutter}     ... {len(d.frames) - len(frames)} more frames (use --deep)")
    if d.truncated:
        lines.append(f"{' ' * gutter} = note: diagnostic output was truncated to the render budget")
    if d.redacted:
        lines.append(f"{' ' * gutter} = note: some values were redacted as sensitive")
    out = [indent + l for l in lines]
    for c in d.causes:
        out.append(indent + "  caused by:")
        out.append(render(c, mode, indent + "    ", max_frames, budget))
    if d.children:
        out.append(indent + f"  contains {len(d.children)} child report(s):")
        cancelled = [c for c in d.children if c.stable_code == "C.TASK.CANCELLED" and not c.children]
        shown = 0
        for i, c in enumerate(d.children):
            if c in cancelled and mode != "deep" and len(cancelled) > 1:
                continue
            if budget is not None and budget.over():
                out.append(indent + "    " + budget.note())
                break
            if mode != "deep" and shown >= MAX_CHILDREN:
                rest = sum(1 for x in d.children[i:] if not (x in cancelled and len(cancelled) > 1))
                out.append(indent + f"    ... {rest} more child report(s) (use --deep or --json)")
                break
            out.append(render(c, mode, indent + "    ", max_frames, budget))
            shown += 1
        if mode != "deep" and len(cancelled) > 1:
            # repetitive cancellations are summarised in the human view (V3 7.13.6)
            paths = [c.task.path for c in cancelled if c.task is not None]
            out.append(indent + f"    {len(cancelled)} sibling task(s) cancelled: " + ", ".join(paths[:6])
                       + (f", ... (+{len(paths) - 6}, use --deep)" if len(paths) > 6 else ""))
    return "\n".join(out)


def leaves(d: Diagnostic) -> list[Diagnostic]:
    """Leaf failures of a nested diagnostic, in canonical (task-path) order; cancelled
    siblings are not failures and are omitted from the flattened view."""
    out: list[Diagnostic] = []
    for c in list(d.causes) + list(d.children):
        if c.children or c.causes:
            out.extend(leaves(c))
        elif c.stable_code != "C.TASK.CANCELLED":
            out.append(c)
    return out


def render_all(diags: Iterable[Diagnostic], mode: str = "default", budget: Optional[RenderBudget] = None) -> str:
    budget = budget or RenderBudget()
    parts = []
    diags = list(diags)
    for i, d in enumerate(diags):
        if budget.over():
            parts.append(budget.note() + f"; {len(diags) - i} diagnostic(s) not shown")
            break
        parts.append(render(d, mode, budget=budget))
    return "\n\n".join(parts)


def summary_line(diags: list[Diagnostic]) -> str:
    errors = sum(1 for d in diags if d.severity == "error")
    warnings = sum(1 for d in diags if d.severity == "warning")
    return f"{errors} error(s), {warnings} warning(s)"
