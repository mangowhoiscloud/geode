"""Tests for GAP 7: Context Compactor (LLM-based summarization)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from core.orchestration.context_compactor import (
    CompactionResult,
    _messages_to_text,
    compact_context,
)


def _build_messages(count: int) -> list[dict[str, Any]]:
    """Build a list of alternating user/assistant messages."""
    msgs: list[dict[str, Any]] = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}: some content here."})
    return msgs


class TestMessagesToText:
    """_messages_to_text() conversion."""

    def test_simple_messages(self) -> None:
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        text = _messages_to_text(msgs)
        assert "[user]: hello" in text
        assert "[assistant]: hi there" in text

    def test_block_content(self) -> None:
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me help"},
                    {"type": "tool_use", "name": "analyze_ip"},
                ],
            }
        ]
        text = _messages_to_text(msgs)
        assert "Let me help" in text
        assert "analyze_ip" in text

    def test_tool_result(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "Success: S-tier"},
                ],
            }
        ]
        text = _messages_to_text(msgs)
        assert "tool_result" in text
        assert "Success" in text


class TestCompactContext:
    """compact_context() behavior."""

    def test_too_few_messages_noop(self) -> None:
        msgs = _build_messages(5)
        result = compact_context(msgs, keep_recent=10)
        assert result.original_count == 5
        assert result.compacted_count == 5
        assert result.summary_text == ""
        assert result.tokens_saved_estimate == 0

    @patch("core.llm.client.call_llm")
    def test_compaction_replaces_middle(self, mock_llm: Any) -> None:
        mock_llm.return_value = "Summary: user discussed IP analysis."

        msgs = _build_messages(30)
        original_first = msgs[0].copy()

        result = compact_context(msgs, keep_recent=10)

        assert result.original_count == 30
        assert result.compacted_count == 12  # first + summary + 10 recent
        assert "Summary:" in result.summary_text
        assert result.tokens_saved_estimate > 0

        # Verify structure: first msg preserved
        assert msgs[0] == original_first
        # Summary message is second
        assert "Context Summary" in str(msgs[1]["content"])

    @patch("core.llm.client.call_llm")
    def test_compaction_calls_budget_model(self, mock_llm: Any) -> None:
        mock_llm.return_value = "Compressed summary."

        msgs = _build_messages(20)
        compact_context(msgs, keep_recent=5)

        # Verify budget model was called (Haiku)
        call_kwargs = mock_llm.call_args
        assert call_kwargs is not None
        model_used = call_kwargs.kwargs.get("model", "")
        assert "haiku" in model_used

    @patch("core.llm.client.call_llm")
    def test_compaction_failure_returns_noop(self, mock_llm: Any) -> None:
        mock_llm.side_effect = RuntimeError("API error")

        msgs = _build_messages(25)
        original_count = len(msgs)

        result = compact_context(msgs, keep_recent=10)

        # No change on failure
        assert result.compacted_count == original_count
        assert result.summary_text == ""
        assert len(msgs) == original_count

    @patch("core.llm.client.call_llm")
    def test_custom_model(self, mock_llm: Any) -> None:
        mock_llm.return_value = "Custom model summary."

        msgs = _build_messages(20)
        compact_context(msgs, keep_recent=5, model="custom-model")

        call_kwargs = mock_llm.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs["model"] == "custom-model"


class TestCompactionResult:
    """CompactionResult dataclass."""

    def test_frozen(self) -> None:
        r = CompactionResult(
            original_count=30,
            compacted_count=12,
            summary_text="summary",
            tokens_saved_estimate=500,
        )
        with pytest.raises(AttributeError):
            r.original_count = 0  # type: ignore[misc]
