"""Pattern matching (V3 3.3, 6.2). Matching is side-effect free and type-exact:
an Int literal pattern never matches a Float, `true` never matches 1."""
from __future__ import annotations

from ...syntax import ast as A
from ..core_types import NONE, OPTION, RESULT
from ..equality import lang_eq
from ..signals import Fault
from ..values import (Borrow, CategoryType, EnumType, FrozenRecord, MutableRecord, RecordType, TupleValue, TypeValue,
                      VariantValue)
from .core import Env

CORE = {"Some": OPTION.cases["Some"], "None": OPTION.cases["None"], "Ok": RESULT.cases["Ok"],
        "Err": RESULT.cases["Err"]}


class PatternMixin:
    def match_pattern(self, pat, v, b: dict, env: Env) -> bool:
        c = pat.__class__
        if type(v) is Borrow:
            v = v.target
        if c is A.BindPat:
            if pat.type is not None:
                ty = pat.ann.get("ty")
                if ty is None:
                    ty = self.type_of_expr(pat.type, env)
                    pat.ann["ty"] = ty
                if not self.registry.check(ty, v):
                    return False
            b[pat.name] = v
            return True
        if c is A.WildcardPat:
            return True
        if c is A.LiteralPat:
            k = pat.kind
            tv = type(v)
            if k == "int":
                return tv is int and v == pat.value
            if k == "float":
                return tv is float and v == pat.value
            if k == "str":
                return tv is str and v == pat.value
            if k == "bool":
                return tv is bool and v == pat.value
            return False
        if c is A.CasePat:
            return self._match_case(pat, v, b, env)
        if c is A.TuplePat:
            if type(v) is not TupleValue or len(v.items) != len(pat.items):
                return False
            for p, x in zip(pat.items, v.items):
                if not self.match_pattern(p, x, b, env):
                    return False
            return True
        if c is A.OrPat:
            for alt in pat.alts:
                trial: dict = {}
                if self.match_pattern(alt, v, trial, env):
                    b.update(trial)
                    return True
            return False
        raise Fault("A.RUNTIME.UNREACHABLE", "unknown pattern kind")

    def _resolve_case_target(self, pat: A.CasePat, env: Env):
        target = pat.ann.get("target")
        if target is not None:
            return target
        if len(pat.path) == 1 and pat.path[0] in CORE:
            target = CORE[pat.path[0]]
        else:
            target = self.resolve_path(pat.path, env, pat.span)
        pat.ann["target"] = target
        return target

    def _match_case(self, pat: A.CasePat, v, b: dict, env: Env) -> bool:
        target = self._resolve_case_target(pat, env)
        tt = type(target)
        from ..values import CaseInfo
        if tt is CaseInfo:
            ci = target
        elif tt is TypeValue and target.kind == "case":
            ci = target.target
        elif tt is VariantValue:  # nullary case value, e.g. Shape.Empty
            ci = target.case
        elif tt is TypeValue and target.kind == "record":
            rt: RecordType = target.target
            if type(v) not in (FrozenRecord, MutableRecord) or v.rtype is not rt:
                return False
            if pat.args is None:
                return True
            for i, (fname, sub) in enumerate(pat.args):
                if fname is None:
                    if len(rt.fields) == 1 and i == 0:
                        fname = rt.fields[0].name
                    else:
                        raise Fault("A.RUNTIME.INVALID_ARGUMENT",
                                    f"record pattern for {rt.name} must name fields (`field: pattern`)")
                idx = rt.field_index.get(fname)
                if idx is None:
                    raise Fault("A.TYPE.UNKNOWN_FIELD", f"record {rt.name} has no field `{fname}`")
                if not self.match_pattern(sub, v.values[idx], b, env):
                    return False
            return True
        elif tt is TypeValue and target.kind == "enum":
            et: EnumType = target.target
            return type(v) is VariantValue and v.case.etype is et and pat.args is None
        else:
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"`{pat.name}` is not a variant case or record type")
        if type(v) is not VariantValue or v.case is not ci:
            return False
        if pat.args is None:
            return True
        fields = ci.fields or []
        if not fields and pat.args:
            raise Fault("A.RUNTIME.INVALID_ARGUMENT", f"case {ci.qualname} has no payload")
        positional = 0
        for fname, sub in pat.args:
            if fname is None:
                if positional >= len(fields):
                    raise Fault("A.RUNTIME.INVALID_ARGUMENT",
                                f"too many sub-patterns for {ci.qualname} ({len(fields)} field(s))")
                idx = positional
                positional += 1
            else:
                idx = ci.field_index.get(fname)
                if idx is None:
                    raise Fault("A.TYPE.UNKNOWN_FIELD", f"case {ci.qualname} has no field `{fname}`")
            if not self.match_pattern(sub, v.values[idx], b, env):
                return False
        return True

    def resolve_path(self, path: list[str], env: Env, span):
        """Resolve a dotted name used in patterns/catches (types, cases, categories)."""
        first = path[0]
        e = env.find(first)
        if e is None:
            if first in CORE and len(path) == 1:
                return CORE[first]
            raise Fault("A.RUNTIME.UNREACHABLE", f"unresolved name `{first}`")
        cur = e.vars[first]
        for seg in path[1:]:
            from ..values import ModuleValue
            if type(cur) is ModuleValue:
                cur = cur.namespace.get(seg)
                if cur is None:
                    raise Fault("A.TYPE.UNKNOWN_FIELD", f"module has no member `{seg}`")
            elif type(cur) is TypeValue and cur.kind == "enum":
                et = cur.target
                ci = et.cases.get(seg)
                if ci is None:
                    raise Fault("A.TYPE.UNKNOWN_FIELD", f"enum {et.name} has no case `{seg}`")
                cur = et.nullary(seg) if ci.fields is None else TypeValue("case", ci, (), f"{et.name}.{seg}")
            else:
                raise Fault("A.TYPE.UNKNOWN_FIELD", f"`{'.'.join(path)}` does not name a case, type or category")
        return cur
