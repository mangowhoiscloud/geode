"""Tests for calendar adapters (Google, Apple/CalDAV, Composite).

Phase 4 validation: CalendarPort implementations + CalendarTools.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from core.infrastructure.adapters.mcp.apple_calendar_adapter import AppleCalendarAdapter
from core.infrastructure.adapters.mcp.composite_calendar import CompositeCalendarAdapter
from core.infrastructure.adapters.mcp.google_calendar_adapter import GoogleCalendarAdapter
from core.infrastructure.ports.calendar_port import (
    CalendarEvent,
    get_calendar,
    set_calendar,
)
from core.tools.calendar_tools import CalendarCreateEventTool, CalendarListEventsTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 3, 18, 14, 0, 0, tzinfo=UTC)


@pytest.fixture()
def mock_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.check_health.return_value = {"google-calendar": True, "caldav": True}
    return mgr


@pytest.fixture()
def google_adapter(mock_manager: MagicMock) -> GoogleCalendarAdapter:
    return GoogleCalendarAdapter(manager=mock_manager)


@pytest.fixture()
def apple_adapter(mock_manager: MagicMock) -> AppleCalendarAdapter:
    return AppleCalendarAdapter(manager=mock_manager)


# ---------------------------------------------------------------------------
# CalendarPort contextvars
# ---------------------------------------------------------------------------


class TestCalendarPort:
    def test_contextvars_injection(self):
        mock = MagicMock()
        set_calendar(mock)
        assert get_calendar() is mock
        set_calendar(None)
        assert get_calendar() is None


class TestCalendarEvent:
    def test_dataclass_creation(self):
        event = CalendarEvent(
            event_id="evt_1",
            title="[GEODE] Test Meeting",
            start=NOW,
            end=NOW + timedelta(hours=1),
            source="google",
            is_geode=True,
        )
        assert event.is_geode
        assert event.title.startswith("[GEODE]")
        assert event.source == "google"


# ---------------------------------------------------------------------------
# Google Calendar Adapter
# ---------------------------------------------------------------------------


class TestGoogleCalendarAdapter:
    def test_list_events_success(
        self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {
            "items": [
                {
                    "id": "evt_1",
                    "summary": "Team Standup",
                    "start": {"dateTime": "2026-03-18T09:00:00+00:00"},
                    "end": {"dateTime": "2026-03-18T09:30:00+00:00"},
                    "description": "Daily standup",
                    "location": "Room A",
                }
            ]
        }
        events = google_adapter.list_events(start=NOW, end=NOW + timedelta(days=1))
        assert len(events) == 1
        assert events[0].title == "Team Standup"
        assert events[0].source == "google"

    def test_list_events_empty(
        self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"items": []}
        events = google_adapter.list_events()
        assert events == []

    def test_list_events_error(
        self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"error": "unauthorized"}
        events = google_adapter.list_events()
        assert events == []

    def test_create_event_success(
        self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"id": "new_evt_1"}
        start = NOW + timedelta(days=1)
        end = start + timedelta(hours=1)

        event = google_adapter.create_event("Meeting", start, end, description="Test")
        assert event.event_id == "new_evt_1"
        assert event.title == "Meeting"
        assert event.source == "google"

    def test_create_event_error(
        self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"error": "quota exceeded"}
        with pytest.raises(RuntimeError, match="quota exceeded"):
            google_adapter.create_event("Meeting", NOW, NOW + timedelta(hours=1))

    def test_delete_event(self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock):
        mock_manager.call_tool.return_value = {"status": "deleted"}
        assert google_adapter.delete_event("evt_1") is True

    def test_delete_event_error(
        self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"error": "not found"}
        assert google_adapter.delete_event("nonexistent") is False

    def test_is_available(self, google_adapter: GoogleCalendarAdapter):
        assert google_adapter.is_available()

    def test_unavailable(self, mock_manager: MagicMock):
        mock_manager.check_health.return_value = {"google-calendar": False}
        adapter = GoogleCalendarAdapter(manager=mock_manager)
        assert not adapter.is_available()
        assert adapter.list_events() == []

    def test_geode_prefix(self, google_adapter: GoogleCalendarAdapter, mock_manager: MagicMock):
        mock_manager.call_tool.return_value = {"id": "g_1"}
        event = google_adapter.create_event("[GEODE] Analysis", NOW, NOW + timedelta(hours=1))
        assert event.is_geode


# ---------------------------------------------------------------------------
# Apple Calendar (CalDAV) Adapter
# ---------------------------------------------------------------------------


class TestAppleCalendarAdapter:
    def test_list_events_success(
        self, apple_adapter: AppleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {
            "events": [
                {
                    "uid": "cal_1",
                    "summary": "Lunch",
                    "start": "2026-03-18T12:00:00+00:00",
                    "end": "2026-03-18T13:00:00+00:00",
                }
            ]
        }
        events = apple_adapter.list_events()
        assert len(events) == 1
        assert events[0].title == "Lunch"
        assert events[0].source == "apple"

    def test_create_event_success(
        self, apple_adapter: AppleCalendarAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"uid": "new_cal_1"}
        event = apple_adapter.create_event("Meeting", NOW, NOW + timedelta(hours=1))
        assert event.event_id == "new_cal_1"
        assert event.source == "apple"

    def test_create_event_unavailable(self, mock_manager: MagicMock):
        mock_manager.check_health.return_value = {"caldav": False}
        adapter = AppleCalendarAdapter(manager=mock_manager)
        with pytest.raises(RuntimeError, match="not available"):
            adapter.create_event("Meeting", NOW, NOW + timedelta(hours=1))

    def test_is_available(self, apple_adapter: AppleCalendarAdapter):
        assert apple_adapter.is_available()


# ---------------------------------------------------------------------------
# Composite Calendar Adapter
# ---------------------------------------------------------------------------


class TestCompositeCalendarAdapter:
    def test_merge_events(self, mock_manager: MagicMock):
        mock_manager.call_tool.side_effect = [
            # Google events
            {
                "items": [
                    {
                        "id": "g1",
                        "summary": "Google Meeting",
                        "start": {"dateTime": "2026-03-18T10:00:00+00:00"},
                        "end": {"dateTime": "2026-03-18T11:00:00+00:00"},
                    }
                ]
            },
            # CalDAV events
            {
                "events": [
                    {
                        "uid": "a1",
                        "summary": "Apple Lunch",
                        "start": "2026-03-18T12:00:00+00:00",
                        "end": "2026-03-18T13:00:00+00:00",
                    }
                ]
            },
        ]
        google = GoogleCalendarAdapter(manager=mock_manager)
        apple = AppleCalendarAdapter(manager=mock_manager)
        composite = CompositeCalendarAdapter([google, apple])

        events = composite.list_events()
        assert len(events) == 2
        # Should be sorted by start time
        assert events[0].title == "Google Meeting"
        assert events[1].title == "Apple Lunch"

    def test_create_event_first_available(self, mock_manager: MagicMock):
        mock_manager.call_tool.return_value = {"id": "g_new"}
        google = GoogleCalendarAdapter(manager=mock_manager)
        apple = AppleCalendarAdapter(manager=mock_manager)
        composite = CompositeCalendarAdapter([google, apple])

        event = composite.create_event("Test", NOW, NOW + timedelta(hours=1))
        assert event.source == "google"

    def test_no_adapters_available(self, mock_manager: MagicMock):
        mock_manager.check_health.return_value = {}
        google = GoogleCalendarAdapter(manager=mock_manager)
        composite = CompositeCalendarAdapter([google])
        assert not composite.is_available()

    def test_list_sources(self, mock_manager: MagicMock):
        google = GoogleCalendarAdapter(manager=mock_manager)
        apple = AppleCalendarAdapter(manager=mock_manager)
        composite = CompositeCalendarAdapter([google, apple])
        sources = composite.list_sources()
        assert "GoogleCalendarAdapter" in sources
        assert "AppleCalendarAdapter" in sources


# ---------------------------------------------------------------------------
# Calendar Tools
# ---------------------------------------------------------------------------


class TestCalendarListEventsTool:
    def test_name_and_description(self):
        tool = CalendarListEventsTool()
        assert tool.name == "calendar_list_events"
        assert "calendar" in tool.description.lower()

    def test_execute_no_adapter(self):
        set_calendar(None)
        tool = CalendarListEventsTool()
        result = tool.execute()
        assert result["result"]["count"] == 0
        assert "note" in result["result"]

    def test_execute_with_adapter(self, mock_manager: MagicMock):
        mock_manager.call_tool.return_value = {
            "items": [
                {
                    "id": "e1",
                    "summary": "Test",
                    "start": {"dateTime": "2026-03-18T10:00:00+00:00"},
                    "end": {"dateTime": "2026-03-18T11:00:00+00:00"},
                }
            ]
        }
        google = GoogleCalendarAdapter(manager=mock_manager)
        composite = CompositeCalendarAdapter([google])
        set_calendar(composite)

        tool = CalendarListEventsTool()
        result = tool.execute()
        assert result["result"]["count"] == 1
        assert result["result"]["events"][0]["title"] == "Test"

        set_calendar(None)


class TestCalendarCreateEventTool:
    def test_name_and_description(self):
        tool = CalendarCreateEventTool()
        assert tool.name == "calendar_create_event"

    def test_execute_no_adapter(self):
        set_calendar(None)
        tool = CalendarCreateEventTool()
        result = tool.execute(title="Test", start_datetime="2026-03-19T14:00:00")
        assert "error" in result

    def test_execute_invalid_datetime(self, mock_manager: MagicMock):
        google = GoogleCalendarAdapter(manager=mock_manager)
        composite = CompositeCalendarAdapter([google])
        set_calendar(composite)

        tool = CalendarCreateEventTool()
        result = tool.execute(title="Test", start_datetime="not-a-date")
        assert "error" in result

        set_calendar(None)
