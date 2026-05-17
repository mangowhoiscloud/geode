"""Discord Poller — polls Discord for new messages via MCP server."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from core.channels.models import InboundMessage
from core.server.supervised.poller_base import BasePoller

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.channels.binding import ChannelManager
    from core.mcp.manager import MCPServerManager
    from core.mcp.notification_port import NotificationPort


class DiscordPoller(BasePoller):
    """Poll Discord for new messages via MCP server."""

    _env_config_var = "DISCORD_BOT_TOKEN"

    def __init__(
        self,
        channel_manager: ChannelManager,
        *,
        mcp_manager: MCPServerManager | None = None,
        notification: NotificationPort | None = None,
        poll_interval_s: float = 3.0,
    ) -> None:
        super().__init__(
            channel_manager,
            mcp_manager=mcp_manager,
            notification=notification,
            poll_interval_s=poll_interval_s,
        )
        self._last_id: dict[str, str] = {}  # channel_id → last message id

    @property
    def channel_name(self) -> str:
        return "discord"

    async def _apoll_once(self) -> None:
        if not self._check_mcp_health():
            return

        for binding in self._get_channel_bindings():
            await self._poll_channel(binding["channel_id"])

    async def _poll_channel(self, channel_id: str) -> None:
        """Poll a single Discord channel for new messages."""
        # ``_poll_once`` (caller) gates this method behind
        # ``_check_mcp_health`` which already guarantees ``_mcp is not None``.
        assert self._mcp is not None

        try:
            args: dict[str, Any] = {"channel_id": channel_id, "limit": 5}
            after = self._last_id.get(channel_id)
            if after:
                args["after"] = after

            result = await self._mcp.acall_tool("discord", "get_messages", args)
            if "error" in result:
                return

            messages = result.get("messages", [])
            for msg in messages:
                msg_id = msg.get("id", "")
                # Skip bot messages
                if msg.get("author", {}).get("bot", False):
                    continue
                if msg_id:
                    self._last_id[channel_id] = msg_id

                inbound = InboundMessage(
                    channel="discord",
                    channel_id=channel_id,
                    sender_id=msg.get("author", {}).get("id", ""),
                    sender_name=msg.get("author", {}).get("username", ""),
                    content=msg.get("content", ""),
                    timestamp=time.time(),
                    metadata={"guild_id": msg.get("guild_id", "")},
                )

                response = self._manager.route_message(inbound)

                if response and self._notification:
                    await self._notification.asend_message("discord", channel_id, response)

        except Exception as exc:
            log.debug("Discord poll error for %s: %s", channel_id, exc)
