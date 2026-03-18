"""Tests for Calendar ↔ Scheduler Bridge.

Phase 5 validation: bidirectional sync between scheduler and calendar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from core.infrastructure.ports.calendar_port import CalendarEvent
from core.orchestration.calendar_bridge import (
    CalendarSchedulerBridge,
    get_calendar_bridge,
    set_calendar_bridge,
)

NOW = datetime(2026, 3, 18, 14, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_scheduler() -> MagicMock:
    scheduler = MagicMock()
    job = MagicMock()
    job.job_id = "job_1"
    job.name = "daily-analysis"
    job.enabled = True
    job.next_run_at_ms = NOW.timestamp() * 1000 + 3600_000  # +1h
    job.schedule.kind.value = "every"
    scheduler.list_jobs.return_value = [job]
    return scheduler


@pytest.fixture()
def mock_calendar() -> MagicMock:
    calendar = MagicMock()
    calendar.is_available.return_value = True
    calendar.list_events.return_value = []
    calendar.create_event.return_value = CalendarEvent(
        event_id="evt_new",
        title="[GEODE] daily-analysis",
        start=NOW + timedelta(hours=1),
        end=NOW + timedelta(hours=1, minutes=30),
        source="google",
        is_geode=True,
    )
    return calendar


@pytest.fixture()
def bridge(mock_scheduler: MagicMock, mock_calendar: MagicMock) -> CalendarSchedulerBridge:
    return CalendarSchedulerBridge(mock_scheduler, mock_calendar)


# ---------------------------------------------------------------------------
# contextvars
# ---------------------------------------------------------------------------


class TestBridgeContextvar:
    def test_set_get_round_trip(self, bridge: CalendarSchedulerBridge):
        set_calendar_bridge(bridge)
        assert get_calendar_bridge() is bridge
        set_calendar_bridge(None)
        assert get_calendar_bridge() is None


# ---------------------------------------------------------------------------
# Push (scheduler → calendar)
# ---------------------------------------------------------------------------


class TestPushToCalendar:
    def test_push_creates_event(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        result = bridge.sync(direction="push")
        assert result["pushed"] == 1
        assert result["errors"] == []
        mock_calendar.create_event.assert_called_once()
        call_args = mock_calendar.create_event.call_args
        assert call_args[0][0].startswith("[GEODE]")

    def test_push_skips_disabled_jobs(
        self, bridge: CalendarSchedulerBridge, mock_scheduler: MagicMock
    ):
        mock_scheduler.list_jobs.return_value[0].enabled = False
        result = bridge.sync(direction="push")
        assert result["pushed"] == 0

    def test_push_skips_duplicate(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        # Calendar already has the event
        mock_calendar.list_events.return_value = [
            CalendarEvent(
                event_id="existing",
                title="[GEODE] daily-analysis",
                start=NOW,
                end=NOW + timedelta(hours=1),
                is_geode=True,
            )
        ]
        result = bridge.sync(direction="push")
        assert result["pushed"] == 0

    def test_push_calendar_unavailable(self, mock_scheduler: MagicMock):
        cal = MagicMock()
        cal.is_available.return_value = False
        bridge = CalendarSchedulerBridge(mock_scheduler, cal)
        result = bridge.sync(direction="push")
        assert result["pushed"] == 0
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# Pull (calendar → scheduler)
# ---------------------------------------------------------------------------


class TestPullFromCalendar:
    def test_pull_creates_job(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        mock_calendar.list_events.return_value = [
            CalendarEvent(
                event_id="cal_1",
                title="[GEODE] weekly-report",
                start=NOW + timedelta(days=3),
                end=NOW + timedelta(days=3, hours=1),
                is_geode=True,
            )
        ]
        result = bridge.sync(direction="pull")
        assert result["pulled"] == 1

    def test_pull_skips_non_geode(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        mock_calendar.list_events.return_value = [
            CalendarEvent(
                event_id="cal_2",
                title="Personal Lunch",
                start=NOW,
                end=NOW + timedelta(hours=1),
                is_geode=False,
            )
        ]
        result = bridge.sync(direction="pull")
        assert result["pulled"] == 0

    def test_pull_skips_existing_job(
        self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock, mock_scheduler: MagicMock
    ):
        mock_calendar.list_events.return_value = [
            CalendarEvent(
                event_id="cal_3",
                title="[GEODE] daily-analysis",  # Same name as existing job
                start=NOW,
                end=NOW + timedelta(hours=1),
                is_geode=True,
            )
        ]
        result = bridge.sync(direction="pull")
        assert result["pulled"] == 0

    def test_pull_calendar_unavailable(self, mock_scheduler: MagicMock):
        cal = MagicMock()
        cal.is_available.return_value = False
        bridge = CalendarSchedulerBridge(mock_scheduler, cal)
        result = bridge.sync(direction="pull")
        assert result["pulled"] == 0
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# Bidirectional sync
# ---------------------------------------------------------------------------


class TestBidirectionalSync:
    def test_sync_both(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        mock_calendar.list_events.return_value = [
            CalendarEvent(
                event_id="cal_4",
                title="[GEODE] new-task",
                start=NOW + timedelta(days=1),
                end=NOW + timedelta(days=1, hours=1),
                is_geode=True,
            )
        ]
        result = bridge.sync(direction="both")
        assert result["pushed"] >= 0
        assert result["pulled"] >= 0
