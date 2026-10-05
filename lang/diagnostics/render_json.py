"""Machine-readable (JSON) rendering of structured diagnostics.

The JSON form preserves every structured field so that an agent never needs to
parse human text (V3 7.13.2/7.13.3). Codes are exposed as outcome/domain/reason
plus the stable display code.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from .model import Diagnostic


def _span(s):
    return s.to_json() if s is not None else None


def to_dict(d: Diagnostic) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": d.code.to_json(),
        "severity": d.severity,
        "blocking": d.blocking,
        "message": d.message,
        "primary": ({"span": _span(d.primary.span), "label": d.primary.message} if d.primary else None),
        "secondary": [{"span": _span(l.span), "label": l.message} for l in d.secondary],
        "notes": [{"message": n.message, "span": _span(n.span)} for n in d.notes],
        "help": list(d.help),
        "expected": d.expected,
        "found": d.found,
        "values": dict(d.values),
        "fixes": [{"description": f.description, "edits": [e.to_json() for e in f.edits]} for f in d.fixes],
        "propagation": [_span(s) for s in d.propagation],
        "frames": [
            {"function": fr.function, "span": _span(fr.span), "locals": dict(fr.locals),
             "locals_truncated": fr.locals_truncated}
            for fr in d.frames
        ],
        "task": None,
        "resource": None,
        "channel": None,
        "select_events": list(d.select_events),
        "causes": [to_dict(c) for c in d.causes],
        "children": [to_dict(c) for c in d.children],
        "likely_cascade": d.likely_cascade,
        "truncated": d.truncated,
        "redacted": d.is_redacted(),
        "extra": d.extra,
    }
    if d.task is not None:
        out["task"] = {"path": d.task.path, "group_site": _span(d.task.group_site),
                       "group_mode": d.task.group_mode, "seed": d.task.seed}
    if d.resource is not None:
        r = d.resource
        out["resource"] = {"resource": r.resource, "acquired_at": _span(r.acquired_at),
                           "scope": _span(r.scope), "release_phase": r.release_phase,
                           "exit_class": r.exit_class}
    if d.channel is not None:
        c = d.channel
        out["channel"] = {"channel_id": c.channel_id, "operation": c.operation,
                          "created_at": _span(c.created_at), "port_id": c.port_id,
                          "reason": c.reason, "message_type": c.message_type,
                          "sequence": c.sequence, "events": list(c.events)}
    return out


def render_json(diags: Iterable[Diagnostic], **extra: Any) -> str:
    payload = {"diagnostics": [to_dict(d) for d in diags]}
    payload.update(extra)
    return json.dumps(payload, indent=2, default=str)
