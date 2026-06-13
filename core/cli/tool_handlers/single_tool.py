"""Tool handlers that each wrap exactly one tool class.

Absorbed from six sibling files in PR-CLEANUP-5 (2026-05-23):
``data.py`` (synthetic data generation), ``notification.py`` (push
notifications), ``output.py`` (report + JSON export),
``offload.py`` (recall offloaded tool results),
``computer_use.py`` (desktop automation, gated by env flag), and
``calendar.py`` (calendar list/create/sync). Each builder used to
live in its own <50-LOC file purely because the original split
followed "one file per tool surface" — but every builder is the
same shape (instantiate the tool class, wrap its ``aexecute`` in
a closure, return ``{tool_name: handler}``), and they share zero
state. Folding them removes 6 sibling files without coupling any
new code paths.

The ``_build_<area>_handlers`` symbol names are preserved verbatim
so ``core/cli/tool_handlers/__init__.py`` and external callers
(e.g. the tool-handler audit script) keep working unchanged.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# data — generate_data
# ---------------------------------------------------------------------------


def _build_data_handlers() -> dict[str, Any]:
    """Build synthetic data tool handlers."""
    from core.tools.data_tools import GenerateDataTool

    generate_data_tool = GenerateDataTool()

    async def handle_generate_data(**kwargs: Any) -> dict[str, Any]:
        return await generate_data_tool.aexecute(**kwargs)

    return {
        "generate_data": handle_generate_data,
    }


# ---------------------------------------------------------------------------
# notification — send_notification
# ---------------------------------------------------------------------------


def _build_notification_handlers() -> dict[str, Any]:
    """Build notification tool handlers."""
    from core.tools.output_tools import SendNotificationTool

    notification_tool = SendNotificationTool()

    async def handle_send_notification(**kwargs: Any) -> dict[str, Any]:
        return await notification_tool.aexecute(**kwargs)

    return {
        "send_notification": handle_send_notification,
    }


# ---------------------------------------------------------------------------
# output — generate_report, export_json
# ---------------------------------------------------------------------------


def _build_output_handlers() -> dict[str, Any]:
    """Build artifact/output tool handlers."""
    from core.tools.output_tools import ExportJsonTool, GenerateReportTool

    report_tool = GenerateReportTool()
    export_tool = ExportJsonTool()

    async def handle_generate_report(**kwargs: Any) -> dict[str, Any]:
        return await report_tool.aexecute(**kwargs)

    async def handle_export_json(**kwargs: Any) -> dict[str, Any]:
        return await export_tool.aexecute(**kwargs)

    return {
        "generate_report": handle_generate_report,
        "export_json": handle_export_json,
    }


# ---------------------------------------------------------------------------
# offload — recall_tool_result
# ---------------------------------------------------------------------------


def _build_offload_handlers() -> dict[str, Any]:
    """Build recall_tool_result handler for retrieving offloaded tool results."""

    def handle_recall_tool_result(**kwargs: Any) -> dict[str, Any]:
        from core.orchestration.tool_offload import get_offload_store

        ref_id = kwargs.get("ref_id", "")
        if not ref_id:
            return {"error": "ref_id is required"}
        store = get_offload_store()
        if store is None:
            return {"error": "Tool offloading is not enabled in this session"}
        result: dict[str, Any] = store.recall(ref_id)
        return result

    return {
        "recall_tool_result": handle_recall_tool_result,
    }


# ---------------------------------------------------------------------------
# computer_use — desktop automation (env-gated)
# ---------------------------------------------------------------------------


def _build_computer_use_handler() -> dict[str, Any]:
    """Build computer-use handler (screenshot + mouse + keyboard).

    Only active when ``GEODE_COMPUTER_USE_ENABLED=true`` and ``pyautogui`` is
    installed. Returns an empty handler dict otherwise.
    """
    from core.llm.providers.anthropic import is_computer_use_enabled

    if not is_computer_use_enabled():
        return {}

    from core.tools.computer_use import ComputerUseHarness

    harness = ComputerUseHarness()

    async def handle_computer(**kwargs: Any) -> dict[str, Any]:
        # ``pop`` (not ``get``) — ``aexecute(action, **kwargs)`` passes
        # ``action`` positionally, so leaving it in ``kwargs`` raised
        # "got multiple values for argument 'action'" on every non-default
        # call (the tool was never live-exercised, so the crash stayed latent).
        action = kwargs.pop("action", "screenshot")
        return await harness.aexecute(action, **kwargs)

    return {"computer": handle_computer}


# ---------------------------------------------------------------------------
# calendar — list / create / sync-scheduler
# ---------------------------------------------------------------------------


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
