"""Notification tool handler — send_notification."""

from __future__ import annotations

from typing import Any


def _build_notification_handlers() -> dict[str, Any]:
    """Build notification tool handlers."""
    from core.tools.output_tools import SendNotificationTool

    notification_tool = SendNotificationTool()

    async def handle_send_notification(**kwargs: Any) -> dict[str, Any]:
        return await notification_tool.aexecute(**kwargs)

    return {
        "send_notification": handle_send_notification,
    }
