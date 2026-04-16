"""Managed credential cache — shared TTL + mtime fingerprint pattern.

Both Claude Code and Codex CLI credential readers use an identical
cache pattern: thread-safe, TTL-based, with file mtime invalidation.
This module extracts that shared infrastructure.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TTL_S = 900  # 15 min (OpenClaw EXTERNAL_CLI_SYNC_TTL_MS)


class CredentialCache:
    """Thread-safe credential cache with TTL and file mtime fingerprint.

    Args:
        file_path: Path relative to $HOME for mtime tracking.
        ttl_s: Cache lifetime in seconds (default 15 min).
    """

    def __init__(self, file_path: str, ttl_s: float = _DEFAULT_TTL_S) -> None:
        self._file_path = file_path
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._value: Any = None
        self._read_at: float = 0.0
        self._mtime: float = 0.0

    def get_file_mtime(self) -> float:
        """Get mtime of the tracked file (0.0 if not found)."""
        try:
            return (Path.home() / self._file_path).stat().st_mtime
        except OSError:
            return 0.0

    def is_valid(self) -> bool:
        """Check if cached value is still valid. Must be called under lock."""
        if self._value is None:
            return False
        if (time.time() - self._read_at) >= self._ttl_s:
            return False
        current_mtime = self.get_file_mtime()
        return not (current_mtime > 0 and current_mtime != self._mtime)

    def get_if_valid(self, *, force_refresh: bool = False) -> tuple[bool, Any]:
        """Return (hit, value). If hit=True, value is the cached credential."""
        with self._lock:
            if not force_refresh and self.is_valid():
                return True, self._value
        return False, None

    def update(self, value: Any, mtime: float) -> None:
        """Store a new value in cache."""
        with self._lock:
            self._value = value
            self._read_at = time.time()
            self._mtime = mtime

    def invalidate(self) -> None:
        """Force next read to bypass cache."""
        with self._lock:
            self._value = None
            self._read_at = 0.0
            self._mtime = 0.0


def refresh_managed_token(
    provider_name: str,
    read_fn: Any,
    profile: Any,
) -> bool:
    """Re-read token from managed storage and update profile if changed.

    Args:
        provider_name: Display name for logging ("Claude Code", "Codex CLI").
        read_fn: Callable that returns credentials dict with "access_token" key.
        profile: Profile object with .key and .expires_at attributes.

    Returns:
        True if token was updated, False otherwise.
    """
    creds = read_fn(force_refresh=True)
    if not creds:
        log.warning("%s credentials unavailable for refresh", provider_name)
        return False

    new_token = creds["access_token"]
    if new_token != profile.key:
        profile.key = new_token
        profile.expires_at = creds.get("expires_at", 0.0)
        log.info("%s OAuth token refreshed (managed)", provider_name)
        return True

    log.debug("%s token unchanged after re-read", provider_name)
    return False
