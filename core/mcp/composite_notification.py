"""Composite Notification Adapter — routes messages to channel-specific adapters."""

from __future__ import annotations

import logging
from typing import Any

from core.mcp.notification_port import NotificationPort, NotificationResult

log = logging.getLogger(__name__)


class CompositeNotificationAdapter:
    """Route notifications to the appropriate channel adapter.

    Each sub-adapter handles one channel (slack, discord, telegram).
    Dispatches based on the ``channel`` parameter in send_message().
    Implements NotificationPort.
    """

    def __init__(self, adapters: list[NotificationPort]) -> None:
        self._adapters = adapters
        self._channel_map: dict[str, NotificationPort] = {}
        for adapter in adapters:
            for ch in adapter.list_channels():
                self._channel_map[ch] = adapter

    async def asend_message(
        self,
        channel: str,
        recipient: str,
        message: str,
        *,
        severity: str = "info",
        **kwargs: Any,
    ) -> NotificationResult:
        """Async notification send through the channel-specific adapter."""
        adapter = self._channel_map.get(channel)
        if adapter is None:
            return NotificationResult(
                success=False,
                channel=channel,
                error=f"No adapter registered for channel '{channel}'",
            )
        if not await adapter.ais_available(channel):
            return NotificationResult(
                success=False,
                channel=channel,
                error=f"Channel '{channel}' not available (transport down or key missing)",
            )
        return await adapter.asend_message(channel, recipient, message, severity=severity, **kwargs)

    async def ais_available(self, channel: str | None = None) -> bool:
        if channel is not None:
            adapter = self._channel_map.get(channel)
            return adapter is not None and await adapter.ais_available(channel)
        for adapter in self._adapters:
            if await adapter.ais_available(None):
                return True
        return False

    def list_channels(self) -> list[str]:
        channels: list[str] = []
        for adapter in self._adapters:
            channels.extend(adapter.list_channels())
        return channels
