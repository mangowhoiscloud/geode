"""Tests for SchedulerLock — O_EXCL lock file + PID liveness probe."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from core.automation.scheduler import SchedulerLock, _is_pid_alive


class TestSchedulerLock:
    """O_EXCL file-based lock tests."""

    def test_acquire_release(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "test.lock"
        lock = SchedulerLock(lock_path)

        assert lock.acquire(timeout_s=1.0)
        assert lock_path.exists()

        # Lock file should contain PID
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()
        assert "acquired_at" in data

        lock.release()
        assert not lock_path.exists()

    def test_context_manager(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "ctx.lock"
        with SchedulerLock(lock_path):
            assert lock_path.exists()
        assert not lock_path.exists()

    def test_double_acquire_fails(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "double.lock"
        lock1 = SchedulerLock(lock_path)
        lock2 = SchedulerLock(lock_path)

        assert lock1.acquire(timeout_s=1.0)
        # Second acquire should fail (same PID, lock held)
        assert not lock2.acquire(timeout_s=0.3)

        lock1.release()
        # Now should succeed
        assert lock2.acquire(timeout_s=1.0)
        lock2.release()

    def test_stale_lock_recovery(self, tmp_path: Path) -> None:
        """Lock with dead PID should be reclaimable."""
        lock_path = tmp_path / "stale.lock"

        # Create a lock file with a non-existent PID
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 99999999,  # Very unlikely to exist
                    "acquired_at": 0.0,  # Very old
                }
            )
        )

        lock = SchedulerLock(lock_path)
        assert lock.acquire(timeout_s=2.0)
        lock.release()

    def test_corrupt_lock_recovery(self, tmp_path: Path) -> None:
        """Corrupt lock file should be reclaimable."""
        lock_path = tmp_path / "corrupt.lock"
        lock_path.write_text("not json")

        lock = SchedulerLock(lock_path)
        assert lock.acquire(timeout_s=2.0)
        lock.release()

    def test_release_idempotent(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "idem.lock"
        lock = SchedulerLock(lock_path)
        lock.acquire(timeout_s=1.0)
        lock.release()
        lock.release()  # Should not raise

    def test_context_manager_timeout(self, tmp_path: Path) -> None:
        """Context manager should raise TimeoutError if lock can't be acquired."""
        lock_path = tmp_path / "timeout.lock"
        lock1 = SchedulerLock(lock_path)
        lock1.acquire(timeout_s=1.0)

        with pytest.raises(TimeoutError), SchedulerLock(lock_path):
            pass  # Should not reach here

        lock1.release()


class TestIsPidAlive:
    """PID liveness check tests."""

    def test_current_pid_alive(self) -> None:
        assert _is_pid_alive(os.getpid())

    def test_nonexistent_pid(self) -> None:
        assert not _is_pid_alive(99999999)

    def test_zero_pid(self) -> None:
        assert not _is_pid_alive(0)

    def test_negative_pid(self) -> None:
        assert not _is_pid_alive(-1)
