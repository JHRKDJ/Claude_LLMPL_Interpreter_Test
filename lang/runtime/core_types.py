"""Core nominal types defined by the runtime (V3 6.14 "Language/runtime core").

Option, Result, ScopeExit, channel outcome enums, AggregateException,
TaskGroupReport/TaskOutcome, and the standard concrete errors/categories that
native operations throw.
"""
from __future__ import annotations

from .. import typesys as T
from ..source import synthetic_span
from .values import CaseInfo, CategoryType, EnumType, FieldInfo, FrozenRecord, RecordType, VariantValue

SPAN = synthetic_span("<core>")


def _enum(name: str, cases: list[tuple[str, list[tuple[str, T.Ty]] | None]], qual: str | None = None,
          is_error: bool = False, category: str | None = None, type_params=()) -> EnumType:
    et = EnumType(name, qual or f"core.{name}", None, is_error=is_error, category=category)
    et.type_params = list(type_params)
    for i, (cname, fields) in enumerate(cases):
        finfos = None
        if fields is not None:
            finfos = [FieldInfo(fn, ft, None, None, False, j, SPAN) for j, (fn, ft) in enumerate(fields)]
        et.cases[cname] = CaseInfo(cname, finfos, i, et, SPAN)
    return et


def _record(name: str, fields: list[tuple[str, T.Ty]], kind: str = "record", category: str | None = None,
            qual: str | None = None, mutable: bool = False) -> RecordType:
    rt = RecordType(name, qual or f"core.{name}", None, mutable, kind=kind, category=category)
    for i, (fn, ft) in enumerate(fields):
        rt.fields.append(FieldInfo(fn, ft, None, None, False, i, SPAN))
        rt.field_index[fn] = i
    return rt


TV = T.TVar
OPTION = _enum("Option", [("Some", [("value", TV("T"))]), ("None", None)], type_params=["T"])
RESULT = _enum("Result", [("Ok", [("value", TV("T"))]), ("Err", [("error", TV("E"))])], type_params=["T", "E"])
SCOPE_EXIT = _enum("ScopeExit", [("Normal", None), ("Failed", None), ("Cancelled", None)])
TRY_SEND = _enum("TrySend", [("Sent", None), ("WouldBlock", None), ("Closed", [("reason", T.STR)])])
TRY_RECEIVE = _enum("TryReceive", [("Message", [("value", TV("T"))]), ("WouldBlock", None),
                                   ("Closed", [("reason", T.STR)])], type_params=["T"])
RECEIVED = _enum("Received", [("Message", [("value", TV("T"))]), ("Closed", [("reason", T.STR)])],
                 type_params=["T"])
CANCEL_REASON = _enum("CancellationReason", [("External", None), ("GroupFailure", [("trigger", T.STR)]),
                                             ("RaceDecided", [("winner", T.STR)]),
                                             ("Deadline", None), ("Other", [("detail", T.STR)])])

# ---- categories and standard errors
CATEGORIES = {
    "IO": CategoryType("IO", "core.IO"),
    "Channels": CategoryType("Channels", "core.Channels"),
    "Time": CategoryType("Time", "core.Time"),
    "Data": CategoryType("Data", "core.Data"),
}

FILE_NOT_FOUND = _record("FileNotFound", [("path", T.STR)], "error", "IO")
PERMISSION_DENIED = _record("PermissionDenied", [("path", T.STR)], "error", "IO")
IO_FAILURE = _record("IOFailure", [("path", T.STR), ("detail", T.STR)], "error", "IO")
JSON_ERROR = _record("JsonError", [("message", T.STR), ("line", T.INT), ("column", T.INT)], "error", "Data")
CHANNEL_CLOSED = _record("ChannelClosed", [("channelId", T.INT), ("operation", T.STR), ("reason", T.STR),
                                           ("portId", T.INT)], "error", "Channels")
DEADLINE_EXCEEDED = _record("DeadlineExceeded", [("deadline", T.INSTANT)], "error", "Time")
AGGREGATE_ENTRY = _record("AggregateEntry", [("source", T.STR), ("taskPath", T.option(T.STR)), ("error", T.DYN)])
AGGREGATE_EXCEPTION = _record("AggregateException", [("entries", T.TCon("List", (T.TNominal("core.AggregateEntry", "record"),)))],
                              "error")
ABANDONMENT_REPORT = _record("AbandonmentReport", [("code", T.STR), ("message", T.STR), ("taskPath", T.STR)])
TASK_OUTCOME = _enum("TaskOutcome", [
    ("Succeeded", [("taskPath", T.STR), ("value", TV("T"))]),
    ("ThrewException", [("taskPath", T.STR), ("exception", TV("E"))]),
    ("Abandoned", [("taskPath", T.STR), ("report", T.TNominal("core.AbandonmentReport", "record"))]),
    ("Cancelled", [("taskPath", T.STR), ("reason", T.STR)]),
    ("NestedGroup", [("taskPath", T.STR), ("report", T.DYN)]),
], type_params=["T", "E"])
TASK_GROUP_REPORT = _record("TaskGroupReport", [("outcomes", T.TCon("List", (T.TNominal("core.TaskOutcome", "enum"),)))])
RECEIVE_SELECTION = _record("ReceiveSelection", [("index", T.INT), ("outcome", T.TNominal("core.Received", "enum"))])
TASK_SELECTION = _record("TaskSelection", [("index", T.INT), ("result", T.TCon("Result", (T.DYN, T.DYN)))])

CORE_ENUMS = {e.name: e for e in (OPTION, RESULT, SCOPE_EXIT, TRY_SEND, TRY_RECEIVE, RECEIVED, CANCEL_REASON,
                                  TASK_OUTCOME)}
CORE_RECORDS = {r.name: r for r in (FILE_NOT_FOUND, PERMISSION_DENIED, IO_FAILURE, JSON_ERROR, CHANNEL_CLOSED,
                                    DEADLINE_EXCEEDED, AGGREGATE_ENTRY, AGGREGATE_EXCEPTION, ABANDONMENT_REPORT,
                                    TASK_GROUP_REPORT, RECEIVE_SELECTION, TASK_SELECTION)}
ALL_CORE_TYPES = {**CORE_ENUMS, **CORE_RECORDS}

NONE = OPTION.nullary("None")
SOME_CASE = OPTION.cases["Some"]
OK_CASE = RESULT.cases["Ok"]
ERR_CASE = RESULT.cases["Err"]


def some(v) -> VariantValue:
    return VariantValue(SOME_CASE, (v,))


def ok(v) -> VariantValue:
    return VariantValue(OK_CASE, (v,))


def err(e, prov=None) -> VariantValue:
    return VariantValue(ERR_CASE, (e,), prov)


def is_some(v) -> bool:
    return type(v) is VariantValue and v.case is SOME_CASE


def is_none(v) -> bool:
    return v is NONE or (type(v) is VariantValue and v.case is OPTION.cases["None"])


def opt(v_or_none, present: bool) -> VariantValue:
    return some(v_or_none) if present else NONE


def make_error(rtype: RecordType, **fields) -> FrozenRecord:
    vals = tuple(fields[f.name] for f in rtype.fields)
    return FrozenRecord(rtype, vals)
