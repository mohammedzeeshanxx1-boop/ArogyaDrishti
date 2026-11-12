"""Simulated clock: measurement time advances at `speed` x wall time and can pause."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Callable


class SimClock:
    def __init__(self, start: datetime, speed: float, monotonic: Callable[[], float] = time.monotonic):
        if speed <= 0:
            raise ValueError("speed must be > 0")
        self.start = start
        self.speed = speed
        self._mono = monotonic
        self._elapsed_sim = 0.0          # simulated seconds accumulated while running
        self._running_since: float | None = None

    @property
    def running(self) -> bool:
        return self._running_since is not None

    def resume(self) -> None:
        if self._running_since is None:
            self._running_since = self._mono()

    def pause(self) -> None:
        if self._running_since is not None:
            self._elapsed_sim += (self._mono() - self._running_since) * self.speed
            self._running_since = None

    def elapsed(self) -> float:
        """Simulated seconds since start."""
        live = (self._mono() - self._running_since) * self.speed if self._running_since is not None else 0.0
        return self._elapsed_sim + live

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.elapsed())

    def wall_seconds_until(self, target: datetime) -> float:
        """Wall-clock seconds until simulated time reaches target (0 if already there)."""
        return max(0.0, (target - self.now()).total_seconds() / self.speed)
