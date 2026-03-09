"""Coalescing — debounce duplicate execution requests.

Inspired by OpenClaw's heartbeat-wake coalescing:
- 250ms window to merge duplicate wake requests
- Thread-safe via threading.Lock
- Callback fires once after window expires with no new requests
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)


class CoalescingQueue:
    """Debounce duplicate requests within a time window.

    Usage:
        queue = CoalescingQueue(window_ms=250)

        def on_fire(key, data):
            print(f"Executing {key}")

        queue.submit("ip:berserk:analysis", on_fire, {"ip": "Berserk"})
        queue.submit("ip:berserk:analysis", on_fire, {"ip": "Berserk"})
        # → on_fire called ONCE after 250ms (second submit resets timer)
    """

    def __init__(self, window_ms: float = 250.0) -> None:
        self._window_s = window_ms / 1000.0
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._stats = _CoalescingStats()

    @property
    def stats(self) -> _CoalescingStats:
        return self._stats

    def submit(
        self,
        key: str,
        callback: Any,
        data: Any = None,
    ) -> bool:
        """Submit a request. Returns True if new, False if coalesced.

        Args:
            key: Deduplication key (e.g. session key).
            callback: Called as callback(key, data) after window expires.
            data: Arbitrary data passed to callback.
        """
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
                self._stats.coalesced += 1
                coalesced = True
                log.debug("Coalesced request for key=%s", key)
            else:
                coalesced = False

            timer = threading.Timer(
                self._window_s,
                self._fire,
                args=(key, callback, data),
            )
            timer.daemon = True
            self._timers[key] = timer
            timer.start()
            self._stats.submitted += 1

        return not coalesced

    def _fire(self, key: str, callback: Any, data: Any) -> None:
        """Execute the callback after the debounce window."""
        with self._lock:
            self._timers.pop(key, None)

        try:
            callback(key, data)
            self._stats.executed += 1
        except Exception:
            self._stats.errors += 1
            log.exception("Coalescing callback failed for key=%s", key)

    def cancel(self, key: str) -> bool:
        """Cancel a pending request. Returns True if found."""
        with self._lock:
            timer = self._timers.pop(key, None)
            if timer is not None:
                timer.cancel()
                return True
        return False

    def cancel_all(self) -> int:
        """Cancel all pending requests. Returns count cancelled."""
        with self._lock:
            count = len(self._timers)
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        return count

    @property
    def pending_count(self) -> int:
        """Number of pending (not yet fired) requests."""
        with self._lock:
            return len(self._timers)


class _CoalescingStats:
    """Track coalescing statistics."""

    def __init__(self) -> None:
        self.submitted: int = 0
        self.coalesced: int = 0
        self.executed: int = 0
        self.errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "submitted": self.submitted,
            "coalesced": self.coalesced,
            "executed": self.executed,
            "errors": self.errors,
        }
