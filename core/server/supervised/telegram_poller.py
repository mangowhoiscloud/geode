"""Telegram Poller — polls Telegram for new messages via MCP server."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from core.messaging.models import InboundMessage
from core.server.supervised.poller_base import BasePoller

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager
    from core.mcp.notification_port import NotificationPort
    from core.messaging.binding import ChannelManager


class TelegramPoller(BasePoller):
    """Poll Telegram for new messages via MCP server (getUpdates)."""

    _env_config_var = "TELEGRAM_BOT_TOKEN"

    def __init__(
        self,
        channel_manager: ChannelManager,
        *,
        mcp_manager: MCPServerManager | None = None,
        notification: NotificationPort | None = None,
        poll_interval_s: float = 2.0,
    ) -> None:
        super().__init__(
            channel_manager,
            mcp_manager=mcp_manager,
            notification=notification,
            poll_interval_s=poll_interval_s,
        )
        self._last_update_id: int = 0

    @property
    def channel_name(self) -> str:
        return "telegram"

    async def _apoll_once(self) -> None:
        if not self._check_mcp_health():
            return
        # ``_check_mcp_health`` returned True ⇒ ``_mcp is not None``;
        # localise the invariant for mypy.
        assert self._mcp is not None

        try:
            args: dict[str, Any] = {"limit": 10}
            if self._last_update_id:
                args["offset"] = self._last_update_id + 1

            result = await self._mcp.acall_tool("telegram", "get_updates", args)
            if "error" in result:
                return

            updates = result.get("result", result.get("updates", []))
            for update in updates:
                update_id = update.get("update_id", 0)
                self._last_update_id = max(self._last_update_id, update_id)

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

                response = await self._manager.aroute_message(inbound)

                if response and self._notification:
                    await self._notification.asend_message("telegram", chat_id, response)

        except Exception as exc:
            log.debug("Telegram poll error: %s", exc)
