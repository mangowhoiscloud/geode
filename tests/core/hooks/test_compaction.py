"""Tests for client-side conversation compaction and provider-aware context strategy."""

from __future__ import annotations

import asyncio

import pytest
from core.orchestration.compaction import (
    COMPACTION_MARKER,
    _build_summary_input,
    compact_conversation,
)
from core.orchestration.context_budget import resolve_context_budget_policy

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
        policy = resolve_context_budget_policy()
        msgs = [{"role": "user", "content": "x" * 10_000}]
        result = _build_summary_input(msgs)
        assert len(result) <= policy.summary_input_message_max_chars + 100
        assert "truncated" in result

    def test_empty_messages(self):
        assert _build_summary_input([]) == ""


# ---------------------------------------------------------------------------
# compact_conversation — native histories retain their provider-owned summary
# ---------------------------------------------------------------------------


class TestCompactConversation:
    def test_native_anthropic_history_skip(self):
        msgs = [{"role": "user", "content": "hi"}] * 20
        msgs.append({"role": "assistant", "content": [{"type": "compaction", "content": "native"}]})
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

        async def mock_summarize(text, provider, model, *, max_tokens, **_observation):
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

    def test_compact_empty_summary_preserves_history_and_reports_failure(self, monkeypatch):
        """The manager must distinguish a failed summary from a no-op."""
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(20)]

        async def mock_fail(text, provider, model, *, max_tokens, **_observation):
            return None

        monkeypatch.setattr(
            "core.orchestration.compaction._call_summarize",
            mock_fail,
        )

        with pytest.raises(ValueError, match="Compaction summary was empty"):
            asyncio.run(
                compact_conversation(msgs, provider="openai", model="gpt-4.1", keep_recent=5)
            )
        assert msgs == [{"role": "user", "content": f"msg {i}"} for i in range(20)]
