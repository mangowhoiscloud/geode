"""Tests for LLM tool-use loop (generate_with_tools).

Tests use mocked API responses to verify multi-turn tool calling
for both ClaudeAdapter and OpenAIAdapter.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.llm.client import ToolCallRecord, ToolUseResult

# ---------------------------------------------------------------------------
# Helpers: mock Anthropic responses
# ---------------------------------------------------------------------------


def _make_anthropic_tool_use_response(
    *,
    tool_name: str = "dummy_tool",
    tool_input: dict[str, Any] | None = None,
    tool_use_id: str = "toolu_01",
) -> MagicMock:
    """Create a mock Anthropic response that requests tool use."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input or {"query": "test"}
    tool_block.id = tool_use_id

    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [tool_block]
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


def _make_anthropic_text_response(text: str = "Final answer") -> MagicMock:
    """Create a mock Anthropic response with text content."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [text_block]
    response.usage = MagicMock(input_tokens=200, output_tokens=100)
    return response


# ---------------------------------------------------------------------------
# Helpers: mock OpenAI responses
# ---------------------------------------------------------------------------


def _make_openai_tool_call_response(
    *,
    func_name: str = "dummy_tool",
    func_args: str = '{"query": "test"}',
    tool_call_id: str = "call_01",
) -> MagicMock:
    """Create a mock OpenAI response that requests tool calls."""
    tc = MagicMock()
    tc.function.name = func_name
    tc.function.arguments = func_args
    tc.id = tool_call_id

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message.content = None
    choice.message.tool_calls = [tc]

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    return response


def _make_openai_text_response(text: str = "Final answer") -> MagicMock:
    """Create a mock OpenAI response with text content."""
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = text
    choice.message.tool_calls = None

    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=200, completion_tokens=100)
    return response


# ---------------------------------------------------------------------------
# ToolCallRecord / ToolUseResult dataclass tests
# ---------------------------------------------------------------------------


class TestToolCallRecord:
    def test_creation(self):
        record = ToolCallRecord(
            tool_name="search",
            tool_input={"q": "test"},
            tool_result={"data": "found"},
            duration_ms=42.5,
        )
        assert record.tool_name == "search"
        assert record.tool_input == {"q": "test"}
        assert record.tool_result == {"data": "found"}
        assert record.duration_ms == 42.5


class TestToolUseResult:
    def test_creation(self):
        result = ToolUseResult(
            text="answer",
            tool_calls=[],
            usage=[],
            rounds=1,
        )
        assert result.text == "answer"
        assert result.rounds == 1
        assert result.tool_calls == []

    def test_with_tool_calls(self):
        record = ToolCallRecord("t", {}, {"r": 1}, 10.0)
        result = ToolUseResult(text="done", tool_calls=[record], usage=[], rounds=2)
        assert len(result.tool_calls) == 1
        assert result.rounds == 2


# ---------------------------------------------------------------------------
# ClaudeAdapter.generate_with_tools tests
# ---------------------------------------------------------------------------


class TestClaudeAdapterToolUse:
    @patch("core.llm.client.get_anthropic_client")
    def test_no_tool_use(self, mock_get_client: MagicMock):
        """When model doesn't request tools, returns text immediately."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_anthropic_text_response("Hello")
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter

        adapter = ClaudeAdapter()
        result = adapter.generate_with_tools(
            "system prompt",
            "user prompt",
            tools=[{"name": "dummy", "description": "test", "input_schema": {}}],
            tool_executor=lambda name, **kw: {"result": "ok"},
        )

        assert isinstance(result, ToolUseResult)
        assert result.text == "Hello"
        assert result.tool_calls == []
        assert result.rounds == 1

    @patch("core.llm.client.get_anthropic_client")
    def test_single_tool_call(self, mock_get_client: MagicMock):
        """Model calls one tool, then returns text."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _make_anthropic_tool_use_response(tool_name="search", tool_input={"q": "test"}),
            _make_anthropic_text_response("Found it"),
        ]
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter

        executor_calls: list[tuple[str, dict[str, Any]]] = []

        def mock_executor(name: str, **kwargs: Any) -> dict[str, Any]:
            executor_calls.append((name, kwargs))
            return {"data": "search result"}

        adapter = ClaudeAdapter()
        result = adapter.generate_with_tools(
            "system",
            "user",
            tools=[{"name": "search", "description": "search", "input_schema": {}}],
            tool_executor=mock_executor,
        )

        assert result.text == "Found it"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "search"
        assert result.tool_calls[0].tool_result == {"data": "search result"}
        assert result.rounds == 2
        assert len(executor_calls) == 1

    @patch("core.llm.client.get_anthropic_client")
    def test_tool_executor_error(self, mock_get_client: MagicMock):
        """Tool execution errors are captured, not raised."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            _make_anthropic_tool_use_response(),
            _make_anthropic_text_response("Handled error"),
        ]
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter

        def failing_executor(name: str, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("Tool broke")

        adapter = ClaudeAdapter()
        result = adapter.generate_with_tools(
            "sys",
            "usr",
            tools=[{"name": "dummy_tool", "description": "t", "input_schema": {}}],
            tool_executor=failing_executor,
        )

        assert result.text == "Handled error"
        assert len(result.tool_calls) == 1
        assert "error" in result.tool_calls[0].tool_result

    @patch("core.llm.client.get_anthropic_client")
    def test_max_rounds_enforced(self, mock_get_client: MagicMock):
        """After max_tool_rounds, loop stops."""
        mock_client = MagicMock()
        # Always request tool use — on last round tool_choice=none forces text
        mock_client.messages.create.side_effect = [
            _make_anthropic_tool_use_response(tool_use_id=f"toolu_{i}") for i in range(2)
        ] + [_make_anthropic_text_response("Forced end")]
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter

        adapter = ClaudeAdapter()
        result = adapter.generate_with_tools(
            "sys",
            "usr",
            tools=[{"name": "dummy_tool", "description": "t", "input_schema": {}}],
            tool_executor=lambda n, **kw: {"ok": True},
            max_tool_rounds=3,
        )

        assert result.text == "Forced end"
        assert len(result.tool_calls) == 2
        assert result.rounds == 3


# ---------------------------------------------------------------------------
# OpenAIAdapter.generate_with_tools tests
# ---------------------------------------------------------------------------


class TestOpenAIAdapterToolUse:
    @patch("core.infrastructure.adapters.llm.openai_adapter._get_openai_client")
    def test_no_tool_use(self, mock_get_client: MagicMock):
        """When model doesn't request tools, returns text immediately."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_openai_text_response("Hello")
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter()
        result = adapter.generate_with_tools(
            "system",
            "user",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "dummy", "description": "t", "parameters": {}},
                }
            ],
            tool_executor=lambda name, **kw: {"result": "ok"},
        )

        assert isinstance(result, ToolUseResult)
        assert result.text == "Hello"
        assert result.tool_calls == []
        assert result.rounds == 1

    @patch("core.infrastructure.adapters.llm.openai_adapter._get_openai_client")
    def test_single_tool_call(self, mock_get_client: MagicMock):
        """Model calls one tool, then returns text."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_openai_tool_call_response(func_name="search", func_args='{"q": "test"}'),
            _make_openai_text_response("Found it"),
        ]
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

        executor_calls: list[tuple[str, dict[str, Any]]] = []

        def mock_executor(name: str, **kwargs: Any) -> dict[str, Any]:
            executor_calls.append((name, kwargs))
            return {"data": "result"}

        adapter = OpenAIAdapter()
        result = adapter.generate_with_tools(
            "system",
            "user",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "search", "description": "s", "parameters": {}},
                }
            ],
            tool_executor=mock_executor,
        )

        assert result.text == "Found it"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "search"
        assert result.rounds == 2
        assert len(executor_calls) == 1

    @patch("core.infrastructure.adapters.llm.openai_adapter._get_openai_client")
    def test_tool_executor_error(self, mock_get_client: MagicMock):
        """Tool execution errors are captured, not raised."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_openai_tool_call_response(),
            _make_openai_text_response("Handled"),
        ]
        mock_get_client.return_value = mock_client

        from core.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter()
        result = adapter.generate_with_tools(
            "sys",
            "usr",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "dummy_tool",
                        "description": "t",
                        "parameters": {},
                    },
                }
            ],
            tool_executor=lambda n, **kw: (_ for _ in ()).throw(RuntimeError("broke")),
        )

        assert result.text == "Handled"
        assert "error" in result.tool_calls[0].tool_result


# ---------------------------------------------------------------------------
# LLM port contextvar tests
# ---------------------------------------------------------------------------


class TestLLMToolContextVar:
    def test_get_llm_tool_not_injected(self):
        """get_llm_tool() raises when not injected."""
        from core.infrastructure.ports.llm_port import _llm_tool_ctx, get_llm_tool

        _llm_tool_ctx.set(None)
        with pytest.raises(RuntimeError, match="tool callable not injected"):
            get_llm_tool()

    def test_set_and_get_llm_tool(self):
        """set_llm_callable with tool_fn makes it available via get_llm_tool."""
        from core.infrastructure.ports.llm_port import (
            _llm_tool_ctx,
            get_llm_tool,
            set_llm_callable,
        )

        dummy_tool_fn = lambda *a, **kw: None  # noqa: E731

        set_llm_callable(
            lambda *a, **kw: {},
            lambda *a, **kw: "",
            tool_fn=dummy_tool_fn,
        )

        result = get_llm_tool()
        assert result is dummy_tool_fn

        # Cleanup
        _llm_tool_ctx.set(None)
