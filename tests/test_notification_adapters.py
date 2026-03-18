"""Tests for notification adapters (Slack, Discord, Telegram, Composite).

Phase 2 validation: NotificationPort implementations + CompositeNotificationAdapter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.infrastructure.adapters.mcp.composite_notification import (
    CompositeNotificationAdapter,
)
from core.infrastructure.adapters.mcp.discord_adapter import DiscordNotificationAdapter
from core.infrastructure.adapters.mcp.slack_adapter import SlackNotificationAdapter
from core.infrastructure.adapters.mcp.telegram_adapter import TelegramNotificationAdapter
from core.infrastructure.ports.notification_port import (
    NotificationPort,
    NotificationResult,
    get_notification,
    set_notification,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_manager() -> MagicMock:
    """MCP server manager mock."""
    mgr = MagicMock()
    mgr.check_health.return_value = {"slack": True, "discord": True, "telegram": True}
    mgr.call_tool.return_value = {"ts": "1234567890.123456"}
    return mgr


@pytest.fixture()
def slack_adapter(mock_manager: MagicMock) -> SlackNotificationAdapter:
    return SlackNotificationAdapter(manager=mock_manager)


@pytest.fixture()
def discord_adapter(mock_manager: MagicMock) -> DiscordNotificationAdapter:
    return DiscordNotificationAdapter(manager=mock_manager)


@pytest.fixture()
def telegram_adapter(mock_manager: MagicMock) -> TelegramNotificationAdapter:
    return TelegramNotificationAdapter(manager=mock_manager)


# ---------------------------------------------------------------------------
# NotificationPort Protocol
# ---------------------------------------------------------------------------


class TestNotificationPort:
    def test_port_is_protocol(self):
        """NotificationPort is a runtime-checkable Protocol."""
        assert hasattr(NotificationPort, "__protocol_attrs__") or hasattr(
            NotificationPort, "__abstractmethods__"
        )

    def test_contextvars_injection(self):
        """set_notification / get_notification round-trip."""
        mock_adapter = MagicMock()
        mock_adapter.send_message = MagicMock(
            return_value=NotificationResult(success=True, channel="test")
        )
        mock_adapter.is_available = MagicMock(return_value=True)
        mock_adapter.list_channels = MagicMock(return_value=["test"])

        set_notification(mock_adapter)
        assert get_notification() is mock_adapter

        # Cleanup
        set_notification(None)
        assert get_notification() is None


class TestNotificationResult:
    def test_success_result(self):
        result = NotificationResult(success=True, channel="slack", message_id="123")
        assert result.success
        assert result.channel == "slack"
        assert result.message_id == "123"
        assert result.error is None

    def test_failure_result(self):
        result = NotificationResult(success=False, channel="discord", error="timeout")
        assert not result.success
        assert result.error == "timeout"


# ---------------------------------------------------------------------------
# Slack Adapter
# ---------------------------------------------------------------------------


class TestSlackNotificationAdapter:
    def test_send_message_success(
        self, slack_adapter: SlackNotificationAdapter, mock_manager: MagicMock
    ):
        result = slack_adapter.send_message("slack", "#general", "Hello!")
        assert result.success
        assert result.channel == "slack"
        assert result.message_id == "1234567890.123456"
        mock_manager.call_tool.assert_called_once_with(
            "slack", "send_message", {"channel": "#general", "text": "Hello!"}
        )

    def test_send_message_error(
        self, slack_adapter: SlackNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"error": "channel_not_found"}
        result = slack_adapter.send_message("slack", "#nonexistent", "Hello!")
        assert not result.success
        assert "channel_not_found" in result.error

    def test_send_message_unavailable(self, mock_manager: MagicMock):
        mock_manager.check_health.return_value = {"slack": False}
        adapter = SlackNotificationAdapter(manager=mock_manager)
        result = adapter.send_message("slack", "#general", "Hello!")
        assert not result.success

    def test_send_message_no_manager(self):
        adapter = SlackNotificationAdapter(manager=None)
        assert not adapter.is_available()

    def test_is_available(self, slack_adapter: SlackNotificationAdapter):
        assert slack_adapter.is_available()

    def test_list_channels(self, slack_adapter: SlackNotificationAdapter):
        assert slack_adapter.list_channels() == ["slack"]

    def test_send_message_exception(
        self, slack_adapter: SlackNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.side_effect = Exception("connection lost")
        result = slack_adapter.send_message("slack", "#general", "Hello!")
        assert not result.success
        assert "connection lost" in result.error


# ---------------------------------------------------------------------------
# Discord Adapter
# ---------------------------------------------------------------------------


class TestDiscordNotificationAdapter:
    def test_send_message_success(
        self, discord_adapter: DiscordNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"id": "msg_123"}
        result = discord_adapter.send_message("discord", "123456", "Hello Discord!")
        assert result.success
        assert result.channel == "discord"
        mock_manager.call_tool.assert_called_once_with(
            "discord", "send_message", {"channel_id": "123456", "content": "Hello Discord!"}
        )

    def test_send_message_error(
        self, discord_adapter: DiscordNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"error": "forbidden"}
        result = discord_adapter.send_message("discord", "123456", "Hello!")
        assert not result.success

    def test_is_available(self, discord_adapter: DiscordNotificationAdapter):
        assert discord_adapter.is_available()

    def test_list_channels(self, discord_adapter: DiscordNotificationAdapter):
        assert discord_adapter.list_channels() == ["discord"]


# ---------------------------------------------------------------------------
# Telegram Adapter
# ---------------------------------------------------------------------------


class TestTelegramNotificationAdapter:
    def test_send_message_success(
        self, telegram_adapter: TelegramNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"message_id": 42}
        result = telegram_adapter.send_message("telegram", "123456789", "Hello Telegram!")
        assert result.success
        assert result.channel == "telegram"
        assert result.message_id == "42"
        mock_manager.call_tool.assert_called_once_with(
            "telegram", "send_message", {"chat_id": "123456789", "text": "Hello Telegram!"}
        )

    def test_send_message_error(
        self, telegram_adapter: TelegramNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.call_tool.return_value = {"error": "chat not found"}
        result = telegram_adapter.send_message("telegram", "invalid", "Hello!")
        assert not result.success

    def test_is_available(self, telegram_adapter: TelegramNotificationAdapter):
        assert telegram_adapter.is_available()

    def test_list_channels(self, telegram_adapter: TelegramNotificationAdapter):
        assert telegram_adapter.list_channels() == ["telegram"]


# ---------------------------------------------------------------------------
# Composite Notification Adapter
# ---------------------------------------------------------------------------


class TestCompositeNotificationAdapter:
    def test_route_to_slack(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(manager=mock_manager)
        discord = DiscordNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord])

        result = composite.send_message("slack", "#general", "Hello!")
        assert result.success
        assert result.channel == "slack"

    def test_route_to_discord(self, mock_manager: MagicMock):
        mock_manager.call_tool.return_value = {"id": "msg_1"}
        slack = SlackNotificationAdapter(manager=mock_manager)
        discord = DiscordNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord])

        result = composite.send_message("discord", "123", "Hello!")
        assert result.success
        assert result.channel == "discord"

    def test_unknown_channel(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack])

        result = composite.send_message("email", "user@test.com", "Hello!")
        assert not result.success
        assert "No adapter" in result.error

    def test_unavailable_channel(self, mock_manager: MagicMock):
        mock_manager.check_health.return_value = {"slack": False}
        slack = SlackNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack])

        result = composite.send_message("slack", "#general", "Hello!")
        assert not result.success
        assert "not available" in result.error

    def test_is_available_any(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(manager=mock_manager)
        discord = DiscordNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord])
        assert composite.is_available()

    def test_is_available_specific_channel(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack])
        assert composite.is_available("slack")
        assert not composite.is_available("discord")

    def test_list_channels(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(manager=mock_manager)
        discord = DiscordNotificationAdapter(manager=mock_manager)
        telegram = TelegramNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord, telegram])

        channels = composite.list_channels()
        assert "slack" in channels
        assert "discord" in channels
        assert "telegram" in channels

    def test_empty_adapters(self):
        composite = CompositeNotificationAdapter([])
        assert not composite.is_available()
        assert composite.list_channels() == []
