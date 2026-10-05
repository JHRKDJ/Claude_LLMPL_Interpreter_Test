"""Tasks, cancellation scopes and structured task groups (V3 5.12, 6.8, 7.10).

This module owns the *data* and *policy* of the task tree:
- `Task`: one language task (stack of cancel scopes, mask depth, outcome, frames).
- `CancelScope`: a region whose cancellation is resolved at its own boundary
  (task root, group body, `within`). Cancelling a scope cascades to nested group
  scopes of the same task and to their child tasks.
- `TaskGroup`: the one substrate behind fail-fast / collect / race / firstSuccess.
  `on_child_done` implements the observation and triggering rules (AMB-002).

The evaluator (interp/) drives execution; the scheduler moves the baton.
"""
from __future__ import annotations

import itertools
from collections import deque
from typing import Optional

from .signals import ChildOrigin, Thrown

_task_ids = itertools.count(1)


class Outcome:
    __slots__ = ("kind", "value", "thrown", "diagnostic", "reason")

    def __init__(self, kind: str, value=None, thrown: Optional[Thrown] = None, diagnostic=None,
                 reason: Optional[str] = None):
        self.kind = kind  # ok | threw | abandoned | cancelled
        self.value = value
        self.thrown = thrown
        self.diagnostic = diagnostic
        self.reason = reason

    def __repr__(self) -> str:
        return f"Outcome({self.kind})"


class CancelScope:
    __slots__ = ("kind", "task", "group", "cancelled", "reason", "within_deadline", "timer", "span")

    def __init__(self, kind: str, task: "Task", group: Optional["TaskGroup"] = None, span=None):
        self.kind = kind  # task | group | within
        self.task = task
        self.group = group
        self.cancelled = False
        self.reason: Optional[str] = None
        self.within_deadline = None
        self.timer = None
        self.span = span


class Task:
    def __init__(self, sched, path: str, name: str, parent: Optional["Task"] = None,
                 group: Optional["TaskGroup"] = None):
        self.id = next(_task_ids)
        self.sched = sched
        self.path = path
        self.name = name
        self.parent = parent
        self.group = group
        self.coro = None
        self.root_scope = CancelScope("task", self)
        self.scopes: list[CancelScope] = [self.root_scope]
        self.groups: list[TaskGroup] = []  # groups opened by this task (stack)
        # cancellation masks (cleanup, release): one floor per masked region, recording how
        # many cancel scopes existed when it began (BUG-0033)
        self.mask_floors: list[int] = []
        self.outcome: Optional[Outcome] = None
        self.done = False
        self.in_ready = False
        self.frames: list = []
        self.wait = None  # current Wait, for diagnostics and cancellation
        self.wake = None  # ("value", v) | ("cancel", None) | ("abandon", diag)
        self.awaiters: list = []  # tasks awaiting this task
        self.watchers: list = []  # select states interested in this task's completion
        self.held_ports: set = set()
        self.select_ring: deque = deque(maxlen=32)
        self.origin = ChildOrigin(self)
        self.failure_delivered = False
        self.depth = 0
        self.cleanup_reports: list = []
        sched.all_tasks.append(self)

    # ------------------------------------------------------------ cancellation
    @property
    def mask(self) -> int:
        """Masking depth. Assigning a larger value enters masked regions, a smaller one
        leaves them (so `task.mask += 1` / `task.mask -= 1` bracket a cleanup)."""
        return len(self.mask_floors)

    @mask.setter
    def mask(self, value: int) -> None:
        while len(self.mask_floors) < value:
            self.mask_floors.append(len(self.scopes))
        while len(self.mask_floors) > value:
            self.mask_floors.pop()

    def cancel_pending(self) -> bool:
        """A cancellation is deliverable unless it belongs to a scope that was already
        open when the innermost mask began: masking delays the *pending* cancellation, but
        a deadline opened inside the cleanup itself still fires (V3 5.6.3; BUG-0033)."""
        floor = self.mask_floors[-1] if self.mask_floors else 0
        for s in self.scopes[floor:]:
            if s.cancelled:
                return True
        return False

    def pending_scope(self) -> Optional[CancelScope]:
        for s in self.scopes:
            if s.cancelled:
                return s
        return None

    def __repr__(self) -> str:
        return f"<task {self.path}>"


class Wait:
    """What a blocked task is waiting for (diagnostics + cancellation unregistration)."""

    __slots__ = ("kind", "detail", "cancellable", "unregister", "target", "span")

    def __init__(self, kind: str, detail: str, cancellable: bool = True, unregister=None, target=None, span=None):
        self.kind = kind  # await | quiesce | channel | select | sleep | within
        self.detail = detail
        self.cancellable = cancellable
        self.unregister = unregister
        self.target = target
        self.span = span


def cancel_scope(scope: CancelScope, reason: str) -> None:
    """Request cancellation of `scope`, cascading to nested groups and child tasks."""
    if scope.cancelled:
        return
    scope.cancelled = True
    scope.reason = reason
    task = scope.task
    try:
        idx = task.scopes.index(scope)
    except ValueError:
        idx = 0
    # nested group scopes of the same task (opened inside this scope)
    for s in task.scopes[idx:]:
        if s.group is not None:
            for child in s.group.children:
                if not child.done:
                    cancel_scope(child.root_scope, reason)
    if scope.group is not None and scope not in task.scopes:
        for child in scope.group.children:
            if not child.done:
                cancel_scope(child.root_scope, reason)
    wake_for_cancel(task)


def wake_for_cancel(task: Task) -> None:
    w = task.wait
    if w is None or task.done or not w.cancellable:
        return
    if not task.cancel_pending():
        return
    if w.unregister is not None:
        w.unregister()
    task.wait = None
    task.wake = ("cancel", None)
    task.sched.make_ready(task)


def wake(task: Task, value=None) -> None:
    w = task.wait
    if w is not None and w.unregister is not None:
        w.unregister()
    task.wait = None
    task.wake = ("value", value)
    task.sched.make_ready(task)


class TaskGroup:
    MODES = ("failfast", "collect", "race", "firstSuccess")

    def __init__(self, mode: str, site, owner: Task, label: str):
        self.mode = mode
        self.site = site
        self.owner = owner
        self.label = label
        self.scope = CancelScope("group", owner, self, site)
        self.children: list[Task] = []
        self.live = 0
        self.counter = itertools.count(1)
        self.triggered = False
        self.trigger_reason: Optional[str] = None
        self.winner: Optional[Task] = None
        self.exit_wait = False
        self.closed = False

    def child_path(self, name: str) -> str:
        return f"{self.owner.path}/{self.label}/{next(self.counter)}:{name}"

    def trigger(self, reason: str) -> None:
        if not self.triggered:
            self.triggered = True
            self.trigger_reason = reason
        cancel_scope(self.scope, reason)

    def owner_awaiting(self, child: Task) -> bool:
        """Is the group body blocked waiting on exactly this child (an `await` of its
        handle, or a select with a `task` branch on it)? Then a failure is delivered
        there for observation instead of triggering fail-fast (AMB-002)."""
        w = self.owner.wait
        if w is None:
            return False
        if w.kind == "await":
            return w.target is child
        if w.kind == "select" and w.target:
            return child in w.target
        return False

    def on_child_done(self, child: Task) -> None:
        self.live -= 1
        out = child.outcome
        if self.mode == "failfast":
            if out.kind == "threw":
                if self.owner_awaiting(child) and not self.scope.cancelled:
                    child.failure_delivered = True
                else:
                    self.trigger(f"sibling task {child.path} failed")
            elif out.kind == "abandoned":
                self.trigger(f"sibling task {child.path} abandoned")
        elif self.mode == "collect":
            pass
        elif self.mode == "race":
            if self.winner is None:
                self.winner = child
                self.trigger(f"race decided by {child.path}")
            elif out.kind == "abandoned":
                self.trigger(f"task {child.path} abandoned")
        elif self.mode == "firstSuccess":
            if out.kind == "ok" and self.winner is None:
                self.winner = child
                self.trigger(f"first success by {child.path}")
            elif out.kind == "abandoned":
                self.trigger(f"task {child.path} abandoned")
        # wake tasks awaiting this child
        for w_task in list(child.awaiters):
            if w_task.wait is not None and w_task.wait.target is child:
                wake(w_task, child)
        child.awaiters.clear()
        for st in list(child.watchers):
            st.recheck()
        if self.live == 0 and self.exit_wait:
            if self.owner.wait is not None and self.owner.wait.kind == "quiesce":
                wake(self.owner, None)

    def ordered_children(self) -> list[Task]:
        return list(self.children)
