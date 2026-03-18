"""Tests for context overflow detection (Karpathy P6 Context Budget)."""

from __future__ import annotations

from core.orchestration.context_monitor import (
    WARNING_THRESHOLD,
    ContextMetrics,
    check_context,
    estimate_message_tokens,
    prune_oldest_messages,
)

# ---------------------------------------------------------------------------
# estimate_message_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_messages(self):
        assert estimate_message_tokens([]) == 1  # min 1

    def test_simple_text(self):
        msg = [{"role": "user", "content": "hello world"}]  # 11 chars → ~2-3 tokens
        tokens = estimate_message_tokens(msg)
        assert tokens >= 1
        assert tokens < 20

    def test_list_content_blocks(self):
        msg = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Here is my response."},
                    {"type": "tool_use", "id": "tu_1", "name": "search", "input": {}},
                ],
            }
        ]
        tokens = estimate_message_tokens(msg)
        assert tokens > 1

    def test_tool_result_content(self):
        msg = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": "search result text here with some data",
                    }
                ],
            }
        ]
        tokens = estimate_message_tokens(msg)
        assert tokens > 1

    def test_nested_list_content(self):
        msg = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": [
                            {"type": "text", "text": "nested result"},
                        ],
                    }
                ],
            }
        ]
        tokens = estimate_message_tokens(msg)
        assert tokens > 1

    def test_string_content_in_list(self):
        msg = [{"role": "user", "content": ["plain string"]}]
        tokens = estimate_message_tokens(msg)
        assert tokens >= 1

    def test_large_conversation(self):
        """Large conversation should estimate more tokens."""
        small = [{"role": "user", "content": "short"}]
        large = [{"role": "user", "content": "x" * 10000}]
        assert estimate_message_tokens(large) > estimate_message_tokens(small)


# ---------------------------------------------------------------------------
# check_context
# ---------------------------------------------------------------------------


class TestCheckContext:
    def test_small_context_no_warning(self):
        msgs = [{"role": "user", "content": "hello"}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert not metrics.is_warning
        assert not metrics.is_critical
        assert metrics.usage_pct < WARNING_THRESHOLD
        assert metrics.remaining_tokens > 0

    def test_large_context_triggers_warning(self):
        # Build messages that exceed 80% of context window
        # claude-opus-4-6 = 200k context
        # 80% = 160k tokens → ~640k chars
        big_msg = "x" * (640_000)
        msgs = [{"role": "user", "content": big_msg}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert metrics.is_warning

    def test_critical_threshold(self):
        # 95% of 200k = 190k tokens → ~760k chars
        big_msg = "x" * (760_000)
        msgs = [{"role": "user", "content": big_msg}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert metrics.is_critical

    def test_unknown_model_uses_default(self):
        msgs = [{"role": "user", "content": "hi"}]
        metrics = check_context(msgs, "unknown-model-xyz")
        # Should use 200_000 as default
        assert metrics.context_window == 200_000

    def test_system_prompt_counted(self):
        msgs = [{"role": "user", "content": "hi"}]
        small = check_context(msgs, "claude-opus-4-6", system_prompt="")
        big = check_context(msgs, "claude-opus-4-6", system_prompt="y" * 100_000)
        assert big.estimated_tokens > small.estimated_tokens

    def test_metrics_dataclass_fields(self):
        metrics = check_context([{"role": "user", "content": "test"}], "claude-opus-4-6")
        assert isinstance(metrics, ContextMetrics)
        assert isinstance(metrics.estimated_tokens, int)
        assert isinstance(metrics.context_window, int)
        assert isinstance(metrics.usage_pct, float)
        assert isinstance(metrics.remaining_tokens, int)
        assert isinstance(metrics.is_warning, bool)
        assert isinstance(metrics.is_critical, bool)

    def test_usage_pct_capped_at_100(self):
        huge_msg = "x" * 2_000_000
        metrics = check_context([{"role": "user", "content": huge_msg}], "claude-opus-4-6")
        assert metrics.usage_pct <= 100.0


# ---------------------------------------------------------------------------
# prune_oldest_messages
# ---------------------------------------------------------------------------


class TestPruneOldestMessages:
    def test_no_prune_when_small(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(5)]
        result = prune_oldest_messages(msgs, keep_recent=10)
        assert len(result) == 5

    def test_prune_keeps_first_and_recent(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(50)]
        result = prune_oldest_messages(msgs, keep_recent=5)
        assert len(result) == 6  # first + last 5
        assert result[0]["content"] == "msg0"
        assert result[-1]["content"] == "msg49"

    def test_prune_exact_boundary(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = prune_oldest_messages(msgs, keep_recent=10)
        assert len(result) == 10  # no pruning needed

    def test_default_keep_recent(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(30)]
        result = prune_oldest_messages(msgs)
        # Default keep_recent=10 → first + last 10 = 11
        assert len(result) == 11
