"""Base Calendar Adapter — shared logic for MCP-backed calendar services.

Subclasses override ``_build_list_args``, ``_build_create_args``,
``_parse_events``, and class attributes for API-specific differences.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.mcp.calendar_port import CalendarEvent

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager


class BaseCalendarAdapter:
    """Abstract base for MCP-backed calendar adapters.

    Subclasses MUST define:
        _source:          "google" | "apple"
        _default_server:  Default MCP server name
        _delete_id_key:   Arg key for event ID in delete calls
        _default_calendar: Default calendar name when none specified
    """

    _source: str
    _default_server: str
    _delete_id_key: str
    _default_calendar: str

    def __init__(
        self,
        *,
        manager: MCPServerManager | None = None,
        server_name: str | None = None,
    ) -> None:
        self._manager = manager
        self._server_name = server_name or self._default_server

    # --- Shared methods ---

    def is_available(self) -> bool:
        if self._manager is None:
            return False
        health = self._manager.check_health()
        return health.get(self._server_name, False)

    async def ais_available(self) -> bool:
        """Async availability check for async service callers."""
        return await asyncio.to_thread(self.is_available)

    async def adelete_event(self, event_id: str) -> bool:
        """Async MCP-backed event deletion."""
        if not await self.ais_available():
            return False
        assert self._manager is not None
        try:
            result = await self._manager.acall_tool(
                self._server_name, "delete_event", {self._delete_id_key: event_id}
            )
            return "error" not in result
        except Exception as exc:
            log.warning("%s delete_event failed: %s", self._source.title(), exc)
            return False

    async def alist_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        """Async MCP-backed event listing."""
        if not await self.ais_available():
            return []
        assert self._manager is not None
        now = datetime.now(UTC)
        time_min = (start or now).isoformat()
        time_max = (end or now + timedelta(days=7)).isoformat()
        try:
            args = self._build_list_args(time_min, time_max, max_results, calendar_name)
            result = await self._manager.acall_tool(self._server_name, "list_events", args)
            if "error" in result:
                log.warning("%s list_events error: %s", self._source.title(), result["error"])
                return []
            return self._parse_events(self._extract_event_items(result))
        except Exception as exc:
            log.warning("%s list_events failed: %s", self._source.title(), exc)
            return []

    async def acreate_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        *,
        description: str = "",
        location: str = "",
        calendar_name: str | None = None,
    ) -> CalendarEvent:
        """Async MCP-backed event creation."""
        if not await self.ais_available():
            raise RuntimeError(f"{self._source.title()} MCP server not available")
        assert self._manager is not None
        args = self._build_create_args(title, start, end, description, location, calendar_name)
        result = await self._manager.acall_tool(self._server_name, "create_event", args)
        if "error" in result:
            raise RuntimeError(f"{self._source.title()} create_event failed: {result['error']}")
        return CalendarEvent(
            event_id=self._extract_event_id(result),
            title=title,
            start=start,
            end=end,
            description=description,
            location=location,
            source=self._source,
            calendar_name=calendar_name or self._default_calendar,
            is_geode=title.startswith("[GEODE]"),
        )

    async def alist_calendars(self) -> list[str]:
        """Async MCP-backed calendar listing."""
        if not await self.ais_available():
            return []
        assert self._manager is not None
        try:
            result = await self._manager.acall_tool(self._server_name, "list_calendars", {})
            return self._extract_calendar_names(result)
        except Exception:
            return []

    # --- Template methods for subclass overrides ---

    def _build_list_args(
        self,
        time_min: str,
        time_max: str,
        max_results: int,
        calendar_name: str | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _build_create_args(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str,
        location: str,
        calendar_name: str | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _extract_event_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _extract_event_id(self, result: dict[str, Any]) -> str:
        raise NotImplementedError

    def _extract_calendar_names(self, result: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def _parse_events(self, items: list[dict[str, Any]]) -> list[CalendarEvent]:
        raise NotImplementedError
