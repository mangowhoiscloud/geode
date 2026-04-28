"""Tests for provider-agnostic agentic response normalization + write fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.agent.tool_executor import _write_denial_with_fallback
from core.cli.agentic_response import (
    AgenticResponse,
    TextBlock,
    ToolUseBlock,
    normalize_anthropic,
    normalize_openai,
    normalize_openai_responses,
)


class TestAgenticResponse:
    def test_default_response(self):
        r = AgenticResponse()
        assert r.content == []
        assert r.stop_reason == "end_turn"
        assert r.usage.input_tokens == 0

    def test_text_block_attributes(self):
        b = TextBlock(text="hello")
        assert b.type == "text"
        assert b.text == "hello"

    def test_tool_use_block_attributes(self):
        b = ToolUseBlock(id="tu_1", name="search", input={"q": "test"})
        assert b.type == "tool_use"
        assert b.id == "tu_1"
        assert b.name == "search"
        assert b.input == {"q": "test"}


class TestNormalizeAnthropic:
    def _make_response(
        self,
        *,
        content=None,
        stop_reason="end_turn",
        input_tokens=100,
        output_tokens=50,
    ):
        resp = MagicMock()
        resp.content = content or []
        resp.stop_reason = stop_reason
        resp.usage = MagicMock()
        resp.usage.input_tokens = input_tokens
        resp.usage.output_tokens = output_tokens
        return resp

    def test_text_response(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello world"
        resp = self._make_response(content=[text_block])

        result = normalize_anthropic(resp)
        assert isinstance(result, AgenticResponse)
        assert result.stop_reason == "end_turn"
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert result.content[0].text == "Hello world"
        assert result.usage.input_tokens == 100

    def test_tool_use_response(self):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_1"
        tool_block.name = "search_ips"
        tool_block.input = {"query": "dark"}
        resp = self._make_response(content=[tool_block], stop_reason="tool_use")

        result = normalize_anthropic(resp)
        assert result.stop_reason == "tool_use"
        assert len(result.content) == 1
        block = result.content[0]
        assert block.type == "tool_use"
        assert block.id == "tu_1"
        assert block.name == "search_ips"
        assert block.input == {"query": "dark"}

    def test_mixed_content(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I'll search for you."
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_2"
        tool_block.name = "list_ips"
        tool_block.input = {}
        resp = self._make_response(content=[text_block, tool_block], stop_reason="tool_use")

        result = normalize_anthropic(resp)
        assert len(result.content) == 2
        assert result.content[0].type == "text"
        assert result.content[1].type == "tool_use"


class TestNormalizeOpenAI:
    def _make_response(
        self,
        *,
        content="Hello",
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=100,
        completion_tokens=50,
    ):
        resp = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        choice.message.tool_calls = tool_calls
        choice.finish_reason = finish_reason
        resp.choices = [choice]
        resp.usage = MagicMock()
        resp.usage.prompt_tokens = prompt_tokens
        resp.usage.completion_tokens = completion_tokens
        return resp

    def test_text_response(self):
        resp = self._make_response()
        result = normalize_openai(resp)
        assert result.stop_reason == "end_turn"
        assert len(result.content) == 1
        assert result.content[0].text == "Hello"

    def test_tool_calls_response(self):
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "list_ips"
        tc.function.arguments = '{"limit": 5}'
        resp = self._make_response(
            content=None,
            tool_calls=[tc],
            finish_reason="tool_calls",
        )

        result = normalize_openai(resp)
        assert result.stop_reason == "tool_use"
        assert len(result.content) == 1
        block = result.content[0]
        assert block.type == "tool_use"
        assert block.id == "call_1"
        assert block.name == "list_ips"
        assert block.input == {"limit": 5}

    def test_text_plus_tool_calls(self):
        tc = MagicMock()
        tc.id = "call_2"
        tc.function.name = "search_ips"
        tc.function.arguments = '{"query": "mecha"}'
        resp = self._make_response(
            content="Let me search.",
            tool_calls=[tc],
            finish_reason="tool_calls",
        )

        result = normalize_openai(resp)
        assert result.stop_reason == "tool_use"
        assert len(result.content) == 2
        assert result.content[0].type == "text"
        assert result.content[1].type == "tool_use"

    def test_usage_mapping(self):
        resp = self._make_response(prompt_tokens=200, completion_tokens=80)
        result = normalize_openai(resp)
        assert result.usage.input_tokens == 200
        assert result.usage.output_tokens == 80

    def test_empty_choices(self):
        resp = MagicMock()
        resp.choices = []
        result = normalize_openai(resp)
        assert result.stop_reason == "end_turn"
        assert result.content == []

    def test_malformed_arguments(self):
        tc = MagicMock()
        tc.id = "call_3"
        tc.function.name = "test"
        tc.function.arguments = "not-json"
        resp = self._make_response(
            content=None,
            tool_calls=[tc],
            finish_reason="tool_calls",
        )
        result = normalize_openai(resp)
        assert result.content[0].input == {}


class TestNormalizeOpenAIResponses:
    """Test normalize_openai_responses for the Responses API output format."""

    @staticmethod
    def _make_message_item(text: str) -> MagicMock:
        item = MagicMock()
        item.type = "message"
        sub = MagicMock()
        sub.type = "output_text"
        sub.text = text
        item.content = [sub]
        return item

    @staticmethod
    def _make_function_call_item(call_id: str, name: str, arguments: str) -> MagicMock:
        item = MagicMock()
        item.type = "function_call"
        item.call_id = call_id
        item.name = name
        item.arguments = arguments
        return item

    @staticmethod
    def _make_web_search_item() -> MagicMock:
        item = MagicMock()
        item.type = "web_search_call"
        return item

    def test_text_response(self) -> None:
        resp = MagicMock()
        resp.output = [self._make_message_item("Hello")]
        resp.usage = MagicMock(input_tokens=10, output_tokens=5)
        result = normalize_openai_responses(resp)
        assert result.stop_reason == "end_turn"
        assert len(result.content) == 1
        assert result.content[0].text == "Hello"

    def test_function_call_response(self) -> None:
        resp = MagicMock()
        resp.output = [self._make_function_call_item("fc_1", "search", '{"q": "test"}')]
        resp.usage = MagicMock(input_tokens=10, output_tokens=5)
        result = normalize_openai_responses(resp)
        assert result.stop_reason == "tool_use"
        assert result.content[0].id == "fc_1"
        assert result.content[0].input == {"q": "test"}

    def test_web_search_transparent(self) -> None:
        resp = MagicMock()
        resp.output = [self._make_web_search_item(), self._make_message_item("Results")]
        resp.usage = MagicMock(input_tokens=10, output_tokens=5)
        result = normalize_openai_responses(resp)
        assert result.stop_reason == "end_turn"
        assert len(result.content) == 1
        assert result.content[0].text == "Results"

    def test_empty_output(self) -> None:
        resp = MagicMock()
        resp.output = []
        resp.usage = None  # explicit: no usage so the post-parse anomaly
        # check (visible-output-but-zero-blocks) cannot trip on MagicMock
        result = normalize_openai_responses(resp)
        assert result.content == []
        # v0.53.3 — empty output no longer drops usage; usage is preserved
        # as zeros even when output is empty (the Codex Plus
        # ``Completed.output``-omitted edge case).
        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0


# ---------------------------------------------------------------------------
# Write fallback tests
# ---------------------------------------------------------------------------


class TestWriteDenialWithFallback:
    def test_known_tool_has_hint(self):
        result = _write_denial_with_fallback("memory_save")
        assert result["denied"] is True
        assert "error" in result
        assert "fallback_hint" in result
        assert result["fallback_hint"] != ""
        assert "memory_search" in result["fallback_hint"]

    def test_unknown_tool_no_hint(self):
        result = _write_denial_with_fallback("unknown_write_tool")
        assert result["denied"] is True
        assert result["fallback_hint"] == ""
        assert "Do NOT retry" in result["error"]

    def test_calendar_tool(self):
        result = _write_denial_with_fallback("calendar_create_event")
        assert "calendar_list_events" in result["fallback_hint"]

    def test_set_api_key(self):
        result = _write_denial_with_fallback("set_api_key")
        # v0.50.1: denial hint now points users at the unified /login command
        # (set_api_key is a thin alias for the legacy /key paste path).
        assert "/login" in result["fallback_hint"]

    def test_all_write_tools_have_fallbacks(self):
        from core.agent.tool_executor import WRITE_TOOLS

        for tool in WRITE_TOOLS:
            result = _write_denial_with_fallback(tool)
            assert result["denied"] is True
            assert "error" in result
