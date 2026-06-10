"""Tests for ContextWindowManager — extracted from AgenticLoop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent.context_manager import ContextWindowManager
from core.agent.loop import _ContextExhaustedError


class TestContextWindowManager:
    """Test context window management logic."""

    def _make_mgr(self, *, quiet: bool = True) -> ContextWindowManager:
        return ContextWindowManager(hooks=None, quiet=quiet)

    # -- maybe_prune_messages --

    def test_no_prune_under_threshold(self) -> None:
        mgr = self._make_mgr()
        msgs: list[dict[str, Any]] = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        mgr.maybe_prune_messages(msgs)
        assert len(msgs) == 10

    def test_no_prune_at_threshold(self) -> None:
        mgr = self._make_mgr()
        msgs: list[dict[str, Any]] = [{"role": "user", "content": f"m{i}"} for i in range(30)]
        mgr.maybe_prune_messages(msgs)
        assert len(msgs) == 30

    def test_prune_above_threshold(self) -> None:
        mgr = self._make_mgr()
        msgs: list[dict[str, Any]] = [{"role": "user", "content": "first"}]
        for i in range(1, 32):
            role = "assistant" if i % 2 else "user"
            msgs.append({"role": role, "content": f"m{i}"})
        mgr.maybe_prune_messages(msgs)
        assert msgs[0]["content"] == "first"
        assert "(earlier rounds omitted)" in str(msgs[1]["content"])

    # -- repair_messages --

    def test_repair_no_orphans(self) -> None:
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
        ]
        original_len = len(msgs)
        ContextWindowManager.repair_messages(msgs)
        assert len(msgs) == original_len

    def test_repair_removes_orphan(self) -> None:
        msgs: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t99", "content": "orphan"}],
            },
        ]
        ContextWindowManager.repair_messages(msgs)
        # Orphaned tool_result should be removed
        assert len(msgs) < 3

    # -- _notify_context_event --

    def test_notify_quiet_mode_no_error(self) -> None:
        """Quiet mode should not raise even with no UI available."""
        mgr = self._make_mgr(quiet=True)
        mgr._notify_context_event("prune", original_count=10, new_count=5)

    # -- _resolve_overflow_strategy --

    def test_resolve_strategy_anthropic_no_action(self) -> None:
        """Anthropic below 95% should return 'none'."""

        class FakeMetrics:
            usage_pct = 60.0
            context_window = 200_000

        class FakeSettings:
            compact_keep_recent = 8

        mgr = self._make_mgr()
        result = asyncio.run(
            mgr._resolve_overflow_strategy(FakeMetrics(), FakeSettings(), "claude-3", "anthropic")
        )
        assert result["strategy"] == "none"

    def test_resolve_strategy_openai_compact(self) -> None:
        """OpenAI at 85% should trigger compact."""

        class FakeMetrics:
            usage_pct = 85.0
            context_window = 200_000

        class FakeSettings:
            compact_keep_recent = 8

        mgr = self._make_mgr()
        result = asyncio.run(
            mgr._resolve_overflow_strategy(FakeMetrics(), FakeSettings(), "gpt-4o", "openai")
        )
        assert result["strategy"] == "compact"

    def test_resolve_strategy_prune_at_95(self) -> None:
        """Any provider at 95%+ should trigger prune."""

        class FakeMetrics:
            usage_pct = 96.0
            context_window = 200_000

        class FakeSettings:
            compact_keep_recent = 8

        mgr = self._make_mgr()
        result = asyncio.run(
            mgr._resolve_overflow_strategy(FakeMetrics(), FakeSettings(), "gpt-4o", "openai")
        )
        assert result["strategy"] == "prune"

    def test_check_context_overflow_awaits_compaction_inside_running_loop(self) -> None:
        """Compaction should be awaited, not driven via run_until_complete."""
        mgr = self._make_mgr()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
        ]
        compacted = [{"role": "user", "content": "compacted"}]

        warning_metrics = SimpleNamespace(
            estimated_tokens=170_000,
            context_window=200_000,
            usage_pct=85.0,
            remaining_tokens=30_000,
            is_warning=True,
            is_critical=False,
            is_ceiling_exceeded=False,
        )
        settings = MagicMock()
        settings.compact_keep_recent = 8
        settings.observation_mask_keep_rounds = 3
        compact = AsyncMock(return_value=(compacted, True))

        async def _run() -> None:
            with (
                patch(
                    "core.orchestration.context_monitor.check_context", return_value=warning_metrics
                ),
                patch("core.orchestration.context_monitor.mask_stale_observations", return_value=0),
                patch("core.orchestration.compaction.compact_conversation", compact),
                patch("core.config.settings", settings),
            ):
                await mgr.check_context_overflow("system", messages, "gpt-4o", "openai")

        asyncio.run(_run())

        compact.assert_awaited_once()
        assert messages == compacted

    def test_check_context_overflow_raises_context_exhausted(self) -> None:
        """Unrecoverable critical context should propagate to AgenticLoop."""
        mgr = self._make_mgr()
        metrics = SimpleNamespace(
            estimated_tokens=198_000,
            context_window=200_000,
            usage_pct=99.0,
            remaining_tokens=2_000,
            is_warning=True,
            is_critical=True,
            is_ceiling_exceeded=False,
        )
        settings = MagicMock()
        settings.compact_keep_recent = 8

        async def _run() -> None:
            with (
                patch("core.orchestration.context_monitor.check_context", return_value=metrics),
                patch(
                    "core.orchestration.context_monitor.prune_oldest_messages",
                    side_effect=lambda m, **kw: m,
                ),
                patch("core.config.settings", settings),
            ):
                await mgr.check_context_overflow(
                    "system", [{"role": "user", "content": "too much"}], "gpt-4o", "openai"
                )

        try:
            asyncio.run(_run())
        except _ContextExhaustedError:
            return
        raise AssertionError("expected _ContextExhaustedError")
