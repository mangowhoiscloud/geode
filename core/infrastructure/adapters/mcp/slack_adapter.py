"""Slack Notification Adapter — send messages via Slack MCP server.

Implements NotificationPort for the "slack" channel.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.infrastructure.ports.notification_port import NotificationResult

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.infrastructure.adapters.mcp.manager import MCPServerManager


class SlackNotificationAdapter:
    """Send notifications via Slack MCP server."""

    def __init__(
        self,
        *,
        manager: MCPServerManager | None = None,
        server_name: str = "slack",
    ) -> None:
        self._manager = manager
        self._server_name = server_name

    def send_message(
        self,
        channel: str,
        recipient: str,
        message: str,
        *,
        severity: str = "info",
        **kwargs: Any,
    ) -> NotificationResult:
        if not self.is_available():
            return NotificationResult(
                success=False, channel="slack", error="Slack MCP server not available"
            )
        try:
            result = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name,
                "send_message",
                {"channel": recipient, "text": message},
            )
            if "error" in result:
                return NotificationResult(
                    success=False, channel="slack", error=result["error"]
                )
            return NotificationResult(
                success=True,
                channel="slack",
                message_id=result.get("ts"),
                metadata={"recipient": recipient},
            )
        except Exception as exc:
            log.warning("Slack send_message failed: %s", exc)
            return NotificationResult(
                success=False, channel="slack", error=str(exc)
            )

    def is_available(self, channel: str | None = None) -> bool:
        if self._manager is None:
            return False
        health = self._manager.check_health()
        return health.get(self._server_name, False)

    def list_channels(self) -> list[str]:
        return ["slack"]
