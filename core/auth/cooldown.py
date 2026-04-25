"""Cooldown Tracker — per-profile error tracking and backoff management.

Provides a standalone tracker that can be used independently of ProfileRotator
for simpler use cases (e.g. single-key cooldown on rate limits).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.auth.rotation import calculate_cooldown_ms


@dataclass
class CooldownEntry:
    """Tracks error state for a single key/profile."""

    error_count: int = 0
    cooldown_until: float = 0.0
    last_error: str = ""
    last_error_at: float = 0.0

    @property
    def is_cooling_down(self) -> bool:
        return time.time() < self.cooldown_until

    @property
    def remaining_ms(self) -> int:
        remaining = self.cooldown_until - time.time()
        return max(0, int(remaining * 1000))


class CooldownTracker:
    """Track cooldown state for multiple keys/profiles.

    Usage:
        tracker = CooldownTracker()
        tracker.record_failure("sk-ant-xxx", "rate_limit")
        if tracker.is_available("sk-ant-xxx"):
            # safe to use
    """

    def __init__(self) -> None:
        self._entries: dict[str, CooldownEntry] = {}

    def record_failure(self, key: str, error_type: str = "") -> int:
        """Record a failure. Returns cooldown duration in ms."""
        entry = self._entries.setdefault(key, CooldownEntry())
        entry.error_count += 1
        entry.last_error = error_type
        entry.last_error_at = time.time()
        cooldown_ms = calculate_cooldown_ms(entry.error_count)
        entry.cooldown_until = time.time() + cooldown_ms / 1000.0
        return cooldown_ms

    def record_success(self, key: str) -> None:
        """Record a success — reset error state."""
        entry = self._entries.get(key)
        if entry:
            entry.error_count = 0
            entry.cooldown_until = 0.0
            entry.last_error = ""

    def is_available(self, key: str) -> bool:
        """Check if a key is available (not cooling down)."""
        entry = self._entries.get(key)
        if entry is None:
            return True
        return not entry.is_cooling_down

    def get_remaining_ms(self, key: str) -> int:
        """Get remaining cooldown time in ms. Returns 0 if available."""
        entry = self._entries.get(key)
        if entry is None:
            return 0
        return entry.remaining_ms

    def get_entry(self, key: str) -> CooldownEntry | None:
        return self._entries.get(key)

    def clear(self, key: str | None = None) -> None:
        if key:
            self._entries.pop(key, None)
        else:
            self._entries.clear()
