"""Managed credential cache for external credential owners.

The Codex CLI reader uses a thread-safe, TTL-based cache with file snapshot
invalidation. This module keeps that lifecycle independent from the provider.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _credential_path(value: str | Path | Callable[[], Path]) -> Path:
    path = value() if callable(value) else Path(value)
    return path if path.is_absolute() else Path.home() / path


def read_json_credentials_file(path: str | Path) -> dict[str, Any] | None:
    """Read and parse an absolute path or a path relative to ``$HOME``.

    Returns the parsed dict, or ``None`` if the file is missing, unreadable,
    invalid JSON, or not a JSON object. Callers extract the field they need.
    """
    try:
        raw = _credential_path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


_DEFAULT_TTL_S = 900  # 15 min (OpenClaw EXTERNAL_CLI_SYNC_TTL_MS)


class CredentialCache:
    """Thread-safe credential cache with TTL and a file identity fingerprint.

    Args:
        file_path: Path relative to $HOME for mtime tracking.
        ttl_s: Cache lifetime in seconds (default 15 min).
    """

    def __init__(
        self,
        file_path: str | Path | Callable[[], Path],
        ttl_s: float = _DEFAULT_TTL_S,
    ) -> None:
        self._file_path = file_path
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._value: Any = None
        self._read_at: float = 0.0
        self._snapshot: tuple[Path, int, int, int, int] | None = None

    def file_path(self) -> Path:
        return _credential_path(self._file_path)

    def _fingerprint(self) -> tuple[Path, int, int, int, int] | None:
        path = self.file_path()
        try:
            stat = path.stat()
        except OSError:
            return None
        return path, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def read(self, loader: Callable[[], Any], *, force_refresh: bool = False) -> Any:
        """Serialize reads and invalidation; cache only an unchanged file snapshot."""
        with self._lock:
            before = self._fingerprint()
            if (
                not force_refresh
                and self._value is not None
                and before is not None
                and before == self._snapshot
                and time.monotonic() - self._read_at < self._ttl_s
            ):
                return self._value
            for _ in range(2):
                if before is None:
                    break
                value = loader()
                after = self._fingerprint()
                if before == after:
                    self._value = value
                    self._snapshot = after
                    self._read_at = time.monotonic()
                    return value
                before = after
            self._value = None
            self._snapshot = None
            return None

    def invalidate(self) -> None:
        """Force the next read to bypass cache, including an in-flight read."""
        with self._lock:
            self._value = None
            self._read_at = 0.0
            self._snapshot = None


def refresh_managed_token(
    provider_name: str,
    read_fn: Any,
    profile: Any,
) -> bool:
    """Re-read token from managed storage and update profile if changed.

    Args:
        provider_name: Display name for logging (for example, "Codex CLI").
        read_fn: Callable that returns credentials dict with "access_token" key.
        profile: Profile object with .key and .expires_at attributes.

    Returns:
        True if token was updated, False otherwise.
    """
    previous = (profile.key, profile.refresh_token, profile.expires_at)
    creds = read_fn(force_refresh=True)
    if not creds:
        log.warning("%s credentials unavailable for refresh", provider_name)
        return False

    if previous != (profile.key, profile.refresh_token, profile.expires_at):
        log.debug("%s profile changed during refresh; discarding stale read", provider_name)
        return False

    new_token = creds["access_token"]
    if new_token != profile.key:
        profile.key = new_token
        profile.expires_at = creds.get("expires_at", 0.0)
        profile.refresh_token = creds.get("refresh_token", "")
        log.info("%s OAuth token refreshed (managed)", provider_name)
        return True

    log.debug("%s token unchanged after re-read", provider_name)
    return False
