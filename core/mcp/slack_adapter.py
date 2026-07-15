"""Slack Notification Adapter — direct Web API send (PR-SLACK-TRANSPORT).

Implements NotificationPort for the "slack" channel over
:class:`core.messaging.slack_transport.SlackTransport`. Previously an
MCP-backed :class:`BaseNotificationAdapter` subclass — that path was dead
at runtime because the ``slack`` MCP server lost its 10s startup race on
every boot (see slack_transport module docstring). Module/class names are
kept so registry wiring and callers are untouched.
"""

from __future__ import annotations

import logging
from typing import Any

from core.mcp.notification_port import NotificationResult

log = logging.getLogger(__name__)


class SlackNotificationAdapter:
    """Send notifications straight to the Slack Web API."""

    _channel_name = "slack"

    def __init__(self, *, transport: Any | None = None) -> None:
        from core.messaging.slack_transport import get_slack_transport

        self._transport = transport or get_slack_transport()

    async def asend_message(
        self,
        channel: str,
        recipient: str,
        message: str,
        *,
        severity: str = "info",
        **kwargs: Any,
    ) -> NotificationResult:
        """Post *message* to *recipient* (channel id or #name)."""
        if not self._transport.configured:
            return NotificationResult(
                success=False, channel="slack", error="SLACK_BOT_TOKEN not configured"
            )
        try:
            data = await self._transport.post_message(
                recipient,
                message,
                thread_ts=str(kwargs.get("thread_ts", "")),
            )
            ts = data.get("ts")
            return NotificationResult(
                success=True,
                channel="slack",
                message_id=str(ts) if ts is not None else None,
                metadata={"recipient": recipient},
            )
        except Exception as exc:
            log.warning("Slack send_message failed: %s", exc)
            return NotificationResult(success=False, channel="slack", error=str(exc))

    async def ais_available(self, channel: str | None = None) -> bool:
        return bool(await self._transport.ais_available())

    def is_available(self, channel: str | None = None) -> bool:
        """Sync availability: configuration only (no event-loop hop)."""
        return bool(self._transport.configured)

    def list_channels(self) -> list[str]:
        return [self._channel_name]
