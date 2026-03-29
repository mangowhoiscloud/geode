"""Lane Queue — concurrency control with named lanes.

Inspired by OpenClaw's Lane Queue system:
- SessionLane: per-session-key serialization (same key → serial, different keys → parallel)
- Lane (Global): max N concurrent across all sessions
- All execution paths: SessionLane.acquire(key) → Global.acquire(key) → Execute

OpenClaw defect fixes:
- max_sessions cap prevents unbounded session key creation
- cleanup_idle() evicts sessions idle beyond timeout
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 4
DEFAULT_TIMEOUT_S = 300.0  # 5 minutes


class Lane:
    """A single concurrency lane with semaphore-based limiting.

    Usage:
        lane = Lane("global", max_concurrent=8)
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

    # --- Internal: for LaneQueue.acquire_all() duck-typing ----

    def _raw_acquire(self, key: str) -> bool:
        """Acquire slot using lane's default timeout. For acquire_all()."""
        acquired = self._semaphore.acquire(timeout=self.timeout_s)
        if not acquired:
            self._stats.inc_timeouts()
            return False
        with self._lock:
            self._active[key] = time.time()
        self._stats.inc_acquired()
        return True

    def _raw_release(self, key: str) -> None:
        """Release slot. For acquire_all()."""
        self._semaphore.release()
        with self._lock:
            self._active.pop(key, None)
        self._stats.inc_released()


# ---------------------------------------------------------------------------
# SessionLane — per-key serialization (OpenClaw Session Lane pattern)
# ---------------------------------------------------------------------------


@dataclass
class _SessionEntry:
    """Per-session-key state: a Semaphore(1) + metadata."""

    semaphore: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(1))
    last_used: float = field(default_factory=time.time)
    held: bool = False


class SessionLane:
    """Per-session-key serialization lane.

    Each unique session key gets its own ``Semaphore(1)``.  Same key →
    serial.  Different keys → fully parallel.  Bounded by *max_sessions*
    to prevent unbounded memory growth (OpenClaw defect fix).

    API matches :class:`Lane` for duck-typing in :meth:`LaneQueue.acquire_all`.
    """

    def __init__(
        self,
        *,
        max_sessions: int = 256,
        idle_timeout_s: float = 300.0,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.name = "session"
        self.max_sessions = max_sessions
        self.idle_timeout_s = idle_timeout_s
        self.timeout_s = timeout_s
        self._sessions: dict[str, _SessionEntry] = {}
        self._lock = threading.Lock()
        self._stats = _LaneStats()

    @property
    def stats(self) -> _LaneStats:
        return self._stats

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._sessions.values() if e.held)

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # --- Context manager (matches Lane.acquire) ---

    @contextmanager
    def acquire(self, key: str) -> Generator[None, None, None]:
        """Acquire the per-key semaphore. Blocks if same key is active."""
        entry = self._get_or_create(key)
        acquired = entry.semaphore.acquire(timeout=self.timeout_s)
        if not acquired:
            self._stats.inc_timeouts()
            raise TimeoutError(f"SessionLane timeout for key '{key}' after {self.timeout_s}s")
        entry.held = True
        entry.last_used = time.time()
        self._stats.inc_acquired()
        try:
            yield
        finally:
            entry.held = False
            entry.last_used = time.time()
            entry.semaphore.release()
            self._stats.inc_released()

    # --- Non-blocking (matches Lane.try_acquire) ---

    def try_acquire(self, key: str) -> bool:
        """Non-blocking acquire. Returns True if acquired."""
        entry = self._get_or_create(key)
        acquired = entry.semaphore.acquire(timeout=0)
        if not acquired:
            self._stats.inc_timeouts()
            return False
        entry.held = True
        entry.last_used = time.time()
        self._stats.inc_acquired()
        return True

    # --- Blocking with timeout (matches Lane.acquire_timeout) ---

    def acquire_timeout(self, key: str, timeout_s: float) -> bool:
        """Blocking acquire with explicit timeout."""
        entry = self._get_or_create(key)
        acquired = entry.semaphore.acquire(timeout=timeout_s)
        if not acquired:
            self._stats.inc_timeouts()
            return False
        entry.held = True
        entry.last_used = time.time()
        self._stats.inc_acquired()
        return True

    # --- Manual release (matches Lane.manual_release) ---

    def manual_release(self, key: str) -> None:
        """Release after try_acquire/acquire_timeout."""
        with self._lock:
            entry = self._sessions.get(key)
        if entry is not None:
            entry.held = False
            entry.last_used = time.time()
            entry.semaphore.release()
            self._stats.inc_released()

    # --- Observability ---

    def get_active(self) -> dict[str, float]:
        """Return held sessions with elapsed time since last use."""
        now = time.time()
        with self._lock:
            return {k: now - e.last_used for k, e in self._sessions.items() if e.held}

    # --- Idle cleanup (OpenClaw defect fix) ---

    def cleanup_idle(self) -> int:
        """Evict sessions idle beyond *idle_timeout_s*. Returns count evicted."""
        with self._lock:
            return self._evict_idle_locked()

    # --- Internal: for LaneQueue.acquire_all() duck-typing ---

    def _raw_acquire(self, key: str) -> bool:
        entry = self._get_or_create(key)
        acquired = entry.semaphore.acquire(timeout=self.timeout_s)
        if not acquired:
            self._stats.inc_timeouts()
            return False
        entry.held = True
        entry.last_used = time.time()
        self._stats.inc_acquired()
        return True

    def _raw_release(self, key: str) -> None:
        with self._lock:
            entry = self._sessions.get(key)
        if entry is not None:
            entry.held = False
            entry.last_used = time.time()
            entry.semaphore.release()
            self._stats.inc_released()

    # --- Internal helpers ---

    def _get_or_create(self, key: str) -> _SessionEntry:
        with self._lock:
            entry = self._sessions.get(key)
            if entry is not None:
                return entry
            if len(self._sessions) >= self.max_sessions:
                self._evict_idle_locked()
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError(
                    f"SessionLane full ({self.max_sessions} sessions, no idle sessions to evict)"
                )
            entry = _SessionEntry()
            self._sessions[key] = entry
            return entry

    def _evict_idle_locked(self) -> int:
        """Evict idle sessions. Must hold self._lock."""
        now = time.time()
        to_remove = [
            k
            for k, e in self._sessions.items()
            if not e.held and (now - e.last_used) > self.idle_timeout_s
        ]
        for k in to_remove:
            del self._sessions[k]
        if to_remove:
            log.debug("SessionLane: evicted %d idle sessions", len(to_remove))
        return len(to_remove)


class LaneQueue:
    """Multi-lane concurrency control system with per-key session serialization.

    Usage (OpenClaw pattern: SessionLane → Global Lane → Execute)::

        queue = LaneQueue()
        queue.set_session_lane(SessionLane(max_sessions=256))
        queue.add_lane("global", max_concurrent=8)

        with queue.acquire_all("gateway:slack:C123:U456", ["session", "global"]):
            # ... do work (session serialized + global gated) ...
    """

    def __init__(self) -> None:
        self._lanes: dict[str, Lane] = {}
        self._session_lane: SessionLane | None = None

    def set_session_lane(self, session_lane: SessionLane) -> None:
        """Register the SessionLane for per-key serialization."""
        self._session_lane = session_lane

    @property
    def session_lane(self) -> SessionLane | None:
        """The SessionLane, if registered."""
        return self._session_lane

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
        names = list(self._lanes.keys())
        if self._session_lane is not None:
            names.insert(0, "session")
        return names

    @contextmanager
    def acquire_all(
        self,
        key: str,
        lane_names: list[str],
    ) -> Generator[None, None, None]:
        """Acquire slots in multiple lanes (in order). Releases all on exit.

        Supports both :class:`Lane` and :class:`SessionLane` via duck-typed
        ``_raw_acquire`` / ``_raw_release`` methods.

        Args:
            key: Work item identifier (session key).
            lane_names: Lane names to acquire in order.
                Use ``"session"`` for the SessionLane.
        """
        acquired: list[Lane | SessionLane] = []
        try:
            for name in lane_names:
                if name == "session":
                    if self._session_lane is None:
                        continue  # no session lane registered, skip
                    if not self._session_lane._raw_acquire(key):
                        raise TimeoutError(f"SessionLane timeout for key '{key}'")
                    acquired.append(self._session_lane)
                else:
                    lane = self._lanes.get(name)
                    if lane is None:
                        raise KeyError(f"Lane '{name}' not found")
                    if not lane._raw_acquire(key):
                        raise TimeoutError(
                            f"Lane '{name}' timeout after {lane.timeout_s}s "
                            f"(max_concurrent={lane.max_concurrent})"
                        )
                    acquired.append(lane)

            yield

        finally:
            for item in reversed(acquired):
                item._raw_release(key)

    def status(self) -> dict[str, Any]:
        """Get status of all lanes."""
        result: dict[str, Any] = {}
        if self._session_lane is not None:
            result["session"] = {
                "active": self._session_lane.active_count,
                "sessions": self._session_lane.session_count,
                "max_sessions": self._session_lane.max_sessions,
            }
        for name, lane in self._lanes.items():
            result[name] = {
                "active": lane.active_count,
                "max": lane.max_concurrent,
                "available": lane.available,
            }
        return result


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
