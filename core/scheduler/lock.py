"""Cross-process scheduler store lock on a separate lock-file inode.

The store is replaced by ``os.replace`` on every write, so it cannot carry the
lock. :func:`core.memory.atomic_write.exclusive_file_lock` excludes threads and
processes and is released by the kernel when its holder dies, so there is no
stale-owner heuristic to get wrong.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from core.memory.atomic_write import exclusive_file_lock


class SchedulerLock:
    """Exclusive advisory lock held for one short store transaction."""

    def __init__(self, lock_path: Path, session_id: str = "") -> None:
        # ``session_id`` is accepted for API compatibility; the kernel lock
        # identifies its holder, so it no longer carries meaning.
        del session_id
        self._lock_path = lock_path
        self._held: AbstractContextManager[None] | None = None

    def acquire(self, timeout_s: float = 10.0) -> bool:
        """Acquire within ``timeout_s``; False means another holder kept it.

        Not reentrant and not shareable: use one instance per transaction.
        """
        if self._held is not None:
            raise RuntimeError(f"SchedulerLock already held: {self._lock_path}")
        held = exclusive_file_lock(self._lock_path, timeout_s=timeout_s)
        try:
            held.__enter__()
        except TimeoutError:
            return False
        self._held = held
        return True

    def release(self) -> None:
        held, self._held = self._held, None
        if held is not None:
            held.__exit__(None, None, None)

    def __enter__(self) -> SchedulerLock:
        if not self.acquire():
            raise TimeoutError(f"Could not acquire scheduler lock: {self._lock_path}")
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()
