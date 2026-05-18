"""GLM agentic_call streams documented Chat Completions request fields."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.llm.agentic_response import AgenticResponse
from core.llm.providers.glm import GlmAgenticAdapter


def _chunk(
    *,
    content: str = "",
    reasoning: str = "",
    finish_reason: str | None = None,
    usage: Any = None,
) -> Any:
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=[])
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _stream(usage: Any | None = None) -> list[Any]:
    return [
        _chunk(content="hel", reasoning="think "),
        _chunk(content="lo", reasoning="done", finish_reason="stop", usage=usage),
    ]


class _Completions:
    def __init__(self, sink: list[dict[str, Any]], responses: list[Any]) -> None:
        self._sink = sink
        self._responses = responses

    def create(self, **kwargs: Any) -> Any:
        self._sink.append(dict(kwargs))
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


class _Client:
    def __init__(self, sink: list[dict[str, Any]], responses: list[Any]) -> None:
        self.chat = SimpleNamespace(completions=_Completions(sink, responses))


def test_glm_agentic_call_streams_without_unsupported_cache_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    usage = SimpleNamespace(
        prompt_tokens=20,
        completion_tokens=5,
        prompt_tokens_details=SimpleNamespace(cached_tokens=11),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
    )
    client = _Client(captured, [_stream(usage)])
    adapter = GlmAgenticAdapter()
    monkeypatch.setattr(adapter, "_ensure_client", lambda model: client)

    tools = [{"type": "function", "name": "lookup", "description": "lookup", "parameters": {}}]
    result = asyncio.run(
        adapter.agentic_call(
            model="glm-5.1",
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            tool_choice="auto",
            max_tokens=64,
            temperature=0.1,
            effort="high",
        )
    )

    assert isinstance(result, AgenticResponse)
    assert captured[0]["stream"] is True
    assert "prompt_cache_key" not in captured[0]
    assert "stream_options" not in captured[0]
    assert result.content[0].text == "hello"
    assert result.reasoning_summaries == ["think done"]
    assert result.usage.input_tokens == 20
    assert result.usage.cache_read_tokens == 11


def test_glm_auto_cache_usage_normalizes_without_prompt_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    usage = SimpleNamespace(
        prompt_tokens=31,
        completion_tokens=7,
        prompt_tokens_details=SimpleNamespace(cached_tokens=19),
    )
    client = _Client(captured, [_stream(usage)])
    adapter = GlmAgenticAdapter()
    monkeypatch.setattr(adapter, "_ensure_client", lambda model: client)

    result = asyncio.run(
        adapter.agentic_call(
            model="glm-5.1",
            system="system",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            tool_choice="auto",
            max_tokens=64,
            temperature=0.1,
            effort="high",
        )
    )

    assert isinstance(result, AgenticResponse)
    assert len(captured) == 1
    assert "prompt_cache_key" not in captured[0]
    assert result.usage.input_tokens == 31
    assert result.usage.output_tokens == 7
    assert result.usage.cache_read_tokens == 19
