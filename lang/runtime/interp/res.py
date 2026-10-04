"""Resource scopes, providers, borrows, abandonment-safe release (V3 5.5, 5.6, 7.9;
SPEC-015; IMPL-003).

`use x = provider(args) { body }`:
  1. the provider runs until its single `yield v`;
  2. `yield` runs the scope body (binding `x` to a Borrow of v) and *captures* the
     body's outcome, so body exceptions/cancellation never enter provider code;
  3. the provider continues with the exit class (`ScopeExit`) and performs normal
     release — under cancellation masking if the body was cancelled;
  4. the saved body outcome and any release failure combine per V3 5.6.
On abandonment, provider continuation and defers never run; only registered
abandonment-safe release primitives run (innermost first), and their failures are
appended to the abandonment diagnostic.
"""
from __future__ import annotations

from ...diagnostics import Note, ResourceProvenance
from ...syntax import ast as A
from ..core_types import SCOPE_EXIT
from ..equality import type_name
from ..signals import Abandoned, Cancelled, Fault, Thrown
from ..values import Borrow, Builtin, BuiltinBound, Closure, ResourceState, UNIT
from .core import Env


class ProviderCtx:
    __slots__ = ("node", "env", "run_body", "yielded", "outcome", "masked", "abandon_actions", "state", "name",
                 "frame_base", "depth_base")

    def __init__(self, node, env, name):
        self.node = node
        self.env = env
        self.yielded = False
        self.outcome = None  # ("ok", v) | ("threw", Thrown) | ("cancelled", Cancelled)
        self.masked = False
        self.abandon_actions: list = []  # (builtin, receiver, span)
        self.state = None
        self.name = name
        self.run_body = None
        self.frame_base = 0  # logical frame depth of the scope owner
        self.depth_base = 0


class NativeProvider:
    """Protocol for providers implemented in Python (e.g. std.fs.openRead)."""

    name = "resource"

    def acquire(self, interp, span):  # -> handle (may raise Thrown)
        raise NotImplementedError

    def release(self, interp, exit_class: str, span):  # normal release (may raise Thrown)
        return None

    def abandon_release(self, interp):  # abandonment-safe release; must not allocate app effects
        return None


class ResourceMixin:
    def borrow_target(self, b: Borrow, span, env):
        st = b.state
        if not st.active:
            d = self.make_diag("A.RESOURCE.USE_AFTER_RELEASE",
                               f"resource `{st.name}` ({st.provider_name}) is used after its scope ended", span, env,
                               help="resources are only usable inside their `use` block")
            d.resource = ResourceProvenance(st.provider_name, st.acquired_at, st.scope_span, None, None)
            raise Abandoned(d)
        if st.task is not self.sched.current:
            raise self.abandon("A.RESOURCE.CROSS_TASK", f"resource `{st.name}` is borrowed from another task",
                               span, env)
        return b.target

    def eval_Use(self, node: A.Use, env: Env):
        init = node.init
        try_node = None
        awaited = False
        e = init
        if e.__class__ is A.Try:
            try_node = e
            e = e.expr
        if e.__class__ is A.Await:
            awaited = True
            e = e.expr
        if e.__class__ is not A.Call:
            raise self.abandon("A.RESOURCE.PROVIDER_OUTSIDE_USE",
                               "a `use` scope must be initialised by calling a resource provider", init.span, env,
                               help="write `use x = try provider(args) { ... }`")
        if awaited:
            self.check_cancel(init.span)
        try:
            if e.callee.__class__ is A.Field:
                obj = self.eval(e.callee.obj, env)
                f = self.get_member(obj, e.callee.name, e.callee, env)
            else:
                f = self.eval(e.callee, env)
            args, kwargs = self.eval_args(e, env)
        except Thrown as t:
            if try_node is not None:
                t.prov.chain.append(try_node.span)
            raise
        if type(f) is Closure and f.is_resource:
            return self._use_closure_provider(node, f, args, kwargs, awaited, try_node, env)
        b = f.builtin if type(f) is BuiltinBound else f
        if type(b) is Builtin and b.is_provider:
            return self._use_native_provider(node, b, f, args, try_node, env)
        raise self.abandon("A.RESOURCE.PROVIDER_OUTSIDE_USE",
                           f"`{e.callee.span.text}` is not a resource provider ({type_name(f)})", e.span, env,
                           help="declare providers with `resource fn name(...) yields T { ... yield v ... }`")

    # ------------------------------------------------------------------ body
    def _run_scope_body(self, node: A.Use, env: Env, value, provider_name: str):
        task = self.sched.current
        target = value.target if type(value) is Borrow else value
        state = ResourceState(task, node.span, node.init.span, node.name, provider_name)
        borrow = Borrow(target, state)
        benv = Env(env)
        benv.vars[node.name] = borrow
        try:
            v = self.exec_block(node.body, benv)
            if type(v) is Borrow:
                raise self.abandon("A.RESOURCE.ESCAPE", "a `use` scope cannot produce its resource as its value",
                                   node.body.span, benv, help="return data derived from the resource instead")
            return ("ok", v), state
        except Thrown as t:
            return ("threw", t), state
        except Cancelled as c:
            return ("cancelled", c), state
        finally:
            state.active = False

    # ------------------------------------------------------------------ user providers
    def _use_closure_provider(self, node, f: Closure, args, kwargs, awaited, try_node, env):
        task = self.sched.current
        ctx = ProviderCtx(node, env, f.name)

        def run_body(value, ctx=ctx):
            outcome, state = self._run_scope_body(node, env, value, f.name)
            ctx.state = state
            return outcome
        ctx.run_body = run_body
        ctx.frame_base = len(task.frames)
        ctx.depth_base = task.depth
        release_error = None
        try:
            self.call_closure(f, args, kwargs, node.init.span, awaited=awaited, node=node.init,
                              provider_body=ctx)
        except Thrown as t:
            if try_node is not None:
                t.prov.chain.append(try_node.span)
            if not ctx.yielded:
                raise  # acquisition failure: nothing was acquired by this scope
            release_error = t
        except Abandoned as a:
            self._run_abandon_actions(ctx, a)
            raise
        finally:
            if ctx.masked:
                task.mask -= 1
                ctx.masked = False
        if not ctx.yielded:
            raise self.abandon("A.RESOURCE.NO_YIELD", f"provider `{f.name}` returned without yielding a resource",
                               node.init.span, env, help="a provider must `yield` exactly once; report acquisition "
                                                         "failure by throwing a declared error")
        return self._combine_release(ctx.outcome, release_error, f.name, node, env, ctx.state)

    def run_provider_body(self, clo, decl, fenv, ctx: ProviderCtx):
        self.exec_block(decl.body, fenv, scope=False)
        return UNIT

    def eval_Yield(self, node: A.Yield, env: Env):
        task = self.sched.current
        fr = task.frames[-1]
        ctx = fr.provider_state
        if ctx is None:
            raise self.abandon("A.RESOURCE.NO_YIELD", "`yield` used outside a resource provider", node.span, env)
        if ctx.yielded:
            raise self.abandon("A.RESOURCE.MULTIPLE_YIELD", f"provider `{ctx.name}` yielded a second time",
                               node.span, env, help="a provider establishes exactly one lifetime: yield once")
        v = self.eval(node.value, env)
        ctx.yielded = True
        # The scope body belongs to the scope owner's activation: hide the suspended
        # provider frames while it runs (BUG-0001), then restore them for release.
        suspended = task.frames[ctx.frame_base:]
        del task.frames[ctx.frame_base:]
        depth = task.depth
        task.depth = ctx.depth_base
        try:
            outcome = ctx.run_body(v)
        finally:
            task.frames.extend(suspended)
            task.depth = depth
        ctx.outcome = outcome
        kind = outcome[0]
        if kind == "cancelled":
            task.mask += 1
            ctx.masked = True
            return SCOPE_EXIT.nullary("Cancelled")
        if kind == "threw":
            return SCOPE_EXIT.nullary("Failed")
        return SCOPE_EXIT.nullary("Normal")

    def exec_OnAbandonStmt(self, st: A.OnAbandonStmt, env: Env):
        fr = self.sched.current.frames[-1]
        ctx = fr.provider_state
        if ctx is None:
            raise self.abandon("A.RESOURCE.PROVIDER_OUTSIDE_USE", "`onAbandon` is only valid inside a resource provider",
                               st.span, env)
        call = st.call
        if call.__class__ is not A.Call or call.callee.__class__ is not A.Field or call.args:
            raise self.abandon("A.RESOURCE.PROVIDER_OUTSIDE_USE",
                               "`onAbandon` takes a call of a built-in release primitive, e.g. `onAbandon file.close()`",
                               st.span, env)
        recv = self.eval(call.callee.obj, env)
        target = recv.target if type(recv) is Borrow else recv
        m = self.get_member(target, call.callee.name, call.callee, env)
        if type(m) is not BuiltinBound or not m.builtin.abandon_safe:
            raise self.abandon("A.RESOURCE.PROVIDER_OUTSIDE_USE",
                               f"`{call.callee.name}` is not an abandonment-safe release primitive; abandonment-safe "
                               f"release may only close/release/revoke/roll back built-in resources", st.span, env)
        ctx.abandon_actions.append((m.builtin, target, st.span))

    def _run_abandon_actions(self, ctx: ProviderCtx, a: Abandoned) -> None:
        for b, recv, span in reversed(ctx.abandon_actions):
            try:
                b.impl(self, recv, [], span)
            except BaseException as e:  # never replaces the original abandonment
                a.diagnostic.notes.append(Note(f"abandonment-safe release `{b.name}` failed: {e}", span))

    # ------------------------------------------------------------------ native providers
    def _use_native_provider(self, node, b: Builtin, f, args, try_node, env):
        task = self.sched.current
        prov: NativeProvider = b.impl(self, args, node.init.span)
        try:
            handle = prov.acquire(self, node.init.span)
        except Thrown as t:
            if try_node is not None:
                t.prov.chain.append(try_node.span)
            raise
        try:
            outcome, state = self._run_scope_body(node, env, handle, prov.name)
        except Abandoned as a:
            try:
                prov.abandon_release(self)
            except BaseException as e:
                a.diagnostic.notes.append(Note(f"abandonment-safe release of {prov.name} failed: {e}"))
            raise
        exit_class = {"ok": "Normal", "threw": "Failed", "cancelled": "Cancelled"}[outcome[0]]
        release_error = None
        if outcome[0] == "cancelled":
            task.mask += 1
        try:
            prov.release(self, exit_class, node.span)
        except Thrown as t:
            if try_node is not None:
                t.prov.chain.append(try_node.span)
            release_error = t
        finally:
            if outcome[0] == "cancelled":
                task.mask -= 1
        return self._combine_release(outcome, release_error, prov.name, node, env, state)

    # ------------------------------------------------------------------ combination
    def _combine_release(self, outcome, release_error, provider_name, node, env, state):
        kind, payload = outcome
        if release_error is None:
            if kind == "ok":
                return payload
            raise payload
        if kind == "ok":
            raise release_error
        if kind == "threw":
            raise self.aggregate_thrown([("body", payload), ("release", release_error)], node.span)
        # cancelled: report the release failure, keep cancelling
        self.report_cleanup_during_cancel(release_error, f"release of {provider_name}", node.span)
        payload.cleanup_failures.append(release_error)
        raise payload
