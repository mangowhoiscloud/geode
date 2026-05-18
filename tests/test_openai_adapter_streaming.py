"""OpenAI PAYG agentic_call uses Responses streaming."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.llm.agentic_response import AgenticResponse
from core.llm.providers.openai import OpenAIAgenticAdapter


class _FakeResponsesStream:
    def __init__(self, events: list[Any], final_response: Any) -> None:
        self._events = events
        self._final_response = final_response
        self._index = 0

    async def __aenter__(self) -> _FakeResponsesStream:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def __aiter__(self) -> _FakeResponsesStream:
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def get_final_response(self) -> Any:
        return self._final_response


def _message_item(text: str) -> Any:
    return SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=text)],
    )


def _function_item() -> Any:
    return SimpleNamespace(
        type="function_call",
        call_id="call_1",
        name="lookup",
        arguments='{"q":"geode"}',
    )


def test_openai_agentic_call_streaming_matches_blocking_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    streamed_items = [_message_item("hello"), _function_item()]
    final_response = SimpleNamespace(
        output=[],
        usage=SimpleNamespace(input_tokens=34, output_tokens=12),
    )
    events = [
        SimpleNamespace(type="response.output_item.done", item=item) for item in streamed_items
    ]

    class _Responses:
        def stream(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _FakeResponsesStream(events, final_response)

    class _Client:
        responses = _Responses()

    adapter = OpenAIAgenticAdapter()
    monkeypatch.setattr(adapter, "_ensure_client", lambda model: _Client())
    monkeypatch.setattr("core.llm.providers.openai._OPENAI_NATIVE_TOOLS", [])
    monkeypatch.setattr(
        "core.llm.providers.anthropic.is_computer_use_enabled",
        lambda: False,
    )

    result = asyncio.run(
        adapter.agentic_call(
            model="gpt-5.5",
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            tools=[
                {
                    "type": "function",
                    "name": "lookup",
                    "description": "lookup",
                    "parameters": {},
                }
            ],
            tool_choice="auto",
            max_tokens=128,
            temperature=0.2,
            effort="high",
        )
    )

    assert isinstance(result, AgenticResponse)
    assert captured["model"] == "gpt-5.5"
    assert captured["store"] is False
    assert "prompt_cache_key" in captured
    assert result.stop_reason == "tool_use"
    assert result.content[0].text == "hello"
    assert result.content[1].id == "call_1"
    assert result.content[1].input == {"q": "geode"}
    assert result.usage.input_tokens == 34
    assert result.usage.output_tokens == 12
