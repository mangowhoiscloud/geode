"""Slack Poller — polls Slack for new messages via MCP server."""

from __future__ import annotations

import logging
import os
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
        import json as _json

        try:
            args: dict[str, Any] = {"channel_id": channel_id, "limit": 5}
            oldest = self._last_ts.get(channel_id)
            if oldest:
                args["oldest"] = oldest

            result = self._mcp.call_tool("slack", "slack_get_channel_history", args)  # type: ignore[union-attr]

            # MCP returns {"content": [{"text": "{\"ok\":true,\"messages\":[...]}"}]}
            parsed = result
            if "content" in result and isinstance(result["content"], list):
                try:
                    text = result["content"][0].get("text", "")
                    parsed = _json.loads(text) if text else result
                except (IndexError, _json.JSONDecodeError, KeyError):
                    parsed = result

            if "error" in parsed or not parsed.get("ok", True):
                log.debug("Slack history error: %s", parsed.get("error", "unknown"))
                return

            messages = parsed.get("messages", [])
            if not messages:
                return

            # First poll: seed oldest ts and skip all existing messages
            if not oldest:
                latest_ts = max(m.get("ts", "0") for m in messages)
                self._last_ts[channel_id] = latest_ts
                log.info(
                    "Slack poller seeded ts=%s for %s (%d skipped)",
                    latest_ts,
                    channel_id,
                    len(messages),
                )
                return

            # Process only new messages (newer than oldest)
            new_max_ts = oldest
            for msg in messages:
                ts = msg.get("ts", "")
                if not ts or ts <= oldest:
                    continue
                # Skip bot messages (own messages + other bots)
                if msg.get("subtype") == "bot_message" or "bot_id" in msg:
                    if ts > new_max_ts:
                        new_max_ts = ts
                    continue

                if ts > new_max_ts:
                    new_max_ts = ts

                content = msg.get("text", "").strip()
                if not content:
                    continue

                log.info("Slack message from %s: %s", msg.get("user", "?"), content[:80])

                inbound = InboundMessage(
                    channel="slack",
                    channel_id=channel_id,
                    sender_id=msg.get("user", ""),
                    sender_name=msg.get("username", msg.get("user", "")),
                    content=content,
                    timestamp=float(ts),
                    thread_id=msg.get("thread_ts", ""),
                )

                response = self._manager.route_message(inbound)
                log.info("Processor returned: %s", (response or "")[:80])

                if response:
                    self._send_response(channel_id, response, thread_ts=inbound.thread_id or ts)

            self._last_ts[channel_id] = new_max_ts

        except Exception:
            log.warning("Slack poll error for %s", channel_id, exc_info=True)

    def _send_response(self, channel_id: str, text: str, *, thread_ts: str = "") -> None:
        """Send response back to Slack via the same MCP connection used for polling."""
        if self._mcp is None:
            return
        try:
            args: dict[str, Any] = {"channel_id": channel_id, "text": text}
            if thread_ts:
                args["thread_ts"] = thread_ts
            self._mcp.call_tool("slack", "slack_post_message", args)
            log.info("Slack response sent to %s", channel_id)
        except Exception as exc:
            log.warning("Failed to send Slack response: %s", exc)
