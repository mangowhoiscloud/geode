"""Lane Queue — concurrency control with named lanes.

Inspired by OpenClaw's Lane Queue system:
- Session Lane: serial per session (same session requests queued)
- Global Lane: max N concurrent across all sessions
- Named lanes with independent maxConcurrent and timeout settings
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 4
DEFAULT_TIMEOUT_S = 300.0  # 5 minutes


class Lane:
    """A single concurrency lane with semaphore-based limiting.

    Usage:
        lane = Lane("global", max_concurrent=4)
        with lane.acquire("ip:berserk:analysis"):
            # ... do work ...
    """

    def __init__(
        self,
        name: str,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.name = name
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stats = _LaneStats()

    @property
    def stats(self) -> _LaneStats:
        return self._stats

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def available(self) -> int:
        return self.max_concurrent - self.active_count

    @contextmanager
    def acquire(self, key: str) -> Generator[None, None, None]:
        """Acquire a slot in this lane. Blocks if at capacity.

        Args:
            key: Identifier for the work item.

        Raises:
            TimeoutError: If slot not acquired within timeout.
        """
        acquired = self._semaphore.acquire(timeout=self.timeout_s)
        if not acquired:
            self._stats.inc_timeouts()
            raise TimeoutError(
                f"Lane '{self.name}' timeout after {self.timeout_s}s "
                f"(max_concurrent={self.max_concurrent})"
            )

        with self._lock:
            self._active[key] = time.time()
        self._stats.inc_acquired()

        log.debug(
            "Lane '%s' acquired by %s (%d/%d active)",
            self.name,
            key,
            self.active_count,
            self.max_concurrent,
        )

        try:
            yield
        finally:
            with self._lock:
                self._active.pop(key, None)
            self._stats.inc_released()
            self._semaphore.release()
            log.debug("Lane '%s' released by %s", self.name, key)

    def acquire_timeout(self, key: str, timeout_s: float) -> bool:
        """Blocking acquire with explicit timeout (for IsolatedRunner).

        Returns True if a slot was acquired within *timeout_s*.
        Caller must call :meth:`manual_release` when done.
        """
        acquired = self._semaphore.acquire(timeout=timeout_s)
        if not acquired:
            self._stats.inc_timeouts()
            return False
        with self._lock:
            self._active[key] = time.time()
        self._stats.inc_acquired()
        log.debug(
            "Lane '%s' acquire_timeout(%.1fs) by %s (%d/%d active)",
            self.name,
            timeout_s,
            key,
            self.active_count,
            self.max_concurrent,
        )
        return True

    def try_acquire(self, key: str) -> bool:
        """Non-blocking acquire for async patterns (e.g. scheduler).

        Returns True if a slot was acquired, False if lane is full.
        Caller must call :meth:`manual_release` when done.
        """
        acquired = self._semaphore.acquire(timeout=0)
        if not acquired:
            self._stats.inc_timeouts()
            return False
        with self._lock:
            self._active[key] = time.time()
        self._stats.inc_acquired()
        log.debug(
            "Lane '%s' try_acquire by %s (%d/%d active)",
            self.name,
            key,
            self.active_count,
            self.max_concurrent,
        )
        return True

    def manual_release(self, key: str) -> None:
        """Release a slot acquired via :meth:`try_acquire`."""
        with self._lock:
            self._active.pop(key, None)
        self._stats.inc_released()
        self._semaphore.release()
        log.debug("Lane '%s' manual_release by %s", self.name, key)

    def get_active(self) -> dict[str, float]:
        """Get active work items with elapsed time."""
        now = time.time()
        with self._lock:
            return {k: now - v for k, v in self._active.items()}


class LaneQueue:
    """Multi-lane concurrency control system.

    Usage:
        queue = LaneQueue()
        queue.add_lane("session", max_concurrent=1)  # Serial per session
        queue.add_lane("global", max_concurrent=4)    # Max 4 concurrent

        with queue.acquire_all("ip:berserk:analysis", ["session", "global"]):
            # ... do work (holds both lanes) ...
    """

    def __init__(self) -> None:
        self._lanes: dict[str, Lane] = {}

    def add_lane(
        self,
        name: str,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> Lane:
        """Add a named lane."""
        lane = Lane(name, max_concurrent=max_concurrent, timeout_s=timeout_s)
        self._lanes[name] = lane
        return lane

    def get_lane(self, name: str) -> Lane | None:
        return self._lanes.get(name)

    def list_lanes(self) -> list[str]:
        return list(self._lanes.keys())

    @contextmanager
    def acquire_all(
        self,
        key: str,
        lane_names: list[str],
    ) -> Generator[None, None, None]:
        """Acquire slots in multiple lanes (in order). Releases all on exit.

        Args:
            key: Work item identifier.
            lane_names: Lane names to acquire in order.
        """
        acquired_sems: list[Lane] = []
        try:
            for name in lane_names:
                lane = self._lanes.get(name)
                if lane is None:
                    raise KeyError(f"Lane '{name}' not found")
                if not lane._semaphore.acquire(timeout=lane.timeout_s):
                    raise TimeoutError(
                        f"Lane '{name}' timeout after {lane.timeout_s}s "
                        f"(max_concurrent={lane.max_concurrent})"
                    )
                acquired_sems.append(lane)
                with lane._lock:
                    lane._active[key] = time.time()
                lane._stats.inc_acquired()

            yield

        finally:
            for lane in reversed(acquired_sems):
                lane._semaphore.release()
            for lane in reversed(acquired_sems):
                with lane._lock:
                    lane._active.pop(key, None)
                lane._stats.inc_released()

    def status(self) -> dict[str, Any]:
        """Get status of all lanes."""
        return {
            name: {
                "active": lane.active_count,
                "max": lane.max_concurrent,
                "available": lane.available,
            }
            for name, lane in self._lanes.items()
        }


class _LaneStats:
    """Track lane statistics."""

    def __init__(self) -> None:
        self.acquired: int = 0
        self.released: int = 0
        self.timeouts: int = 0
        self._lock = threading.Lock()

    def inc_acquired(self) -> None:
        with self._lock:
            self.acquired += 1

    def inc_released(self) -> None:
        with self._lock:
            self.released += 1

    def inc_timeouts(self) -> None:
        with self._lock:
            self.timeouts += 1

    def to_dict(self) -> dict[str, int]:
        with self._lock:
            return {
                "acquired": self.acquired,
                "released": self.released,
                "timeouts": self.timeouts,
            }
