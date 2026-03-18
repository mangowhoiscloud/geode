"""Telegram Poller — polls Telegram for new messages via MCP server."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from core.gateway.models import InboundMessage
from core.gateway.pollers.base import BasePoller

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.gateway.channel_manager import ChannelManager
    from core.infrastructure.adapters.mcp.manager import MCPServerManager
    from core.infrastructure.ports.notification_port import NotificationPort


class TelegramPoller(BasePoller):
    """Poll Telegram for new messages via MCP server (getUpdates)."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        *,
        mcp_manager: MCPServerManager | None = None,
        notification: NotificationPort | None = None,
        poll_interval_s: float = 2.0,
    ) -> None:
        super().__init__(channel_manager, poll_interval_s=poll_interval_s)
        self._mcp = mcp_manager
        self._notification = notification
        self._last_update_id: int = 0

    @property
    def channel_name(self) -> str:
        return "telegram"

    def is_configured(self) -> bool:
        return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))

    def _poll_once(self) -> None:
        if self._mcp is None:
            return

        health = self._mcp.check_health()
        if not health.get("telegram", False):
            return

        try:
            args: dict[str, Any] = {"limit": 10}
            if self._last_update_id:
                args["offset"] = self._last_update_id + 1

            result = self._mcp.call_tool("telegram", "get_updates", args)
            if "error" in result:
                return

            updates = result.get("result", result.get("updates", []))
            for update in updates:
                update_id = update.get("update_id", 0)
                if update_id > self._last_update_id:
                    self._last_update_id = update_id

                message = update.get("message", {})
                if not message:
                    continue

                chat = message.get("chat", {})
                chat_id = str(chat.get("id", ""))
                sender = message.get("from", {})

                inbound = InboundMessage(
                    channel="telegram",
                    channel_id=chat_id,
                    sender_id=str(sender.get("id", "")),
                    sender_name=sender.get("first_name", sender.get("username", "")),
                    content=message.get("text", ""),
                    timestamp=float(message.get("date", time.time())),
                )

                response = self._manager.route_message(inbound)

                if response and self._notification:
                    self._notification.send_message("telegram", chat_id, response)

        except Exception as exc:
            log.debug("Telegram poll error: %s", exc)
