"""Tests for SchedulerLock — flock on a separate lock-file inode."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from core.scheduler import SchedulerLock

_HOLD = """
import sys, time
from pathlib import Path
from core.scheduler import SchedulerLock
lock = SchedulerLock(Path(sys.argv[1]))
assert lock.acquire(timeout_s=5)
print("held", flush=True)
time.sleep(60)
"""


def _hold_in_child(lock_path: Path) -> subprocess.Popen[str]:
    proc = subprocess.Popen(  # noqa: S603  # nosec B603 - fixed test interpreter argv
        [sys.executable, "-c", _HOLD, str(lock_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"
    return proc


class TestSchedulerLock:
    def test_acquire_release_reacquire(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock = SchedulerLock(lock_path)
        assert lock.acquire(timeout_s=1.0)
        assert lock_path.exists()
        lock.release()
        # The lock file is a stable inode: released, not deleted.
        assert lock_path.exists()
        assert SchedulerLock(lock_path).acquire(timeout_s=1.0)

    def test_context_manager_excludes_second_holder(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "ctx.lock"
        with SchedulerLock(lock_path):
            assert not SchedulerLock(lock_path).acquire(timeout_s=0.1)
        assert SchedulerLock(lock_path).acquire(timeout_s=1.0)

    def test_release_idempotent(self, tmp_path: Path) -> None:
        lock = SchedulerLock(tmp_path / "idem.lock")
        assert lock.acquire()
        lock.release()
        lock.release()

    def test_legacy_lock_content_is_irrelevant(self, tmp_path: Path) -> None:
        """An old O_EXCL-era lock file (any content) does not block or get trusted."""
        lock_path = tmp_path / "legacy.lock"
        lock_path.write_text('{"pid": 1, "acquired_at": 0, "session_id": "x"}')
        assert SchedulerLock(lock_path).acquire(timeout_s=0.5)

    def test_other_process_holder_blocks_until_it_dies(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "proc.lock"
        proc = _hold_in_child(lock_path)
        try:
            assert not SchedulerLock(lock_path).acquire(timeout_s=0.2)
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
            # The kernel released the dead holder's lock; no stale heuristic.
            deadline = time.monotonic() + 5
            while not SchedulerLock(lock_path).acquire(timeout_s=0.1):
                assert time.monotonic() < deadline
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    def test_symlinked_lock_path_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere"
        target.write_text("")
        link = tmp_path / "link.lock"
        link.symlink_to(target)
        with pytest.raises(OSError):
            SchedulerLock(link).acquire(timeout_s=0.1)
