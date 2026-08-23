"""NotificationPort — Protocol interface for messaging adapters.

Defines the contract for sending notifications to external messaging
services (Slack, Discord, Telegram, email, webhook).

The runtime composition root injects implementations into the tools that use them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class NotificationResult:
    """Result from a notification send attempt."""

    success: bool
    channel: str  # "slack", "discord", "telegram", "email", "webhook"
    message_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class NotificationPort(Protocol):
    """Async-only port for sending notifications to external messaging services."""

    async def asend_message(
        self,
        channel: str,
        recipient: str,
        message: str,
        *,
        severity: str = "info",
        **kwargs: Any,
    ) -> NotificationResult:
        """Send a message to the specified channel and recipient.

        Args:
            channel: Messaging service name ("slack", "discord", "telegram").
            recipient: Target (channel name, user ID, chat ID, etc.).
            message: Message body text.
            severity: "info", "warning", or "critical".
            **kwargs: Channel-specific options (e.g., thread_ts for Slack).

        Returns:
            NotificationResult with success status and optional message_id.
        """
        ...

    async def ais_available(self, channel: str | None = None) -> bool:
        """Check if the notification service (or a specific channel) is reachable."""
        ...

    def list_channels(self) -> list[str]:
        """Return list of supported channel names."""
        ...
