"""Slack Notification Adapter — send messages via Slack MCP server.

Implements NotificationPort for the "slack" channel.
"""

from __future__ import annotations

from core.mcp.base_notification import BaseNotificationAdapter


class SlackNotificationAdapter(BaseNotificationAdapter):
    """Send notifications via Slack MCP server."""

    _channel_name = "slack"
    _default_server = "slack"
    _tool_name = "slack_post_message"
    _message_key = "text"
    _recipient_key = "channel_id"
    _forward_keys = ("thread_ts",)
    _message_id_key = "ts"
