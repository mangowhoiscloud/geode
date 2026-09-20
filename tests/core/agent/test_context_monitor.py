"""Tests for context overflow detection (Karpathy P6 Context Budget)."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from core.orchestration.context_monitor import (
    ABSOLUTE_TOKEN_CEILING,
    CHARS_PER_TOKEN,
    WARNING_THRESHOLD,
    ContextMetrics,
    adaptive_prune,
    check_context,
    estimate_message_tokens,
    mask_stale_observations,
    prune_oldest_messages,
    summarize_tool_results,
)

# ---------------------------------------------------------------------------
# estimate_message_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    @pytest.mark.parametrize("shape", ["anthropic", "responses", "legacy_responses"])
    def test_native_replay_counts_wire_content_once(self, shape, monkeypatch):
        from core.llm.adapters._anthropic_common import build_messages
        from core.llm.adapters._openai_common import build_codex_input
        from core.llm.adapters.translation import build_adapter_request

        monkeypatch.delenv("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", raising=False)
        content = [
            {"type": "text", "text": "visible " * 100},
            {"type": "tool_use", "id": "c", "name": "read_file", "input": {"path": "x" * 1000}},
        ]
        reasoning = {"type": "reasoning", "encrypted_content": "opaque" * 1000, "id": "rs_1"}
        message = {"role": "assistant", "content": content}
        if shape == "anthropic":
            message["anthropic_content"] = [
                {"type": "thinking", "thinking": "thought " * 1000, "signature": "signed"},
                {"type": "redacted_thinking", "data": "opaque" * 100},
                *content,
                "ignored non-dict entry",
            ]
        elif shape == "responses":
            message["codex_output_items"] = [
                {**reasoning, "status": "completed", "summary": []},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": content[0]["text"]},
                    ],
                },
                {
                    "type": "function_call",
                    "call_id": "c",
                    "name": "read_file",
                    "arguments": json.dumps(content[1]["input"]),
                },
            ]
            # Full output wins over legacy replay, even for conflicting persisted data.
            message["codex_reasoning_items"] = [{**reasoning, "encrypted_content": "x" * 50_000}]
        else:
            message["codex_reasoning_items"] = [reasoning, "ignored non-dict entry"]
        message["metadata"] = deepcopy(message)  # Resume metadata is not sent again.
        original = deepcopy(message)
        req = build_adapter_request(
            model="claude-fable-5" if shape == "anthropic" else "gpt-5.6-sol",
            system="",
            messages=[message],
            tools=[],
            tool_choice="auto",
            max_tokens=1024,
            temperature=0.0,
            thinking_budget=0,
            effort="high",
        )
        wire = (
            build_messages(req)[0]["content"]
            if shape == "anthropic"
            else build_codex_input(req, backend="platform")
        )
        expected = estimate_message_tokens([{"role": "assistant", "content": wire}])
        assert estimate_message_tokens([message]) == expected
        assert expected > estimate_message_tokens([{"role": "assistant", "content": content}])
        assert message == original

    def test_responses_replay_opt_out_uses_legacy_wire(self, monkeypatch):
        from core.llm.adapters._openai_common import build_codex_input
        from core.llm.adapters.base import AdapterCallRequest, Message

        monkeypatch.setenv("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", "true")
        output = [{"type": "reasoning", "encrypted_content": "unused" * 10_000}]
        legacy = [{"type": "reasoning", "encrypted_content": "retained" * 1000, "id": "rs_1"}]
        message = {
            "role": "assistant",
            "content": "visible",
            "codex_output_items": output,
            "codex_reasoning_items": legacy,
        }
        wire = build_codex_input(
            AdapterCallRequest(
                model="gpt-5.6-sol",
                messages=(
                    Message(
                        role="assistant",
                        content="visible",
                        codex_output_items=tuple(output),
                        codex_reasoning_items=tuple(legacy),
                    ),
                ),
            ),
            backend="platform",
        )
        assert "id" not in wire[0]
        assert wire[0]["summary"] == []
        assert estimate_message_tokens([message]) == estimate_message_tokens(
            [
                {"role": "assistant", "content": wire},
            ]
        )

    @pytest.mark.parametrize("invalid", [None, "x" * 1000, {"text": "x" * 1000}, ["x" * 1000]])
    def test_invalid_native_sidecars_are_not_counted(self, invalid):
        message = {
            "role": "assistant",
            "content": "visible",
            "anthropic_content": invalid,
            "codex_output_items": invalid,
            "codex_reasoning_items": invalid,
            "metadata": {"anthropic_content": [{"thinking": "x" * 10_000}]},
        }
        assert estimate_message_tokens([message]) == estimate_message_tokens(
            [
                {"role": "assistant", "content": "visible"},
            ]
        )

    def test_mixed_source_sidecars_use_largest_representation_not_sum(self, monkeypatch):
        monkeypatch.delenv("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", raising=False)
        content = "visible " * 100
        sidecars = {
            "anthropic_content": [
                {"type": "thinking", "thinking": "a" * 5000, "signature": "s"},
                {"type": "text", "text": content},
            ],
            "codex_output_items": [{"type": "reasoning", "encrypted_content": "b" * 10_000}],
            "chat_reasoning": {
                "provider": "glm",
                "source": "glm-payg",
                "model": "glm-5",
                "fields": {"reasoning_content": "c" * 15_000},
            },
        }
        message = {"role": "assistant", "content": content, **sidecars}
        original = deepcopy(message)
        alternatives = [
            estimate_message_tokens([{"role": "assistant", "content": content, key: value}])
            for key, value in sidecars.items()
        ]
        assert estimate_message_tokens([message]) == max(alternatives)
        assert message == original
        # Translation drops all assistant-only replay after a role change.
        message["role"] = "user"
        assert estimate_message_tokens([message]) == len(content) // CHARS_PER_TOKEN
        # Legacy reasoning without encrypted_content is not replayable.
        assert (
            estimate_message_tokens(
                [
                    {
                        "role": "assistant",
                        "content": content,
                        "codex_reasoning_items": [{"summary": "x" * 10_000}],
                    }
                ]
            )
            == len(content) // CHARS_PER_TOKEN
        )

    @pytest.mark.parametrize(
        "fields",
        [
            {"reasoning_content": "original 생각 " * 100},
            {
                "reasoning": "summary",
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "first", "signature": "signed"},
                    {"type": "reasoning.encrypted", "data": "opaque" * 100},
                ],
            },
        ],
    )
    def test_chat_replay_counts_wire_fields_once_without_modifying_them(self, fields):
        from core.llm.adapters._openai_common import build_chat_completion_kwargs
        from core.llm.adapters.base import AdapterCallRequest, Message

        replay = {
            "provider": "openrouter",
            "source": "openrouter-payg",
            "model": "anthropic/claude-fable-5",
            "fields": fields,
        }
        message = {
            "role": "assistant",
            "content": "visible answer",
            "chat_reasoning": replay,
            "metadata": {"chat_reasoning": replay},  # SQLite resume repeats this sidecar.
        }
        original = deepcopy(message)
        wire = build_chat_completion_kwargs(
            AdapterCallRequest(
                model=replay["model"],
                messages=(
                    Message(role="assistant", content=message["content"], chat_reasoning=replay),
                ),
            ),
            provider=replay["provider"],
            adapter_name=replay["source"],
            model=replay["model"],
        )["messages"][0]
        wire_fields = {key: wire[key] for key in fields}
        expected_chars = len(wire["content"]) + len(json.dumps(wire_fields, ensure_ascii=False))
        assert estimate_message_tokens([message]) == expected_chars // CHARS_PER_TOKEN
        assert message == original
        assert wire_fields == fields

    def test_invalid_or_non_assistant_chat_replay_is_not_counted(self):
        message = {
            "role": "assistant",
            "content": "visible answer",
            "chat_reasoning": {"fields": {"reasoning_content": "x" * 10000}},
        }
        expected = estimate_message_tokens([{"role": "assistant", "content": "visible answer"}])
        assert estimate_message_tokens([message]) == expected
        message["role"] = "user"
        message["chat_reasoning"].update(provider="glm", source="glm-payg", model="glm-5")
        assert estimate_message_tokens([message]) == expected

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
        # Build messages that exceed the large-window warning threshold.
        big_msg = "x" * (3_200_000)
        msgs = [{"role": "user", "content": big_msg}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert metrics.is_warning

    def test_critical_threshold(self):
        # Large-window critical threshold should trip before API overflow.
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

    def test_ceiling_exceeded_on_large_model(self):
        """200K+ tokens on a 1M model should set is_ceiling_exceeded."""
        # 250K tokens → 1M chars
        big_msg = "x" * 1_000_000
        msgs = [{"role": "user", "content": big_msg}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert metrics.estimated_tokens > ABSOLUTE_TOKEN_CEILING
        assert metrics.is_ceiling_exceeded
        # But not warning/critical (250K/1M = 25%)
        assert not metrics.is_warning
        assert not metrics.is_critical

    def test_ceiling_not_exceeded_small_context(self):
        """Small messages on 1M model should not trigger ceiling."""
        msgs = [{"role": "user", "content": "hello"}]
        metrics = check_context(msgs, "claude-opus-4-6")
        assert not metrics.is_ceiling_exceeded

    def test_ceiling_not_triggered_for_200k_model(self):
        """Exactly-200K models are excluded — percentage thresholds handle them.

        GAP-X1 (2026-05-12): switched fixture from ``glm-5`` (202_752 per
        z.ai docs — slightly above the 200K ceiling) to ``claude-opus-4-5``
        which is registered at exactly ``200_000``.  The ceiling rule
        (``ctx_window > 200K AND tokens > 200K``) genuinely fires for the
        GLM family now that the precise window is reflected; the original
        intent of this test was "models whose window IS 200K skip the
        ceiling layer", so the new fixture preserves that invariant.
        """
        big_msg = "x" * 1_000_000
        msgs = [{"role": "user", "content": big_msg}]
        metrics = check_context(msgs, "claude-opus-4-5")
        # context_window == 200K, NOT > 200K → ceiling should be False
        assert not metrics.is_ceiling_exceeded
        # But percentage thresholds should fire
        assert metrics.is_warning or metrics.is_critical

    def test_ceiling_field_exists(self):
        """ContextMetrics includes is_ceiling_exceeded field."""
        metrics = check_context([{"role": "user", "content": "hi"}], "claude-opus-4-6")
        assert isinstance(metrics.is_ceiling_exceeded, bool)


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
    @pytest.mark.parametrize("shape", ["anthropic", "openai"])
    def test_loaded_skill_is_read_before_summarizing_and_then_remains_reloadable(self, shape):
        body = "IMPORTANT_RULE " + "x" * 16_000
        arguments = {"name": "synthetic-skill"}
        content = json.dumps({"result": {"name": arguments["name"], "instructions": body}})
        if shape == "anthropic":
            result = {"type": "tool_result", "tool_use_id": "skill-1", "content": content}
            messages = [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "skill-1",
                            "name": "use_skill",
                            "input": arguments,
                        }
                    ],
                },
                {"role": "user", "content": [result]},
            ]
        else:
            result = {"role": "tool", "tool_call_id": "skill-1", "content": content}
            messages = [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "skill-1",
                            "type": "function",
                            "function": {"name": "use_skill", "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                result,
            ]

        assert summarize_tool_results(messages, 200_000)[0] == 0
        assert result["content"] == content

        messages.append({"role": "assistant", "content": "Read the skill."})
        assert summarize_tool_results(messages, 200_000)[0] == 1
        assert "synthetic-skill" in result["content"]
        assert "call use_skill again before applying" in result["content"]
        assert "IMPORTANT_RULE" not in result["content"]

    def test_masked_skill_keeps_reload_instructions(self):
        result = {"type": "tool_result", "tool_use_id": "skill-1", "content": "x" * 1_000}
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "skill-1",
                        "name": "use_skill",
                        "input": {"name": "demo"},
                    }
                ],
            },
            {"role": "user", "content": [result]},
            {"role": "assistant", "content": "Read the skill."},
            {"role": "user", "content": "Continue."},
            {"role": "assistant", "content": "More work."},
        ]

        assert mask_stale_observations(messages, keep_recent_rounds=1) == 1
        assert '"demo"' in result["content"]
        assert "call use_skill again before applying" in result["content"]

    def test_no_tool_results(self):
        msgs = [{"role": "user", "content": "hello"}]
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=80_000)
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
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=80_000)
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
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=80_000)
        assert count == 1
        assert "[unknown]" in msgs[0]["content"][0]["content"]
        assert "summarized from" in msgs[0]["content"][0]["content"]

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
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=80_000)
        assert count == 1

    def test_assistant_messages_skipped(self):
        msgs = [{"role": "assistant", "content": [{"type": "text", "text": "x" * 100_000}]}]
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=80_000)
        assert count == 0

    def test_non_list_content_skipped(self):
        msgs = [{"role": "user", "content": "x" * 100_000}]
        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=80_000)
        assert count == 0


# ---------------------------------------------------------------------------
# adaptive_prune
# ---------------------------------------------------------------------------


class TestAdaptivePrune:
    def test_fresh_parallel_skill_result_survives_tight_budget(self):
        calls = [
            {
                "id": name,
                "type": "function",
                "function": {
                    "name": "use_skill" if name == "skill" else "read_document",
                    "arguments": "{}",
                },
            }
            for name in ("skill", "other-1", "other-2")
        ]
        fresh_batch = [
            {"role": "assistant", "tool_calls": calls},
            {"role": "tool", "tool_call_id": "skill", "content": "IMPORTANT_RULE " + "x" * 16_000},
            {"role": "tool", "tool_call_id": "other-1", "content": "small"},
            {"role": "tool", "tool_call_id": "other-2", "content": "small"},
        ]
        messages = [
            {"role": "user", "content": "request"},
            {"role": "assistant", "content": "old"},
            *fresh_batch,
        ]

        result = adaptive_prune(messages, target_tokens=10_000)

        assert result[-4:] == fresh_batch

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
    def test_large_model_uses_global_limit(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        # Large tiers do not add a tighter model-specific cap.
        assert _compute_model_tool_limit("claude-opus-4-6") is None

    def test_glm5_uses_small_tier_cap(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        limit = _compute_model_tool_limit("glm-5")
        assert limit > 0

    def test_200k_model_uses_small_tier_cap(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        assert _compute_model_tool_limit("glm-5-turbo") > 0

    def test_unknown_model_uses_default_window_cap(self):
        from core.agent.tool_executor import _compute_model_tool_limit

        assert _compute_model_tool_limit("unknown-xyz") > 0

    def test_small_model_respects_global_limit_and_opt_out(self, monkeypatch):
        from core.agent.tool_executor import _compute_model_tool_limit
        from core.config import settings

        monkeypatch.setattr(settings, "max_tool_result_tokens", 100)
        assert _compute_model_tool_limit("unknown-xyz") == 100

        for unlimited in (0, -1):
            monkeypatch.setattr(settings, "max_tool_result_tokens", unlimited)
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

    def test_truncated_json_never_exceeds_limit(self):
        from core.agent.tool_executor import _guard_tool_result

        result = {"content": '"\\\n' * 10_000}
        guarded = _guard_tool_result(result, max_tokens=32)

        assert guarded["_truncated"] is True
        assert len(json.dumps(guarded, ensure_ascii=False)) <= 32 * 4
        assert len(json.dumps(guarded, ensure_ascii=False)) < len(
            json.dumps(result, ensure_ascii=False)
        )

    def test_oversized_summary_is_bounded(self):
        from core.agent.tool_executor import _guard_tool_result

        guarded = _guard_tool_result({"summary": "x" * 10_000}, max_tokens=32)

        assert guarded["_truncated"] is True
        assert len(json.dumps(guarded, ensure_ascii=False)) <= 32 * 4
