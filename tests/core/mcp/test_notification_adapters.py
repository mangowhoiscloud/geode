"""Tests for notification adapters (Slack, Discord, Telegram, Composite).

Phase 2 validation: NotificationPort implementations + CompositeNotificationAdapter.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.mcp.composite_notification import (
    CompositeNotificationAdapter,
)
from core.mcp.discord_adapter import DiscordNotificationAdapter
from core.mcp.notification_port import (
    NotificationPort,
    NotificationResult,
    get_notification,
    set_notification,
)
from core.mcp.slack_adapter import SlackNotificationAdapter
from core.mcp.telegram_adapter import TelegramNotificationAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_manager() -> MagicMock:
    """MCP server manager mock."""
    mgr = MagicMock()
    mgr.check_health.return_value = {"slack": True, "discord": True, "telegram": True}
    mgr.acall_tool = AsyncMock(return_value={"ts": "async-ts"})
    return mgr


class _FakeSlackTransport:
    """Double for core.messaging.slack_transport.SlackTransport."""

    def __init__(self, *, configured: bool = True, fail: str = "") -> None:
        self.configured = configured
        self._fail = fail
        self.posted: list[dict] = []

    async def ais_available(self) -> bool:
        return self.configured and not self._fail

    async def post_message(self, channel_id, text, *, thread_ts="", mrkdwn=True):
        if self._fail:
            from core.messaging.slack_transport import SlackTransportError

            raise SlackTransportError(self._fail)
        self.posted.append({"channel": channel_id, "text": text, "thread_ts": thread_ts})
        return {"ok": True, "ts": "async-ts"}


@pytest.fixture()
def slack_transport() -> _FakeSlackTransport:
    return _FakeSlackTransport()


@pytest.fixture()
def slack_adapter(slack_transport: _FakeSlackTransport) -> SlackNotificationAdapter:
    return SlackNotificationAdapter(transport=slack_transport)


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
        self,
        slack_adapter: SlackNotificationAdapter,
        slack_transport: _FakeSlackTransport,
    ):
        result = asyncio.run(slack_adapter.asend_message("slack", "#general", "Hello!"))
        assert result.success
        assert result.channel == "slack"
        assert result.message_id == "async-ts"
        assert slack_transport.posted == [
            {"channel": "#general", "text": "Hello!", "thread_ts": ""}
        ]

    def test_asend_message_forwards_thread_ts(
        self,
        slack_adapter: SlackNotificationAdapter,
        slack_transport: _FakeSlackTransport,
    ):
        result = asyncio.run(
            slack_adapter.asend_message(
                "slack", "#general", "Hello async!", thread_ts="171234.5678"
            )
        )
        assert result.success
        assert result.message_id == "async-ts"
        assert slack_transport.posted[0]["thread_ts"] == "171234.5678"

    def test_send_message_error(self):
        adapter = SlackNotificationAdapter(
            transport=_FakeSlackTransport(fail="chat.postMessage: channel_not_found")
        )
        result = asyncio.run(adapter.asend_message("slack", "#nonexistent", "Hello!"))
        assert not result.success
        assert "channel_not_found" in result.error

    def test_send_message_unconfigured(self):
        adapter = SlackNotificationAdapter(transport=_FakeSlackTransport(configured=False))
        result = asyncio.run(adapter.asend_message("slack", "#general", "Hello!"))
        assert not result.success
        assert "not configured" in result.error

    def test_unconfigured_transport_not_available(self):
        adapter = SlackNotificationAdapter(transport=_FakeSlackTransport(configured=False))
        assert not adapter.is_available()

    def test_is_available(self, slack_adapter: SlackNotificationAdapter):
        assert slack_adapter.is_available()

    def test_list_channels(self, slack_adapter: SlackNotificationAdapter):
        assert slack_adapter.list_channels() == ["slack"]

    def test_send_message_exception(self):
        adapter = SlackNotificationAdapter(transport=_FakeSlackTransport(fail="connection lost"))
        result = asyncio.run(adapter.asend_message("slack", "#general", "Hello!"))
        assert not result.success
        assert "connection lost" in result.error


# ---------------------------------------------------------------------------
# Discord Adapter
# ---------------------------------------------------------------------------


class TestDiscordNotificationAdapter:
    def test_send_message_success(
        self, discord_adapter: DiscordNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.acall_tool.return_value = {"id": "msg_123"}
        result = asyncio.run(discord_adapter.asend_message("discord", "123456", "Hello Discord!"))
        assert result.success
        assert result.channel == "discord"
        mock_manager.acall_tool.assert_awaited_once_with(
            "discord", "send_message", {"channel_id": "123456", "content": "Hello Discord!"}
        )

    def test_send_message_error(
        self, discord_adapter: DiscordNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.acall_tool.return_value = {"error": "forbidden"}
        result = asyncio.run(discord_adapter.asend_message("discord", "123456", "Hello!"))
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
        mock_manager.acall_tool.return_value = {"message_id": 42}
        result = asyncio.run(
            telegram_adapter.asend_message("telegram", "123456789", "Hello Telegram!")
        )
        assert result.success
        assert result.channel == "telegram"
        assert result.message_id == "42"
        mock_manager.acall_tool.assert_awaited_once_with(
            "telegram", "send_message", {"chat_id": "123456789", "text": "Hello Telegram!"}
        )

    def test_send_message_error(
        self, telegram_adapter: TelegramNotificationAdapter, mock_manager: MagicMock
    ):
        mock_manager.acall_tool.return_value = {"error": "chat not found"}
        result = asyncio.run(telegram_adapter.asend_message("telegram", "invalid", "Hello!"))
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
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport())
        discord = DiscordNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord])

        result = asyncio.run(composite.asend_message("slack", "#general", "Hello!"))
        assert result.success
        assert result.channel == "slack"

    def test_route_to_discord(self, mock_manager: MagicMock):
        mock_manager.acall_tool.return_value = {"id": "msg_1"}
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport())
        discord = DiscordNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord])

        result = asyncio.run(composite.asend_message("discord", "123", "Hello!"))
        assert result.success
        assert result.channel == "discord"

    def test_unknown_channel(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport())
        composite = CompositeNotificationAdapter([slack])

        result = asyncio.run(composite.asend_message("email", "user@test.com", "Hello!"))
        assert not result.success
        assert "No adapter" in result.error

    def test_unavailable_channel(self):
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport(configured=False))
        composite = CompositeNotificationAdapter([slack])

        result = asyncio.run(composite.asend_message("slack", "#general", "Hello!"))
        assert not result.success
        assert "not available" in result.error

    def test_is_available_any(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport())
        discord = DiscordNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord])
        assert asyncio.run(composite.ais_available())

    def test_is_available_specific_channel(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport())
        composite = CompositeNotificationAdapter([slack])
        assert asyncio.run(composite.ais_available("slack"))
        assert not asyncio.run(composite.ais_available("discord"))

    def test_list_channels(self, mock_manager: MagicMock):
        slack = SlackNotificationAdapter(transport=_FakeSlackTransport())
        discord = DiscordNotificationAdapter(manager=mock_manager)
        telegram = TelegramNotificationAdapter(manager=mock_manager)
        composite = CompositeNotificationAdapter([slack, discord, telegram])

        channels = composite.list_channels()
        assert "slack" in channels
        assert "discord" in channels
        assert "telegram" in channels

    def test_empty_adapters(self):
        composite = CompositeNotificationAdapter([])
        assert not asyncio.run(composite.ais_available())
        assert composite.list_channels() == []
