"""Suspend-aware active-runtime deadlines."""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass, field

_active: weakref.WeakSet[SuspendAwareDeadline] = weakref.WeakSet()
_lock = threading.Lock()


@dataclass(eq=False)
class SuspendAwareDeadline:
    """A timeout budget that discounts likely process suspension."""

    budget_seconds: float | None
    poll_interval: float = 0.1
    freeze_grace_seconds: float = 30.0
    _started: float = field(default_factory=time.monotonic, init=False)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.budget_seconds is not None:
            self.budget_seconds = max(0.0, float(self.budget_seconds))
        with _lock:
            _active.add(self)

    def __enter__(self) -> SuspendAwareDeadline:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with _lock:
            _active.discard(self)

    def credit_poll_sleep(self, slept: float) -> float:
        overrun = max(0.0, slept - self.poll_interval)
        if overrun > self.freeze_grace_seconds:
            self._started += overrun
            return overrun
        return 0.0

    def credit_process_suspend(self, frozen_seconds: float) -> None:
        if frozen_seconds > self.freeze_grace_seconds:
            self._started += frozen_seconds - self.freeze_grace_seconds

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._started)

    def expired(self) -> bool:
        return self.budget_seconds is not None and self.elapsed() >= self.budget_seconds

    def remaining(self) -> float:
        if self.budget_seconds is None:
            return float("inf")
        return max(0.0, self.budget_seconds - self.elapsed())


def credit_active_deadlines_process_suspend(frozen_seconds: float) -> None:
    """Credit all active deadlines after an external suspend signal."""

    with _lock:
        deadlines = tuple(_active)
    for deadline in deadlines:
        deadline.credit_process_suspend(frozen_seconds)
