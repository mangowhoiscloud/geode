"""Retired direct-API models fail before network or replacement routing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.errors import ModelSourceUnavailableError


@pytest.fixture(autouse=True)
def _isolate_anthropic_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


async def _request(adapter: AnthropicPaygAdapter, method: str, model: str) -> None:
    req = AdapterCallRequest(model=model, messages=[Message(role="user", content="offline")])
    if method == "astream":
        async for _ in adapter.astream(req):
            pass
    elif method == "aweb_search":
        await adapter.aweb_search("offline", model=model)
    elif method == "acomplete_text":
        await adapter.acomplete_text("offline", model=model)
    else:
        await adapter.acomplete(req)


@pytest.mark.parametrize("method", ["acomplete", "astream", "aweb_search", "acomplete_text"])
@pytest.mark.parametrize("model", ["claude-opus-4-1", "claude-sonnet-4-20250514"])
def test_retired_model_rejected_before_network_or_web_search_replacement(
    monkeypatch: pytest.MonkeyPatch, method: str, model: str
) -> None:
    adapter = AnthropicPaygAdapter()
    messages = Mock()
    client = SimpleNamespace(base_url="https://api.anthropic.com", messages=messages)
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    with pytest.raises(ModelSourceUnavailableError, match=r"retired.*Anthropic API"):
        asyncio.run(_request(adapter, method, model))
    assert messages.mock_calls == []


@pytest.mark.parametrize("method", ["aweb_search", "acomplete_text"])
def test_retired_default_rejected_without_silent_replacement(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    import core.config as cfg

    monkeypatch.setattr(cfg, "ANTHROPIC_PRIMARY", "claude-opus-4-1")
    adapter = AnthropicPaygAdapter()
    messages = Mock()
    client = SimpleNamespace(base_url="https://api.anthropic.com", messages=messages)
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
    with pytest.raises(ModelSourceUnavailableError, match=r"retired.*Anthropic API"):
        asyncio.run(_request(adapter, method, ""))
    assert messages.mock_calls == []


def test_list_filters_retired_user_override_without_rewriting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.config as cfg

    monkeypatch.setattr(cfg, "ANTHROPIC_PRIMARY", "claude-opus-4-1")
    monkeypatch.setattr(cfg, "ANTHROPIC_FALLBACK_CHAIN", ["claude-opus-4", "claude-opus-4-8"])
    ids = [model.id for model in AnthropicPaygAdapter().list_models()]
    assert "claude-opus-4-8" in ids
    assert "claude-opus-4-1" not in ids
    assert "claude-opus-4" not in ids
    assert len(ids) == len(set(ids))
    assert cfg.ANTHROPIC_PRIMARY == "claude-opus-4-1"


@pytest.mark.parametrize(
    "cached_url,current_env,should_block",
    [
        ("http://127.0.0.1:9/custom", "https://api.anthropic.com", False),
        ("https://api.anthropic.com", "http://127.0.0.1:9/custom", True),
    ],
)
def test_actual_cached_sdk_endpoint_owns_retirement_not_changed_environment(
    monkeypatch: pytest.MonkeyPatch, cached_url: str, current_env: str, should_block: bool
) -> None:
    import anthropic
    import httpx
    from core.config import settings

    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-20250514",
                "content": [{"type": "text", "text": "offline response"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        )

    def build_client(api_key: str, *, base_url: str | None = None) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            auth_token="",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(settings, "anthropic_api_key", "offline-test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", cached_url)
    monkeypatch.setattr(
        "core.llm.adapters.anthropic_payg.build_async_anthropic_client", build_client
    )
    adapter = AnthropicPaygAdapter()

    async def run() -> None:
        client = adapter._get_client()
        monkeypatch.setenv("ANTHROPIC_BASE_URL", current_env)
        assert adapter._get_client() is client  # the real loop-affine cache
        try:
            if should_block:
                with pytest.raises(ModelSourceUnavailableError):
                    await _request(adapter, "acomplete", "claude-sonnet-4-20250514")
            else:
                await _request(adapter, "acomplete", "claude-sonnet-4-20250514")
        finally:
            await client.close()

    asyncio.run(run())
    assert len(calls) == (0 if should_block else 1)
    if calls:
        assert calls[0].url.host == "127.0.0.1"


def test_custom_host_retains_configured_models_in_adapter_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.config as cfg

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    monkeypatch.setattr(cfg, "ANTHROPIC_PRIMARY", "claude-opus-4-1")
    monkeypatch.setattr(cfg, "ANTHROPIC_FALLBACK_CHAIN", [])
    assert "claude-opus-4-1" in [model.id for model in AnthropicPaygAdapter().list_models()]
