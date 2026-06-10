"""Tests for client-side conversation compaction and provider-aware context strategy."""

from __future__ import annotations

import asyncio

from core.orchestration.compaction import (
    COMPACTION_MARKER,
    _build_summary_input,
    compact_conversation,
)

# ---------------------------------------------------------------------------
# _build_summary_input
# ---------------------------------------------------------------------------


class TestBuildSummaryInput:
    def test_simple_messages(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _build_summary_input(msgs)
        assert "user: Hello" in result
        assert "assistant: Hi there" in result

    def test_tool_result_blocks(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "tool output here", "tool_use_id": "t1"}
                ],
            }
        ]
        result = _build_summary_input(msgs)
        assert "tool output" in result

    def test_caps_long_content(self):
        msgs = [{"role": "user", "content": "x" * 5000}]
        result = _build_summary_input(msgs)
        assert len(result) <= 2100  # 2000 cap + role prefix

    def test_empty_messages(self):
        assert _build_summary_input([]) == ""


# ---------------------------------------------------------------------------
# compact_conversation — skip for Anthropic
# ---------------------------------------------------------------------------


class TestCompactConversation:
    def test_anthropic_skip(self):
        msgs = [{"role": "user", "content": "hi"}] * 20
        result, did_compact = asyncio.run(
            compact_conversation(msgs, provider="anthropic", model="claude-opus-4-6")
        )
        assert not did_compact
        assert result is msgs

    def test_too_few_messages(self):
        msgs = [{"role": "user", "content": "hi"}] * 5
        result, did_compact = asyncio.run(
            compact_conversation(msgs, provider="openai", model="gpt-4.1", keep_recent=10)
        )
        assert not did_compact

    def test_compact_with_mock(self, monkeypatch):
        """Test full compaction flow with mocked LLM call."""
        msgs = [{"role": "user", "content": f"message {i}"} for i in range(20)]

        async def mock_summarize(text, provider, model):
            return "Summary of conversation about messages 0-9."

        monkeypatch.setattr(
            "core.orchestration.compaction._call_summarize",
            mock_summarize,
        )

        result, did_compact = asyncio.run(
            compact_conversation(msgs, provider="openai", model="gpt-4.1", keep_recent=5)
        )
        assert did_compact
        assert len(result) < len(msgs)
        # Should contain summary, marker, and recent messages
        contents = [m.get("content", "") for m in result]
        assert any("Summary" in str(c) for c in contents)
        assert any(COMPACTION_MARKER in str(c) for c in contents)
        # Recent messages preserved
        assert any("message 19" in str(c) for c in contents)

    def test_compact_fallback_on_failure(self, monkeypatch):
        """If summarization fails, return original messages."""
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(20)]

        async def mock_fail(text, provider, model):
            return None

        monkeypatch.setattr(
            "core.orchestration.compaction._call_summarize",
            mock_fail,
        )

        result, did_compact = asyncio.run(
            compact_conversation(msgs, provider="openai", model="gpt-4.1", keep_recent=5)
        )
        assert not did_compact
        assert result is msgs


# ---------------------------------------------------------------------------
# context_action hook — provider-aware strategy
# ---------------------------------------------------------------------------


class TestContextActionStrategy:
    def test_anthropic_none_at_warning(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 1_000_000, "usage_pct": 85},
                "provider": "anthropic",
            },
        )
        assert result["strategy"] == "none"

    def test_anthropic_prune_at_critical(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 1_000_000, "usage_pct": 96},
                "provider": "anthropic",
            },
        )
        assert result["strategy"] == "prune"

    def test_openai_compact_at_warning(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 1_000_000, "usage_pct": 85},
                "provider": "openai",
            },
        )
        assert result["strategy"] == "compact"

    def test_openai_prune_at_critical(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 1_000_000, "usage_pct": 96},
                "provider": "openai",
            },
        )
        assert result["strategy"] == "prune"

    def test_glm_compact_at_warning(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 200_000, "usage_pct": 82},
                "provider": "glm",
            },
        )
        assert result["strategy"] == "compact"

    def test_glm_none_below_threshold(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 200_000, "usage_pct": 50},
                "provider": "glm",
            },
        )
        assert result["strategy"] == "none"

    def test_small_context_model_prune(self):
        from core.hooks.context_action import make_context_action_handler
        from core.hooks.system import HookEvent

        _, handler = make_context_action_handler()
        result = handler(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            {
                "metrics": {"context_window": 128_000, "usage_pct": 85},
                "provider": "openai",
            },
        )
        assert result["strategy"] == "prune"
        assert result["keep_recent"] <= 5
