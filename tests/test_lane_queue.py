"""Tests for LaneQueue — concurrency control with named lanes."""

from __future__ import annotations

import threading
import time

import pytest
from core.orchestration.lane_queue import Lane, LaneQueue, SessionLane


class TestLane:
    def test_acquire_and_release(self):
        lane = Lane("test", max_concurrent=2)
        assert lane.active_count == 0
        assert lane.available == 2

        with lane.acquire("job-1"):
            assert lane.active_count == 1
            assert lane.available == 1

        assert lane.active_count == 0
        assert lane.available == 2

    def test_concurrent_limit(self):
        lane = Lane("test", max_concurrent=1, timeout_s=0.1)
        acquired = threading.Event()
        release = threading.Event()

        def hold_lane():
            with lane.acquire("blocker"):
                acquired.set()
                release.wait(timeout=2.0)

        t = threading.Thread(target=hold_lane, daemon=True)
        t.start()
        acquired.wait(timeout=1.0)

        # Second acquire should timeout
        with pytest.raises(TimeoutError, match="timeout"), lane.acquire("blocked"):
            pass

        release.set()
        t.join(timeout=1.0)

    def test_stats_tracking(self):
        lane = Lane("test", max_concurrent=2)
        with lane.acquire("job-1"):
            pass

        assert lane.stats.acquired == 1
        assert lane.stats.released == 1
        assert lane.stats.timeouts == 0

    def test_get_active(self):
        lane = Lane("test", max_concurrent=2)
        with lane.acquire("job-1"):
            active = lane.get_active()
            assert "job-1" in active
            assert active["job-1"] >= 0

    def test_stats_to_dict(self):
        lane = Lane("test")
        d = lane.stats.to_dict()
        assert set(d.keys()) == {"acquired", "released", "timeouts"}


class TestLaneQueue:
    def test_add_and_list_lanes(self):
        q = LaneQueue()
        q.add_lane("global", max_concurrent=8)
        assert q.list_lanes() == ["global"]

    def test_list_lanes_with_session(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=8)
        assert "session" in q.list_lanes()
        assert "global" in q.list_lanes()

    def test_get_lane(self):
        q = LaneQueue()
        q.add_lane("test")
        lane = q.get_lane("test")
        assert lane is not None
        assert lane.name == "test"

    def test_get_nonexistent_lane(self):
        q = LaneQueue()
        assert q.get_lane("nope") is None

    def test_session_lane_property(self):
        q = LaneQueue()
        assert q.session_lane is None
        sl = SessionLane(max_sessions=10)
        q.set_session_lane(sl)
        assert q.session_lane is sl

    def test_acquire_all_session_and_global(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=8)

        with q.acquire_all("gateway:slack:C123", ["session", "global"]):
            assert q.session_lane is not None and q.session_lane.active_count == 1
            gl = q.get_lane("global")
            assert gl is not None and gl.active_count == 1

        assert q.session_lane.active_count == 0
        gl = q.get_lane("global")
        assert gl is not None and gl.active_count == 0

    def test_acquire_all_unknown_lane(self):
        q = LaneQueue()
        with pytest.raises(KeyError, match="not found"), q.acquire_all("job-1", ["nonexistent"]):
            pass

    def test_acquire_all_no_session_lane_skips(self):
        """If no session lane registered, 'session' in lane_names is skipped."""
        q = LaneQueue()
        q.add_lane("global", max_concurrent=8)
        with q.acquire_all("key", ["session", "global"]):
            gl = q.get_lane("global")
            assert gl is not None and gl.active_count == 1

    def test_acquire_all_partial_failure_releases_session(self):
        """If global times out, session lane must be released."""
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=1, timeout_s=0.1)

        # Exhaust global
        gl = q.get_lane("global")
        assert gl is not None
        gl._semaphore.acquire()

        with pytest.raises(TimeoutError), q.acquire_all("key", ["session", "global"]):
            pass

        # Session lane must be released
        assert q.session_lane is not None and q.session_lane.active_count == 0
        gl._semaphore.release()

    def test_status_with_session_lane(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=256))
        q.add_lane("global", max_concurrent=8)

        status = q.status()
        assert "session" in status
        assert status["session"]["max_sessions"] == 256
        assert status["global"]["max"] == 8


# ---------------------------------------------------------------------------
# C4 Regression: acquire_all partial failure (v0.35.1 fix)
# ---------------------------------------------------------------------------


class TestAcquireAllPartialFailure:
    """Verify partial failure releases only acquired lanes."""

    def test_second_lane_timeout_releases_first(self) -> None:
        """If 2nd lane times out, 1st lane must be released."""
        q = LaneQueue()
        q.add_lane("fast", max_concurrent=1, timeout_s=5.0)
        q.add_lane("slow", max_concurrent=1, timeout_s=0.1)

        slow = q.get_lane("slow")
        assert slow is not None
        slow._semaphore.acquire()

        fast = q.get_lane("fast")
        assert fast is not None

        with pytest.raises(TimeoutError, match="slow"), q.acquire_all("job-x", ["fast", "slow"]):
            pass

        # Fast lane must be released (no leak)
        assert fast.active_count == 0
        slow._semaphore.release()


# ---------------------------------------------------------------------------
# SessionLane — per-key serialization
# ---------------------------------------------------------------------------


class TestSessionLane:
    """Verify per-session-key serialization (OpenClaw pattern)."""

    def test_same_key_serializes(self) -> None:
        """Two threads with same key — second blocks until first releases."""
        sl = SessionLane(timeout_s=0.2)
        acquired = threading.Event()
        release = threading.Event()
        blocked = threading.Event()

        def holder():
            with sl.acquire("key-A"):
                acquired.set()
                release.wait(timeout=2.0)

        def waiter():
            acquired.wait(timeout=1.0)
            ok = sl.try_acquire("key-A")
            if not ok:
                blocked.set()

        t1 = threading.Thread(target=holder, daemon=True)
        t2 = threading.Thread(target=waiter, daemon=True)
        t1.start()
        t2.start()
        t2.join(timeout=1.0)

        assert blocked.is_set(), "Second acquire should fail (same key held)"
        release.set()
        t1.join(timeout=1.0)

    def test_different_keys_parallel(self) -> None:
        """Two threads with different keys — both proceed immediately."""
        sl = SessionLane()
        assert sl.try_acquire("key-A")
        assert sl.try_acquire("key-B")
        assert sl.active_count == 2
        sl.manual_release("key-A")
        sl.manual_release("key-B")

    def test_try_acquire_and_manual_release(self) -> None:
        sl = SessionLane()
        assert sl.try_acquire("k1")
        assert not sl.try_acquire("k1")  # same key, held
        sl.manual_release("k1")
        assert sl.try_acquire("k1")  # re-acquired after release
        sl.manual_release("k1")

    def test_acquire_timeout(self) -> None:
        sl = SessionLane()
        sl.try_acquire("k1")
        assert not sl.acquire_timeout("k1", timeout_s=0.05)
        sl.manual_release("k1")

    def test_context_manager_release(self) -> None:
        sl = SessionLane()
        with sl.acquire("k1"):
            assert sl.active_count == 1
        assert sl.active_count == 0

    def test_max_sessions_cap(self) -> None:
        sl = SessionLane(max_sessions=3, idle_timeout_s=0.0)
        sl.try_acquire("a")
        sl.try_acquire("b")
        sl.try_acquire("c")
        # All 3 held, no idle to evict
        with pytest.raises(RuntimeError, match="SessionLane full"):
            sl.try_acquire("d")
        sl.manual_release("a")
        sl.manual_release("b")
        sl.manual_release("c")

    def test_idle_eviction_on_cap(self) -> None:
        sl = SessionLane(max_sessions=2, idle_timeout_s=0.0)
        sl.try_acquire("a")
        sl.manual_release("a")  # now idle
        sl.try_acquire("b")
        sl.manual_release("b")  # now idle
        # Both idle — next create triggers eviction
        sl.try_acquire("c")  # evicts a and/or b, creates c
        assert sl.session_count <= 2
        sl.manual_release("c")

    def test_cleanup_idle(self) -> None:
        sl = SessionLane(idle_timeout_s=0.0)
        sl.try_acquire("a")
        sl.manual_release("a")
        time.sleep(0.01)
        evicted = sl.cleanup_idle()
        assert evicted == 1
        assert sl.session_count == 0

    def test_held_session_not_evicted(self) -> None:
        sl = SessionLane(idle_timeout_s=0.0)
        sl.try_acquire("held")
        time.sleep(0.01)
        evicted = sl.cleanup_idle()
        assert evicted == 0
        assert sl.session_count == 1
        sl.manual_release("held")

    def test_get_active(self) -> None:
        sl = SessionLane()
        sl.try_acquire("a")
        sl.try_acquire("b")
        active = sl.get_active()
        assert "a" in active
        assert "b" in active
        sl.manual_release("a")
        active = sl.get_active()
        assert "a" not in active
        assert "b" in active
        sl.manual_release("b")

    def test_stats_tracking(self) -> None:
        sl = SessionLane()
        sl.try_acquire("a")
        sl.manual_release("a")
        assert sl.stats.acquired == 1
        assert sl.stats.released == 1

        assert not sl.try_acquire("x") or True  # acquire x
        sl.manual_release("x")
        # try_acquire on held key
        sl.try_acquire("z")
        assert not sl.try_acquire("z")
        assert sl.stats.timeouts == 1
        sl.manual_release("z")
