"""Tests for StuckDetector — auto-release long-running tasks."""

from __future__ import annotations

from core.orchestration.stuck_detection import StuckDetector


class TestStuckDetector:
    def test_mark_running_and_complete(self):
        d = StuckDetector(timeout_s=10.0)
        d.mark_running("session-1")
        assert d.running_count == 1

        completed = d.mark_completed("session-1")
        assert completed is True
        assert d.running_count == 0

    def test_complete_nonexistent_returns_false(self):
        d = StuckDetector()
        assert d.mark_completed("nope") is False

    def test_check_stuck_not_expired(self):
        d = StuckDetector(timeout_s=3600.0)
        d.mark_running("session-1")
        stuck = d.check_stuck()
        assert stuck == []
        assert d.running_count == 1

    def test_check_stuck_expired(self):
        d = StuckDetector(timeout_s=0.0)  # Immediate timeout
        d.mark_running("session-1")
        stuck = d.check_stuck()
        assert stuck == ["session-1"]
        assert d.running_count == 0
        assert d.stats.released == 1

    def test_stuck_callback(self):
        released: list[str] = []

        d = StuckDetector(timeout_s=0.0, on_stuck=lambda key: released.append(key))
        d.mark_running("a")
        d.mark_running("b")
        d.check_stuck()

        assert sorted(released) == ["a", "b"]

    def test_get_running_elapsed(self):
        d = StuckDetector()
        d.mark_running("session-1")
        running = d.get_running()
        assert "session-1" in running
        assert running["session-1"] >= 0

    def test_metadata_stored(self):
        d = StuckDetector()
        d.mark_running("s1", metadata={"ip": "Berserk"})
        assert d.running_count == 1

    def test_monitor_start_stop(self):
        d = StuckDetector(check_interval_s=0.05)
        d.start_monitor()
        assert d.is_monitoring is True

        d.stop_monitor()
        assert d.is_monitoring is False

    def test_monitor_start_idempotent(self):
        d = StuckDetector(check_interval_s=0.05)
        d.start_monitor()
        d.start_monitor()  # Should not error
        d.stop_monitor()

    def test_stats_to_dict(self):
        d = StuckDetector()
        s = d.stats.to_dict()
        assert set(s.keys()) == {"checks", "released"}

    def test_timeout_property(self):
        d = StuckDetector(timeout_s=42.0)
        assert d.timeout_s == 42.0
