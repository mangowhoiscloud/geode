"""Tests for Gateway — inbound message routing.

Phase 6 validation: ChannelManager, Bindings, Pollers.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from core.gateway.channel_manager import ChannelManager, get_gateway, set_gateway
from core.gateway.models import ChannelBinding, InboundMessage
from core.gateway.pollers.base import BasePoller
from core.gateway.pollers.discord_poller import DiscordPoller
from core.gateway.pollers.slack_poller import SlackPoller
from core.gateway.pollers.telegram_poller import TelegramPoller

# ---------------------------------------------------------------------------
# InboundMessage
# ---------------------------------------------------------------------------


class TestInboundMessage:
    def test_creation(self):
        msg = InboundMessage(
            channel="slack",
            channel_id="C12345",
            sender_id="U67890",
            sender_name="Alice",
            content="analyze Berserk",
            timestamp=time.time(),
        )
        assert msg.channel == "slack"
        assert msg.content == "analyze Berserk"
        assert msg.thread_id == ""


# ---------------------------------------------------------------------------
# ChannelBinding
# ---------------------------------------------------------------------------


class TestChannelBinding:
    def test_defaults(self):
        binding = ChannelBinding(channel="slack")
        assert binding.auto_respond is True
        assert binding.require_mention is False
        assert binding.max_rounds == 5
        assert binding.channel_id == ""

    def test_specific_binding(self):
        binding = ChannelBinding(
            channel="discord",
            channel_id="123456",
            require_mention=True,
            max_rounds=3,
        )
        assert binding.channel_id == "123456"
        assert binding.require_mention is True


# ---------------------------------------------------------------------------
# ChannelManager
# ---------------------------------------------------------------------------


class TestChannelManager:
    def test_route_message_with_binding(self):
        manager = ChannelManager()
        manager.set_processor(lambda content, meta: f"Response to: {content}")
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C12345",
            sender_id="U1",
            sender_name="Alice",
            content="hello",
            timestamp=time.time(),
        )
        response = manager.route_message(msg)
        assert response == "Response to: hello"

    def test_route_message_no_binding(self):
        manager = ChannelManager()
        manager.set_processor(lambda content, meta: "response")

        msg = InboundMessage(
            channel="telegram",
            channel_id="999",
            sender_id="U1",
            sender_name="Bob",
            content="hello",
            timestamp=time.time(),
        )
        response = manager.route_message(msg)
        assert response is None

    def test_specific_binding_wins(self):
        """Most-specific binding (channel + channel_id) should win."""
        manager = ChannelManager()
        manager.set_processor(lambda content, meta: "processed")

        # Add generic binding
        manager.add_binding(ChannelBinding(channel="slack"))
        # Add specific binding
        manager.add_binding(ChannelBinding(channel="slack", channel_id="C12345", max_rounds=10))

        msg = InboundMessage(
            channel="slack",
            channel_id="C12345",
            sender_id="U1",
            sender_name="Alice",
            content="hello",
            timestamp=time.time(),
        )
        response = manager.route_message(msg)
        assert response == "processed"

    def test_require_mention_filter(self):
        manager = ChannelManager()
        manager.set_processor(lambda content, meta: "processed")
        manager.add_binding(ChannelBinding(channel="discord", require_mention=True))

        # Without mention — should be ignored
        msg = InboundMessage(
            channel="discord",
            channel_id="D1",
            sender_id="U1",
            sender_name="Alice",
            content="hello",
            timestamp=time.time(),
        )
        assert manager.route_message(msg) is None

        # With mention — should be processed
        msg.content = "hey @geode analyze this"
        assert manager.route_message(msg) == "processed"

    def test_remove_binding(self):
        manager = ChannelManager()
        manager.add_binding(ChannelBinding(channel="slack"))
        assert manager.remove_binding("slack")
        assert not manager.remove_binding("slack")  # Already removed

    def test_no_processor(self):
        manager = ChannelManager()
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="hello",
            timestamp=time.time(),
        )
        assert manager.route_message(msg) is None

    def test_stats(self):
        manager = ChannelManager()
        manager.set_processor(lambda content, meta: "ok")
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="hello",
            timestamp=time.time(),
        )
        manager.route_message(msg)

        stats = manager.get_stats()
        assert stats["received"] == 1
        assert stats["processed"] == 1

    def test_list_bindings(self):
        manager = ChannelManager()
        manager.add_binding(ChannelBinding(channel="slack", channel_id="C1"))
        manager.add_binding(ChannelBinding(channel="discord"))

        bindings = manager.list_bindings()
        assert len(bindings) == 2

    def test_processor_exception(self):
        manager = ChannelManager()
        manager.set_processor(lambda content, meta: 1 / 0)
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="crash",
            timestamp=time.time(),
        )
        response = manager.route_message(msg)
        assert "Error" in response


# ---------------------------------------------------------------------------
# Pollers
# ---------------------------------------------------------------------------


class TestBasePoller:
    def test_start_stop_lifecycle(self):
        manager = ChannelManager()

        class TestPoller(BasePoller):
            channel_name = "test"
            polled = False

            def _poll_once(self):
                self.polled = True

            def is_configured(self):
                return True

        poller = TestPoller(manager, poll_interval_s=0.1)
        poller.start()
        time.sleep(0.3)  # Allow 2-3 polls
        poller.stop()
        assert poller.polled

    def test_not_configured_skip(self):
        manager = ChannelManager()

        class UnconfiguredPoller(BasePoller):
            channel_name = "test"

            def _poll_once(self):
                pass

            def is_configured(self):
                return False

        poller = UnconfiguredPoller(manager)
        poller.start()
        # Thread should not be started
        assert poller._thread is None


class TestSlackPoller:
    def test_is_configured(self):
        manager = ChannelManager()
        poller = SlackPoller(manager)
        # Without SLACK_BOT_TOKEN env var, should not be configured
        with patch.dict("os.environ", {}, clear=True):
            assert not poller.is_configured()

    def test_is_configured_with_token(self):
        manager = ChannelManager()
        poller = SlackPoller(manager)
        with patch.dict("os.environ", {"SLACK_BOT_TOKEN": "xoxb-test"}):
            assert poller.is_configured()

    def test_channel_name(self):
        manager = ChannelManager()
        poller = SlackPoller(manager)
        assert poller.channel_name == "slack"


class TestDiscordPoller:
    def test_is_configured(self):
        manager = ChannelManager()
        poller = DiscordPoller(manager)
        with patch.dict("os.environ", {}, clear=True):
            assert not poller.is_configured()

    def test_channel_name(self):
        manager = ChannelManager()
        poller = DiscordPoller(manager)
        assert poller.channel_name == "discord"


class TestTelegramPoller:
    def test_is_configured(self):
        manager = ChannelManager()
        poller = TelegramPoller(manager)
        with patch.dict("os.environ", {}, clear=True):
            assert not poller.is_configured()

    def test_channel_name(self):
        manager = ChannelManager()
        poller = TelegramPoller(manager)
        assert poller.channel_name == "telegram"


# ---------------------------------------------------------------------------
# GatewayPort contextvars
# ---------------------------------------------------------------------------


class TestGatewayPort:
    def test_contextvars(self):
        mock = MagicMock()
        set_gateway(mock)
        assert get_gateway() is mock
        set_gateway(None)
        assert get_gateway() is None


# ---------------------------------------------------------------------------
# OpenClaw pattern: Session Key, Lane Queue, allowed_tools, Config reload
# ---------------------------------------------------------------------------


class TestGatewaySessionKey:
    def test_build_gateway_session_key(self):
        from core.memory.session_key import build_gateway_session_key

        key = build_gateway_session_key("slack", "C12345", "U67890")
        assert key.startswith("gateway:slack:")
        assert "c12345" in key
        assert "u67890" in key

    def test_build_gateway_session_key_no_sender(self):
        from core.memory.session_key import build_gateway_session_key

        key = build_gateway_session_key("telegram", "987654")
        assert key == "gateway:telegram:987654"

    def test_build_gateway_session_key_with_thread_id(self):
        from core.memory.session_key import build_gateway_session_key

        key = build_gateway_session_key("slack", "C12345", "U67890", thread_id="1234567890.123456")
        assert "1234567890_123456" in key
        # Without thread_id should be shorter
        key_no_thread = build_gateway_session_key("slack", "C12345", "U67890")
        assert len(key) > len(key_no_thread)

    def test_different_threads_different_keys(self):
        from core.memory.session_key import build_gateway_session_key

        k1 = build_gateway_session_key("slack", "C1", "U1", thread_id="111.000")
        k2 = build_gateway_session_key("slack", "C1", "U1", thread_id="222.000")
        k3 = build_gateway_session_key("slack", "C1", "U1")
        assert k1 != k2
        assert k1 != k3


class TestAllowedToolsEnforcement:
    def test_allowed_tools_hint_injected(self):
        """Binding's allowed_tools should be prefixed to content."""
        received_content = []
        manager = ChannelManager()
        manager.set_processor(lambda c, m: (received_content.append(c), "ok")[1])
        manager.add_binding(
            ChannelBinding(
                channel="slack",
                allowed_tools=["list_ips", "search_ips"],
            )
        )

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="show IPs",
            timestamp=time.time(),
        )
        manager.route_message(msg)
        assert "[allowed_tools:" in received_content[0]
        assert "list_ips" in received_content[0]

    def test_no_allowed_tools_no_prefix(self):
        """Without allowed_tools, content passes through unchanged."""
        received_content = []
        manager = ChannelManager()
        manager.set_processor(lambda c, m: (received_content.append(c), "ok")[1])
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="hello",
            timestamp=time.time(),
        )
        manager.route_message(msg)
        assert received_content[0] == "hello"


class TestLaneQueueIntegration:
    def test_route_with_lane_queue(self):
        """Messages should flow through gateway lane when available."""
        from core.orchestration.lane_queue import LaneQueue

        lq = LaneQueue()
        lq.add_lane("gateway", max_concurrent=2)

        manager = ChannelManager(lane_queue=lq)
        manager.set_processor(lambda c, m: f"processed: {c}")
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="test",
            timestamp=time.time(),
        )
        response = manager.route_message(msg)
        assert response == "processed: test"

    def test_route_without_lane_queue(self):
        """Messages should still work without lane queue."""
        manager = ChannelManager(lane_queue=None)
        manager.set_processor(lambda c, m: "ok")
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C1",
            sender_id="U1",
            sender_name="Alice",
            content="test",
            timestamp=time.time(),
        )
        assert manager.route_message(msg) == "ok"


class TestBindingConfigReload:
    def test_load_bindings_from_config(self):
        config = {
            "gateway": {
                "bindings": {
                    "rules": [
                        {"channel": "slack", "channel_id": "C123", "auto_respond": True},
                        {"channel": "discord", "require_mention": True},
                    ]
                }
            }
        }
        manager = ChannelManager()
        loaded = manager.load_bindings_from_config(config)
        assert loaded == 2
        bindings = manager.list_bindings()
        assert len(bindings) == 2

    def test_load_empty_config(self):
        manager = ChannelManager()
        loaded = manager.load_bindings_from_config({})
        assert loaded == 0

    def test_reload_replaces_bindings(self):
        manager = ChannelManager()
        manager.add_binding(ChannelBinding(channel="telegram"))
        assert len(manager.list_bindings()) == 1

        config = {
            "gateway": {
                "bindings": {
                    "rules": [
                        {"channel": "slack"},
                    ]
                }
            }
        }
        manager.load_bindings_from_config(config)
        bindings = manager.list_bindings()
        assert len(bindings) == 1
        assert bindings[0]["channel"] == "slack"


class TestMultiTurnMetadata:
    """Verify that route_message passes metadata to the processor."""

    def test_metadata_contains_session_key(self):
        """Processor receives session_key in metadata."""
        captured: list[dict] = []
        manager = ChannelManager()
        manager.set_processor(lambda c, m: (captured.append(m), "ok")[1])
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C123",
            sender_id="U456",
            sender_name="Bob",
            content="hello",
            timestamp=time.time(),
            thread_id="1234567890.123456",
        )
        manager.route_message(msg)

        assert len(captured) == 1
        meta = captured[0]
        assert "session_key" in meta
        assert "c123" in meta["session_key"]
        assert "u456" in meta["session_key"]
        assert "1234567890_123456" in meta["session_key"]
        assert meta["thread_id"] == "1234567890.123456"
        assert meta["channel"] == "slack"

    def test_metadata_without_thread_id(self):
        """Messages without thread_id still get session_key."""
        captured: list[dict] = []
        manager = ChannelManager()
        manager.set_processor(lambda c, m: (captured.append(m), "ok")[1])
        manager.add_binding(ChannelBinding(channel="slack"))

        msg = InboundMessage(
            channel="slack",
            channel_id="C123",
            sender_id="U456",
            sender_name="Bob",
            content="hello",
            timestamp=time.time(),
        )
        manager.route_message(msg)

        meta = captured[0]
        assert "session_key" in meta
        assert meta["thread_id"] == ""

    def test_thread_scoped_session_keys_differ(self):
        """Different threads produce different session keys."""
        keys: list[str] = []
        manager = ChannelManager()
        manager.set_processor(lambda c, m: (keys.append(m["session_key"]), "ok")[1])
        manager.add_binding(ChannelBinding(channel="slack"))

        for thread_id in ["111.000", "222.000"]:
            msg = InboundMessage(
                channel="slack",
                channel_id="C123",
                sender_id="U456",
                sender_name="Bob",
                content="hello",
                timestamp=time.time(),
                thread_id=thread_id,
            )
            manager.route_message(msg)

        assert len(keys) == 2
        assert keys[0] != keys[1]


class TestPollerLifecycle:
    def test_start_stop_pollers(self):
        manager = ChannelManager()
        mock_poller = MagicMock()
        manager.register_poller(mock_poller)

        manager.start()
        mock_poller.start.assert_called_once()

        manager.stop()
        mock_poller.stop.assert_called_once()
