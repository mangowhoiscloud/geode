"""Apple Calendar Adapter — calendar operations via CalDAV MCP server.

Implements CalendarPort for Apple Calendar / any CalDAV server.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.infrastructure.ports.calendar_port import CalendarEvent

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.infrastructure.adapters.mcp.manager import MCPServerManager


class AppleCalendarAdapter:
    """Calendar operations via CalDAV MCP server (Apple Calendar, Nextcloud, etc.)."""

    def __init__(
        self,
        *,
        manager: MCPServerManager | None = None,
        server_name: str = "caldav",
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
                "start": time_min,
                "end": time_max,
                "limit": max_results,
            }
            if calendar_name:
                args["calendar"] = calendar_name
            result = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name, "list_events", args
            )
            if "error" in result:
                log.warning("CalDAV list_events error: %s", result["error"])
                return []
            return self._parse_events(result.get("events", []))
        except Exception as exc:
            log.warning("CalDAV list_events failed: %s", exc)
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
            raise RuntimeError("CalDAV MCP server not available")
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

        result = self._manager.call_tool(  # type: ignore[union-attr]
            self._server_name, "create_event", args
        )
        if "error" in result:
            raise RuntimeError(f"CalDAV create_event failed: {result['error']}")

        return CalendarEvent(
            event_id=result.get("uid", result.get("id", "")),
            title=title,
            start=start,
            end=end,
            description=description,
            location=location,
            source="apple",
            calendar_name=calendar_name or "default",
            is_geode=title.startswith("[GEODE]"),
        )

    def delete_event(self, event_id: str) -> bool:
        if not self.is_available():
            return False
        try:
            result = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name, "delete_event", {"uid": event_id}
            )
            return "error" not in result
        except Exception as exc:
            log.warning("CalDAV delete_event failed: %s", exc)
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
            items = result.get("calendars", [])
            return [c.get("name", c.get("displayName", "")) for c in items]
        except Exception:
            return []

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
