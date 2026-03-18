"""CalendarPort — Protocol interface for calendar adapters.

Defines the contract for reading/writing calendar events from external
calendar services (Google Calendar, Apple Calendar via CalDAV).

Injection via contextvars follows the same pattern as DomainPort.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class CalendarEvent:
    """Unified calendar event representation."""

    event_id: str
    title: str
    start: datetime
    end: datetime
    description: str = ""
    location: str = ""
    source: str = ""  # "google", "apple", "caldav"
    calendar_name: str = ""
    is_geode: bool = False  # True if prefixed with [GEODE]
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CalendarPort(Protocol):
    """Port for calendar operations (read/write events)."""

    def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        """List events within a time range.

        Args:
            start: Range start (defaults to now).
            end: Range end (defaults to +7 days).
            calendar_name: Filter by calendar name (None = all).
            max_results: Maximum events to return.

        Returns:
            List of CalendarEvent sorted by start time.
        """
        ...

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
        """Create a new calendar event.

        Args:
            title: Event title.
            start: Event start datetime.
            end: Event end datetime.
            description: Optional event description.
            location: Optional location string.
            calendar_name: Target calendar (None = default).

        Returns:
            Created CalendarEvent with assigned event_id.
        """
        ...

    def delete_event(self, event_id: str) -> bool:
        """Delete an event by ID. Returns True if deleted."""
        ...

    def is_available(self) -> bool:
        """Check if the calendar service is reachable."""
        ...

    def list_calendars(self) -> list[str]:
        """Return available calendar names."""
        ...


# ---------------------------------------------------------------------------
# contextvars injection (same pattern as DomainPort)
# ---------------------------------------------------------------------------

_calendar_ctx: ContextVar[CalendarPort | None] = ContextVar("calendar_port", default=None)


def set_calendar(adapter: CalendarPort | None) -> None:
    """Set the active calendar adapter for the current context."""
    _calendar_ctx.set(adapter)


def get_calendar() -> CalendarPort | None:
    """Get the active calendar adapter, or None if not set."""
    return _calendar_ctx.get()
