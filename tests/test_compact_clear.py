"""Tests for /compact, /clear, manage_context tool, and model switch guard."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from core.orchestration.context_monitor import (
    adaptive_prune,
    estimate_message_tokens,
    summarize_tool_results,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": text}


def _make_tool_result(tool_use_id: str, content: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
    }


def _make_tool_use_assistant(tool_use_id: str, name: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_use_id, "name": name, "input": {}}],
    }


def _build_conversation(n_pairs: int, tool_result_size: int = 100) -> list[dict[str, Any]]:
    """Build conversation with n tool_use/tool_result pairs."""
    msgs: list[dict[str, Any]] = [_make_msg("user", "initial question")]
    for i in range(n_pairs):
        msgs.append(_make_tool_use_assistant(f"tool_{i}", "web_fetch"))
        msgs.append(_make_tool_result(f"tool_{i}", "x" * tool_result_size))
    return msgs


# ---------------------------------------------------------------------------
# TestSummarizeToolResults
# ---------------------------------------------------------------------------


class TestSummarizeToolResults:
    def test_small_results_unchanged(self):
        msgs = _build_conversation(3, tool_result_size=50)
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=100_000)
        assert count == 0

    def test_large_result_summarized(self):
        msgs = [
            _make_msg("user", "hello"),
            _make_tool_use_assistant("t1", "web_fetch"),
            _make_tool_result("t1", "x" * 10_000),
        ]
        count, before, after = summarize_tool_results(msgs, target_window=10_000)
        assert count == 1
        assert before > after
        result_block = msgs[2]["content"][0]
        assert "[summarized:" in result_block["content"]
        assert result_block["type"] == "tool_result"
        assert result_block["tool_use_id"] == "t1"

    def test_idempotent(self):
        msgs = [
            _make_msg("user", "hello"),
            _make_tool_use_assistant("t1", "web_fetch"),
            _make_tool_result("t1", "x" * 10_000),
        ]
        summarize_tool_results(msgs, target_window=10_000)
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=10_000)
        assert count == 0


# ---------------------------------------------------------------------------
# TestAdaptivePrune
# ---------------------------------------------------------------------------


class TestAdaptivePrune:
    def test_under_budget_no_change(self):
        msgs = [_make_msg("user", "hi"), _make_msg("assistant", "hello")]
        result = adaptive_prune(msgs, target_tokens=100_000)
        assert len(result) == 2

    def test_preserves_first_message(self):
        msgs = _build_conversation(20, tool_result_size=500)
        result = adaptive_prune(msgs, target_tokens=5_000)
        assert result[0] == msgs[0]

    def test_preserves_last_pair(self):
        msgs = _build_conversation(20, tool_result_size=500)
        result = adaptive_prune(msgs, target_tokens=5_000)
        assert result[-1] == msgs[-1]
        assert result[-2] == msgs[-2]

    def test_prunes_large_conversation(self):
        msgs = _build_conversation(50, tool_result_size=1000)
        result = adaptive_prune(msgs, target_tokens=10_000)
        assert len(result) < len(msgs)

    def test_returns_new_list(self):
        msgs = _build_conversation(5)
        result = adaptive_prune(msgs, target_tokens=100_000)
        assert result is not msgs

    def test_within_budget(self):
        msgs = _build_conversation(10, tool_result_size=200)
        result = adaptive_prune(msgs, target_tokens=50_000)
        tokens = estimate_message_tokens(result)
        assert tokens <= 50_000 * 0.7 + 1000


# ---------------------------------------------------------------------------
# TestUsagePctUncapped
# ---------------------------------------------------------------------------


class TestUsagePctUncapped:
    def test_usage_pct_exceeds_100(self):
        """usage_pct should reflect actual value, not capped at 100."""
        from core.orchestration.context_monitor import check_context

        msgs = [_make_msg("user", "x" * 400_000)]
        # Patch at the import source inside check_context
        with patch(
            "core.llm.token_tracker.MODEL_CONTEXT_WINDOW",
            {"tiny-model": 10_000},
        ):
            metrics = check_context(msgs, "tiny-model")
            assert metrics.usage_pct > 100.0


# ---------------------------------------------------------------------------
# TestCmdCompact
# ---------------------------------------------------------------------------


class TestCmdCompact:
    def _make_ctx(self, messages: list[dict[str, Any]]) -> MagicMock:
        ctx = MagicMock()
        ctx.messages = messages
        ctx._sanitize_tool_pairs = MagicMock()
        return ctx

    def test_compact_empty(self):
        from core.cli.commands import cmd_compact, set_conversation_context

        set_conversation_context(None)
        cmd_compact("")  # should not raise

    def test_compact_normal(self):
        from core.cli.commands import cmd_compact, set_conversation_context

        msgs = _build_conversation(10, tool_result_size=500)
        ctx = self._make_ctx(msgs)
        set_conversation_context(ctx)

        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "glm-5"
            cmd_compact("")

        ctx._sanitize_tool_pairs.assert_called_once()

    def test_compact_hard(self):
        from core.cli.commands import cmd_compact, set_conversation_context

        msgs = _build_conversation(10, tool_result_size=500)
        ctx = self._make_ctx(msgs)
        set_conversation_context(ctx)

        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "glm-5"
            cmd_compact("--hard")

        assert len(ctx.messages) == 2


# ---------------------------------------------------------------------------
# TestCmdClear
# ---------------------------------------------------------------------------


class TestCmdClear:
    def test_clear_empty(self):
        from core.cli.commands import cmd_clear, set_conversation_context

        ctx = MagicMock()
        ctx.messages = []
        set_conversation_context(ctx)
        cmd_clear("")
        ctx.clear.assert_not_called()

    def test_clear_with_force(self):
        from core.cli.commands import cmd_clear, set_conversation_context

        ctx = MagicMock()
        ctx.messages = [_make_msg("user", "hi"), _make_msg("assistant", "hello")]
        set_conversation_context(ctx)
        cmd_clear("--force")
        ctx.clear.assert_called_once()

    @patch("builtins.input", return_value="n")
    def test_clear_cancel(self, mock_input: MagicMock):
        from core.cli.commands import cmd_clear, set_conversation_context

        ctx = MagicMock()
        ctx.messages = [_make_msg("user", "hi")]
        set_conversation_context(ctx)
        cmd_clear("")
        ctx.clear.assert_not_called()


# ---------------------------------------------------------------------------
# TestModelSwitchGuard
# ---------------------------------------------------------------------------


class TestModelSwitchGuard:
    def _make_profile(self, model_id: str, label: str) -> Any:
        from core.cli.commands import ModelProfile

        return ModelProfile(id=model_id, provider="test", label=label, cost="$")

    @patch("core.cli.commands._upsert_env")
    @patch("core.cli.commands._check_provider_key")
    def test_downgrade_blocked(
        self,
        mock_key: MagicMock,
        mock_env: MagicMock,
    ):
        from core.cli.commands import (
            _apply_model,
            set_conversation_context,
        )

        ctx = MagicMock()
        # 1M chars = ~250K tokens — exceeds GLM-5 200K window
        ctx.messages = [_make_msg("user", "x" * 1_000_000)]
        set_conversation_context(ctx)

        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "claude-opus-4-6"
            profile = self._make_profile("glm-5", "GLM-5")
            _apply_model(profile)

        mock_env.assert_not_called()

    @patch("core.cli.commands._upsert_env")
    @patch("core.cli.commands._check_provider_key")
    def test_downgrade_allowed_when_fits(
        self,
        mock_key: MagicMock,
        mock_env: MagicMock,
    ):
        from core.cli.commands import (
            _apply_model,
            set_conversation_context,
        )

        ctx = MagicMock()
        ctx.messages = [_make_msg("user", "small context")]
        set_conversation_context(ctx)

        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "claude-opus-4-6"
            profile = self._make_profile("glm-5", "GLM-5")
            _apply_model(profile)

        mock_env.assert_called_once()

    @patch("core.cli.commands._upsert_env")
    @patch("core.cli.commands._check_provider_key")
    def test_upgrade_always_allowed(
        self,
        mock_key: MagicMock,
        mock_env: MagicMock,
    ):
        from core.cli.commands import (
            _apply_model,
            set_conversation_context,
        )

        ctx = MagicMock()
        ctx.messages = [_make_msg("user", "x" * 400_000)]
        set_conversation_context(ctx)

        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "glm-5"
            profile = self._make_profile("claude-opus-4-6", "Opus 4.6")
            _apply_model(profile)

        mock_env.assert_called_once()

    @patch("core.cli.commands._upsert_env")
    @patch("core.cli.commands._check_provider_key")
    def test_same_model_no_guard(
        self,
        mock_key: MagicMock,
        mock_env: MagicMock,
    ):
        from core.cli.commands import _apply_model

        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "glm-5"
            profile = self._make_profile("glm-5", "GLM-5")
            _apply_model(profile)

        mock_env.assert_not_called()


# ---------------------------------------------------------------------------
# TestManageContextHandler
# ---------------------------------------------------------------------------


class TestManageContextHandler:
    def test_status(self):
        from core.cli.commands import set_conversation_context
        from core.cli.tool_handlers import _build_context_handlers

        ctx = MagicMock()
        ctx.messages = [
            _make_msg("user", "hi"),
            _make_msg("assistant", "hello"),
        ]
        set_conversation_context(ctx)

        handlers = _build_context_handlers()
        with patch("core.config.settings") as mock_settings:
            mock_settings.model = "claude-opus-4-6"
            result = handlers["manage_context"](action="status")

        assert result["status"] == "ok"
        assert result["messages"] == 2

    def test_clear_needs_force(self):
        from core.cli.commands import set_conversation_context
        from core.cli.tool_handlers import _build_context_handlers

        ctx = MagicMock()
        ctx.messages = [_make_msg("user", "hi")]
        set_conversation_context(ctx)

        handlers = _build_context_handlers()
        result = handlers["manage_context"](action="clear", force=False)
        assert result["status"] == "confirmation_needed"
        ctx.clear.assert_not_called()

    def test_clear_with_force(self):
        from core.cli.commands import set_conversation_context
        from core.cli.tool_handlers import _build_context_handlers

        ctx = MagicMock()
        ctx.messages = [_make_msg("user", "hi")]
        set_conversation_context(ctx)

        handlers = _build_context_handlers()
        result = handlers["manage_context"](action="clear", force=True)
        assert result["status"] == "ok"
        ctx.clear.assert_called_once()

    def test_no_context(self):
        from core.cli.commands import set_conversation_context
        from core.cli.tool_handlers import _build_context_handlers

        set_conversation_context(None)
        handlers = _build_context_handlers()
        result = handlers["manage_context"](action="status")
        assert "error" in result


# ---------------------------------------------------------------------------
# TestEscalationCompact
# ---------------------------------------------------------------------------


class TestEscalationCompact:
    def test_escalation_compacts_when_needed(self):
        context = MagicMock()
        context.messages = [_make_msg("user", "x" * 400_000)]

        loop = MagicMock()
        loop.model = "glm-5"
        loop.context = context
        loop._provider = "glm"
        loop._adapter = MagicMock(fallback_chain=["glm-5", "glm-5-turbo", "glm-4.7-flash"])
        loop.update_model = MagicMock()

        from core.agent.agentic_loop import AgenticLoop

        result = AgenticLoop._try_model_escalation(loop)
        assert result is True
        loop.update_model.assert_called_once()

    def test_escalation_no_compact_when_fits(self):
        context = MagicMock()
        context.messages = [_make_msg("user", "small")]

        loop = MagicMock()
        loop.model = "glm-5"
        loop.context = context
        loop._provider = "glm"
        loop._adapter = MagicMock(fallback_chain=["glm-5", "glm-5-turbo"])
        loop.update_model = MagicMock()

        from core.agent.agentic_loop import AgenticLoop

        result = AgenticLoop._try_model_escalation(loop)
        assert result is True
        loop.update_model.assert_called_once()
