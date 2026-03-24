"""Telegram Notification Adapter — send messages via Telegram MCP server.

Implements NotificationPort for the "telegram" channel.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.mcp.notification_port import NotificationResult

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager


class TelegramNotificationAdapter:
    """Send notifications via Telegram MCP server."""

    def __init__(
        self,
        *,
        manager: MCPServerManager | None = None,
        server_name: str = "telegram",
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
                success=False,
                channel="telegram",
                error="Telegram MCP server not available",
            )
        try:
            args: dict[str, Any] = {"chat_id": recipient, "text": message}
            for key in ("reply_to_message_id",):
                if key in kwargs:
                    args[key] = kwargs[key]

            raw = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name,
                "send_message",
                args,
            )
            result = self._parse_mcp_result(raw)
            if "error" in result:
                return NotificationResult(success=False, channel="telegram", error=result["error"])
            return NotificationResult(
                success=True,
                channel="telegram",
                message_id=str(result.get("message_id", "")),
                metadata={"recipient": recipient},
            )
        except Exception as exc:
            log.warning("Telegram send_message failed: %s", exc)
            return NotificationResult(success=False, channel="telegram", error=str(exc))

    def is_available(self, channel: str | None = None) -> bool:
        if self._manager is None:
            return False
        health = self._manager.check_health()
        return health.get(self._server_name, False)

    def list_channels(self) -> list[str]:
        return ["telegram"]

    @staticmethod
    def _parse_mcp_result(raw: dict[str, Any]) -> dict[str, Any]:
        """Parse MCP content wrapper."""
        import json

        if "content" in raw and isinstance(raw["content"], list):
            try:
                text = raw["content"][0].get("text", "")
                return json.loads(text) if text else raw
            except (IndexError, json.JSONDecodeError, KeyError):
                pass
        return raw
