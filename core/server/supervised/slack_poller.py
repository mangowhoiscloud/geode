"""Slack Poller — polls Slack channels via the direct Web API transport.

PR-SLACK-TRANSPORT (2026-07-15): previously polled through the ``slack``
MCP server, which lost a 10s startup race on every daemon boot and left
this poller as a silent no-op behind its health gate. Now consumes
:class:`core.messaging.slack_transport.SlackTransport` directly; the MCP
manager argument is accepted for BasePoller signature compatibility but
unused. Inbound remains polling (Socket Mode needs an app-level xapp
token the deployment does not have yet — documented follow-up).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from core.messaging.models import InboundMessage
from core.server.supervised.poller_base import BasePoller

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager
    from core.mcp.notification_port import NotificationPort
    from core.messaging.binding import ChannelManager


class SlackPoller(BasePoller):
    """Poll Slack channels for new messages via the Web API transport."""

    DEDUP_TTL_S = 300  # 5 minutes — matches Kiki's event dedup window
    _env_config_var = "SLACK_BOT_TOKEN"

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
        from core.messaging.slack_transport import get_slack_transport

        self._transport = get_slack_transport()
        self._last_ts: dict[str, str] = {}  # channel_id → last message ts
        self._seen_events: dict[str, float] = {}  # "channel:ts" → seen_at (dedup)

    @property
    def channel_name(self) -> str:
        return "slack"

    async def _apoll_once(self) -> None:
        if not await self._transport.ais_available():
            return

        # Evict expired dedup entries
        self._evict_stale_dedup()

        for binding in self._get_channel_bindings():
            await self._poll_channel(binding["channel_id"])

    async def _poll_channel(self, channel_id: str) -> None:
        """Poll a single Slack channel for new messages.

        Deferred-ts pattern: timestamp is updated AFTER each message is
        successfully processed. If processing fails mid-batch, unprocessed
        messages will be re-fetched on the next poll cycle.
        """
        try:
            oldest = self._last_ts.get(channel_id)
            messages = await self._transport.channel_history(
                channel_id, oldest=oldest or "", limit=5
            )
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

            # Collect new messages, sorted by timestamp (oldest first)
            new_messages = sorted(
                [m for m in messages if m.get("ts", "0") > oldest],
                key=lambda m: m.get("ts", "0"),
            )
            if not new_messages:
                return

            # Process each message; advance ts only AFTER successful processing.
            # On failure, break — unprocessed messages re-fetched next cycle.
            for msg in new_messages:
                ts = msg.get("ts", "")
                if not ts:
                    continue

                # Dedup: skip already-processed messages (prevents re-processing
                # on crash/restart within TTL window)
                dedup_key = f"{channel_id}:{ts}"
                if dedup_key in self._seen_events:
                    self._last_ts[channel_id] = ts
                    continue

                # Skip bot messages (own messages + other bots)
                if msg.get("subtype") == "bot_message" or "bot_id" in msg:
                    self._last_ts[channel_id] = ts
                    continue

                content = msg.get("text", "").strip()
                if not content:
                    self._last_ts[channel_id] = ts
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

                is_mention = self._manager._is_mentioned(inbound)
                if is_mention:
                    await self._add_reaction(channel_id, ts, "eyes")

                try:
                    response = await self._manager.aroute_message(inbound)
                    log.info("Processor returned: %s", (response or "")[:80])
                    if is_mention:
                        await self._add_reaction(channel_id, ts, "white_check_mark")

                    if response:
                        await self._send_response(
                            channel_id,
                            response,
                            thread_ts=inbound.thread_id or ts,
                        )
                except Exception as exc:
                    log.warning("Failed to process message ts=%s: %s", ts, exc)
                    # Error reaction: X emoji for visible failure feedback
                    if is_mention:
                        await self._add_reaction(channel_id, ts, "x")
                    break

                # Advance ts + mark as seen (dedup) only after success
                self._last_ts[channel_id] = ts
                self._seen_events[dedup_key] = time.monotonic()

        except Exception:
            log.warning("Slack poll error for %s", channel_id, exc_info=True)

    def _evict_stale_dedup(self) -> None:
        """Remove dedup entries older than TTL."""
        now = time.monotonic()
        stale = [k for k, v in self._seen_events.items() if now - v > self.DEDUP_TTL_S]
        for k in stale:
            del self._seen_events[k]

    async def _add_reaction(self, channel_id: str, message_ts: str, emoji: str) -> None:
        """Add a reaction emoji to a message (best-effort, non-blocking)."""
        try:
            await self._transport.add_reaction(channel_id, message_ts, emoji)
        except Exception:
            log.debug("add_reaction failed for %s", channel_id)

    async def _send_response(self, channel_id: str, text: str, *, thread_ts: str = "") -> None:
        """Send the routed response back through the Web API transport."""
        try:
            await self._transport.post_message(
                channel_id,
                text,
                thread_ts=thread_ts,
            )
            log.info("Slack response sent to %s", channel_id)
        except Exception as exc:
            log.warning("Failed to send Slack response: %s", exc)
