"""openai-payg Responses API migration guards.

PR-OPENAI-RESPONSES (2026-06-13). ``acomplete``/``astream`` left Chat
Completions and joined the shared Responses builder
(``build_responses_kwargs``, ``backend="platform"``) that codex-oauth
already used — completing the migration ``acomplete_text``/
``aweb_search`` started, and putting openai-payg on the surface where
OpenAI ships new features (tool_search deferred loading is
Responses-only).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from core.llm.adapters._capability_impls import openai_web_search_urls
from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec


def test_web_search_url_projection_accepts_null_sources() -> None:
    sources, citations, activated = openai_web_search_urls(
        [SimpleNamespace(type="web_search_call", action=SimpleNamespace(sources=None))]
    )

    assert sources == ()
    assert citations == ()
    assert activated is True


REPO_ROOT = Path(__file__).resolve().parents[4]


def _request(**overrides: object) -> AdapterCallRequest:
    request_kwargs: dict = {
        "model": "gpt-5.5",
        "messages": (Message(role="user", content="hi"),),
        "system_prompt": "test system",
        "max_tokens": 4096,
    }
    request_kwargs.update(overrides)
    return AdapterCallRequest(**request_kwargs)


def test_platform_backend_sends_max_output_tokens() -> None:
    """The Codex backend 400s on max_output_tokens; the platform API
    supports it — the backend param must carry exactly this delta."""
    platform = build_responses_kwargs(_request(), backend="platform", adapter_name="openai-payg")
    codex = build_responses_kwargs(_request(), backend="codex", adapter_name="codex-oauth")
    assert platform["max_output_tokens"] == 4096
    assert "max_output_tokens" not in codex


def test_platform_backend_shares_responses_shape_with_codex() -> None:
    """Everything except the max_output_tokens delta is one builder —
    instructions carry the system prompt, store=False, flat tools."""
    tool_specs = (ToolSpec(name="demo", description="demo", input_schema={"type": "object"}),)
    platform = build_responses_kwargs(
        _request(tools=tool_specs), backend="platform", adapter_name="openai-payg"
    )
    assert platform["instructions"] == "test system"
    assert platform["store"] is False
    flat_tool = platform["tools"][0]
    assert flat_tool["type"] == "function"
    assert flat_tool["name"] == "demo"
    assert "function" not in flat_tool, "Responses uses the FLAT shape, not Chat nesting"


def test_payg_adapter_module_has_left_chat_completions() -> None:
    """Source pin: the adapter must not fall back to chat.completions —
    Chat Completions now lives only on the GLM adapters."""
    adapter_source = (REPO_ROOT / "core" / "llm" / "adapters" / "openai_payg.py").read_text(
        encoding="utf-8"
    )
    assert "chat.completions" not in adapter_source
    assert "responses.stream" in adapter_source
    assert 'backend="platform"' in adapter_source


def test_reasoning_branch_applies_on_platform_backend() -> None:
    """gpt-5.x on the platform backend keeps the reasoning passthrough
    (encrypted content replay) exactly as on codex."""
    platform = build_responses_kwargs(
        _request(effort="high"), backend="platform", adapter_name="openai-payg"
    )
    assert platform["include"] == ["reasoning.encrypted_content"]
    assert platform["reasoning"]["effort"] == "high"
    assert "temperature" not in platform


def test_usage_carries_cached_input_tokens() -> None:
    """Responses reports cache hits under input_tokens_details.cached_tokens
    — both backends must surface them (Codex review finding 1; the codex
    path had always dropped them)."""
    from types import SimpleNamespace

    from core.llm.adapters._openai_common import translate_codex_response

    fake_response = SimpleNamespace(
        output_text="ok",
        output=[],
        status="completed",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            input_tokens_details=SimpleNamespace(cached_tokens=64, cache_write_tokens=7),
            output_tokens_details=SimpleNamespace(reasoning_tokens=8),
        ),
    )
    result = translate_codex_response(fake_response)
    assert result.usage.cached_input_tokens == 64
    assert result.usage.cache_write_tokens == 7
    assert result.usage.reasoning_tokens == 8


def test_stop_sequences_drop_is_observable(caplog) -> None:
    """Responses has no ``stop`` param — the builder must warn, never
    silently drop (Codex review finding 2)."""
    import logging

    with caplog.at_level(logging.WARNING, logger="core.llm.adapters._openai_common"):
        build_responses_kwargs(
            _request(stop_sequences=("END",)), backend="platform", adapter_name="openai-payg"
        )
    assert any("stop_sequences unsupported" in r.message for r in caplog.records)


@pytest.mark.parametrize("source", ["payg", "subscription"])
@pytest.mark.parametrize(
    "ending", ["completed", "incomplete", "failed", "eof", "error", "mismatch"]
)
def test_responses_stream_preserves_native_items_and_terminal_status(
    monkeypatch: pytest.MonkeyPatch, source: str, ending: str
) -> None:
    from core.llm.adapters.base import StreamEvent
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    call = {
        "type": "function_call",
        "id": "fc-fixture",
        "call_id": "call-fixture",
        "name": "demo",
        "arguments": '{"x":1}',
        "status": "completed",
    }
    reasoning = {
        "type": "reasoning",
        "id": "rs-fixture",
        "encrypted_content": "fixture-replay",
        "summary": [{"type": "summary_text", "text": "Checking."}],
    }
    response = {
        "id": "resp-fixture",
        "object": "response",
        "created_at": 0,
        "model": "gpt-6-sol",
        "status": "in_progress",
        "output": [],
    }
    events = [
        {"type": "response.created", "response": response},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**call, "arguments": ""},
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc-fixture",
            "output_index": 0,
            "delta": '{"x":',
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc-fixture",
            "output_index": 0,
            "delta": "1}",
        },
        {"type": "response.output_item.done", "output_index": 0, "item": call},
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": "Checking.",
            "item_id": "rs-fixture",
            "output_index": 1,
            "summary_index": 0,
        },
        {"type": "response.output_item.done", "output_index": 1, "item": reasoning},
    ]
    if ending in {"completed", "incomplete", "failed", "mismatch"}:
        events.append(
            {
                "type": f"response.{ending}" if ending != "mismatch" else "response.completed",
                "response": {
                    **response,
                    "status": ending,
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 3,
                        "total_tokens": 15,
                        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 7},
                    },
                },
            }
        )
    elif ending == "error":
        events.append({"type": "error", "code": "fixture_error", "message": "fixture"})
    payload = "".join(
        "event: "
        + event["type"]
        + "\ndata: "
        + json.dumps({**event, "sequence_number": index})
        + "\n\n"
        for index, event in enumerate(events)
    )
    wire: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(json.loads(request.content))
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    emitted: list[StreamEvent] = []

    async def consume() -> None:
        async with openai.AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as client:
            adapter = OpenAIPaygAdapter() if source == "payg" else CodexOAuthAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
            async for event in adapter.astream(_request(model="gpt-6-sol")):
                emitted.append(event)

    if ending in {"completed", "incomplete"}:
        asyncio.run(consume())
        stop = emitted[-1]
        assert stop.kind == "stop" and stop.payload["stop_reason"] == ending
        assert stop.payload["response_id"] == "resp-fixture"
        assert stop.payload["codex_output_items"][1]["encrypted_content"] == "fixture-replay"
    else:
        with pytest.raises((RuntimeError, openai.APIError)):
            asyncio.run(consume())
        assert not any(event.kind == "stop" for event in emitted)
    assert wire[0]["model"] == "gpt-6-sol"
    assert ("max_output_tokens" in wire[0]) is (source == "payg")
    assert [event.payload for event in emitted if event.kind == "thinking"] == [
        {"text": "Checking."}
    ]
    tools = [event.payload for event in emitted if event.kind == "tool_use"]
    assert tools == (
        [{"id": "call-fixture", "name": "demo", "input": '{"x":1}'}]
        if ending == "completed"
        else []
    )
    usages = [event.payload for event in emitted if event.kind == "usage"]
    if ending in {"completed", "incomplete", "failed"}:
        assert len(usages) == 1
        assert usages[0]["input_tokens"] == 12
        assert usages[0]["cached_input_tokens"] == 0
        assert usages[0]["cached_input_tokens_present"] is True
        assert usages[0]["cache_write_tokens"] == 7
        assert usages[0]["reasoning_tokens_present"] is False
    else:
        assert not usages
