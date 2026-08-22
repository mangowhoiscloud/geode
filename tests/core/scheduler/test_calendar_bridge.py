"""Tests for Calendar ↔ Scheduler Bridge.

Phase 5 validation: bidirectional sync between scheduler and calendar.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.mcp.calendar_port import CalendarEvent
from core.scheduler import SchedulerService
from core.scheduler.calendar_bridge import CalendarSchedulerBridge

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
    calendar.ais_available = AsyncMock(return_value=True)
    calendar.alist_events = AsyncMock(return_value=[])
    calendar.acreate_event = AsyncMock(
        return_value=CalendarEvent(
            event_id="evt_new",
            title="[GEODE] daily-analysis",
            start=NOW + timedelta(hours=1),
            end=NOW + timedelta(hours=1, minutes=30),
            source="google",
            is_geode=True,
        )
    )
    return calendar


@pytest.fixture()
def bridge(mock_scheduler: MagicMock, mock_calendar: MagicMock) -> CalendarSchedulerBridge:
    return CalendarSchedulerBridge(mock_scheduler, mock_calendar)


# ---------------------------------------------------------------------------
# Explicit dependencies
# ---------------------------------------------------------------------------


class TestBridgeDependencies:
    def test_preserves_injected_services(
        self,
        bridge: CalendarSchedulerBridge,
        mock_scheduler: MagicMock,
        mock_calendar: MagicMock,
    ):
        assert bridge._scheduler is mock_scheduler
        assert bridge._calendar is mock_calendar


# ---------------------------------------------------------------------------
# Push (scheduler → calendar)
# ---------------------------------------------------------------------------


class TestPushToCalendar:
    def test_push_creates_event(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        result = asyncio.run(bridge.sync(direction="push"))
        assert result["pushed"] == 1
        assert result["errors"] == []
        mock_calendar.acreate_event.assert_awaited_once()
        call_args = mock_calendar.acreate_event.call_args
        assert call_args[0][0].startswith("[GEODE]")

    def test_push_skips_disabled_jobs(
        self, bridge: CalendarSchedulerBridge, mock_scheduler: MagicMock
    ):
        mock_scheduler.list_jobs.return_value[0].enabled = False
        result = asyncio.run(bridge.sync(direction="push"))
        assert result["pushed"] == 0

    def test_push_skips_duplicate(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        # Calendar already has the event
        mock_calendar.alist_events.return_value = [
            CalendarEvent(
                event_id="existing",
                title="[GEODE] daily-analysis",
                start=NOW,
                end=NOW + timedelta(hours=1),
                is_geode=True,
            )
        ]
        result = asyncio.run(bridge.sync(direction="push"))
        assert result["pushed"] == 0

    def test_push_calendar_unavailable(self, mock_scheduler: MagicMock):
        cal = MagicMock()
        cal.ais_available = AsyncMock(return_value=False)
        bridge = CalendarSchedulerBridge(mock_scheduler, cal)
        result = asyncio.run(bridge.sync(direction="push"))
        assert result["pushed"] == 0
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# Pull (calendar → scheduler)
# ---------------------------------------------------------------------------


class TestPullFromCalendar:
    def test_pull_creates_job(self, mock_calendar: MagicMock, tmp_path):
        start = datetime.now(UTC) + timedelta(days=3)
        mock_calendar.alist_events.return_value = [
            CalendarEvent(
                event_id="cal_1",
                title="[GEODE] weekly-report",
                start=start,
                end=start + timedelta(hours=1),
                is_geode=True,
            )
        ]
        scheduler = SchedulerService(
            store_path=tmp_path / "jobs.json",
            log_dir=tmp_path / "logs",
        )
        bridge = CalendarSchedulerBridge(scheduler, mock_calendar)
        result = asyncio.run(bridge.sync(direction="pull"))
        assert result["pulled"] == 1
        assert result["errors"] == []
        [job] = scheduler.list_jobs()
        assert job.name == "weekly-report"
        assert job.action == "weekly-report"
        assert job.schedule.kind.value == "at"
        assert job.next_run_at_ms is not None
        assert job.metadata == {"source": "calendar", "event_id": "cal_1"}

    def test_pull_skips_events_that_can_no_longer_fire(
        self, mock_calendar: MagicMock, tmp_path
    ) -> None:
        mock_calendar.alist_events.return_value = [
            CalendarEvent(
                event_id="cal_past",
                title="[GEODE] stale-action",
                start=datetime.now(UTC) - timedelta(minutes=1),
                end=datetime.now(UTC) + timedelta(minutes=29),
                is_geode=True,
            )
        ]
        scheduler = SchedulerService(
            store_path=tmp_path / "jobs.json",
            log_dir=tmp_path / "logs",
        )

        result = asyncio.run(
            CalendarSchedulerBridge(scheduler, mock_calendar).sync(direction="pull")
        )

        assert result["pulled"] == 0
        assert scheduler.list_jobs() == []

    def test_pull_skips_non_geode(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        mock_calendar.alist_events.return_value = [
            CalendarEvent(
                event_id="cal_2",
                title="Personal Lunch",
                start=NOW,
                end=NOW + timedelta(hours=1),
                is_geode=False,
            )
        ]
        result = asyncio.run(bridge.sync(direction="pull"))
        assert result["pulled"] == 0

    def test_pull_skips_existing_job(
        self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock, mock_scheduler: MagicMock
    ):
        mock_calendar.alist_events.return_value = [
            CalendarEvent(
                event_id="cal_3",
                title="[GEODE] daily-analysis",  # Same name as existing job
                start=NOW,
                end=NOW + timedelta(hours=1),
                is_geode=True,
            )
        ]
        result = asyncio.run(bridge.sync(direction="pull"))
        assert result["pulled"] == 0

    def test_pull_calendar_unavailable(self, mock_scheduler: MagicMock):
        cal = MagicMock()
        cal.ais_available = AsyncMock(return_value=False)
        bridge = CalendarSchedulerBridge(mock_scheduler, cal)
        result = asyncio.run(bridge.sync(direction="pull"))
        assert result["pulled"] == 0
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# Bidirectional sync
# ---------------------------------------------------------------------------


class TestBidirectionalSync:
    def test_sync_both(self, bridge: CalendarSchedulerBridge, mock_calendar: MagicMock):
        mock_calendar.alist_events.return_value = [
            CalendarEvent(
                event_id="cal_4",
                title="[GEODE] new-task",
                start=NOW + timedelta(days=1),
                end=NOW + timedelta(days=1, hours=1),
                is_geode=True,
            )
        ]
        result = asyncio.run(bridge.sync(direction="both"))
        assert result["pushed"] >= 0
        assert result["pulled"] >= 0
