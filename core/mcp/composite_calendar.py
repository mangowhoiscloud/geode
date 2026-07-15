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
            if not await _supports(adapter, "read"):
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
        # Native /login-google and the legacy Google Calendar MCP can both
        # point at the same account. Keep compatibility without returning the
        # same Google event twice when both adapters are available.
        unique: dict[tuple[str, str], CalendarEvent] = {}
        for event in merged:
            key = (event.source, event.event_id)
            if not event.event_id:
                key = (event.source, f"{event.start.isoformat()}:{event.title}")
            unique.setdefault(key, event)
        deduplicated = sorted(unique.values(), key=lambda e: e.start)
        return deduplicated[:max_results]

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
            if not await _supports(adapter, "write"):
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
            if not await _supports(adapter, "write"):
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
        return any([await _supports(adapter, "read") for adapter in self._adapters])

    async def alist_calendars(self) -> list[str]:
        calendars: list[str] = []
        for adapter in self._adapters:
            if await _supports(adapter, "read"):
                calendars.extend(await adapter.alist_calendars())
        return calendars

    async def alist_sources(self) -> list[str]:
        """Return names of available calendar source adapters."""
        sources: list[str] = []
        for adapter in self._adapters:
            if await _supports(adapter, "read"):
                sources.append(type(adapter).__name__)
        return sources


async def _supports(adapter: CalendarPort, capability: str) -> bool:
    """Check an optional capability probe, falling back to availability.

    Older adapters expose only ``ais_available`` and are assumed to support
    both reads and writes. Newer adapters can advertise ``acan_read`` and
    ``acan_write`` independently so a read-only source cannot capture a
    mutation intended for a later writable source.
    """
    probe = getattr(adapter, f"acan_{capability}", None)
    if callable(probe):
        return bool(await probe())
    return bool(await adapter.ais_available())
