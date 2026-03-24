"""Composite Calendar Adapter — merges events from multiple calendar sources.

Same pattern as CompositeSignalAdapter: chains multiple CalendarPort
implementations and merges results.
"""

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

    def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        merged: list[CalendarEvent] = []
        for adapter in self._adapters:
            if not adapter.is_available():
                continue
            try:
                events = adapter.list_events(
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
        for adapter in self._adapters:
            if adapter.is_available():
                return adapter.create_event(
                    title,
                    start,
                    end,
                    description=description,
                    location=location,
                    calendar_name=calendar_name,
                )
        raise RuntimeError("No calendar adapter available")

    def delete_event(self, event_id: str) -> bool:
        for adapter in self._adapters:
            if adapter.is_available():
                try:
                    if adapter.delete_event(event_id):
                        return True
                except Exception as exc:
                    log.debug("delete_event failed on %s: %s", type(adapter).__name__, exc)
                    continue
        return False

    def is_available(self) -> bool:
        return any(a.is_available() for a in self._adapters)

    def list_calendars(self) -> list[str]:
        calendars: list[str] = []
        for adapter in self._adapters:
            if adapter.is_available():
                calendars.extend(adapter.list_calendars())
        return calendars

    def list_sources(self) -> list[str]:
        """Return names of available calendar source adapters."""
        sources: list[str] = []
        for adapter in self._adapters:
            if adapter.is_available():
                sources.append(type(adapter).__name__)
        return sources
