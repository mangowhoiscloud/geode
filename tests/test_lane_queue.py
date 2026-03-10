"""Tests for LaneQueue — concurrency control with named lanes."""

from __future__ import annotations

import threading

import pytest
from core.orchestration.lane_queue import Lane, LaneQueue


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
        q.add_lane("session", max_concurrent=1)
        q.add_lane("global", max_concurrent=4)
        assert q.list_lanes() == ["session", "global"]

    def test_get_lane(self):
        q = LaneQueue()
        q.add_lane("test")
        lane = q.get_lane("test")
        assert lane is not None
        assert lane.name == "test"

    def test_get_nonexistent_lane(self):
        q = LaneQueue()
        assert q.get_lane("nope") is None

    def test_acquire_all(self):
        q = LaneQueue()
        q.add_lane("session", max_concurrent=1)
        q.add_lane("global", max_concurrent=4)

        with q.acquire_all("job-1", ["session", "global"]):
            session = q.get_lane("session")
            global_lane = q.get_lane("global")
            assert session is not None and session.active_count == 1
            assert global_lane is not None and global_lane.active_count == 1

        assert session is not None and session.active_count == 0
        assert global_lane is not None and global_lane.active_count == 0

    def test_acquire_all_unknown_lane(self):
        q = LaneQueue()
        with pytest.raises(KeyError, match="not found"), q.acquire_all("job-1", ["nonexistent"]):
            pass

    def test_status(self):
        q = LaneQueue()
        q.add_lane("session", max_concurrent=1)
        q.add_lane("global", max_concurrent=4)

        status = q.status()
        assert status["session"]["max"] == 1
        assert status["global"]["max"] == 4
        assert status["session"]["active"] == 0

    def test_session_lane_serial(self):
        """Session lane (max_concurrent=1) ensures serial execution."""
        q = LaneQueue()
        q.add_lane("session", max_concurrent=1, timeout_s=0.1)

        acquired = threading.Event()
        release = threading.Event()

        def hold():
            with q.acquire_all("job-1", ["session"]):
                acquired.set()
                release.wait(timeout=2.0)

        t = threading.Thread(target=hold, daemon=True)
        t.start()
        acquired.wait(timeout=1.0)

        # Second session acquire should block/timeout
        session = q.get_lane("session")
        assert session is not None and session.active_count == 1

        release.set()
        t.join(timeout=1.0)
