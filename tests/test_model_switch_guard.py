"""Tests for model switch context guard — hybrid adaptation.

Scenarios from research doc §5.3:
T1: Large context → small model → adapts (tool result summarize + prune)
T2: Small context → small model → no adaptation needed
T3: Huge context → small model → adapts to fit
T4: Small model → large model (upgrade) → no adaptation
T5: Escalation path — fallback triggers adaptation
T6: Pure text (no tool results) → pruning only
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from core.agent.agentic_loop import AgenticLoop
from core.agent.conversation import ConversationContext
from core.agent.tool_executor import ToolExecutor
from core.orchestration.context_monitor import (
    check_context,
    summarize_tool_results,
)


def _make_tool_result_msg(content: str, tool_use_id: str = "tu_1") -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
    }


def _build_large_conversation(
    num_tool_results: int = 10,
    tool_result_chars: int = 50_000,
    num_text_msgs: int = 5,
) -> list[dict[str, Any]]:
    """Build a conversation with large tool results."""
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "initial question"}]
    for i in range(num_tool_results):
        msgs.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"tu_{i}",
                        "name": "web_fetch",
                        "input": {"url": "http://example.com"},
                    }
                ],
            }
        )
        msgs.append(_make_tool_result_msg("x" * tool_result_chars, f"tu_{i}"))
    for i in range(num_text_msgs):
        msgs.append({"role": "user", "content": f"follow-up question {i}"})
        msgs.append({"role": "assistant", "content": f"response {i}"})
    return msgs


# ---------------------------------------------------------------------------
# T1: Opus(500K) → GLM-5(80K) — adaptation with tool result summarization
# ---------------------------------------------------------------------------


class TestT1LargeToSmall:
    def test_tool_results_summarized(self):
        msgs = _build_large_conversation(num_tool_results=10, tool_result_chars=50_000)
        # Before: ~125K tokens of tool results
        before_tokens = check_context(msgs, "glm-5").estimated_tokens
        assert before_tokens > 80_000  # exceeds GLM-5 window

        count = summarize_tool_results(msgs, target_window=80_000)
        assert count > 0

        after_tokens = check_context(msgs, "glm-5").estimated_tokens
        assert after_tokens < before_tokens

    def test_adapt_context_reduces_tokens(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation()

        loop = _make_loop(ctx, model="claude-opus-4-6")
        before = check_context(ctx.messages, "glm-5").estimated_tokens

        loop._adapt_context_for_model("glm-5")

        after = check_context(ctx.messages, "glm-5").estimated_tokens
        assert after < before


# ---------------------------------------------------------------------------
# T2: Small context → GLM-5 — no adaptation
# ---------------------------------------------------------------------------


class TestT2SmallContext:
    def test_no_adaptation_needed(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        original = list(ctx.messages)

        loop = _make_loop(ctx, model="claude-opus-4-6")
        loop._adapt_context_for_model("glm-5")

        # Messages unchanged
        assert ctx.messages == original


# ---------------------------------------------------------------------------
# T3: Huge context → still fits after adaptation
# ---------------------------------------------------------------------------


class TestT3HugeContext:
    def test_extreme_context_adapted(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=30, tool_result_chars=100_000)
        before = check_context(ctx.messages, "glm-5")
        assert before.usage_pct > 200  # way over

        loop = _make_loop(ctx, model="claude-opus-4-6")
        loop._adapt_context_for_model("glm-5")

        after = check_context(ctx.messages, "glm-5")
        assert after.estimated_tokens < before.estimated_tokens


# ---------------------------------------------------------------------------
# T4: GLM-5 → Opus (upgrade) — no adaptation
# ---------------------------------------------------------------------------


class TestT4Upgrade:
    def test_upgrade_no_adaptation(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "x" * 50_000},
            {"role": "assistant", "content": "response"},
        ]
        original_count = len(ctx.messages)

        loop = _make_loop(ctx, model="glm-5")
        loop._adapt_context_for_model("claude-opus-4-6")

        # No changes — context fits easily in 1M window
        assert len(ctx.messages) == original_count


# ---------------------------------------------------------------------------
# T6: Pure text (no tool results) — pruning only
# ---------------------------------------------------------------------------


class TestT6PureText:
    def test_text_only_pruned(self):
        msgs = []
        for i in range(100):
            msgs.append({"role": "user", "content": f"{'y' * 5_000} q{i}"})
            msgs.append({"role": "assistant", "content": f"{'z' * 5_000} a{i}"})

        # Should exceed 80K context of GLM-5
        before = check_context(msgs, "glm-5")
        assert before.is_warning

        ctx = ConversationContext()
        ctx.messages = msgs

        loop = _make_loop(ctx, model="claude-opus-4-6")
        loop._adapt_context_for_model("glm-5")

        after = check_context(ctx.messages, "glm-5")
        assert after.estimated_tokens < before.estimated_tokens


# ---------------------------------------------------------------------------
# update_model triggers adaptation
# ---------------------------------------------------------------------------


class TestUpdateModelIntegration:
    def test_update_model_calls_adapt(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation()

        loop = _make_loop(ctx, model="claude-opus-4-6")
        before = check_context(ctx.messages, "glm-5").estimated_tokens

        with patch("core.cli.ui.agentic_ui.update_session_model"):
            loop.update_model("glm-5", "zhipuai")

        after = check_context(ctx.messages, "glm-5").estimated_tokens
        assert after < before

    def test_update_model_empty_context_no_crash(self):
        ctx = ConversationContext()  # empty

        loop = _make_loop(ctx, model="claude-opus-4-6")
        with patch("core.cli.ui.agentic_ui.update_session_model"):
            loop.update_model("glm-5", "zhipuai")
        # No crash


# ---------------------------------------------------------------------------
# usage_pct cap removed
# ---------------------------------------------------------------------------


class TestUsagePctNoCap:
    def test_exceeds_100_percent(self):
        huge_msg = "x" * 2_000_000  # ~500K tokens
        metrics = check_context([{"role": "user", "content": huge_msg}], "glm-5")
        # 500K / 80K = 625%
        assert metrics.usage_pct > 100.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(ctx: ConversationContext, model: str = "claude-opus-4-6") -> AgenticLoop:
    """Create a minimal AgenticLoop for testing context adaptation."""
    adapter = MagicMock()
    adapter.fallback_chain = [model]
    executor = ToolExecutor()

    with patch("core.agent.agentic_loop.resolve_agentic_adapter", return_value=adapter):
        loop = AgenticLoop(
            model=model,
            context=ctx,
            tool_executor=executor,
        )
    return loop
