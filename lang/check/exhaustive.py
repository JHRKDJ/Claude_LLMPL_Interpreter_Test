"""Match exhaustiveness and redundancy (V3 3.3, 5.15.5; usefulness algorithm).

Closed types: Bool, Option, Result, user/core enums, tuples and records (single
constructor). Every other type (Int, Str, Float, Dyn, protocols...) is open: only a
wildcard or untyped binding covers it. Guarded arms never count towards coverage.
"""
from __future__ import annotations

from typing import Optional

from .. import typesys as T
from ..syntax import ast as A

WILD = "_"
CORE = {"Some", "None", "Ok", "Err"}


class Ctor:
    __slots__ = ("name", "args", "label")

    def __init__(self, name, args, label):
        self.name = name
        self.args = args  # list[Ty]
        self.label = label


def constructors(chk, t) -> Optional[list[Ctor]]:
    if t == T.BOOL:
        return [Ctor("true", [], "true"), Ctor("false", [], "false")]
    if isinstance(t, T.TCon) and t.name == "Option":
        return [Ctor("Some", [t.args[0]], "Some"), Ctor("None", [], "None")]
    if isinstance(t, T.TCon) and t.name == "Result":
        return [Ctor("Ok", [t.args[0]], "Ok"), Ctor("Err", [t.args[1]], "Err")]
    if isinstance(t, T.TTuple):
        return [Ctor("tuple", list(t.items), "")]
    if isinstance(t, T.TNominal):
        ti = chk.types.get(t.qualname)
        if ti is None:
            return None
        if ti.kind in ("enum", "errorenum"):
            return [Ctor(c, [ft for _, ft in (fields or [])], f"{ti.name}.{c}") for c, fields in ti.cases.items()]
        if ti.kind in ("record", "mrecord", "error"):
            return [Ctor("record", list(ti.fields.values()), ti.name)]
    return None


class Pat:
    """Normalised pattern: wild, ctor(name, subs), lit(value), or alts."""

    __slots__ = ("kind", "name", "subs", "value", "alts")

    def __init__(self, kind, name=None, subs=None, value=None, alts=None):
        self.kind = kind
        self.name = name
        self.subs = subs or []
        self.value = value
        self.alts = alts or []


def normalise(chk, p, t) -> Pat:
    c = p.__class__
    if c is A.WildcardPat:
        return Pat("wild")
    if c is A.BindPat:
        if p.type is not None:
            return Pat("lit", value=("type", p.type.span.text))
        return Pat("wild")
    if c is A.LiteralPat:
        if p.kind == "bool":
            return Pat("ctor", "true" if p.value else "false")
        return Pat("lit", value=(p.kind, p.value))
    if c is A.OrPat:
        return Pat("or", alts=[normalise(chk, a, t) for a in p.alts])
    if c is A.TuplePat:
        items = t.items if isinstance(t, T.TTuple) and len(t.items) == len(p.items) else [T.DYN] * len(p.items)
        return Pat("ctor", "tuple", [normalise(chk, sp, it) for sp, it in zip(p.items, items)])
    if c is A.CasePat:
        ctors = constructors(chk, t)
        if len(p.path) == 1 and p.path[0] in CORE:
            name = p.path[0]
        elif ctors and ctors[0].name == "record":
            name = "record"
        else:
            name = p.path[-1]
        ctor = next((k for k in ctors or [] if k.name == name), None)
        if ctor is None:
            return Pat("lit", value=("case", ".".join(p.path)))
        arity = len(ctor.args)
        subs = [Pat("wild")] * arity
        if p.args is not None:
            field_names = _field_names(chk, t, name)
            pos = 0
            for fname, sp in p.args:
                if fname is None:
                    idx = pos
                    pos += 1
                else:
                    idx = field_names.index(fname) if fname in field_names else None
                if idx is not None and idx < arity:
                    subs[idx] = normalise(chk, sp, ctor.args[idx])
        return Pat("ctor", name, subs)
    return Pat("wild")


def _field_names(chk, t, ctor_name) -> list[str]:
    if isinstance(t, T.TNominal):
        ti = chk.types.get(t.qualname)
        if ti is not None:
            if ctor_name == "record":
                return list(ti.fields)
            fields = ti.cases.get(ctor_name) or []
            return [f for f, _ in fields]
    if ctor_name in ("Some", "Ok"):
        return ["value"]
    if ctor_name == "Err":
        return ["error"]
    return []


def expand(row: list[Pat]) -> list[list[Pat]]:
    if row and row[0].kind == "or":
        out = []
        for a in row[0].alts:
            out.extend(expand([a] + row[1:]))
        return out
    return [row]


def is_wild(p: Pat) -> bool:
    return p.kind == "wild"


def specialize(rows, ctor: Ctor):
    out = []
    arity = len(ctor.args)
    for r in rows:
        for row in expand(r):
            h = row[0]
            if is_wild(h):
                out.append([Pat("wild")] * arity + row[1:])
            elif h.kind == "ctor" and h.name == ctor.name:
                out.append(list(h.subs) + row[1:])
    return out


def default(rows):
    out = []
    for r in rows:
        for row in expand(r):
            if is_wild(row[0]):
                out.append(row[1:])
    return out


def missing(chk, rows, tys, depth: int = 0) -> Optional[list[str]]:
    """A witness (pattern strings) not covered by rows, or None if exhaustive."""
    if depth > 30:
        return None
    if not tys:
        return None if rows else []
    rows = [row for r in rows for row in expand(r)]
    ctors = constructors(chk, tys[0])
    heads = {r[0].name for r in rows if r[0].kind == "ctor"}
    if ctors is None:
        w = missing(chk, default(rows), tys[1:], depth + 1)
        return None if w is None else [WILD] + w
    if all(c.name in heads for c in ctors):
        for c in ctors:
            w = missing(chk, specialize(rows, c), list(c.args) + list(tys[1:]), depth + 1)
            if w is not None:
                return [render(c, w[:len(c.args)])] + w[len(c.args):]
        return None
    w = missing(chk, default(rows), tys[1:], depth + 1)
    if w is None:
        return None
    absent = next(c for c in ctors if c.name not in heads)
    return [render(absent, [WILD] * len(absent.args))] + w


def useful(chk, rows, v: list[Pat], tys, depth: int = 0) -> bool:
    if depth > 30:
        return True
    if not tys:
        return not rows
    rows = [row for r in rows for row in expand(r)]
    h = v[0]
    if h.kind == "or":
        return any(useful(chk, rows, [a] + v[1:], tys, depth + 1) for a in h.alts)
    ctors = constructors(chk, tys[0])
    if h.kind == "ctor" and ctors is not None:
        c = next((k for k in ctors if k.name == h.name), None)
        if c is None:
            return True
        return useful(chk, specialize(rows, c), list(h.subs) + v[1:], list(c.args) + list(tys[1:]), depth + 1)
    if h.kind == "lit":
        sub = [r[1:] for r in rows if is_wild(r[0]) or (r[0].kind == "lit" and r[0].value == h.value)]
        return useful(chk, sub, v[1:], tys[1:], depth + 1)
    # wildcard
    heads = {r[0].name for r in rows if r[0].kind == "ctor"}
    if ctors is not None and all(c.name in heads for c in ctors):
        return any(useful(chk, specialize(rows, c), [Pat("wild")] * len(c.args) + v[1:],
                          list(c.args) + list(tys[1:]), depth + 1) for c in ctors)
    return useful(chk, default(rows), v[1:], tys[1:], depth + 1)


def render(c: Ctor, subs: list[str]) -> str:
    if c.name == "tuple":
        return "(" + ", ".join(subs) + ")"
    if not c.args:
        return c.label
    return f"{c.label}(" + ", ".join(subs) + ")"


def check_match(chk, node: A.Match, scrut_ty) -> None:
    rows = []
    for arm in node.arms:
        p = normalise(chk, arm.pattern, scrut_ty)
        if arm.guard is None:
            if rows and not useful(chk, rows, [p], [scrut_ty]):
                chk.advise("S.MATCH.UNREACHABLE_ARM", "this match arm can never be selected (earlier arms cover it)",
                           arm.pattern.span)
            rows.append([p])
    w = missing(chk, rows, [scrut_ty])
    if w is not None:
        closed = constructors(chk, scrut_ty) is not None
        what = w[0]
        msg = (f"match is not exhaustive: `{what}` is not covered" if closed else
               "match over an open type needs a catch-all arm (`_ => ...`)")
        chk.oblig("S.MATCH.NON_EXHAUSTIVE", msg, node.scrutinee.span, label="scrutinee",
                  help=f"add an arm for `{what}`" if closed else "add `_ => ...`",
                  notes=["guarded arms do not count towards exhaustiveness"] if any(a.guard for a in node.arms) else None)
