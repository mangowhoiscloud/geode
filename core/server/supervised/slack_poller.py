"""Slack inbound receiver — Socket Mode with a polling compatibility fallback.

When ``SLACK_APP_TOKEN`` is configured, Slack pushes Events API envelopes over
Socket Mode and this receiver performs no ``conversations.history`` polling.
The existing bot-token Web API transport remains the single outbound owner.

Deployments that haven't provisioned an app-level ``xapp-`` token yet retain
the old polling path with an explicit degraded-mode warning. This compatibility
fallback can be removed after the migration window.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from core.messaging.models import InboundMessage
from core.messaging.slack_socket_mode import SlackSocketModeClient
from core.messaging.slack_transport import SlackTransportError
from core.server.supervised.poller_base import BasePoller

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager
    from core.mcp.notification_port import NotificationPort
    from core.messaging.binding import ChannelManager


class SlackPoller(BasePoller):
    """Receive Slack messages through Socket Mode or the legacy poll fallback."""

    DEDUP_TTL_S = 300
    THREAD_CONTINUATION_TTL_S = 7 * 24 * 60 * 60
    THREAD_CONTINUATION_MAX = 5000
    POLL_CHANNEL_ERROR_COOLDOWN_S = 60.0
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
        self._socket_mode = SlackSocketModeClient()
        self._last_ts: dict[str, str] = {}
        self._seen_events: dict[str, float] = {}
        self._inflight_events: set[str] = set()
        self._engaged_threads: dict[tuple[str, str], float] = {}
        self._poll_retry_after: dict[str, float] = {}

    @property
    def channel_name(self) -> str:
        return "slack"

    @property
    def inbound_mode(self) -> str:
        """The mode selected at process startup."""
        return "socket_mode" if self._socket_mode.configured else "polling_fallback"

    def is_configured(self) -> bool:
        """Configured when the outbound bot token resolves from env or dotenv."""
        return bool(self._transport.configured)

    async def _run_loop_async(self) -> None:
        if self._socket_mode.configured:
            log.info("Slack inbound mode: Socket Mode (push)")
            await self._socket_mode.run(
                self._handle_socket_event,
                self._stop_event.is_set,
            )
            return

        log.warning(
            "Slack inbound mode: polling fallback (SLACK_APP_TOKEN not set, interval=%.1fs)",
            self._poll_interval,
        )
        await super()._run_loop_async()

    # --- Socket Mode -----------------------------------------------------

    async def _handle_socket_event(self, payload: dict[str, Any]) -> None:
        """Normalize one Events API callback after the envelope was ACKed."""
        event = payload.get("event")
        if not isinstance(event, dict):
            return
        if event.get("type") not in {"message", "app_mention"}:
            return

        channel_id = str(event.get("channel", ""))
        if not channel_id or not self._is_bound_channel(channel_id):
            return

        self._evict_stale_dedup()
        timestamp = str(event.get("ts") or event.get("event_ts") or "")
        event_id = str(payload.get("event_id", ""))
        if event.get("type") == "app_mention":
            # The event type itself is authoritative mention evidence. Keep
            # routing correct even when the optional auth.test bot-ID lookup
            # failed during bootstrap; ChannelManager strips this marker
            # before sending content to the model.
            event = {**event, "text": f"@geode {event.get('text', '')}"}
        # Slack may deliver one mention as both ``message`` and
        # ``app_mention`` with different event IDs but the same message ts.
        dedup_key = f"{channel_id}:{timestamp}" if timestamp else event_id
        await self._process_message(channel_id, event, dedup_key=dedup_key)

    def _is_bound_channel(self, channel_id: str) -> bool:
        return any(binding["channel_id"] == channel_id for binding in self._get_channel_bindings())

    # --- Polling fallback ------------------------------------------------

    async def _apoll_once(self) -> None:
        if not await self._transport.ais_available():
            return

        self._evict_stale_dedup()
        for binding in self._get_channel_bindings():
            await self._poll_channel(binding["channel_id"])

    async def _poll_channel(self, channel_id: str) -> None:
        """Poll a single channel while a deployment is awaiting an app token."""
        now = time.monotonic()
        if now < self._poll_retry_after.get(channel_id, 0.0):
            return

        try:
            oldest = self._last_ts.get(channel_id)
            messages = await self._transport.channel_history(
                channel_id,
                oldest=oldest or "",
                limit=5,
            )
            self._poll_retry_after.pop(channel_id, None)
            if not messages:
                return

            if not oldest:
                latest_ts = max(str(message.get("ts", "0")) for message in messages)
                self._last_ts[channel_id] = latest_ts
                log.info(
                    "Slack polling fallback seeded ts=%s for %s (%d skipped)",
                    latest_ts,
                    channel_id,
                    len(messages),
                )
                return

            new_messages = sorted(
                [message for message in messages if str(message.get("ts", "0")) > oldest],
                key=lambda message: str(message.get("ts", "0")),
            )
            for message in new_messages:
                timestamp = str(message.get("ts", ""))
                if not timestamp:
                    continue
                processed = await self._process_message(
                    channel_id,
                    message,
                    dedup_key=f"{channel_id}:{timestamp}",
                )
                if not processed:
                    break
                self._last_ts[channel_id] = timestamp
        except SlackTransportError as exc:
            if any(code in str(exc) for code in ("not_in_channel", "channel_not_found")):
                self._poll_retry_after[channel_id] = (
                    time.monotonic() + self.POLL_CHANNEL_ERROR_COOLDOWN_S
                )
                log.warning(
                    "Slack polling fallback paused for %s (%s); invite the bot to the channel",
                    channel_id,
                    exc,
                )
                return
            log.warning("Slack poll error for %s: %s", channel_id, exc)
        except Exception:
            log.warning("Slack poll error for %s", channel_id, exc_info=True)

    # --- Shared message path --------------------------------------------

    async def _process_message(
        self,
        channel_id: str,
        message: dict[str, Any],
        *,
        dedup_key: str,
    ) -> bool:
        """Route one Slack message. ``False`` asks polling to retry it later."""
        timestamp = str(message.get("ts") or message.get("event_ts") or "")
        if not timestamp:
            return True
        if dedup_key in self._seen_events or dedup_key in self._inflight_events:
            return True
        if message.get("subtype") == "bot_message" or "bot_id" in message:
            return True

        content = str(message.get("text", "")).strip()
        if not content:
            return True

        try:
            parsed_timestamp = float(timestamp)
        except ValueError:
            log.warning("Slack ignored message with invalid timestamp")
            return True

        self._inflight_events.add(dedup_key)
        log.info("Slack message from %s: %s", message.get("user", "?"), content[:80])

        raw_thread_id = str(message.get("thread_ts", ""))
        # GEODE always replies to a top-level Slack message in a thread. Use
        # that root timestamp from the first turn onward so its session/lane/
        # checkpoint key is identical to every later thread reply.
        thread_id = raw_thread_id or timestamp
        inbound = InboundMessage(
            channel="slack",
            channel_id=channel_id,
            sender_id=str(message.get("user", "")),
            sender_name=str(message.get("username", message.get("user", ""))),
            content=content,
            timestamp=parsed_timestamp,
            thread_id=thread_id,
        )
        is_mention = self._manager._is_mentioned(inbound)
        is_thread_reply = bool(raw_thread_id and raw_thread_id != timestamp)
        is_thread_continuation = is_thread_reply and (
            self._is_engaged_thread(channel_id, thread_id)
            or self._manager.has_persisted_session(inbound)
        )
        is_addressed = is_mention or is_thread_continuation

        # A top-level mention becomes the root of the response thread. A
        # mention inside an existing thread engages that root instead. Record
        # it before awaiting the agent so a quick follow-up cannot race the
        # first response and get dropped by the mention gate.
        if is_addressed:
            self._remember_engaged_thread(channel_id, thread_id)

        if is_addressed:
            await self._add_reaction(channel_id, timestamp, "eyes")

        try:
            response = await self._manager.aroute_message(
                inbound,
                mention_override=is_thread_continuation,
            )
            log.info("Processor returned: %s", (response or "")[:80])
            if is_addressed:
                await self._add_reaction(channel_id, timestamp, "white_check_mark")
            if response:
                await self._send_response(
                    channel_id,
                    response,
                    thread_ts=thread_id,
                )
        except Exception as exc:
            log.warning("Failed to process Slack message ts=%s: %s", timestamp, exc)
            if is_addressed:
                await self._add_reaction(channel_id, timestamp, "x")
            return False
        finally:
            self._inflight_events.discard(dedup_key)

        self._seen_events[dedup_key] = time.monotonic()
        return True

    def _is_engaged_thread(self, channel_id: str, thread_ts: str) -> bool:
        """Return whether GEODE is already participating in this Slack thread."""
        now = time.monotonic()
        self._evict_stale_threads(now)
        return (channel_id, thread_ts) in self._engaged_threads

    def _remember_engaged_thread(self, channel_id: str, thread_ts: str) -> None:
        """Remember a mention-started thread with bounded, channel-scoped state."""
        if not channel_id or not thread_ts:
            return
        now = time.monotonic()
        self._evict_stale_threads(now)
        self._engaged_threads[(channel_id, thread_ts)] = now
        excess = len(self._engaged_threads) - self.THREAD_CONTINUATION_MAX
        if excess > 0:
            oldest = sorted(self._engaged_threads, key=self._engaged_threads.__getitem__)[:excess]
            for key in oldest:
                del self._engaged_threads[key]

    def _evict_stale_threads(self, now: float) -> None:
        stale = [
            key
            for key, seen_at in self._engaged_threads.items()
            if now - seen_at > self.THREAD_CONTINUATION_TTL_S
        ]
        for key in stale:
            del self._engaged_threads[key]

    def _evict_stale_dedup(self) -> None:
        now = time.monotonic()
        stale = [
            key for key, seen_at in self._seen_events.items() if now - seen_at > self.DEDUP_TTL_S
        ]
        for key in stale:
            del self._seen_events[key]

    async def _add_reaction(self, channel_id: str, message_ts: str, emoji: str) -> None:
        try:
            await self._transport.add_reaction(channel_id, message_ts, emoji)
        except Exception:
            log.debug("add_reaction failed for %s", channel_id)

    async def _send_response(self, channel_id: str, text: str, *, thread_ts: str = "") -> None:
        try:
            await self._transport.post_message(
                channel_id,
                text,
                thread_ts=thread_ts,
            )
            log.info("Slack response sent to %s", channel_id)
        except Exception as exc:
            log.warning("Failed to send Slack response: %s", exc)
