"""Discord Notification Adapter — send messages via Discord MCP server.

Implements NotificationPort for the "discord" channel.
"""

from __future__ import annotations

from core.mcp.base_notification import BaseNotificationAdapter


class DiscordNotificationAdapter(BaseNotificationAdapter):
    """Send notifications via Discord MCP server."""

    _channel_name = "discord"
    _default_server = "discord"
    _tool_name = "send_message"
    _message_key = "content"
    _recipient_key = "channel_id"
    _forward_keys = ("message_reference",)
    _message_id_key = "id"
