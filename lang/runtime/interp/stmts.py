"""Statements, blocks, loops, `defer`, and the cleanup-failure combination table.

Unwinding rules (V3 5.6, 7.9.6, 7.9.8; SPEC-016):
- `defer` is block-scoped, LIFO, and runs (masked against cancellation) on normal
  exit, recoverable exception and cancellation — never during abandonment.
- Cleanup failures combine per the V3 5.6 table:
    normal  + cleanup error   -> throw the cleanup error (several -> AggregateException)
    thrown  + cleanup error   -> AggregateException(original, cleanup...)
    cancel  + cleanup error   -> report cleanup failure, keep cancelling
    abandon                   -> defers do not run
"""
from __future__ import annotations

from ...diagnostics import Diagnostic, Label, Note, code
from ...syntax import ast as A
from ..builtins.common import kind_of
from ..capture import Budget, safe_repr
from ..core_types import AGGREGATE_ENTRY, AGGREGATE_EXCEPTION, NONE, some
from ..equality import hash_key, type_name
from ..frozen import is_frozen
from ..signals import (Abandoned, BreakSignal, Cancelled, ContinueSignal, ErrorProvenance, Fault, HardTermination,
                       ReturnSignal, Signal, Thrown)
from ..values import (UNINIT, UNIT, Borrow, FrozenList, FrozenMap, FrozenRecord, FrozenSet, MutableList, MutableMap,
                      MutableRecord, MutableSet, RangeValue, TupleValue, VariantValue)
from .core import Env
from .exprs import binop


class StmtMixin:
    # ------------------------------------------------------------------ blocks
    def exec_block(self, block: A.Block, env: Env, scope: bool = True):
        benv = Env(env) if scope else env
        defers = None
        result = UNIT
        ev = self.eval
        try:
            for st in block.stmts:
                c = st.__class__
                if c is A.ExprStmt:
                    result = ev(st.expr, benv)
                elif c is A.DeferStmt:
                    if defers is None:
                        defers = []
                    defers.append((st, benv))
                    result = UNIT
                else:
                    self._stmt[c](st, benv)
                    result = UNIT
        except (Abandoned, HardTermination):
            raise
        except BaseException as exc:
            if defers:
                self.run_defers(defers, exc, block)
            raise
        if defers:
            self.run_defers(defers, None, block)
        return result

    def run_defers(self, defers, pending, block) -> None:
        task = self.sched.current
        task.mask += 1
        errors: list[Thrown] = []
        try:
            for st, denv in reversed(defers):
                try:
                    body = st.body
                    if body.__class__ is A.Block:
                        self.exec_block(body, denv)
                    else:
                        self.eval(body, denv)
                except Thrown as t:
                    t.prov.chain.append(st.span)
                    errors.append(t)
                except (ReturnSignal, BreakSignal, ContinueSignal):
                    raise self.abandon("A.RUNTIME.UNREACHABLE", "control transfer out of a `defer` block",
                                       st.span, denv)
        finally:
            task.mask -= 1
        if errors:
            self.combine_cleanup(pending, errors, "defer", block.span)

    def combine_cleanup(self, pending, errors: list[Thrown], source: str, span) -> None:
        """Apply the V3 5.6 cleanup-failure table. Raises the combined outcome, or
        returns (for pending cancellation) after reporting."""
        if isinstance(pending, Cancelled):
            for e in errors:
                self.report_cleanup_during_cancel(e, source, span)
                pending.cleanup_failures.append(e)
            return
        if isinstance(pending, Thrown):
            parts = [("body", pending)] + [(source, e) for e in errors]
            raise self.aggregate_thrown(parts, span)
        # normal exit (including return/break/continue)
        if len(errors) == 1:
            raise errors[0]
        raise self.aggregate_thrown([(source, e) for e in errors], span)

    def aggregate_thrown(self, parts, span, cancel_pending: bool = False) -> Thrown:
        """Build `AggregateException` from (source, Thrown-or-(path, Thrown)) parts."""
        entries = []
        prov = self.new_provenance(span)
        prov.cancel_pending = cancel_pending
        for source, t in parts:
            path = None
            if isinstance(t, tuple):
                path, t = t
            elif t.origin is not None:
                path = t.origin.task.path
            entries.append(FrozenRecord(AGGREGATE_ENTRY, (source, some(path) if path else NONE, t.error)))
            prov.parts.append((source, path, t.error, t.prov))
        agg = FrozenRecord(AGGREGATE_EXCEPTION, (FrozenList(tuple(entries)),))
        return Thrown(agg, prov)

    def report_cleanup_during_cancel(self, t: Thrown, source: str, span) -> None:
        d = Diagnostic(code("W.CLEANUP.FAILED_DURING_CANCELLATION"),
                       f"{source} cleanup failed while cancellation was pending: {self.error_summary(t.error)}",
                       severity="warning", primary=Label(t.prov.created_at or span, "cleanup failure raised here"))
        d.notes.append(Note("the pending cancellation is preserved and redelivered after cleanup (V3 5.6)"))
        d.task = self.task_provenance()
        self.sched.current.cleanup_reports.append(d)
        self.runtime_warnings.append(d)

    def error_summary(self, e) -> str:
        return safe_repr(e, Budget(200))

    # ------------------------------------------------------------------ statements
    def exec_ExprStmt(self, st: A.ExprStmt, env: Env):
        self.eval(st.expr, env)

    def exec_LetStmt(self, st: A.LetStmt, env: Env):
        ty = None
        if st.type is not None:
            ty = self.type_of_expr(st.type, env)
        if st.value is None:
            for name, _ in st.names:
                env.define(name, UNINIT, st.is_const, ty)
            return
        v = self.eval(st.value, env)
        if type(v) is Borrow:
            raise self.abandon("A.RESOURCE.ESCAPE",
                               "a resource cannot be bound with `let`; use it through its `use` binding",
                               st.span, env, help="pass the `use` binding directly to helpers (as a borrow)")
        if st.destructure:
            if type(v) is not TupleValue or len(v.items) != len(st.names):
                raise self.abandon("A.TYPE.DYNAMIC_MISMATCH",
                                   f"cannot destructure {type_name(v)} into {len(st.names)} bindings",
                                   st.span, env, expected=f"tuple of {len(st.names)}", found=type_name(v))
            if ty is not None:
                self.check_annotation(ty, v, st.value.span, st.type, env, "binding annotation")
            for (name, _), item in zip(st.names, v.items):
                env.define(name, item, st.is_const)
            return
        if ty is not None:
            self.check_annotation(ty, v, st.value.span, st.type, env, "binding annotation")
        env.define(st.names[0][0], v, st.is_const, ty)

    def exec_AssignStmt(self, st: A.AssignStmt, env: Env):
        target = st.target
        tc = target.__class__
        if tc is A.Name:
            e = env.find(target.name)
            if e is None:
                raise self.abandon("A.RUNTIME.UNREACHABLE", f"assignment to unknown binding `{target.name}`",
                                   target.span, env)
            if e.consts and target.name in e.consts:
                raise self.abandon("A.RUNTIME.UNREACHABLE", f"assignment to const `{target.name}`", target.span, env)
            if e.kind in ("module", "prelude"):
                raise self.abandon("A.RUNTIME.UNREACHABLE", f"`{target.name}` is not a reassignable binding",
                                   target.span, env)
            if st.op == "=":
                v = self.eval(st.value, env)
            else:
                cur = e.vars[target.name]
                if cur is UNINIT:
                    raise self.abandon("A.BINDING.UNINITIALISED", f"`{target.name}` is read before it is initialised",
                                       target.span, env)
                rhs = self.eval(st.value, env)
                v = self._compound(st, cur, rhs, env)
            if type(v) is Borrow:
                raise self.abandon("A.RESOURCE.ESCAPE", "a resource cannot be assigned to an ordinary binding",
                                   st.span, env)
            if e.types and target.name in e.types:
                self.check_annotation(e.types[target.name], v, st.value.span, None, env, "binding annotation")
            e.vars[target.name] = v
            return
        if tc is A.Field:
            obj = self.eval(target.obj, env)
            if type(obj) is Borrow:
                obj = self.borrow_target(obj, target.span, env)
            if type(obj) is not MutableRecord:
                raise self.abandon("A.TYPE.FROZEN_MUTATION",
                                   f"cannot assign field `{target.name}` of {type_name(obj)}: it is not a mutable record",
                                   target.span, env,
                                   help="frozen values are updated with `value with { field: x }`"
                                   if type(obj) is FrozenRecord else None)
            rt = obj.rtype
            i = rt.field_index.get(target.name)
            if i is None:
                raise self.unknown_member(obj, target.name, target, env, list(rt.field_index))
            if target.name in rt.invariant_fields and not self.in_own_method(obj):
                raise self.abandon("A.CONTRACT.INVARIANT_FIELD_WRITE",
                                   f"field `{target.name}` participates in an invariant of {rt.name}; it may only be "
                                   f"assigned inside {rt.name}'s own methods", target.span, env,
                                   help=f"add a method on {rt.name} that performs this update")
            if st.op == "=":
                v = self.eval(st.value, env)
            else:
                v = self._compound(st, obj.values[i], self.eval(st.value, env), env)
            obj.values[i] = self.check_field_value(rt, rt.fields[i], v, st.value.span, env)
            return
        if tc is A.Index:
            obj = self.eval(target.obj, env)
            if type(obj) is Borrow:
                obj = self.borrow_target(obj, target.span, env)
            idx = self.eval(target.indices[0], env)
            if st.op == "=":
                v = self.eval(st.value, env)
            else:
                v = self._compound(st, self.index_get(obj, idx, target, env), self.eval(st.value, env), env)
            self.index_set(obj, idx, v, target, env)
            return
        raise self.abandon("A.RUNTIME.UNREACHABLE", "invalid assignment target", st.span, env)

    def _compound(self, st, cur, rhs, env):
        op = st.op[0]
        try:
            return binop(op, cur, rhs)
        except Fault as f:
            raise self.abandon_fault(f, st.span, env)

    def index_set(self, obj, idx, v, node, env):
        t = type(obj)
        if type(v) is Borrow:
            raise self.abandon("A.RESOURCE.ESCAPE", "a resource borrow cannot be stored in a collection", node.span, env)
        if t is MutableList:
            n = len(obj.items)
            if type(idx) is not int or idx < 0 or idx >= n:
                raise self.abandon("A.INDEX.OUT_OF_RANGE", f"index {safe_repr(idx)} is out of range for length {n}",
                                   node.span, env)
            obj.items[idx] = self.check_elem_write(obj, v, node.span)
            obj.version += 1
            return
        if t is MutableMap:
            if not is_frozen(idx):
                raise self.abandon("A.TYPE.UNHASHABLE", f"map keys must be frozen values, found {type_name(idx)}",
                                   node.span, env)
            obj.data[hash_key(idx)] = (idx, v)
            obj.version += 1
            return
        if t in (FrozenList, FrozenMap, FrozenSet, str, TupleValue):
            raise self.abandon("A.TYPE.FROZEN_MUTATION", f"cannot assign into a frozen {type_name(obj)}", node.span,
                               env, help="frozen collections are updated by creating new values, e.g. `xs.replaced(i, v)`"
                                         " or `m.inserted(k, v)`; or use a Mutable collection")
        raise self.abandon("A.TYPE.OPERAND_MISMATCH", f"{type_name(obj)} does not support index assignment",
                           node.span, env)

    def check_elem_write(self, coll, v, span):
        et = getattr(coll, "elem_type", None)
        if et is not None and not self.registry.check(et, v):
            raise Fault("A.TYPE.DYNAMIC_MISMATCH",
                        f"element written into MutableList[{et}] has type {type_name(v)}",
                        expected=str(et), found=type_name(v))
        return v

    def exec_ReturnStmt(self, st: A.ReturnStmt, env: Env):
        v = UNIT if st.value is None else self.eval(st.value, env)
        raise ReturnSignal(v, st.span)

    def exec_BreakStmt(self, st, env):
        raise BreakSignal()

    def exec_ContinueStmt(self, st, env):
        raise ContinueSignal()

    def exec_ThrowStmt(self, st: A.ThrowStmt, env: Env):
        v = self.eval(st.value, env)
        if not ((type(v) is FrozenRecord and v.rtype.is_error) or (type(v) is VariantValue and v.case.etype.is_error)):
            raise self.abandon("A.TYPE.OPERAND_MISMATCH",
                               f"only declared error types can be thrown; found {type_name(v)}", st.value.span, env,
                               help="declare it with `error Name { ... }` or `error enum Name { ... }`")
        raise Thrown(v, self.new_provenance(st.span))

    def exec_NonlocalStmt(self, st, env):
        return None

    def exec_DeferStmt(self, st, env):  # only reached outside exec_block (should not happen)
        raise self.abandon("A.RUNTIME.UNREACHABLE", "defer outside a block", st.span, env)

    def exec_AssertStmt(self, st: A.AssertStmt, env: Env):
        v = self.eval(st.cond, env)
        if type(v) is not bool:
            raise self.abandon("A.TYPE.NON_BOOL_CONDITION", f"assert condition must be a Bool, found {type_name(v)}",
                               st.cond.span, env)
        if not v:
            msg = "assertion failed"
            if st.message is not None:
                m = self.eval(st.message, env)
                msg = f"assertion failed: {m if type(m) is str else safe_repr(m)}"
            values = self.explain_values(st.cond, env)
            raise self.abandon("A.ASSERT.FAILED", msg, st.cond.span, env, values=values,
                               label="this condition was false")

    def explain_values(self, expr, env, limit: int = 8) -> dict:
        """Values of the simple sub-expressions of a failed condition (side-effect-free
        nodes only: names, field reads, literals-free comparisons)."""
        out: dict[str, str] = {}
        budget = Budget(600)
        for node in A.walk(expr):
            if len(out) >= limit:
                break
            if isinstance(node, (A.Name, A.Field)) and not isinstance(node, A.Literal):
                try:
                    v = self._pure_eval(node, env)
                except BaseException:
                    continue
                key = node.span.text if node.span.file.text else getattr(node, "name", "?")
                if key not in out and not isinstance(v, type(self)):
                    name = node.name if isinstance(node, (A.Name, A.Field)) else None
                    out[key] = safe_repr(v, budget, name=name)
        return out

    def _pure_eval(self, node, env):
        if isinstance(node, A.Name):
            return self.eval_Name(node, env)
        if isinstance(node, A.Field):
            obj = self._pure_eval(node.obj, env)
            if type(obj) in (FrozenRecord, MutableRecord):
                i = obj.rtype.field_index.get(node.name)
                if i is not None:
                    return obj.values[i]
            from ..builtins.registry import PROPS
            k = kind_of(obj)
            if k is not None and node.name in PROPS.get(k, {}):
                return PROPS[k][node.name][0](self, obj)
            raise KeyError(node.name)
        raise KeyError("not pure")

    # ------------------------------------------------------------------ loops
    def exec_WhileStmt(self, st: A.WhileStmt, env: Env):
        while True:
            ok, bindings = self.eval_cond(st.cond, env)
            if not ok:
                return
            benv = env
            if bindings:
                benv = Env(env)
                benv.vars.update(bindings)
            try:
                self.exec_block(st.body, benv)
            except BreakSignal:
                return
            except ContinueSignal:
                continue

    def exec_ForStmt(self, st: A.ForStmt, env: Env):
        if st.is_await:
            return self.exec_for_await(st, env)
        it = self.eval(st.iterable, env)
        if type(it) is Borrow:
            it = self.borrow_target(it, st.iterable.span, env)
        t = type(it)
        version_src = None
        if t is FrozenList or t is TupleValue:
            seq = it.items
        elif t is MutableList:
            seq = it.items
            version_src = it
        elif t is RangeValue:
            seq = it.as_range()
        elif t is FrozenSet:
            seq = list(it.data.values())
        elif t is MutableSet:
            seq = list(it.data.values())
            version_src = it
        elif t is FrozenMap or t is MutableMap:
            raise self.abandon("A.TYPE.NOT_ITERABLE", "maps are not directly iterable", st.iterable.span, env,
                               help="iterate `.keys()`, `.values()` or `.entries()` (entries yield (key, value) tuples)")
        elif t is str:
            raise self.abandon("A.TYPE.NOT_ITERABLE", "strings are not directly iterable", st.iterable.span, env,
                               help="iterate `.chars()` (code points) or `.lines()`")
        else:
            raise self.abandon("A.TYPE.NOT_ITERABLE", f"{type_name(it)} is not iterable", st.iterable.span, env)
        version = version_src.version if version_src is not None else None
        pat = st.pattern
        simple = pat.__class__ is A.BindPat and pat.type is None
        n = len(seq) if version_src is not None else None
        i = 0
        while True:
            if version_src is not None:
                if version_src.version != version:
                    raise self.abandon("A.COLLECTION.MODIFIED_DURING_ITERATION",
                                       f"{type_name(version_src)} was modified while being iterated", st.span, env,
                                       help="iterate over a snapshot (`xs.freeze()` or `xs.mutableCopy()`) or "
                                            "collect changes and apply them after the loop")
                if i >= len(seq):
                    break
                item = seq[i]
            else:
                if i >= len(seq):
                    break
                item = seq[i]
            i += 1
            benv = Env(env)
            if simple:
                benv.vars[pat.name] = item
            else:
                b: dict = {}
                if not self.match_pattern(pat, item, b, env):
                    raise self.abandon("A.MATCH.NO_ARM", f"for-loop pattern does not match element "
                                       f"{safe_repr(item, Budget(160))}", pat.span, env)
                benv.vars.update(b)
            try:
                self.exec_block(st.body, benv, scope=False)
            except BreakSignal:
                return
            except ContinueSignal:
                continue
        del n

    # ------------------------------------------------------------------ helpers
    def in_own_method(self, obj: MutableRecord) -> bool:
        """True when the innermost frame is a method of obj's type executing on obj."""
        task = self.sched.current
        for fr in reversed(task.frames):
            if fr.self_value is obj or (type(fr.self_value) is Borrow and fr.self_value.target is obj):
                return True
            if fr.closure is not None and getattr(fr.closure, "is_lambda", False):
                continue
            return False
        return False


def make_stmt_dispatch(interp) -> dict:
    return {
        A.ExprStmt: interp.exec_ExprStmt,
        A.LetStmt: interp.exec_LetStmt,
        A.AssignStmt: interp.exec_AssignStmt,
        A.ReturnStmt: interp.exec_ReturnStmt,
        A.BreakStmt: interp.exec_BreakStmt,
        A.ContinueStmt: interp.exec_ContinueStmt,
        A.ThrowStmt: interp.exec_ThrowStmt,
        A.NonlocalStmt: interp.exec_NonlocalStmt,
        A.AssertStmt: interp.exec_AssertStmt,
        A.WhileStmt: interp.exec_WhileStmt,
        A.ForStmt: interp.exec_ForStmt,
        A.DeferStmt: interp.exec_DeferStmt,
        A.OnAbandonStmt: interp.exec_OnAbandonStmt,
    }
