"""Tests for graceful serve drain — SIGTERM → active session completion wait."""

from __future__ import annotations

import threading
import time

from core.orchestration.lane_queue import Lane, SessionLane


class TestGracefulDrainLogic:
    """Test the drain polling logic used by serve shutdown."""

    def test_drain_completes_when_no_active(self):
        """Drain loop exits immediately when no sessions are active."""
        sl = SessionLane(max_sessions=10)
        assert sl.active_count == 0

        # Simulate drain loop
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                break
            time.sleep(0.1)
        assert sl.active_count == 0

    def test_drain_waits_for_active_session(self):
        """Drain loop waits until active session releases."""
        sl = SessionLane(max_sessions=10)
        released = threading.Event()

        def _hold_session():
            with sl.acquire("test-session"):
                time.sleep(0.3)
            released.set()

        t = threading.Thread(target=_hold_session)
        t.start()
        time.sleep(0.05)  # let thread acquire

        assert sl.active_count == 1

        # Drain loop
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                break
            time.sleep(0.1)

        assert sl.active_count == 0
        assert released.is_set()
        t.join()

    def test_drain_timeout_with_stuck_session(self):
        """Drain loop respects timeout when session is stuck."""
        sl = SessionLane(max_sessions=10)
        stop = threading.Event()

        def _hold_forever():
            with sl.acquire("stuck-session"):
                stop.wait()  # hold until test says stop

        t = threading.Thread(target=_hold_forever, daemon=True)
        t.start()
        time.sleep(0.05)

        assert sl.active_count == 1

        # Drain with short timeout
        drain_timeout = 0.3
        deadline = time.monotonic() + drain_timeout
        timed_out = True
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                timed_out = False
                break
            time.sleep(0.05)

        assert timed_out
        assert sl.active_count == 1

        # Cleanup
        stop.set()
        t.join(timeout=2.0)

    def test_global_lane_active_count(self):
        """Lane.active_count reflects held slots."""
        lane = Lane("test", max_concurrent=4)
        assert lane.active_count == 0

        acquired = threading.Event()
        release = threading.Event()

        def _hold():
            with lane.acquire("w1"):
                acquired.set()
                release.wait()

        t = threading.Thread(target=_hold, daemon=True)
        t.start()
        acquired.wait(timeout=2.0)
        assert lane.active_count == 1

        release.set()
        t.join(timeout=2.0)
        assert lane.active_count == 0

    def test_multiple_sessions_drain(self):
        """Drain waits for all concurrent sessions to complete."""
        sl = SessionLane(max_sessions=10)
        threads: list[threading.Thread] = []
        completed = {"count": 0}
        lock = threading.Lock()

        def _hold(key: str, hold_time: float):
            with sl.acquire(key):
                time.sleep(hold_time)
            with lock:
                completed["count"] += 1

        # Start 3 sessions with different hold times
        for i, hold in enumerate([0.1, 0.2, 0.3]):
            t = threading.Thread(target=_hold, args=(f"s{i}", hold))
            t.start()
            threads.append(t)
        time.sleep(0.05)
        assert sl.active_count == 3

        # Drain
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                break
            time.sleep(0.05)

        assert sl.active_count == 0
        assert completed["count"] == 3
        for t in threads:
            t.join()


class TestCLIPollerStopAccepting:
    """Test CLIPoller.stop_accepting() method."""

    def test_stop_accepting_exists(self):
        """CLIPoller has stop_accepting method."""
        from core.gateway.pollers.cli_poller import CLIPoller

        assert hasattr(CLIPoller, "stop_accepting")

    def test_stop_accepting_idempotent(self):
        """Calling stop_accepting on non-started poller does not crash."""
        from unittest.mock import MagicMock

        from core.gateway.pollers.cli_poller import CLIPoller

        services = MagicMock()
        poller = CLIPoller(services)
        # Should not raise
        poller.stop_accepting()
        poller.stop_accepting()  # second call also safe
