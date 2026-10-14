"""GPT-6.1 Sol route contracts (official docs and Codex 0.162.0 catalogue, 2026-10-14).

Only the HTTP transport is fake: the production adapters, SDK clients and
request builders produce the serialized body under test.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.errors import LLMRequestValidationError, ModelSourceUnavailableError

MODEL = "gpt-6.1-sol"


def _sse(model: str) -> str:
    call = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": '{"q":"x"}',
        "status": "completed",
    }
    response = {"id": "resp-1", "object": "response", "created_at": 0, "model": model}
    events = [
        {
            "type": "response.created",
            "response": {**response, "status": "in_progress", "output": []},
        },
        {"type": "response.output_item.added", "output_index": 0, "item": call},
        {"type": "response.output_item.done", "output_index": 0, "item": call},
        {
            "type": "response.completed",
            "response": {
                **response,
                "status": "completed",
                "output": [call],
                "usage": {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11},
            },
        },
    ]
    return "".join(
        f"event: {e['type']}\ndata: {json.dumps({**e, 'sequence_number': i})}\n\n"
        for i, e in enumerate(events)
    )


@pytest.mark.parametrize("source", ["payg", "subscription"])
def test_serialized_responses_request_per_route(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    from core.llm.adapters import _openai_common
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    wire: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(request)
        return httpx.Response(200, text=_sse(MODEL), headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(
        _openai_common,
        "_build_async_httpx_client",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    request = AdapterCallRequest(
        model=MODEL,
        messages=(Message(role="user", content="look it up"),),
        system_prompt="Mode: test.",
        max_tokens=200_000,
        effort="low",
        temperature=0.7,
        tools=(ToolSpec(name="lookup", description="Lookup", input_schema={"type": "object"}),),
    )

    async def run() -> list:
        adapter: OpenAIPaygAdapter | CodexOAuthAdapter
        if source == "payg":
            adapter = OpenAIPaygAdapter()
            client = _openai_common.build_async_openai_client(
                "fixture", base_url="https://api.openai.com/v1"
            )
        else:
            adapter = CodexOAuthAdapter()
            client = _openai_common.build_async_codex_client("fixture")
        monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
        async with client:
            return [event async for event in adapter.astream(request)]

    events = asyncio.run(run())

    assert len(wire) == 1
    body = json.loads(wire[0].content)
    expected_url = (
        "https://api.openai.com/v1/responses"
        if source == "payg"
        else "https://chatgpt.com/backend-api/codex/responses"
    )
    assert str(wire[0].url) == expected_url
    assert body["model"] == MODEL
    assert body["reasoning"]["effort"] == "low"
    assert body["tools"][0]["type"] == "function" and body["tools"][0]["name"] == "lookup"
    assert body["store"] is False and "temperature" not in body
    if source == "payg":
        assert body["max_output_tokens"] == 128_000  # published Platform output limit
    else:
        assert "max_output_tokens" not in body  # server-managed under the plan
        assert wire[0].headers["originator"] == "codex_cli_rs"
    tool_uses = [event.payload for event in events if event.kind == "tool_use"]
    assert tool_uses == [{"id": "call-1", "name": "lookup", "input": '{"q":"x"}'}]


@pytest.mark.parametrize("source", ["payg", "subscription"])
@pytest.mark.parametrize("effort", ["none", "minimal", "ultra"])
def test_undocumented_efforts_fail_before_client(
    monkeypatch: pytest.MonkeyPatch, source: str, effort: str
) -> None:
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    adapter = OpenAIPaygAdapter() if source == "payg" else CodexOAuthAdapter()
    client = Mock(side_effect=AssertionError("unsupported effort reached the client"))
    monkeypatch.setattr(adapter, "_get_client", client)
    with pytest.raises(LLMRequestValidationError, match="unsupported"):
        asyncio.run(adapter.acomplete(AdapterCallRequest(model=MODEL, messages=(), effort=effort)))
    client.assert_not_called()


def test_context_admission_distinguishes_platform_and_codex_routes() -> None:
    from core.orchestration.context_budget import resolve_context_budget_policy

    platform = resolve_context_budget_policy(MODEL, provider="openai", source="payg")
    codex = resolve_context_budget_policy(MODEL, provider="openai-codex", source="subscription")
    assert (platform.context_window, platform.max_input_tokens) == (1_050_000, 922_000)
    assert codex.context_window == 500_000 and codex.max_input_tokens is None
    # A configured window may reach the client ceiling but never the API size.
    raised = resolve_context_budget_policy(
        MODEL, provider="openai-codex", source="subscription", context_window=1_050_000
    )
    assert raised.context_window == 872_000


@pytest.mark.parametrize(
    ("input_tokens", "cached", "output_tokens", "expected"),
    [
        (100_000, 0, 10_000, 100_000 * 2e-6 + 10_000 * 10e-6),
        (272_000, 72_000, 0, 200_000 * 2e-6 + 72_000 * 0.1e-6),
        (300_000, 100_000, 10_000, 200_000 * 4e-6 + 100_000 * 0.2e-6 + 10_000 * 15e-6),
    ],
)
def test_platform_tariff_and_full_request_long_context_tier(
    input_tokens: int, cached: int, output_tokens: int, expected: float
) -> None:
    from core.llm.token_tracker import TokenTracker

    cost = TokenTracker().calculate_cost(
        MODEL, input_tokens, output_tokens, cache_read_tokens=cached
    )
    assert cost == pytest.approx(expected)


def test_saved_retired_subscription_default_is_rejected_not_remapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.config as cfg
    from core.config import settings
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    monkeypatch.setattr(settings, "model_policy_path", "")
    monkeypatch.setattr(cfg, "CODEX_PRIMARY", "gpt-5.5")
    adapter = CodexOAuthAdapter()
    client = Mock(side_effect=AssertionError("retired model reached credentials"))
    monkeypatch.setattr(adapter, "_get_client", client)
    with pytest.raises(ModelSourceUnavailableError) as caught:
        asyncio.run(adapter.acomplete_text("probe"))
    message = str(caught.value)
    assert "gpt-5.5 is retired on 2026-10-14" in message
    assert "gpt-6-sol" in message and "will not switch models or billing sources" in message
    client.assert_not_called()
    assert cfg.CODEX_PRIMARY == "gpt-5.5"
