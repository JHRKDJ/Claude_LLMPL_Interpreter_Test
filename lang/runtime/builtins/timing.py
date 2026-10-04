"""`time` and `cancel` prelude namespaces and `sleep` (V3 7.10.2, 7.12.9).

Time comes from the scheduler clock: the real monotonic clock by default, or a
virtual clock under `--clock=virtual` (IMPL-002).
"""
from __future__ import annotations

from ..signals import Fault
from ..values import UNIT, Duration, Instant
from .registry import module_fn, prelude


@module_fn("prelude.time", "now", 0, sig="fn() -> Instant")
def _now(interp, args, span):
    return Instant(interp.sched.now())


@module_fn("prelude.time", "sleep", 1, sig="async fn(Duration) -> Unit", is_async=True)
def _time_sleep(interp, args, span):
    return _sleep(interp, args, span)


@prelude("sleep", 1, sig="async fn(Duration) -> Unit", is_async=True)
def _sleep(interp, args, span):
    d = args[0]
    if type(d) is not Duration:
        raise Fault("A.RUNTIME.INVALID_ARGUMENT", "sleep expects a Duration, e.g. `sleep(10.millis)`")
    return interp.sleep_for(d.nanos, span)


@module_fn("prelude.cancel", "check", 0, sig="fn() -> Unit")
def _check(interp, args, span):
    interp.check_cancel(span)
    return UNIT
