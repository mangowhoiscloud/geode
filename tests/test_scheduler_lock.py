"""Tests for SchedulerLock — O_EXCL lock file + PID liveness probe."""

from __future__ import annotations

import json
import os
import time
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
        lock1 = SchedulerLock(lock_path, session_id="session-1")
        lock2 = SchedulerLock(lock_path, session_id="session-2")

        assert lock1.acquire(timeout_s=1.0)
        # Second acquire should fail (different session, same PID alive)
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
        lock1 = SchedulerLock(lock_path, session_id="owner")
        lock1.acquire(timeout_s=1.0)

        with pytest.raises(TimeoutError), SchedulerLock(lock_path, session_id="other"):
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


class TestSessionIdentity:
    """Session ID in lock for idempotent re-acquire."""

    def test_lock_contains_session_id(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "session.lock"
        lock = SchedulerLock(lock_path, session_id="my-session")
        lock.acquire(timeout_s=1.0)

        data = json.loads(lock_path.read_text())
        assert data["session_id"] == "my-session"
        assert data["pid"] == os.getpid()
        lock.release()

    def test_same_session_idempotent_reacquire(self, tmp_path: Path) -> None:
        """Same session_id with different PID should reacquire immediately."""
        lock_path = tmp_path / "idem.lock"

        # Create lock with fake PID but same session
        lock_path.write_text(
            json.dumps(
                {
                    "pid": 99999999,
                    "acquired_at": 0.0,
                    "session_id": "shared-session",
                }
            )
        )

        lock = SchedulerLock(lock_path, session_id="shared-session")
        assert lock.acquire(timeout_s=1.0)

        # Verify PID was updated
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()
        assert data["session_id"] == "shared-session"
        lock.release()

    def test_different_session_blocked(self, tmp_path: Path) -> None:
        """Different session_id with alive PID should block."""
        lock_path = tmp_path / "diff.lock"

        # Create lock with current PID (alive) but different session
        lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "acquired_at": time.time(),
                    "session_id": "other-session",
                }
            )
        )

        lock = SchedulerLock(lock_path, session_id="my-session")
        assert not lock.acquire(timeout_s=0.3)

    def test_default_session_id_uses_pid(self, tmp_path: Path) -> None:
        """Default session_id should be pid-based."""
        lock_path = tmp_path / "default.lock"
        lock = SchedulerLock(lock_path)
        lock.acquire(timeout_s=1.0)

        data = json.loads(lock_path.read_text())
        assert data["session_id"] == f"pid-{os.getpid()}"
        lock.release()
