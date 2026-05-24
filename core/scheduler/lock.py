"""O_EXCL file-based scheduler lock with PID liveness probe (claude-code pattern)."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


class SchedulerLock:
    """Cross-platform file-based lock using O_EXCL atomic creation.

    Lock file contains ``{"pid": N, "acquired_at": T, "session_id": S}``
    for liveness probing and idempotent re-acquire on session restart.
    """

    STALE_TIMEOUT_S: float = 5.0

    def __init__(self, lock_path: Path, session_id: str = "") -> None:
        self._lock_path = lock_path
        self._session_id = session_id or f"pid-{os.getpid()}"
        self._acquired = False

    def _lock_content(self) -> str:
        return json.dumps(
            {
                "pid": os.getpid(),
                "acquired_at": time.time(),
                "session_id": self._session_id,
            }
        )

    def acquire(self, timeout_s: float = 10.0) -> bool:
        """Try to acquire the lock, probing for stale owners."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                try:
                    os.write(fd, self._lock_content().encode())
                finally:
                    os.close(fd)
                self._acquired = True
                return True
            except FileExistsError:
                # Lock file exists — check if owner is alive or same session
                reclaim_result = self._try_reclaim()
                if reclaim_result == "idempotent":
                    # Same session re-acquired — lock file updated in place
                    self._acquired = True
                    return True
                if reclaim_result == "reclaimed":
                    continue  # Stale lock removed, retry O_EXCL
                time.sleep(0.2)
        return False

    def release(self) -> None:
        """Release the lock by removing the lock file."""
        if self._acquired:
            with contextlib.suppress(OSError):
                self._lock_path.unlink(missing_ok=True)
            self._acquired = False

    def _try_reclaim(self) -> str:
        """Check if the current lock owner is dead and reclaim if so.

        Returns:
            "idempotent" — same session re-acquired (lock file updated in place)
            "reclaimed"  — stale lock removed (caller should retry O_EXCL)
            ""           — lock is held by another live session
        """
        try:
            with open(self._lock_path, encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("pid", -1)
            acquired_at = data.get("acquired_at", 0.0)
            owner_session = data.get("session_id", "")
            age = time.time() - acquired_at

            # Idempotent: same session, new PID (restart/resume)
            if owner_session and owner_session == self._session_id:
                try:
                    self._lock_path.write_text(self._lock_content())
                    return "idempotent"
                except OSError:
                    return ""

            if not _is_pid_alive(pid) or age > 600:
                # Owner dead or lock very old — reclaim
                try:
                    self._lock_path.unlink()
                    return "reclaimed"
                except FileNotFoundError:
                    return "reclaimed"
                except OSError:
                    return ""
        except (json.JSONDecodeError, OSError):
            # Corrupt lock file — remove and retry
            try:
                self._lock_path.unlink()
                return "reclaimed"
            except OSError:
                return ""
        return ""

    def __enter__(self) -> SchedulerLock:
        if not self.acquire():
            raise TimeoutError(f"Could not acquire scheduler lock: {self._lock_path}")
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()
