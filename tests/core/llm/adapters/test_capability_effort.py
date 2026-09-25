"""Inherited capability effort must reach the wire, not just the usage record."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.hooks import HookEvent, HookSystem
from core.llm.adapters.base import TextCompletionResult, UsageSummary, WebSearchResult
from core.llm.adapters.codex_oauth import CodexOAuthAdapter
from core.llm.adapters.dispatch import (
    AdapterDispatchError,
    complete_text_via_adapters,
    web_search_via_adapters,
)
from core.llm.adapters.openai_payg import OpenAIPaygAdapter


@pytest.fixture
def observed() -> tuple[HookSystem, list[dict[str, Any]]]:
    hooks = HookSystem()
    rows: list[dict[str, Any]] = []
    hooks.register(HookEvent.LLM_CALL_ENDED, lambda _event, data: rows.append(dict(data)))
    return hooks, rows


@pytest.fixture
def wire_client() -> tuple[Any, list[dict[str, Any]]]:
    message = SimpleNamespace(
        type="message", content=[SimpleNamespace(type="output_text", text="answer")]
    )
    final = SimpleNamespace(
        output=[message],
        output_text="answer",
        status="completed",
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=3,
            input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=7),
        ),
    )
    wire: list[dict[str, Any]] = []

    class Stream:
        async def __aenter__(self) -> Stream:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            pass

        async def __aiter__(self) -> Any:
            yield SimpleNamespace(type="response.output_item.done", item=message)

        async def get_final_response(self) -> Any:
            return final

    def stream(**kwargs: Any) -> Stream:
        wire.append(kwargs)
        return Stream()

    async def create(**kwargs: Any) -> Any:
        wire.append(kwargs)
        return final

    return SimpleNamespace(responses=SimpleNamespace(stream=stream, create=create)), wire


@pytest.mark.parametrize("adapter_class", [CodexOAuthAdapter, OpenAIPaygAdapter])
@pytest.mark.parametrize("capability", ["text", "search"])
@pytest.mark.parametrize("effort", [None, "max"])
def test_capability_wire_and_observed_effort_match(
    monkeypatch: pytest.MonkeyPatch,
    adapter_class: Any,
    capability: str,
    effort: str | None,
    observed: Any,
    wire_client: Any,
) -> None:
    client, wire = wire_client
    adapter = adapter_class()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    # A different default exposes adapters that overwrite the selected model.
    monkeypatch.setattr("core.config.OPENAI_PRIMARY", "gpt-5.5")
    monkeypatch.setattr("core.config.CODEX_PRIMARY", "gpt-5.5")
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    hooks, rows = observed
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters

    result = asyncio.run(dispatch("input", model="gpt-5.6-sol", effort=effort, hooks=hooks))

    assert result.text and len(wire) == len(rows) == 1
    assert wire[0]["model"] == "gpt-5.6-sol"
    assert rows[0]["model"] == "gpt-5.6-sol"
    expected_wire_effort = (
        "medium"
        if effort is None and capability == "text" and adapter.source == "subscription"
        else effort
    )
    assert wire[0].get("reasoning", {}).get("effort") == expected_wire_effort
    assert rows[0]["effort"] == effort
    assert rows[0]["source"] == adapter.source
    assert rows[0]["purpose"] == ("text_completion" if capability == "text" else "hosted_search")
    assert rows[0]["usage"]["input_tokens"] == 12
    assert rows[0]["usage"]["output_tokens"] == 3
    assert rows[0]["usage"]["cached_input_tokens"] == 0
    assert rows[0]["usage"]["cache_write_tokens"] == 7
    assert rows[0]["usage"]["reasoning_tokens"] is None
    if adapter.source == "subscription":
        assert wire[0]["store"] is False
        assert isinstance(wire[0]["input"], list)
        assert "max_output_tokens" not in wire[0]
    if capability == "search":
        assert wire[0]["tools"] == [{"type": "web_search"}]


@pytest.mark.parametrize("adapter_class", [CodexOAuthAdapter, OpenAIPaygAdapter])
@pytest.mark.parametrize("capability", ["text", "search"])
@pytest.mark.parametrize("effort", [None, "max"])
def test_empty_model_uses_selected_route_default_without_losing_inherited_effort(
    monkeypatch: pytest.MonkeyPatch,
    adapter_class: Any,
    capability: str,
    effort: str | None,
    observed: Any,
    wire_client: Any,
) -> None:
    client, wire = wire_client
    adapter = adapter_class()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    monkeypatch.setattr("core.config.CODEX_PRIMARY", "gpt-5.6-sol")
    monkeypatch.setattr("core.config.OPENAI_PRIMARY", "gpt-6-astra")
    # Exercise actual route selection, not a model-filled selection stub.
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [adapter])
    hooks, rows = observed
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters

    result = asyncio.run(
        dispatch(
            "input",
            model="",
            prefer_provider="openai",
            prefer_source=adapter.source,
            effort=effort,
            hooks=hooks,
        )
    )

    expected_model = "gpt-5.6-sol" if adapter.source == "subscription" else "gpt-6-astra"
    assert result.text and len(wire) == len(rows) == 1
    assert wire[0]["model"] == expected_model
    assert rows[0]["model"] == (expected_model if effort is not None else "")
    assert rows[0]["effort"] == effort
    expected_wire_effort = (
        "medium"
        if effort is None and capability == "text" and adapter.source == "subscription"
        else effort
    )
    assert wire[0].get("reasoning", {}).get("effort") == expected_wire_effort


@pytest.mark.parametrize("adapter_class", [CodexOAuthAdapter, OpenAIPaygAdapter])
@pytest.mark.parametrize("capability", ["text", "search"])
def test_empty_model_validates_effort_against_actual_route_default(
    monkeypatch: pytest.MonkeyPatch, adapter_class: Any, capability: str, wire_client: Any
) -> None:
    client, wire = wire_client
    adapter = adapter_class()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    monkeypatch.setattr("core.config.CODEX_PRIMARY", "gpt-5.5")
    monkeypatch.setattr("core.config.OPENAI_PRIMARY", "gpt-5.5")
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [adapter])
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters

    with pytest.raises(AdapterDispatchError) as caught:
        asyncio.run(
            dispatch("input", prefer_provider="openai", prefer_source=adapter.source, effort="max")
        )

    assert isinstance(caught.value.__cause__, ValueError)
    assert "unsupported" in str(caught.value.__cause__)
    assert wire == []


@pytest.mark.parametrize("adapter_class", [CodexOAuthAdapter, OpenAIPaygAdapter])
@pytest.mark.parametrize("capability", ["text", "search"])
@pytest.mark.parametrize("model, effort", [("gpt-5.5", "max"), ("gpt-5.6-sol", "MAX")])
def test_unsupported_explicit_effort_fails_before_provider_request(
    monkeypatch: pytest.MonkeyPatch,
    adapter_class: Any,
    capability: str,
    model: str,
    effort: str,
    wire_client: Any,
) -> None:
    client, wire = wire_client
    adapter = adapter_class()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    monkeypatch.setattr("core.config.OPENAI_PRIMARY", model)
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters

    with pytest.raises(AdapterDispatchError) as caught:
        asyncio.run(dispatch("input", model=model, effort=effort))

    assert isinstance(caught.value.__cause__, ValueError)
    assert "unsupported" in str(caught.value.__cause__)
    assert wire == []  # No clamp to xhigh and no request on another adapter.


@pytest.mark.parametrize("capability", ["text", "search"])
@pytest.mark.parametrize(
    "provider, model", [("anthropic", "claude-haiku-4-5"), ("glm", "glm-5"), ("openai", "gpt-4.1")]
)
def test_non_reasoning_routes_keep_legacy_signature_and_unknown_effort(
    monkeypatch: pytest.MonkeyPatch, capability: str, provider: str, model: str, observed: Any
) -> None:
    class LegacyAdapter:
        name = "legacy"
        source = "payg"

        async def acomplete_text(
            self, prompt: str, *, system: str, model: str, max_tokens: int
        ) -> TextCompletionResult:
            return TextCompletionResult(text="answer", usage=UsageSummary())

        async def aweb_search(self, query: str, *, max_results: int) -> WebSearchResult:
            return WebSearchResult(query=query, text="answer")

    adapter = LegacyAdapter()
    monkeypatch.setattr(adapter, "provider", provider, raising=False)
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    hooks, rows = observed
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters

    result = asyncio.run(dispatch("input", model=model, effort="max", hooks=hooks))

    assert result.text == "answer" and len(rows) == 1
    assert rows[0]["effort"] is None


@pytest.mark.parametrize("capability", ["text", "search"])
def test_inherited_effort_survives_same_adapter_retry(
    monkeypatch: pytest.MonkeyPatch, capability: str, observed: Any
) -> None:
    class ReadError(Exception):
        pass

    result = (
        TextCompletionResult(text="answer", usage=UsageSummary())
        if capability == "text"
        else WebSearchResult(query="input", text="answer")
    )
    call = AsyncMock(side_effect=[ReadError("transport"), result])
    adapter = SimpleNamespace(
        name="codex-oauth",
        provider="openai",
        source="subscription",
        acomplete_text=call,
        aweb_search=call,
    )
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    hooks, rows = observed
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters

    asyncio.run(dispatch("input", model="gpt-5.6-sol", effort="max", hooks=hooks))

    assert len(rows) == call.await_count == 2
    assert rows[0]["llm_call_id"] == rows[1]["llm_call_id"]
    assert rows[0]["llm_attempt_id"] != rows[1]["llm_attempt_id"]
    assert all(row["effort"] == "max" for row in rows)
    assert all(attempt.kwargs["effort"] == "max" for attempt in call.await_args_list)


@pytest.mark.parametrize(
    "model,requested,expected",
    [("gpt-6-sol", 200_000, 128_000), ("o3", 200_000, 100_000), ("gpt-6-sol", 32, 32)],
)
def test_payg_auxiliary_completion_caps_published_output_budget(
    monkeypatch: pytest.MonkeyPatch, wire_client: Any, model: str, requested: int, expected: int
) -> None:
    client, wire = wire_client
    adapter = OpenAIPaygAdapter()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    result = asyncio.run(adapter.acomplete_text("input", model=model, max_tokens=requested))
    assert result.text == "answer"
    assert wire[0]["max_output_tokens"] == expected


@pytest.mark.parametrize("max_tokens", [0, -1])
def test_payg_auxiliary_completion_rejects_nonpositive_budget_before_request(
    monkeypatch: pytest.MonkeyPatch, wire_client: Any, max_tokens: int
) -> None:
    from core.llm.errors import LLMRequestValidationError

    client, wire = wire_client
    adapter = OpenAIPaygAdapter()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    with pytest.raises(LLMRequestValidationError, match="must be positive"):
        asyncio.run(adapter.acomplete_text("input", model="gpt-6-sol", max_tokens=max_tokens))
    assert wire == []


def test_empty_payg_search_keeps_provider_usage_in_failure_hook(
    monkeypatch: pytest.MonkeyPatch, observed: Any
) -> None:
    from core.llm.adapters.base import EmptyModelOutputError

    response = SimpleNamespace(
        output=[],
        usage=SimpleNamespace(input_tokens=12, output_tokens=0),
    )
    create = AsyncMock(return_value=response)
    adapter = OpenAIPaygAdapter()
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    hooks, rows = observed
    with pytest.raises(AdapterDispatchError) as caught:
        asyncio.run(web_search_via_adapters("input", model="gpt-6-sol", hooks=hooks))
    assert isinstance(caught.value.__cause__, EmptyModelOutputError)
    assert create.await_count == len(rows) == 1
    assert rows[0]["error_type"] == "EmptyModelOutputError"
    assert rows[0]["usage"]["input_tokens"] == 12
    assert rows[0]["usage"]["output_tokens"] == 0
    assert rows[0]["usage"]["cached_input_tokens"] is None
    assert rows[0]["cost_usd"] is None


@pytest.mark.parametrize(
    "provider,model,capability",
    [
        ("anthropic", "claude-sonnet-5", "text"),
        ("anthropic", "claude-sonnet-5", "search"),
        ("glm", "glm-5.3", "text"),
    ],
)
@pytest.mark.parametrize("effort", ["low", "max"])
@pytest.mark.parametrize("empty_model", [False, True])
def test_native_capability_effort_reaches_sdk_wire_and_observation(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
    effort: str,
    capability: str,
    empty_model: bool,
) -> None:
    import json

    import httpx
    from anthropic import AsyncAnthropic
    from core.config import settings
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.adapters.glm_payg import GlmPaygAdapter
    from openai import AsyncOpenAI

    bodies: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    hooks = HookSystem()
    hooks.register(HookEvent.LLM_CALL_ENDED, lambda _event, data: rows.append(dict(data)))
    monkeypatch.setattr(settings, "glm_reasoning_effort", "high")
    monkeypatch.setattr("core.config.ANTHROPIC_PRIMARY", "claude-sonnet-5")
    monkeypatch.setattr("core.config.GLM_PRIMARY", "glm-5.3")

    def transport(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if provider == "anthropic":
            return httpx.Response(
                200,
                json={
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": "answer"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chat_test",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            },
        )

    async def run() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        client = (AsyncAnthropic if provider == "anthropic" else AsyncOpenAI)(
            api_key="test-key", http_client=http, max_retries=0
        )
        adapter = AnthropicPaygAdapter() if provider == "anthropic" else GlmPaygAdapter()
        monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
        monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [adapter])
        try:
            dispatch = (
                complete_text_via_adapters if capability == "text" else web_search_via_adapters
            )
            result = await dispatch(
                "input",
                model="" if empty_model else model,
                effort=effort,
                prefer_provider=provider,
                prefer_source="payg",
                hooks=hooks,
            )
            assert result.text == "answer"
        finally:
            await client.close()
        assert client.is_closed()

    asyncio.run(run())
    assert len(bodies) == len(rows) == 1
    actual = (
        bodies[0].get("output_config", {}).get("effort")
        if provider == "anthropic"
        else bodies[0].get("reasoning_effort")
    )
    assert actual == effort
    assert rows[0]["effort"] == effort
    assert bodies[0]["model"] == rows[0]["model"] == model
    assert rows[0]["usage"]["input_tokens"] == 3
    assert rows[0]["usage"]["output_tokens"] == 1


@pytest.mark.parametrize(
    "route,model,effort",
    [
        ("openai", "gpt-5.5", "max"),
        ("codex", "gpt-5.5", "max"),
        ("anthropic", "claude-sonnet-4-6", "xhigh"),
        ("glm", "glm-5.3", "medium"),
    ],
)
@pytest.mark.parametrize("capability", ["agentic", "text", "stream"])
def test_unsupported_native_effort_rejects_before_client_access(
    monkeypatch: pytest.MonkeyPatch, route: str, model: str, effort: str, capability: str
) -> None:
    from unittest.mock import Mock

    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.adapters.base import AdapterCallRequest
    from core.llm.adapters.glm_payg import GlmPaygAdapter
    from core.llm.errors import LLMRequestValidationError

    adapter = {
        "openai": OpenAIPaygAdapter,
        "codex": CodexOAuthAdapter,
        "anthropic": AnthropicPaygAdapter,
        "glm": GlmPaygAdapter,
    }[route]()
    get_client = Mock(side_effect=AssertionError("invalid effort reached client access"))
    monkeypatch.setattr(adapter, "_get_client", get_client)
    with pytest.raises(LLMRequestValidationError):
        if capability == "agentic":
            asyncio.run(
                adapter.acomplete(AdapterCallRequest(model=model, messages=(), effort=effort))
            )
        elif capability == "text":
            asyncio.run(adapter.acomplete_text("input", model=model, effort=effort))
        else:

            async def stream() -> None:
                async for _event in adapter.astream(
                    AdapterCallRequest(model=model, messages=(), effort=effort)
                ):
                    pytest.fail("invalid effort produced a stream event")

            asyncio.run(stream())
    get_client.assert_not_called()


@pytest.mark.parametrize(
    "route,model,effort",
    [
        ("openai", "gpt-5.5", "max"),
        ("codex", "gpt-5.5", "max"),
        ("anthropic", "claude-sonnet-4-6", "xhigh"),
    ],
)
def test_unsupported_search_effort_rejects_before_client_access(
    monkeypatch: pytest.MonkeyPatch, route: str, model: str, effort: str
) -> None:
    from unittest.mock import Mock

    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.errors import LLMRequestValidationError

    adapter = {
        "openai": OpenAIPaygAdapter,
        "codex": CodexOAuthAdapter,
        "anthropic": AnthropicPaygAdapter,
    }[route]()
    get_client = Mock(side_effect=AssertionError("invalid effort reached client access"))
    monkeypatch.setattr(adapter, "_get_client", get_client)
    with pytest.raises(LLMRequestValidationError):
        asyncio.run(adapter.aweb_search("query", model=model, effort=effort))
    get_client.assert_not_called()
