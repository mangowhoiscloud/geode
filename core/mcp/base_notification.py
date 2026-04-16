"""Base Notification Adapter — shared logic for MCP-backed messaging channels.

Subclasses define channel-specific class attributes; the base handles
MCP call orchestration, error handling, availability checks, and result parsing.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from core.mcp.notification_port import NotificationResult

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager


def parse_mcp_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse MCP content wrapper: {"content":[{"text":"{...}"}]} -> inner dict."""
    if "content" in raw and isinstance(raw["content"], list):
        try:
            text = raw["content"][0].get("text", "")
            return json.loads(text) if text else raw
        except (IndexError, json.JSONDecodeError, KeyError):
            pass
    return raw


class BaseNotificationAdapter:
    """Abstract base for MCP-backed notification adapters.

    Subclasses MUST define these class attributes:
        _channel_name:   "slack" | "discord" | "telegram"
        _default_server: Default MCP server name
        _tool_name:      MCP tool to call for sending
        _message_key:    Arg key for message body ("text" or "content")
        _recipient_key:  Arg key for destination ("channel_id" or "chat_id")
        _forward_keys:   Tuple of kwargs to forward (e.g. ("thread_ts",))
        _message_id_key: Result key for sent message ID ("ts", "id", ...)
    """

    _channel_name: str
    _default_server: str
    _tool_name: str
    _message_key: str
    _recipient_key: str
    _forward_keys: tuple[str, ...] = ()
    _message_id_key: str

    def __init__(
        self,
        *,
        manager: MCPServerManager | None = None,
        server_name: str | None = None,
    ) -> None:
        self._manager = manager
        self._server_name = server_name or self._default_server

    def send_message(
        self,
        channel: str,
        recipient: str,
        message: str,
        *,
        severity: str = "info",
        **kwargs: Any,
    ) -> NotificationResult:
        ch = self._channel_name
        if not self.is_available():
            return NotificationResult(
                success=False, channel=ch, error=f"{ch.title()} MCP server not available"
            )
        try:
            args: dict[str, Any] = {self._recipient_key: recipient, self._message_key: message}
            for key in self._forward_keys:
                if key in kwargs:
                    args[key] = kwargs[key]

            raw = self._manager.call_tool(  # type: ignore[union-attr]
                self._server_name,
                self._tool_name,
                args,
            )
            result = parse_mcp_result(raw)
            if "error" in result:
                return NotificationResult(success=False, channel=ch, error=result["error"])
            msg_id = result.get(self._message_id_key)
            return NotificationResult(
                success=True,
                channel=ch,
                message_id=str(msg_id) if msg_id is not None else None,
                metadata={"recipient": recipient},
            )
        except Exception as exc:
            log.warning("%s send_message failed: %s", ch.title(), exc)
            return NotificationResult(success=False, channel=ch, error=str(exc))

    def is_available(self, channel: str | None = None) -> bool:
        if self._manager is None:
            return False
        health = self._manager.check_health()
        return health.get(self._server_name, False)

    def list_channels(self) -> list[str]:
        return [self._channel_name]
