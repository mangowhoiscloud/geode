"""Tests for L1 ClaudeAdapter (wraps existing llm/client.py)."""

from __future__ import annotations

from unittest.mock import patch

from geode.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter
from geode.infrastructure.ports.llm_port import LLMClientPort


class TestClaudeAdapter:
    def test_implements_port(self):
        """ClaudeAdapter is a valid LLMClientPort subclass."""
        adapter = ClaudeAdapter()
        assert isinstance(adapter, LLMClientPort)

    @patch("geode.infrastructure.adapters.llm.claude_adapter.call_llm")
    def test_generate_delegates(self, mock_call):
        mock_call.return_value = "test response"
        adapter = ClaudeAdapter()
        result = adapter.generate("system", "user")
        assert result == "test response"
        mock_call.assert_called_once_with(
            "system", "user", model=None, max_tokens=4096, temperature=0.3
        )

    @patch("geode.infrastructure.adapters.llm.claude_adapter.call_llm")
    def test_generate_with_kwargs(self, mock_call):
        mock_call.return_value = "custom"
        adapter = ClaudeAdapter()
        adapter.generate("s", "u", model="claude-opus", max_tokens=100, temperature=0.8)
        mock_call.assert_called_once_with(
            "s", "u", model="claude-opus", max_tokens=100, temperature=0.8
        )

    @patch("geode.infrastructure.adapters.llm.claude_adapter.call_llm_json")
    def test_generate_structured_delegates(self, mock_call):
        mock_call.return_value = {"score": 4.2}
        adapter = ClaudeAdapter()
        result = adapter.generate_structured("system", "user")
        assert result == {"score": 4.2}

    @patch("geode.infrastructure.adapters.llm.claude_adapter.call_llm_streaming")
    def test_generate_stream_delegates(self, mock_call):
        mock_call.return_value = iter(["hello", " ", "world"])
        adapter = ClaudeAdapter()
        tokens = list(adapter.generate_stream("system", "user"))
        assert tokens == ["hello", " ", "world"]
