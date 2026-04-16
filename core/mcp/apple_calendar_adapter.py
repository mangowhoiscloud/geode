"""Apple Calendar Adapter — calendar operations via CalDAV MCP server.

Implements CalendarPort for Apple Calendar / any CalDAV server.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.mcp.base_calendar import BaseCalendarAdapter
from core.mcp.calendar_port import CalendarEvent

log = logging.getLogger(__name__)


class AppleCalendarAdapter(BaseCalendarAdapter):
    """Calendar operations via CalDAV MCP server (Apple Calendar, Nextcloud, etc.)."""

    _source = "apple"
    _default_server = "caldav"
    _delete_id_key = "uid"
    _default_calendar = "default"

    def _build_list_args(
        self, time_min: str, time_max: str, max_results: int, calendar_name: str | None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"start": time_min, "end": time_max, "limit": max_results}
        if calendar_name:
            args["calendar"] = calendar_name
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
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        if description:
            args["description"] = description
        if location:
            args["location"] = location
        if calendar_name:
            args["calendar"] = calendar_name
        return args

    def _extract_event_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = result.get("events", [])
        return items

    def _extract_event_id(self, result: dict[str, Any]) -> str:
        eid: str = result.get("uid", result.get("id", ""))
        return eid

    def _extract_calendar_names(self, result: dict[str, Any]) -> list[str]:
        items = result.get("calendars", [])
        return [c.get("name", c.get("displayName", "")) for c in items]

    def _parse_events(self, items: list[dict[str, Any]]) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for item in items:
            try:
                title = item.get("summary", item.get("title", ""))
                start_str = item.get("start", item.get("dtstart", ""))
                end_str = item.get("end", item.get("dtend", ""))
                events.append(
                    CalendarEvent(
                        event_id=item.get("uid", item.get("id", "")),
                        title=title,
                        start=(
                            datetime.fromisoformat(start_str) if start_str else datetime.now(UTC)
                        ),
                        end=(datetime.fromisoformat(end_str) if end_str else datetime.now(UTC)),
                        description=item.get("description", ""),
                        location=item.get("location", ""),
                        source="apple",
                        calendar_name=item.get("calendar", ""),
                        is_geode=title.startswith("[GEODE]"),
                    )
                )
            except Exception as exc:
                log.debug("Skipping unparseable CalDAV event: %s", exc)
        events.sort(key=lambda e: e.start)
        return events
