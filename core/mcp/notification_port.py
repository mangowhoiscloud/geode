"""NotificationPort — Protocol interface for messaging adapters.

Defines the contract for sending notifications to external messaging
services (Slack, Discord, Telegram, email, webhook).

Injection is managed via contextvars.
"""

from __future__ import annotations

from contextvars import ContextVar
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


# ---------------------------------------------------------------------------
# contextvars injection
# ---------------------------------------------------------------------------

_notification_ctx: ContextVar[NotificationPort | None] = ContextVar(
    "notification_port", default=None
)
# Process-wide fallback (PR-SLACK-TRANSPORT, 2026-07-15). ContextVars do
# not cross threads, and poller/IPC daemon threads never ran a
# ``set_notification`` — so ``send_notification`` and notification hooks
# fired from those threads silently read None while the gateway (a module
# global) survived. The last adapter set in ANY thread is the process
# fallback, mirroring ``core.messaging.binding.set_gateway``.
_notification_fallback: NotificationPort | None = None


def set_notification(adapter: NotificationPort | None) -> None:
    """Set the active notification adapter (context + process fallback)."""
    global _notification_fallback
    _notification_ctx.set(adapter)
    _notification_fallback = adapter


def get_notification() -> NotificationPort | None:
    """Get the adapter: current context first, then the process fallback."""
    return _notification_ctx.get() or _notification_fallback
