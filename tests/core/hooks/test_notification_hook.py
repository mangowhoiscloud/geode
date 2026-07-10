"""Tests for Notification Hook Plugin.

Event → notification routing. PR-DEAD-PIPELINE (2026-06-10) — the dead
pipeline event family was removed; SUBAGENT_FAILED is the remaining
notification-worthy event.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from core.hooks import HookEvent, HookSystem
from core.hooks.plugins.notification_hook.hook import (
    _format_message,
    register_notification_hooks,
)
from core.mcp.notification_port import NotificationResult, set_notification

# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


class TestFormatMessage:
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

    def test_unmapped_event_falls_through(self):
        msg = _format_message(
            HookEvent.SESSION_ENDED,
            {"session_id": "s1"},
        )
        assert "session_end" in msg


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------


class TestNotificationHookRegistration:
    def test_registers_all_events(self):
        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#test")

        registered = hooks.list_hooks()
        assert "subagent_failed" in registered

    def test_build_hooks_registers_notification_once(self, tmp_path: Path):
        from core.wiring.bootstrap import build_hooks

        hooks, _, _ = build_hooks(
            session_key="test",
            run_id="run-1",
            log_dir=tmp_path,
        )
        names = hooks.list_hooks(HookEvent.SUBAGENT_FAILED)[HookEvent.SUBAGENT_FAILED.value]
        assert names.count("notification_subagent_failed") == 1
        hooks.close()

    def test_hooks_trigger_notification(self):
        """Verify hooks call NotificationPort.asend_message when triggered."""
        mock_adapter = MagicMock()
        mock_adapter.ais_available = AsyncMock(return_value=True)
        mock_adapter.asend_message = AsyncMock(
            return_value=NotificationResult(success=True, channel="slack")
        )
        set_notification(mock_adapter)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#alerts")

        asyncio.run(
            hooks.trigger_async(
                HookEvent.SUBAGENT_FAILED,
                {"task_id": "task_123", "error": "depth exceeded"},
            )
        )

        mock_adapter.asend_message.assert_awaited_once()
        call_args = mock_adapter.asend_message.call_args
        assert call_args[0][0] == "slack"
        assert call_args[0][1] == "#alerts"
        assert "Sub-agent failed" in call_args[0][2]

        set_notification(None)

    def test_hooks_skip_when_no_adapter(self):
        """Hooks should silently skip when no adapter is set."""
        set_notification(None)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#test")

        # Should not raise
        results = asyncio.run(
            hooks.trigger_async(
                HookEvent.SUBAGENT_FAILED,
                {"task_id": "task_123"},
            )
        )
        assert all(r.success for r in results)

    def test_hooks_handle_send_failure(self):
        """Hooks should not crash on notification send failure."""
        mock_adapter = MagicMock()
        mock_adapter.ais_available = AsyncMock(return_value=True)
        mock_adapter.asend_message = AsyncMock(
            return_value=NotificationResult(success=False, channel="slack", error="rate limited")
        )
        set_notification(mock_adapter)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#alerts")

        # Should not raise even though send fails
        results = asyncio.run(
            hooks.trigger_async(
                HookEvent.SUBAGENT_FAILED,
                {"task_id": "task_123", "error": "critical failure"},
            )
        )
        assert all(r.success for r in results)

        set_notification(None)

    def test_custom_channel_and_recipient(self):
        """Can configure custom channel and recipient."""
        mock_adapter = MagicMock()
        mock_adapter.ais_available = AsyncMock(return_value=True)
        mock_adapter.asend_message = AsyncMock(
            return_value=NotificationResult(success=True, channel="discord")
        )
        set_notification(mock_adapter)

        hooks = HookSystem()
        register_notification_hooks(hooks, channel="discord", recipient="123456")

        asyncio.run(hooks.trigger_async(HookEvent.SUBAGENT_FAILED, {"task_id": "task_789"}))

        call_args = mock_adapter.asend_message.call_args
        assert call_args[0][0] == "discord"
        assert call_args[0][1] == "123456"

        set_notification(None)

    def test_subagent_emitter_awaits_notification_once(self):
        from core.agent.sub_agent import SubAgentManager, SubTask
        from core.orchestration.isolated_execution import IsolatedRunner

        mock_adapter = MagicMock()
        mock_adapter.ais_available = AsyncMock(return_value=True)
        mock_adapter.asend_message = AsyncMock(
            return_value=NotificationResult(success=True, channel="slack")
        )
        set_notification(mock_adapter)
        hooks = HookSystem()
        register_notification_hooks(hooks, channel="slack", recipient="#alerts")
        manager = SubAgentManager(IsolatedRunner(), hooks=hooks)
        task = SubTask(task_id="task-1", task_type="analyze", description="test")

        asyncio.run(manager._emit_hook(HookEvent.SUBAGENT_FAILED, task, error="boom"))

        mock_adapter.asend_message.assert_awaited_once()
        set_notification(None)
