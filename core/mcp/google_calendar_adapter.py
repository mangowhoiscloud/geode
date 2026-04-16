"""Google Calendar Adapter — calendar operations via Google Calendar MCP server.

Implements CalendarPort for Google Calendar.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.mcp.base_calendar import BaseCalendarAdapter
from core.mcp.calendar_port import CalendarEvent

log = logging.getLogger(__name__)


class GoogleCalendarAdapter(BaseCalendarAdapter):
    """Calendar operations via Google Calendar MCP server."""

    _source = "google"
    _default_server = "google-calendar"
    _delete_id_key = "eventId"
    _default_calendar = "primary"

    def _build_list_args(
        self, time_min: str, time_max: str, max_results: int, calendar_name: str | None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": max_results,
        }
        if calendar_name:
            args["calendarId"] = calendar_name
        return args

    def _build_create_args(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str,
        location: str,
        calendar_name: str | None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if description:
            args["description"] = description
        if location:
            args["location"] = location
        if calendar_name:
            args["calendarId"] = calendar_name
        return args

    def _extract_event_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = result.get("items", result.get("events", []))
        return items

    def _extract_event_id(self, result: dict[str, Any]) -> str:
        eid: str = result.get("id", "")
        return eid

    def _extract_calendar_names(self, result: dict[str, Any]) -> list[str]:
        items = result.get("items", result.get("calendars", []))
        return [c.get("summary", c.get("id", "")) for c in items]

    def _parse_events(self, items: list[dict[str, Any]]) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for item in items:
            try:
                start_raw = item.get("start", {})
                end_raw = item.get("end", {})
                start_str = start_raw.get("dateTime", start_raw.get("date", ""))
                end_str = end_raw.get("dateTime", end_raw.get("date", ""))
                title = item.get("summary", "")
                events.append(
                    CalendarEvent(
                        event_id=item.get("id", ""),
                        title=title,
                        start=(
                            datetime.fromisoformat(start_str) if start_str else datetime.now(UTC)
                        ),
                        end=(datetime.fromisoformat(end_str) if end_str else datetime.now(UTC)),
                        description=item.get("description", ""),
                        location=item.get("location", ""),
                        source="google",
                        calendar_name=item.get("organizer", {}).get("displayName", ""),
                        is_geode=title.startswith("[GEODE]"),
                    )
                )
            except Exception as exc:
                log.debug("Skipping unparseable Google Calendar event: %s", exc)
        events.sort(key=lambda e: e.start)
        return events
