"""Slack Poller — polls Slack for new messages via MCP server."""

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


class SlackPoller(BasePoller):
    """Poll Slack for new messages via MCP server.

    Uses Slack MCP tools to read channel history and detect new messages.
    Sends responses back via NotificationPort.
    """

    def __init__(
        self,
        channel_manager: ChannelManager,
        *,
        mcp_manager: MCPServerManager | None = None,
        notification: NotificationPort | None = None,
        poll_interval_s: float = 3.0,
    ) -> None:
        super().__init__(channel_manager, poll_interval_s=poll_interval_s)
        self._mcp = mcp_manager
        self._notification = notification
        self._last_ts: dict[str, str] = {}  # channel_id → last message ts

    @property
    def channel_name(self) -> str:
        return "slack"

    def is_configured(self) -> bool:
        return bool(os.environ.get("SLACK_BOT_TOKEN"))

    def _poll_once(self) -> None:
        if self._mcp is None:
            return

        health = self._mcp.check_health()
        if not health.get("slack", False):
            return

        # Get channels to monitor from bindings
        bindings = self._manager.list_bindings()
        slack_bindings = [b for b in bindings if b["channel"] == "slack"]

        for binding in slack_bindings:
            channel_id = binding.get("channel_id", "")
            if not channel_id or channel_id == "*":
                continue
            self._poll_channel(channel_id)

    def _poll_channel(self, channel_id: str) -> None:
        """Poll a single Slack channel for new messages."""
        try:
            args: dict[str, Any] = {"channel": channel_id, "limit": 5}
            oldest = self._last_ts.get(channel_id)
            if oldest:
                args["oldest"] = oldest

            result = self._mcp.call_tool("slack", "get_channel_history", args)  # type: ignore[union-attr]
            if "error" in result:
                return

            messages = result.get("messages", [])
            for msg in messages:
                ts = msg.get("ts", "")
                # Skip our own messages (bot messages)
                if msg.get("subtype") == "bot_message":
                    continue
                if ts and (not oldest or ts > oldest):
                    self._last_ts[channel_id] = ts

                inbound = InboundMessage(
                    channel="slack",
                    channel_id=channel_id,
                    sender_id=msg.get("user", ""),
                    sender_name=msg.get("username", msg.get("user", "")),
                    content=msg.get("text", ""),
                    timestamp=float(ts) if ts else time.time(),
                    thread_id=msg.get("thread_ts", ""),
                )

                response = self._manager.route_message(inbound)

                # Send response back if auto_respond is enabled
                if response and self._notification:
                    self._notification.send_message(
                        "slack",
                        channel_id,
                        response,
                        thread_ts=inbound.thread_id or ts,
                    )

        except Exception as exc:
            log.debug("Slack poll error for %s: %s", channel_id, exc)
