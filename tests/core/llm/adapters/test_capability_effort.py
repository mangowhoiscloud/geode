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
            input_tokens_details=SimpleNamespace(cached_tokens=0),
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
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
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
    if capability == "search" and adapter.source == "payg":
        # Existing PAYG search has no usage projection; effort is not a counter fix.
        assert rows[0]["usage"]["input_tokens"] is None
        assert rows[0]["usage"]["cached_input_tokens"] is None
    else:
        assert rows[0]["usage"]["input_tokens"] == 12
        assert rows[0]["usage"]["cached_input_tokens"] == 0
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
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
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
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
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
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
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
    "provider, model", [("anthropic", "claude-sonnet-4-6"), ("glm", "glm-5"), ("openai", "gpt-4.1")]
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
