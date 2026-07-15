"""Direct Google Calendar adapter tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from core.mcp.google_workspace_calendar import (
    CALENDAR_READ_SCOPE,
    CALENDAR_WRITE_SCOPE,
    GoogleWorkspaceCalendarAdapter,
)


class StubCalendarClient:
    def __init__(
        self,
        *responses: dict[str, Any],
        scopes: tuple[str, ...] = (CALENDAR_READ_SCOPE,),
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.scopes = scopes

    def has_active_account(self) -> bool:
        return True

    def has_any_scope(self, scopes: tuple[str, ...]) -> bool:
        return any(scope in self.scopes for scope in scopes)

    def has_scopes(self, scopes: tuple[str, ...]) -> bool:
        return all(scope in self.scopes for scope in scopes)

    async def request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(204)


def test_list_events_handles_timed_and_all_day_rows() -> None:
    client = StubCalendarClient(
        {
            "items": [
                {
                    "id": "timed",
                    "summary": "Meeting",
                    "start": {"dateTime": "2026-07-16T09:00:00+09:00"},
                    "end": {"dateTime": "2026-07-16T10:00:00+09:00"},
                    "organizer": {"email": "user@example.com"},
                },
                {
                    "id": "all-day",
                    "summary": "Holiday",
                    "start": {"date": "2026-07-17"},
                    "end": {"date": "2026-07-18"},
                },
            ]
        }
    )
    adapter = GoogleWorkspaceCalendarAdapter(client)
    events = asyncio.run(
        adapter.alist_events(
            start=datetime(2026, 7, 16, tzinfo=UTC),
            end=datetime(2026, 7, 19, tzinfo=UTC),
        )
    )
    assert [event.event_id for event in events] == ["timed", "all-day"]
    assert events[1].start == datetime(2026, 7, 17, tzinfo=UTC)
    assert client.calls[0]["any_scope"] is True


def test_create_and_delete_require_calendar_write_scope() -> None:
    client = StubCalendarClient(
        {
            "id": "event-1",
            "summary": "Review",
            "start": {"dateTime": "2026-07-16T10:00:00+00:00"},
            "end": {"dateTime": "2026-07-16T11:00:00+00:00"},
        }
    )
    adapter = GoogleWorkspaceCalendarAdapter(client)
    start = datetime(2026, 7, 16, 10, tzinfo=UTC)
    created = asyncio.run(adapter.acreate_event("Review", start, start.replace(hour=11)))
    assert created.event_id == "event-1"
    assert client.calls[0]["required_scopes"] == (CALENDAR_WRITE_SCOPE,)

    assert asyncio.run(adapter.adelete_event("event/with slash")) is True
    assert client.calls[1]["url"].endswith("event%2Fwith%20slash")
    assert client.calls[1]["required_scopes"] == (CALENDAR_WRITE_SCOPE,)


def test_availability_is_metadata_only() -> None:
    adapter = GoogleWorkspaceCalendarAdapter(StubCalendarClient())
    assert asyncio.run(adapter.ais_available()) is True
    assert asyncio.run(adapter.acan_read()) is True
    assert asyncio.run(adapter.acan_write()) is False
    assert asyncio.run(adapter.alist_calendars()) == ["primary"]

    writable = GoogleWorkspaceCalendarAdapter(StubCalendarClient(scopes=(CALENDAR_WRITE_SCOPE,)))
    assert asyncio.run(writable.acan_read()) is True
    assert asyncio.run(writable.acan_write()) is True
