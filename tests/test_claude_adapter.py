"""Tests for L1 ClaudeAdapter (wraps existing llm/client.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from core.llm.router import ClaudeAdapter, LLMClientPort


class TestClaudeAdapter:
    def test_implements_port(self):
        """ClaudeAdapter is a valid LLMClientPort subclass."""
        adapter = ClaudeAdapter()
        assert isinstance(adapter, LLMClientPort)

    @patch("core.llm.router.call_llm")
    def test_generate_delegates(self, mock_call):
        mock_call.return_value = "test response"
        adapter = ClaudeAdapter()
        result = adapter.generate("system", "user")
        assert result == "test response"
        mock_call.assert_called_once_with(
            "system", "user", model=None, max_tokens=4096, temperature=0.3
        )

    @patch("core.llm.router.call_llm")
    def test_generate_with_kwargs(self, mock_call):
        mock_call.return_value = "custom"
        adapter = ClaudeAdapter()
        adapter.generate("s", "u", model="claude-opus", max_tokens=100, temperature=0.8)
        mock_call.assert_called_once_with(
            "s", "u", model="claude-opus", max_tokens=100, temperature=0.8
        )

    @patch("core.llm.router.call_llm_json")
    def test_generate_structured_delegates(self, mock_call):
        mock_call.return_value = {"score": 4.2}
        adapter = ClaudeAdapter()
        result = adapter.generate_structured("system", "user")
        assert result == {"score": 4.2}

    @patch("core.llm.router.call_llm_streaming_async")
    def test_agenerate_stream_delegates(self, mock_call):
        async def _stream():
            for token in ["hello", " ", "world"]:
                yield token

        async def _collect():
            adapter = ClaudeAdapter()
            return [token async for token in adapter.agenerate_stream("system", "user")]

        mock_call.return_value = _stream()
        tokens = asyncio.run(_collect())
        assert tokens == ["hello", " ", "world"]
