"""Deterministic cooperative scheduler (IMPL-001, IMPL-002).

Each language task runs on its own Python thread, but a baton guarantees that at
most one task thread runs at any time; the scheduler loop (on the thread that
called `run`) decides who runs next. The ready queue is FIFO by default; under
`--schedule=random --seed=N` the next task is chosen with a seeded RNG (V3 7.14.5).

Time is either the real monotonic clock or a virtual clock that only advances
when every task is blocked (discrete-event simulation, IMPL-002).
"""
from __future__ import annotations

import heapq
import itertools
import random
import threading
import time
from collections import deque
from typing import Callable, Optional

STACK_SIZE = 256 * 1024 * 1024
threading.stack_size(STACK_SIZE)


class Coro:
    """A thread that only runs while holding the scheduler baton."""

    __slots__ = ("sched", "fn", "resume", "thread", "started", "finished", "name")

    def __init__(self, sched: "Scheduler", fn: Callable[[], None], name: str):
        self.sched = sched
        self.fn = fn
        self.resume = threading.Semaphore(0)
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.started = False
        self.finished = False
        self.name = name

    def _run(self) -> None:
        self.resume.acquire()
        try:
            self.fn()
        finally:
            self.finished = True
            self.sched._baton.release()

    def switch_in(self) -> None:
        """Called on the scheduler thread: run this coroutine until it yields."""
        if not self.started:
            self.started = True
            self.thread.start()
        self.resume.release()
        self.sched._baton.acquire()

    def switch_out(self) -> None:
        """Called on this coroutine's thread: give the baton back to the scheduler."""
        self.sched._baton.release()
        self.resume.acquire()


class Timer:
    __slots__ = ("deadline", "seq", "callback", "cancelled")

    def __init__(self, deadline: int, seq: int, callback: Callable[[], None]):
        self.deadline = deadline
        self.seq = seq
        self.callback = callback
        self.cancelled = False

    def __lt__(self, other: "Timer") -> bool:
        return (self.deadline, self.seq) < (other.deadline, other.seq)


class Scheduler:
    def __init__(self, clock: str = "real", schedule: str = "fifo", seed: Optional[int] = None):
        self._baton = threading.Semaphore(0)
        self.ready: deque = deque()
        self.current = None
        self.clock = clock
        self.schedule = schedule
        self.seed = seed
        self.rng = random.Random(seed if seed is not None else 0)
        self.timers: list[Timer] = []
        self._seq = itertools.count()
        self.virtual_now = 0
        self.real_start = time.monotonic_ns()
        self.all_tasks: list = []
        self.blocked: set = set()
        self.on_deadlock: Optional[Callable[[], bool]] = None
        self.switches = 0

    # ------------------------------------------------------------------ time
    def now(self) -> int:
        if self.clock == "virtual":
            return self.virtual_now
        return time.monotonic_ns() - self.real_start

    def add_timer(self, deadline: int, callback: Callable[[], None]) -> Timer:
        t = Timer(deadline, next(self._seq), callback)
        heapq.heappush(self.timers, t)
        return t

    def _fire_due_timers(self) -> bool:
        fired = False
        now = self.now()
        while self.timers and (self.timers[0].cancelled or self.timers[0].deadline <= now):
            t = heapq.heappop(self.timers)
            if not t.cancelled:
                t.cancelled = True
                t.callback()
                fired = True
        return fired

    def _next_timer(self) -> Optional[Timer]:
        while self.timers and self.timers[0].cancelled:
            heapq.heappop(self.timers)
        return self.timers[0] if self.timers else None

    # ------------------------------------------------------------------ ready queue
    def make_ready(self, task) -> None:
        if task.in_ready:
            return
        task.in_ready = True
        self.blocked.discard(task)
        self.ready.append(task)

    def _pick(self):
        if self.schedule == "random" and len(self.ready) > 1:
            i = self.rng.randrange(len(self.ready))
            self.ready.rotate(-i)
            t = self.ready.popleft()
            self.ready.rotate(i)
        else:
            t = self.ready.popleft()
        t.in_ready = False
        return t

    def choose_index(self, n: int) -> int:
        """Seeded tie-break helper for select/receiver choice in random mode."""
        if self.schedule == "random" and n > 1:
            return self.rng.randrange(n)
        return 0

    # ------------------------------------------------------------------ blocking
    def block_current(self) -> None:
        """Called on a task thread: suspend the current task until made ready."""
        task = self.current
        self.blocked.add(task)
        task.coro.switch_out()

    def yield_current(self) -> None:
        """Called on a task thread: go to the back of the ready queue."""
        task = self.current
        self.make_ready(task)
        task.coro.switch_out()

    # ------------------------------------------------------------------ main loop
    def run(self, root) -> None:
        self.make_ready(root)
        while True:
            if self.ready:
                task = self._pick()
                self.current = task
                self.switches += 1
                task.coro.switch_in()
                self.current = None
                if self.timers:
                    self._fire_due_timers()
                continue
            if root.done:
                return
            if self._fire_due_timers():
                continue
            nxt = self._next_timer()
            if nxt is not None:
                if self.clock == "virtual":
                    self.virtual_now = max(self.virtual_now, nxt.deadline)
                else:
                    delay = (nxt.deadline - self.now()) / 1e9
                    if delay > 0:
                        time.sleep(min(delay, 0.5))
                self._fire_due_timers()
                continue
            # Nothing ready, no timers: every live task is blocked.
            if self.on_deadlock is not None and self.on_deadlock():
                continue
            return
