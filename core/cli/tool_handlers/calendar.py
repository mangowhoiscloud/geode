"""Calendar tool handlers — list/create events, sync to scheduler."""

from __future__ import annotations

from typing import Any


def _build_calendar_handlers() -> dict[str, Any]:
    """Build calendar tool handlers."""
    from core.tools.calendar_tools import (
        CalendarCreateEventTool,
        CalendarListEventsTool,
        CalendarSyncSchedulerTool,
    )

    list_tool = CalendarListEventsTool()
    create_tool = CalendarCreateEventTool()
    sync_tool = CalendarSyncSchedulerTool()

    async def handle_calendar_list_events(**kwargs: Any) -> dict[str, Any]:
        return await list_tool.aexecute(**kwargs)

    async def handle_calendar_create_event(**kwargs: Any) -> dict[str, Any]:
        return await create_tool.aexecute(**kwargs)

    async def handle_calendar_sync_scheduler(**kwargs: Any) -> dict[str, Any]:
        return await sync_tool.aexecute(**kwargs)

    return {
        "calendar_list_events": handle_calendar_list_events,
        "calendar_create_event": handle_calendar_create_event,
        "calendar_sync_scheduler": handle_calendar_sync_scheduler,
    }
