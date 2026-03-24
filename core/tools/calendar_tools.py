"""Calendar Tools — LLM-callable tools for calendar operations.

Layer 5 tools for calendar management:
- CalendarListEventsTool: List upcoming events (SAFE)
- CalendarCreateEventTool: Create new event (WRITE)
- CalendarSyncSchedulerTool: Sync scheduler jobs ↔ calendar (WRITE)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any


class CalendarListEventsTool:
    """Tool for listing calendar events."""

    @property
    def name(self) -> str:
        return "calendar_list_events"

    @property
    def description(self) -> str:
        return (
            "List upcoming calendar events from Google Calendar or Apple Calendar. "
            "Shows events within a date range. "
            "Examples: '내일 일정 뭐 있어?', 'show my schedule for next week'"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date ISO format (YYYY-MM-DD). Defaults to now.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in ISO format. Defaults to +7 days from start.",
                },
                "calendar_name": {
                    "type": "string",
                    "description": "Filter by calendar name (optional).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum events to return. Default 20.",
                    "default": 20,
                },
            },
            "required": [],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.mcp.calendar_port import get_calendar

        adapter = get_calendar()
        if adapter is None or not adapter.is_available():
            return {
                "result": {
                    "events": [],
                    "count": 0,
                    "note": "No calendar adapter available. Configure credentials.",
                }
            }

        start = _parse_datetime(kwargs.get("start_date"))
        end = _parse_datetime(kwargs.get("end_date"))
        if end is None and start is not None:
            end = start + timedelta(days=7)

        events = adapter.list_events(
            start=start,
            end=end,
            calendar_name=kwargs.get("calendar_name"),
            max_results=kwargs.get("max_results", 20),
        )

        return {
            "result": {
                "events": [
                    {
                        "title": e.title,
                        "start": e.start.isoformat(),
                        "end": e.end.isoformat(),
                        "location": e.location,
                        "source": e.source,
                        "calendar": e.calendar_name,
                        "is_geode": e.is_geode,
                    }
                    for e in events
                ],
                "count": len(events),
            }
        }


class CalendarCreateEventTool:
    """Tool for creating calendar events."""

    @property
    def name(self) -> str:
        return "calendar_create_event"

    @property
    def description(self) -> str:
        return (
            "Create a new event on Google Calendar or Apple Calendar. "
            "Examples: '금요일 3시에 분석 미팅 잡아줘', 'schedule a meeting tomorrow at 2pm'"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title.",
                },
                "start_datetime": {
                    "type": "string",
                    "description": "Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS).",
                },
                "end_datetime": {
                    "type": "string",
                    "description": "End datetime in ISO format. Defaults to +1 hour from start.",
                },
                "description": {
                    "type": "string",
                    "description": "Event description (optional).",
                },
                "location": {
                    "type": "string",
                    "description": "Event location (optional).",
                },
                "calendar_name": {
                    "type": "string",
                    "description": "Target calendar name (optional).",
                },
            },
            "required": ["title", "start_datetime"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.mcp.calendar_port import get_calendar

        adapter = get_calendar()
        if adapter is None or not adapter.is_available():
            return {"error": "No calendar adapter available. Configure credentials."}

        title: str = kwargs["title"]
        start = _parse_datetime(kwargs["start_datetime"])
        if start is None:
            return {"error": "Invalid start_datetime format. Use ISO format."}

        end = _parse_datetime(kwargs.get("end_datetime"))
        if end is None:
            end = start + timedelta(hours=1)

        try:
            event = adapter.create_event(
                title,
                start,
                end,
                description=kwargs.get("description", ""),
                location=kwargs.get("location", ""),
                calendar_name=kwargs.get("calendar_name"),
            )
            return {
                "result": {
                    "created": True,
                    "event_id": event.event_id,
                    "title": event.title,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                    "source": event.source,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            }
        except Exception as exc:
            return {"error": f"Failed to create event: {exc}"}


class CalendarSyncSchedulerTool:
    """Tool for syncing GEODE scheduler jobs with external calendars."""

    @property
    def name(self) -> str:
        return "calendar_sync_scheduler"

    @property
    def description(self) -> str:
        return (
            "Synchronize GEODE scheduled jobs with external calendar. "
            "Push: creates [GEODE]-prefixed calendar events from scheduler jobs. "
            "Pull: imports [GEODE]-prefixed calendar events as scheduler jobs."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["push", "pull", "both"],
                    "description": "push (scheduler→calendar), pull, or both.",
                    "default": "both",
                },
            },
            "required": [],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        from core.orchestration.calendar_bridge import get_calendar_bridge

        bridge = get_calendar_bridge()
        if bridge is None:
            return {"error": "Calendar bridge not available. Configure scheduler + calendar."}

        direction: str = kwargs.get("direction", "both")
        try:
            result = bridge.sync(direction=direction)
            return {"result": result}
        except Exception as exc:
            return {"error": f"Calendar sync failed: {exc}"}


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string, return None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None
