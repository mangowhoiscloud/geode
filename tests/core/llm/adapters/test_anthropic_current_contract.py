"""Offline wire regressions for the public Claude contract retrieved 2026-09-24."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from core.llm.adapters._anthropic_common import (
    build_create_kwargs,
    build_stream_kwargs,
    translate_response,
)
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.errors import LLMRequestValidationError
from core.llm.model_capabilities import get_anthropic_model_spec


@pytest.mark.parametrize(
    "model", ["claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5"]
)
def test_current_models_share_stream_and_completion_contract(model: str) -> None:
    request = AdapterCallRequest(model=model, messages=(), effort="xhigh", temperature=0.2)
    kwargs = build_create_kwargs(request)
    assert kwargs == build_stream_kwargs(request)
    assert kwargs["thinking"]["type"] == "adaptive"
    assert kwargs["output_config"]["effort"] == "xhigh"
    assert "temperature" not in kwargs
    assert get_anthropic_model_spec(model).max_output_tokens == 128_000


@pytest.mark.parametrize("model", ["claude-fable-5-1", "claude-opus-5-5"])
def test_bound_models_preserve_signed_history_and_report_prefix_changes(
    model: str, caplog: pytest.LogCaptureFixture
) -> None:
    native = (
        {"type": "thinking", "thinking": "", "signature": "opaque"},
        {"type": "text", "text": "done"},
    )
    request = AdapterCallRequest(
        model=model,
        messages=(Message(role="assistant", content="done", anthropic_content=native),),
        system_prompt="updated dynamic system context",
    )
    kwargs = build_create_kwargs(request)
    assert kwargs["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert "thinking-binding-controls-2026-08-01" in kwargs["extra_headers"]["anthropic-beta"]
    assert kwargs["messages"][0]["content"][0]["signature"] == "opaque"
    translate_response(
        SimpleNamespace(
            content=[],
            usage=None,
            input_transformations=[
                {"type": "thinking_dropped", "reason": "prefix_binding_mismatch"}
            ],
        )
    )
    assert "prefix_binding_mismatch blocks=1" in caplog.text
    assert "opaque" not in caplog.text


@pytest.mark.parametrize("model", ["claude-fable-5-1", "claude-opus-5-5"])
@pytest.mark.parametrize("choice", ["required", {"type": "tool", "name": "lookup"}])
def test_forced_tool_choice_fails_locally(model: str, choice: str | dict[str, str]) -> None:
    request = AdapterCallRequest(
        model=model,
        messages=(),
        tool_choice=choice,
        tools=(ToolSpec(name="lookup", description="Lookup", input_schema={"type": "object"}),),
    )
    with pytest.raises(LLMRequestValidationError, match="forced tool_choice"):
        build_create_kwargs(request)
    with pytest.raises(LLMRequestValidationError, match="forced tool_choice"):
        build_stream_kwargs(request)


def test_structured_output_preserves_schema_and_effort() -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    request = AdapterCallRequest(model="claude-opus-5-5", messages=(), response_schema=schema)
    kwargs = build_create_kwargs(request)
    assert kwargs["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": schema},
    }
    assert kwargs["output_config"]["format"]["schema"] is not schema
    with pytest.raises(LLMRequestValidationError, match="object root"):
        build_create_kwargs(replace(request, response_schema={"type": "string"}))


def test_output_limit_includes_extended_thinking() -> None:
    with pytest.raises(LLMRequestValidationError, match="including any thinking budget"):
        build_create_kwargs(
            AdapterCallRequest(
                model="claude-haiku-4-5-20251001",
                messages=(),
                max_tokens=63_000,
                thinking_budget=2_000,
            )
        )

    with pytest.raises(LLMRequestValidationError, match="positive"):
        build_create_kwargs(
            AdapterCallRequest(
                model="claude-haiku-4-5-20251001", messages=(), max_tokens=0, thinking_budget=2048
            )
        )


def test_manual_thinking_rejects_forced_tool_choice_without_disabling_thinking() -> None:
    request = AdapterCallRequest(
        model="claude-haiku-4-5-20251001",
        messages=(),
        thinking_budget=2048,
        tool_choice="required",
        tools=(ToolSpec(name="lookup", description="Lookup", input_schema={"type": "object"}),),
    )
    with pytest.raises(LLMRequestValidationError, match="Manual thinking"):
        build_create_kwargs(request)


@pytest.mark.parametrize("model", ["claude-unknown-future"])
def test_unknown_computer_protocol_cannot_be_advertised(model: str) -> None:
    request = AdapterCallRequest(
        model=model, messages=(), executable_tool_names=frozenset({"computer"})
    )
    with patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=True):
        with pytest.raises(LLMRequestValidationError, match=r"[Cc]omputer|computer_toolset"):
            build_create_kwargs(request)
        # An explicit deny avoids the unsupported computer path entirely.
        build_create_kwargs(replace(request, denied_tool_names=frozenset({"computer"})))


def test_current_models_are_listed_from_catalog() -> None:
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.model_catalog import model_ids_for_source

    adapter = AnthropicPaygAdapter()
    ids = [model.id for model in adapter.list_models()]
    assert set(model_ids_for_source(provider="anthropic", source="payg")) <= set(ids)
    assert len(ids) == len(set(ids))
    assert {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5"} <= {
        model.id for model in adapter.list_models()
    }


def test_stream_preserves_sdk_tools_signed_content_and_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import json

    import anthropic
    import httpx
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 1,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 30,
                },
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "check"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "opaque-fixture"},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": "lookup"},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "content_block_start",
            "index": 2,
            "content_block": {
                "type": "tool_use",
                "id": "tool_fixture",
                "name": "lookup",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 2,
            "delta": {"type": "input_json_delta", "partial_json": '{"value":42}'},
        },
        {"type": "content_block_stop", "index": 2},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 12},
        },
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    async def check() -> None:
        async with anthropic.AsyncAnthropic(
            api_key="test-key",
            base_url="https://sdk.test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            monkeypatch.setattr(AnthropicPaygAdapter, "_get_client", lambda _self: client)
            stream = [
                event
                async for event in AnthropicPaygAdapter().astream(
                    AdapterCallRequest(
                        model="claude-opus-5-5", messages=(Message(role="user", content="go"),)
                    )
                )
            ]
        assert [event.kind for event in stream] == ["text", "thinking", "tool_use", "usage", "stop"]
        assert stream[0].payload == {"text": "lookup"}
        assert stream[1].payload == {"text": "check", "signature": "opaque-fixture"}
        assert stream[2].payload == {"id": "tool_fixture", "name": "lookup", "input": {"value": 42}}
        final = stream[-1].payload
        assert stream[-2].payload == final["usage"]
        assert final["stop_reason"] == "tool_use"
        assert final["usage"]["input_tokens"] == 20
        assert final["usage"]["output_tokens"] == 12
        assert final["usage"]["cached_input_tokens"] == 30
        assert final["usage"]["cache_write_tokens"] == 10
        assert final["usage"]["cached_input_tokens_present"] is True
        assert final["usage"]["cache_write_tokens_present"] is True
        assert final["anthropic_content"][0]["signature"] == "opaque-fixture"
        assert [block["type"] for block in final["anthropic_content"]] == [
            "thinking",
            "text",
            "tool_use",
        ]
        assert len(requests) == 1
        assert json.loads(requests[0].content)["thinking"]["type"] == "adaptive"

    asyncio.run(check())


@pytest.mark.parametrize("model", ["claude-opus-5-5", "custom-anthropic-model"])
@pytest.mark.parametrize("limit", [0, -1])
def test_output_limit_is_positive_even_for_custom_models(model: str, limit: int) -> None:
    with pytest.raises(LLMRequestValidationError, match="positive"):
        build_create_kwargs(AdapterCallRequest(model=model, messages=(), max_tokens=limit))


@pytest.mark.parametrize(
    ("model", "limit"),
    [("claude-opus-5-5", 0), ("claude-opus-5-5", 128_001), ("claude-haiku-4-5-20251001", 64_001)],
)
def test_auxiliary_completion_rejects_invalid_output_before_sdk_request(
    model: str, limit: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

    create = AsyncMock()
    client = SimpleNamespace(
        base_url="https://api.anthropic.com", messages=SimpleNamespace(create=create)
    )
    monkeypatch.setattr(AnthropicPaygAdapter, "_get_client", lambda _self: client)
    with pytest.raises(LLMRequestValidationError, match="max_tokens"):
        asyncio.run(AnthropicPaygAdapter().acomplete_text("input", model=model, max_tokens=limit))
    create.assert_not_awaited()


def test_auxiliary_completion_preserves_server_thinking_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

    create = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text="done")])
    )
    client = SimpleNamespace(
        base_url="https://api.anthropic.com", messages=SimpleNamespace(create=create)
    )
    monkeypatch.setattr(AnthropicPaygAdapter, "_get_client", lambda _self: client)
    result = asyncio.run(
        AnthropicPaygAdapter().acomplete_text("input", model="claude-opus-5-5", max_tokens=128_000)
    )
    assert result.text == "done"
    create.assert_awaited_once_with(
        model="claude-opus-5-5",
        max_tokens=128_000,
        messages=[{"role": "user", "content": "input"}],
        timeout=60.0,
    )


@pytest.mark.parametrize("cached_tokens", [None, 0])
def test_hosted_search_preserves_usage_presence_and_sources(
    cached_tokens: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

    source_url = "https://example.test/source"
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text="answer",
                citations=[SimpleNamespace(type="web_search_result_location", url=source_url)],
            ),
            SimpleNamespace(
                type="web_search_tool_result", content=[SimpleNamespace(url=source_url)]
            ),
        ],
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=0,
            cache_read_input_tokens=cached_tokens,
            cache_creation_input_tokens=0,
        ),
    )
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(
        base_url="https://api.anthropic.com", messages=SimpleNamespace(create=create)
    )
    monkeypatch.setattr(AnthropicPaygAdapter, "_get_client", lambda _self: client)
    result = asyncio.run(AnthropicPaygAdapter().aweb_search("query", model="claude-opus-5-5"))
    assert result.text == "answer"
    assert result.source_urls == result.citation_urls == (source_url,)
    assert result.search_activated is result.retrieval_exposed is True
    assert result.usage is not None
    assert result.usage.input_tokens == 12
    assert result.usage.input_tokens_present is True
    assert result.usage.output_tokens == result.usage.cache_write_tokens == 0
    assert result.usage.output_tokens_present is result.usage.cache_write_tokens_present is True
    assert result.usage.cached_input_tokens == 0
    assert result.usage.cached_input_tokens_present is (cached_tokens is not None)
    assert result.usage.reasoning_tokens_present is False
    create.assert_awaited_once()
