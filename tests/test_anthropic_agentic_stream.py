"""GAP-S1 — Anthropic agentic_call uses ``messages.stream`` (not ``.create``).

Pre-fix: ``ClaudeAgenticAdapter.agentic_call._do_call`` called
``await self._client.messages.create(**create_kwargs)`` — non-streaming, so
the user / pipeline only received the response after the full body was
generated, and the SDK held the connection open without TTFB benefit.

Post-fix: same adapter now wraps the call in an
``async with self._client.messages.stream(**create_kwargs) as s`` block and
returns ``await s.get_final_message()``. Same response schema
(``anthropic.types.Message``) — so the downstream normalizer + token
accounting paths are unchanged — but the network now delivers chunks
incrementally and the SDK can surface partial state if the agentic loop
ever wires it up (out of scope for this PR).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.llm.providers.anthropic import ClaudeAgenticAdapter


class _StubMessage:
    """Mimic the subset of ``anthropic.types.Message`` that
    ``normalize_anthropic`` reads.
    """

    def __init__(self) -> None:
        self.id = "msg_stub"
        self.role = "assistant"
        self.content: list[Any] = []
        self.stop_reason = "end_turn"
        self.usage = type(
            "U",
            (),
            {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )()
        self.model = "claude-opus-4-7"


class _StubStream:
    """Async context manager mirroring the Anthropic SDK's
    ``AsyncMessageStreamManager`` → ``AsyncMessageStream`` contract.
    """

    def __init__(self) -> None:
        self._final = _StubMessage()

    async def __aenter__(self) -> _StubStream:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get_final_message(self) -> _StubMessage:
        return self._final


class _StubMessages:
    def __init__(self, sink: dict[str, Any]) -> None:
        self._sink = sink
        self.stream_called = False
        self.create_called = False

    def stream(self, **kwargs: Any) -> _StubStream:
        self.stream_called = True
        self._sink.update(kwargs)
        return _StubStream()

    async def create(self, **kwargs: Any) -> _StubMessage:
        # GAP-S1 regression — adapter must NOT call ``create`` any more.
        self.create_called = True
        self._sink.update(kwargs)
        return _StubMessage()


class _StubClient:
    def __init__(self, sink: dict[str, Any]) -> None:
        self.messages = _StubMessages(sink)


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> tuple[_StubClient, dict[str, Any]]:
    """Patch ``get_async_anthropic_client`` so the adapter picks up the stub."""
    captured: dict[str, Any] = {}
    client = _StubClient(captured)
    monkeypatch.setattr(
        "core.llm.providers.anthropic.get_async_anthropic_client",
        lambda _api_key: client,
    )
    # Bypass the real auth path — pretend a key is configured.
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-stub", raising=False)
    return client, captured


def test_agentic_call_uses_stream_not_create(
    stub_client: tuple[_StubClient, dict[str, Any]],
) -> None:
    """The adapter must invoke ``messages.stream`` (not ``messages.create``)
    so the network connection benefits from chunk-level delivery.
    """
    client, captured = stub_client
    # Bypass normalize_anthropic so we can pass through the stub message.
    import core.llm.agentic_response as _ar

    original_normalize = _ar.normalize_anthropic
    try:
        _ar.normalize_anthropic = lambda r: r  # type: ignore[assignment]
        adapter = ClaudeAgenticAdapter()
        result = asyncio.run(
            adapter.agentic_call(
                model="claude-opus-4-7",
                system="S",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_choice="auto",
                max_tokens=64,
                temperature=0.3,
            )
        )
    finally:
        _ar.normalize_anthropic = original_normalize

    assert client.messages.stream_called, "GAP-S1: agentic_call must use messages.stream"
    assert not client.messages.create_called, (
        "GAP-S1 regression: agentic_call still calling messages.create"
    )
    assert result is not None
    # Stream kwargs include the core fields — exact shape verified by other tests.
    assert captured.get("model") == "claude-opus-4-7"
    assert captured.get("max_tokens") == 64
    assert captured.get("system") is not None  # non-empty sys_blocks
    assert captured.get("messages") is not None


def test_stream_kwargs_preserve_payload(
    stub_client: tuple[_StubClient, dict[str, Any]],
) -> None:
    """Streaming must carry the same kwargs as the prior ``messages.create``
    payload (tools, tool_choice, thinking, system, etc.) — switching the
    transport must not silently drop a parameter.
    """
    client, captured = stub_client
    import core.llm.agentic_response as _ar

    original_normalize = _ar.normalize_anthropic
    try:
        _ar.normalize_anthropic = lambda r: r  # type: ignore[assignment]
        adapter = ClaudeAgenticAdapter()
        asyncio.run(
            adapter.agentic_call(
                model="claude-opus-4-7",
                system="System prompt",
                messages=[{"role": "user", "content": "hello"}],
                tools=[
                    {
                        "name": "test_tool",
                        "description": "x",
                        "input_schema": {"type": "object"},
                    }
                ],
                tool_choice={"type": "auto"},
                max_tokens=128,
                temperature=0.5,
            )
        )
    finally:
        _ar.normalize_anthropic = original_normalize

    # Tools, tool_choice, system, max_tokens all reached the stream call
    assert "tools" in captured
    assert "tool_choice" in captured
    assert "system" in captured
    assert captured["max_tokens"] == 128
