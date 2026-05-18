"""GAP-A2 — OpenAI prompt_cache_key derivation + agentic_call wiring.

OpenAI's Responses API auto-caches matching prefixes. The optional
``prompt_cache_key`` routes similar requests to the same cache pool,
improving hit-rate when system + tools are stable across sessions.

These tests pin the derivation contract (stable across re-orderings of
tool schema keys, different across material changes) and verify the
adapter actually injects the key into the ``responses.create`` kwargs.
"""

from __future__ import annotations

from typing import Any

import pytest
from core.llm.providers.openai import (
    OpenAIAgenticAdapter,
    _build_prompt_cache_key,
    _tools_to_openai,
)

# ---------------------------------------------------------------------------
# Derivation contract
# ---------------------------------------------------------------------------


def test_key_is_stable_for_same_inputs() -> None:
    sys_a = "You are a helpful assistant."
    tools = [{"type": "function", "name": "search", "parameters": {"q": "string"}}]
    assert _build_prompt_cache_key(sys_a, tools) == _build_prompt_cache_key(sys_a, tools)


def test_key_is_stable_across_dict_key_order() -> None:
    """``sort_keys=True`` neutralises serialization-order drift inside
    tool schemas — the cache must not invalidate on cosmetic reordering.
    """
    sys_a = "S"
    t1 = [{"type": "function", "name": "f", "parameters": {"a": 1, "b": 2}}]
    t2 = [{"parameters": {"b": 2, "a": 1}, "name": "f", "type": "function"}]
    assert _build_prompt_cache_key(sys_a, t1) == _build_prompt_cache_key(sys_a, t2)


def test_key_changes_on_system_change() -> None:
    tools: list[dict[str, Any]] = []
    a = _build_prompt_cache_key("S1", tools)
    b = _build_prompt_cache_key("S2", tools)
    assert a != b


def test_key_changes_on_tools_change() -> None:
    sys_a = "S"
    a = _build_prompt_cache_key(sys_a, [{"name": "x"}])
    b = _build_prompt_cache_key(sys_a, [{"name": "y"}])
    assert a != b


def test_key_separator_prevents_collision() -> None:
    """``system + tools_json`` collisions: a system suffix that looks like
    the tools prefix must not collide with the genuine pairing.
    The ``\\x00`` separator inside ``_build_prompt_cache_key`` is what
    guarantees this — verify by constructing a near-collision pair.
    """
    a = _build_prompt_cache_key("hello", [{"name": "world"}])
    # Move the boundary one char into the system side
    b = _build_prompt_cache_key("hell", [{"oname": "world"}])
    assert a != b


def test_key_length_is_32_hex_chars() -> None:
    k = _build_prompt_cache_key("S", [])
    assert len(k) == 32
    int(k, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# Adapter wiring — prompt_cache_key reaches responses.stream
# ---------------------------------------------------------------------------


def test_agentic_call_injects_prompt_cache_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter must include ``prompt_cache_key`` in the kwargs sent to
    ``client.responses.stream``.  Capture the kwargs via a stub client.

    The codebase does not depend on pytest-asyncio, so we drive the async
    method via ``asyncio.run`` directly — matching the pattern used by
    callers in production.
    """
    import asyncio

    captured: dict[str, Any] = {}

    class _StubResponse:
        usage = None
        output: list[Any] = []
        output_text = ""

    class _StubStream:
        async def __aenter__(self) -> _StubStream:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            return False

        def __aiter__(self) -> _StubStream:
            return self

        async def __anext__(self) -> Any:
            raise StopAsyncIteration

        async def get_final_response(self) -> Any:
            return _StubResponse()

    class _StubResponses:
        def stream(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _StubStream()

    class _StubClient:
        def __init__(self) -> None:
            self.responses = _StubResponses()

        def close(self) -> None:
            pass

    adapter = OpenAIAgenticAdapter()
    monkeypatch.setattr(adapter, "_ensure_client", lambda model: _StubClient())
    monkeypatch.setattr("core.llm.providers.openai._OPENAI_NATIVE_TOOLS", [])
    monkeypatch.setattr(
        "core.llm.providers.anthropic.is_computer_use_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "core.llm.agentic_response.normalize_openai_responses",
        lambda r: r,
    )

    sys_prompt = "system XYZ"
    tools: list[dict[str, Any]] = [
        {"type": "function", "name": "lookup", "description": "x", "parameters": {}}
    ]

    asyncio.run(
        adapter.agentic_call(
            model="gpt-5.5",
            system=sys_prompt,
            messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            tool_choice="auto",
            max_tokens=128,
            temperature=0.3,
        )
    )

    assert "prompt_cache_key" in captured, "GAP-A2: prompt_cache_key not injected"
    # The adapter passes the *converted* tools list (post ``_tools_to_openai``)
    # into the hash — caller's raw tools shape is normalised first.  Mirror
    # that here so the expected key matches the captured key.
    expected = _build_prompt_cache_key(sys_prompt, _tools_to_openai(tools))
    assert captured["prompt_cache_key"] == expected
