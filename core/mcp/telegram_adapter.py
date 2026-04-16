"""Telegram Notification Adapter — send messages via Telegram MCP server.

Implements NotificationPort for the "telegram" channel.
"""

from __future__ import annotations

from core.mcp.base_notification import BaseNotificationAdapter


class TelegramNotificationAdapter(BaseNotificationAdapter):
    """Send notifications via Telegram MCP server."""

    _channel_name = "telegram"
    _default_server = "telegram"
    _tool_name = "send_message"
    _message_key = "text"
    _recipient_key = "chat_id"
    _forward_keys = ("reply_to_message_id",)
    _message_id_key = "message_id"
