"""Composite Calendar Adapter — merges events from multiple calendar sources."""

from __future__ import annotations

import logging
from datetime import datetime

from core.mcp.calendar_port import CalendarEvent, CalendarPort

log = logging.getLogger(__name__)


class CompositeCalendarAdapter:
    """Merge calendar events from multiple sources (Google, Apple/CalDAV).

    For reads, events from all available sources are merged and sorted.
    For writes, dispatches to the first available adapter (or specified source).
    Implements CalendarPort.
    """

    def __init__(self, adapters: list[CalendarPort]) -> None:
        self._adapters = adapters

    async def alist_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        """Async event listing across child adapters."""
        merged: list[CalendarEvent] = []
        for adapter in self._adapters:
            if not await adapter.ais_available():
                continue
            try:
                events = await adapter.alist_events(
                    start=start,
                    end=end,
                    calendar_name=calendar_name,
                    max_results=max_results,
                )
                merged.extend(events)
            except Exception as exc:
                log.warning("Calendar adapter %s failed: %s", type(adapter).__name__, exc)
        merged.sort(key=lambda e: e.start)
        return merged[:max_results]

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
        """Async event creation, dispatching to the first available adapter."""
        for adapter in self._adapters:
            if not await adapter.ais_available():
                continue
            return await adapter.acreate_event(
                title,
                start,
                end,
                description=description,
                location=location,
                calendar_name=calendar_name,
            )
        raise RuntimeError("No calendar adapter available")

    async def adelete_event(self, event_id: str) -> bool:
        """Async event deletion across available adapters."""
        for adapter in self._adapters:
            if not await adapter.ais_available():
                continue
            try:
                deleted = await adapter.adelete_event(event_id)
                if deleted:
                    return True
            except Exception as exc:
                log.debug("delete_event failed on %s: %s", type(adapter).__name__, exc)
                continue
        return False

    async def ais_available(self) -> bool:
        return any([await adapter.ais_available() for adapter in self._adapters])

    async def alist_calendars(self) -> list[str]:
        calendars: list[str] = []
        for adapter in self._adapters:
            if await adapter.ais_available():
                calendars.extend(await adapter.alist_calendars())
        return calendars

    async def alist_sources(self) -> list[str]:
        """Return names of available calendar source adapters."""
        sources: list[str] = []
        for adapter in self._adapters:
            if await adapter.ais_available():
                sources.append(type(adapter).__name__)
        return sources
