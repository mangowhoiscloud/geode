"""Tests for context overflow detection (Karpathy P6 Context Budget)."""

from __future__ import annotations

from core.orchestration.context_monitor import (
    WARNING_THRESHOLD,
    ContextMetrics,
    adaptive_prune,
    check_context,
    estimate_message_tokens,
    prune_oldest_messages,
    summarize_tool_results,
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
        # claude-opus-4-6 = 1M context (updated 2026-03-19)
        # 80% = 800k tokens → ~3.2M chars
        big_msg = "x" * (3_200_000)
        msgs = [{"role": "user", "content": big_msg}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert metrics.is_warning

    def test_critical_threshold(self):
        # 95% of 1M = 950k tokens → ~3.8M chars (opus-4-6 has 1M ctx)
        big_msg = "x" * (3_800_000)
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

    def test_usage_pct_not_capped(self):
        """usage_pct should reflect actual value, even above 100%."""
        huge_msg = "x" * 2_000_000
        metrics = check_context([{"role": "user", "content": huge_msg}], "glm-5")
        # 2M chars / 4 = 500K tokens vs 80K window → well above 100%
        assert metrics.usage_pct > 100.0


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


# ---------------------------------------------------------------------------
# summarize_tool_results
# ---------------------------------------------------------------------------


class TestSummarizeToolResults:
    def test_no_tool_results(self):
        msgs = [{"role": "user", "content": "hello"}]
        count = summarize_tool_results(msgs, target_window=80_000)
        assert count == 0

    def test_small_tool_result_untouched(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": "small result",
                    }
                ],
            }
        ]
        count = summarize_tool_results(msgs, target_window=80_000)
        assert count == 0
        assert msgs[0]["content"][0]["content"] == "small result"

    def test_large_tool_result_summarized(self):
        # 80K window → 5% threshold = 4K tokens = 16K chars
        big_content = "x" * 100_000  # ~25K tokens, well above threshold
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": big_content,
                    }
                ],
            }
        ]
        count = summarize_tool_results(msgs, target_window=80_000)
        assert count == 1
        assert "[summarized:" in msgs[0]["content"][0]["content"]

    def test_multiple_results_mixed(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": "x" * 100_000,
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_2",
                        "content": "small",
                    },
                ],
            }
        ]
        count = summarize_tool_results(msgs, target_window=80_000)
        assert count == 1

    def test_assistant_messages_skipped(self):
        msgs = [{"role": "assistant", "content": [{"type": "text", "text": "x" * 100_000}]}]
        count = summarize_tool_results(msgs, target_window=80_000)
        assert count == 0

    def test_non_list_content_skipped(self):
        msgs = [{"role": "user", "content": "x" * 100_000}]
        count = summarize_tool_results(msgs, target_window=80_000)
        assert count == 0


# ---------------------------------------------------------------------------
# adaptive_prune
# ---------------------------------------------------------------------------


class TestAdaptivePrune:
    def test_tiny_conversation_unchanged(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = adaptive_prune(msgs, target_tokens=80_000)
        assert len(result) == 2

    def test_fits_in_budget(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        result = adaptive_prune(msgs, target_tokens=80_000)
        # All should fit — short messages
        assert len(result) == 10

    def test_prunes_to_fit_budget(self):
        # Each message ~2500 tokens (10K chars / 4)
        msgs = [{"role": "user", "content": f"{'x' * 10_000} msg{i}"} for i in range(50)]
        # Budget: 80K * 0.7 = 56K → can fit ~22 messages
        result = adaptive_prune(msgs, target_tokens=80_000)
        assert len(result) < 50
        # First message preserved
        assert "msg0" in result[0]["content"]
        # Last 2 preserved
        assert "msg49" in result[-1]["content"]
        assert "msg48" in result[-2]["content"]

    def test_preserves_first_and_last(self):
        msgs = [
            {"role": "user", "content": "FIRST"},
            {"role": "assistant", "content": "x" * 100_000},
            {"role": "user", "content": "x" * 100_000},
            {"role": "assistant", "content": "SECOND_LAST"},
            {"role": "user", "content": "LAST"},
        ]
        result = adaptive_prune(msgs, target_tokens=10_000)
        assert result[0]["content"] == "FIRST"
        assert result[-1]["content"] == "LAST"
        assert result[-2]["content"] == "SECOND_LAST"

    def test_minimal_when_base_exceeds_budget(self):
        msgs = [
            {"role": "user", "content": "x" * 100_000},
            {"role": "assistant", "content": "mid"},
            {"role": "user", "content": "x" * 100_000},
            {"role": "assistant", "content": "last_a"},
            {"role": "user", "content": "x" * 100_000},
        ]
        # Very tight budget: first + last 2 already exceed it
        result = adaptive_prune(msgs, target_tokens=1_000)
        # Should still return first + last 2 (minimal)
        assert len(result) == 3
        assert result[0] == msgs[0]
        assert result[-1] == msgs[-1]

    def test_chronological_order_preserved(self):
        msgs = [{"role": "user", "content": f"msg{i:02d}"} for i in range(20)]
        result = adaptive_prune(msgs, target_tokens=80_000)
        # Verify chronological order
        contents = [m["content"] for m in result]
        assert contents == sorted(contents)


# ---------------------------------------------------------------------------
# _compute_model_tool_limit
# ---------------------------------------------------------------------------


class TestComputeModelToolLimit:
    def test_large_model_unlimited(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        # 1M context → unlimited (server-side handles it)
        assert _compute_model_tool_limit("claude-opus-4-6") == 0

    def test_glm5_unlimited(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        # GLM-5: 200K context → unlimited (server-side handles it)
        limit = _compute_model_tool_limit("glm-5")
        assert limit == 0

    def test_200k_model_unlimited(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        # 200K context → unlimited (threshold boundary)
        assert _compute_model_tool_limit("glm-5-turbo") == 0

    def test_unknown_model_unlimited(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        # Unknown → default 200K → unlimited
        assert _compute_model_tool_limit("unknown-xyz") == 0


# ---------------------------------------------------------------------------
# _guard_tool_result with model limits
# ---------------------------------------------------------------------------


class TestGuardToolResultModelAware:
    def test_small_result_not_truncated(self):
        from core.agent.tool_executor import _guard_tool_result

        result = {"data": "short text"}
        guarded = _guard_tool_result(result, max_tokens=4000)
        assert "_truncated" not in guarded
        assert guarded == result

    def test_large_result_truncated(self):
        from core.agent.tool_executor import _guard_tool_result

        # 100K chars ≈ 25K tokens, limit = 4K tokens
        result = {"content": "x" * 100_000}
        guarded = _guard_tool_result(result, max_tokens=4000)
        assert guarded.get("_truncated") is True
        assert guarded["_original_tokens"] > 4000

    def test_summary_preserved_on_truncation(self):
        from core.agent.tool_executor import _guard_tool_result

        result = {"summary": "key info", "content": "x" * 100_000, "task_id": "t1"}
        guarded = _guard_tool_result(result, max_tokens=4000)
        assert guarded["summary"] == "key info"
        assert guarded["task_id"] == "t1"
        assert guarded["_truncated"] is True
