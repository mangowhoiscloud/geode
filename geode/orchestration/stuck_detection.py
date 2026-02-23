"""Stuck Detection — auto-release long-running tasks.

Inspired by OpenClaw's stuck job detection:
- Track running_since_ms per session key
- Auto-release after configurable timeout (default 2 hours)
- Integration with HookSystem for notifications
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 7200.0  # 2 hours
DEFAULT_CHECK_INTERVAL_S = 60.0  # Check every minute


class StuckDetector:
    """Detect and release stuck (long-running) pipeline executions.

    Usage:
        detector = StuckDetector(timeout_s=7200)
        detector.mark_running("ip:berserk:analysis")
        # ... later, if still running after 2h ...
        stuck = detector.check_stuck()
        # → ["ip:berserk:analysis"]
    """

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        check_interval_s: float = DEFAULT_CHECK_INTERVAL_S,
        on_stuck: Any | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._check_interval = check_interval_s
        self._on_stuck = on_stuck
        self._running_jobs: dict[str, _JobRecord] = {}
        self._lock = threading.Lock()
        self._monitor_thread: threading.Thread | None = None
        self._monitoring = False
        self._stats = _StuckStats()

    @property
    def stats(self) -> _StuckStats:
        return self._stats

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    def mark_running(self, session_key: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Mark a session as running."""
        with self._lock:
            self._running_jobs[session_key] = _JobRecord(
                session_key=session_key,
                started_at=time.time(),
                metadata=metadata or {},
            )
        log.debug("Marked running: %s", session_key)

    def mark_completed(self, session_key: str) -> bool:
        """Mark a session as completed. Returns True if it was tracked."""
        with self._lock:
            removed = self._running_jobs.pop(session_key, None)
        if removed:
            elapsed = time.time() - removed.started_at
            log.debug("Marked completed: %s (ran %.1fs)", session_key, elapsed)
        return removed is not None

    def check_stuck(self) -> list[str]:
        """Check for stuck jobs and auto-release them.

        Returns list of session keys that were stuck and released.
        """
        now = time.time()
        stuck_keys: list[str] = []

        with self._lock:
            for key, record in list(self._running_jobs.items()):
                elapsed = now - record.started_at
                if elapsed >= self._timeout_s:
                    stuck_keys.append(key)
                    log.warning(
                        "Stuck job detected: %s (running %.0fs, timeout %.0fs)",
                        key,
                        elapsed,
                        self._timeout_s,
                    )

            # Release stuck jobs
            for key in stuck_keys:
                self._running_jobs.pop(key, None)
                self._stats.released += 1

        # Notify callback
        if stuck_keys and self._on_stuck is not None:
            for key in stuck_keys:
                try:
                    self._on_stuck(key)
                except Exception:
                    log.exception("Stuck callback failed for %s", key)

        self._stats.checks += 1
        return stuck_keys

    def get_running(self) -> dict[str, float]:
        """Get all running jobs with elapsed time in seconds."""
        now = time.time()
        with self._lock:
            return {key: now - rec.started_at for key, rec in self._running_jobs.items()}

    @property
    def running_count(self) -> int:
        with self._lock:
            return len(self._running_jobs)

    def start_monitor(self) -> None:
        """Start background monitoring thread."""
        if self._monitoring:
            return
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="stuck-detector",
        )
        self._monitor_thread.start()
        log.info("StuckDetector monitor started (timeout=%.0fs)", self._timeout_s)

    def stop_monitor(self) -> None:
        """Stop background monitoring thread."""
        self._monitoring = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None

    @property
    def is_monitoring(self) -> bool:
        return self._monitoring

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._monitoring:
            self.check_stuck()
            time.sleep(self._check_interval)


class _JobRecord:
    """Internal record for a running job."""

    __slots__ = ("session_key", "started_at", "metadata")

    def __init__(self, *, session_key: str, started_at: float, metadata: dict[str, Any]) -> None:
        self.session_key = session_key
        self.started_at = started_at
        self.metadata = metadata


class _StuckStats:
    """Track stuck detection statistics."""

    def __init__(self) -> None:
        self.checks: int = 0
        self.released: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"checks": self.checks, "released": self.released}
