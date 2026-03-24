"""Tests for Notification Hook Plugin.

Phase 3 validation: event → notification routing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.mcp.notification_port import NotificationResult, set_notification
from core.orchestration.hooks import HookEvent, HookSystem
from core.orchestration.plugins.notification_hook.hook import (
    _format_message,
    register_notification_hooks,
)

# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_pipeline_end(self):
        msg = _format_message(
            HookEvent.PIPELINE_END,
            {"ip_name": "Berserk", "tier": "S", "final_score": 81.3},
        )
        assert "Pipeline completed" in msg
        assert "Berserk" in msg
        assert "S" in msg
        assert "81.3" in msg

    def test_pipeline_error(self):
        msg = _format_message(
            HookEvent.PIPELINE_ERROR,
            {"ip_name": "Test", "error": "timeout"},
        )
        assert "Pipeline error" in msg
        assert "timeout" in msg

    def test_drift_detected(self):
        msg = _format_message(
            HookEvent.DRIFT_DETECTED,
            {"metric": "psm_score"},
        )
        assert "Drift detected" in msg
        assert "psm_score" in msg

    def test_subagent_failed(self):
        msg = _format_message(
            HookEvent.SUBAGENT_FAILED,
            {"task_id": "task_123", "error": "depth exceeded"},
        )
        assert "Sub-agent failed" in msg
        assert "task_123" in msg
        assert "depth exceeded" in msg

    def test_subagent_failed_no_error(self):
        msg = _format_message(
            HookEvent.SUBAGENT_FAILED,
            {"task_id": "task_456"},
        )
        assert "Sub-agent failed" in msg
        assert "depth exceeded" not in msg


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------


class TestNotificationHookRegistration:
    def test_registers_all_events(self):
        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#test")

        registered = hooks.list_hooks()
        assert "pipeline_end" in registered
        assert "pipeline_error" in registered
        assert "drift_detected" in registered
        assert "subagent_failed" in registered

    def test_hooks_trigger_notification(self):
        """Verify hooks call NotificationPort.send_message when triggered."""
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.send_message.return_value = NotificationResult(success=True, channel="slack")
        set_notification(mock_adapter)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#alerts")

        # Trigger PIPELINE_END
        hooks.trigger(
            HookEvent.PIPELINE_END,
            {"ip_name": "Berserk", "tier": "S", "final_score": 81.3},
        )

        mock_adapter.send_message.assert_called_once()
        call_args = mock_adapter.send_message.call_args
        assert call_args[0][0] == "slack"
        assert call_args[0][1] == "#alerts"
        assert "Pipeline completed" in call_args[0][2]

        set_notification(None)

    def test_hooks_skip_when_no_adapter(self):
        """Hooks should silently skip when no adapter is set."""
        set_notification(None)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#test")

        # Should not raise
        results = hooks.trigger(
            HookEvent.PIPELINE_END,
            {"ip_name": "Test", "tier": "A", "final_score": 65.0},
        )
        assert all(r.success for r in results)

    def test_hooks_handle_send_failure(self):
        """Hooks should not crash on notification send failure."""
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.send_message.return_value = NotificationResult(
            success=False, channel="slack", error="rate limited"
        )
        set_notification(mock_adapter)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#alerts")

        # Should not raise even though send fails
        results = hooks.trigger(
            HookEvent.PIPELINE_ERROR,
            {"ip_name": "Test", "error": "critical failure"},
        )
        assert all(r.success for r in results)

        set_notification(None)

    def test_custom_channel_and_recipient(self):
        """Can configure custom channel and recipient."""
        mock_adapter = MagicMock()
        mock_adapter.is_available.return_value = True
        mock_adapter.send_message.return_value = NotificationResult(success=True, channel="discord")
        set_notification(mock_adapter)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="discord", recipient="123456")

        hooks.trigger(HookEvent.DRIFT_DETECTED, {"metric": "psm_score"})

        call_args = mock_adapter.send_message.call_args
        assert call_args[0][0] == "discord"
        assert call_args[0][1] == "123456"

        set_notification(None)
