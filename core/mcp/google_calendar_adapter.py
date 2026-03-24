"""Google Calendar Adapter — calendar operations via Google Calendar MCP server.

Implements CalendarPort for Google Calendar.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.mcp.calendar_port import CalendarEvent

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager


class GoogleCalendarAdapter:
    """Calendar operations via Google Calendar MCP server."""

    def __init__(
        self,
        *,
        manager: MCPServerManager | None = None,
        server_name: str = "google-calendar",
    ) -> None:
        self._manager = manager
        self._server_name = server_name

    def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        if not self.is_available():
            return []
        now = datetime.now(UTC)
        time_min = (start or now).isoformat()
        time_max = (end or now + timedelta(days=7)).isoformat()
        try:
            args: dict[str, Any] = {
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
            }
            if calendar_name:
                args["calendarId"] = calendar_name
            result = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name, "list_events", args
            )
            if "error" in result:
                log.warning("Google Calendar list_events error: %s", result["error"])
                return []
            return self._parse_events(result.get("items", result.get("events", [])))
        except Exception as exc:
            log.warning("Google Calendar list_events failed: %s", exc)
            return []

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        *,
        description: str = "",
        location: str = "",
        calendar_name: str | None = None,
    ) -> CalendarEvent:
        if not self.is_available():
            raise RuntimeError("Google Calendar MCP server not available")
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

        result = self._manager.call_tool(  # type: ignore[union-attr]
            self._server_name, "create_event", args
        )
        if "error" in result:
            raise RuntimeError(f"Google Calendar create_event failed: {result['error']}")

        return CalendarEvent(
            event_id=result.get("id", ""),
            title=title,
            start=start,
            end=end,
            description=description,
            location=location,
            source="google",
            calendar_name=calendar_name or "primary",
            is_geode=title.startswith("[GEODE]"),
        )

    def delete_event(self, event_id: str) -> bool:
        if not self.is_available():
            return False
        try:
            result = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name, "delete_event", {"eventId": event_id}
            )
            return "error" not in result
        except Exception as exc:
            log.warning("Google Calendar delete_event failed: %s", exc)
            return False

    def is_available(self) -> bool:
        if self._manager is None:
            return False
        health = self._manager.check_health()
        return health.get(self._server_name, False)

    def list_calendars(self) -> list[str]:
        if not self.is_available():
            return []
        try:
            result = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name, "list_calendars", {}
            )
            items = result.get("items", result.get("calendars", []))
            return [c.get("summary", c.get("id", "")) for c in items]
        except Exception:
            return []

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
