"""Public SystemOne routes; all provider traffic is an in-memory fake transport."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.adapters.typesafe import (
    JEV_MODEL,
    OPENROUTER_JEV_MODEL,
    SystemOneAdapter,
    call_typesafe,
    parse_choice_answers,
)
from pydantic import SecretStr

QUESTIONS = {
    "decision": {
        "type": "choice",
        "instructions": "Classify only the supplied evidence.",
        "criteria": {"supported": "Evidence exists", "unknown": "Evidence is missing"},
    }
}
ANSWERS = {
    "decision": {
        "type": "choice",
        "choice": "supported",
        "probabilities": {"supported": 0.8, "unknown": 0.2},
        "confidence": 0.6,
    }
}


def _request(model: str) -> AdapterCallRequest:
    return AdapterCallRequest(
        model=model,
        messages=(
            Message(
                "user", json.dumps({"state": {"evidence": "observed"}, "questions": QUESTIONS})
            ),
        ),
        tool_choice="none",
        allowed_tool_names=frozenset(),
    )


@pytest.mark.parametrize("provider", ["typesafe", "openrouter"])
def test_systemone_routes_identity_and_native_accounting(provider: str) -> None:
    seen = []
    requested_model = JEV_MODEL if provider == "typesafe" else OPENROUTER_JEV_MODEL
    actual_model = requested_model if provider == "typesafe" else requested_model + "-20260917"

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        assert body == {
            "state": {"evidence": "observed"},
            "questions": QUESTIONS,
            "model": requested_model,
        }
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": "ts-request-1"},
            json={
                "id": "gen-decision-1",
                "provider": "TypeSafe",
                "model": actual_model,
                "answers": ANSWERS,
                "usage": {"input_tokens": 120, "output_tokens": 0, "cost": 0.00000504},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = SystemOneAdapter(provider, SecretStr("test-secret"), client=client)
            return await adapter.acomplete(_request(adapter.model))

    result = asyncio.run(run())
    assert str(seen[0].url) == (
        "https://api.typesafe.ai/v1/systemone"
        if provider == "typesafe"
        else "https://openrouter.ai/api/v1/systemone"
    )
    assert len(seen) == 1
    assert result.response_model == actual_model
    assert result.stop_reason == "end_turn"
    assert result.usage.input_tokens == 120 and result.usage.input_tokens_present
    assert result.usage.output_tokens == 0 and result.usage.output_tokens_present
    assert not result.usage.cached_input_tokens_present
    assert result.usage.reported_cost_usd == (None if provider == "typesafe" else 0.00000504)
    assert result.response_id == ("ts-request-1" if provider == "typesafe" else "gen-decision-1")
    assert parse_choice_answers(result.text, QUESTIONS) == ANSWERS


@pytest.mark.parametrize("bad_field", ["model", "provider", "cost", "json"])
def test_inadmissible_completed_response_keeps_known_consumption(bad_field: str) -> None:
    def transport(_request: httpx.Request) -> httpx.Response:
        if bad_field == "json":
            return httpx.Response(200, text="not json")
        body = {
            "model": OPENROUTER_JEV_MODEL,
            "provider": "TypeSafe",
            "answers": ANSWERS,
            "usage": {"input_tokens": 10, "output_tokens": 0, "cost": 0.1},
        }
        if bad_field == "cost":
            body["usage"]["cost"] = "unknown"
        else:
            body[bad_field] = "other-route"
        return httpx.Response(200, json=body)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = SystemOneAdapter("openrouter", SecretStr("test-secret"), client=client)
            return await adapter.acomplete(_request(adapter.model))

    result = asyncio.run(run())
    assert result.stop_reason == "invalid_response"
    assert result.usage.input_tokens == (0 if bad_field == "json" else 10)
    assert result.usage.input_tokens_present is (bad_field != "json")


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.1, 1.1])
def test_choice_nonfinite_or_out_of_range_is_not_a_verdict(invalid: float) -> None:
    answer = {**ANSWERS["decision"], "confidence": invalid}
    with pytest.raises(ValueError):
        parse_choice_answers(json.dumps({"decision": answer}), QUESTIONS)


def test_http_error_has_one_attempt_and_no_route_fallback() -> None:
    seen = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429, json={"error": "rate limited"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = SystemOneAdapter("typesafe", SecretStr("test-secret"), client=client)
            await adapter.acomplete(_request(adapter.model))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())
    assert len(seen) == 1


def test_decision_route_rejects_generation_and_malformed_input_before_dispatch() -> None:
    adapter = SystemOneAdapter("typesafe", SecretStr("test-secret"))
    for request in (
        replace(_request(adapter.model), model="gpt-6-astra"),
        replace(_request(adapter.model), executable_tool_names=frozenset({"bash"})),
        replace(_request(adapter.model), messages=(Message("user", "Write a poem"),)),
        replace(
            _request(adapter.model), messages=(Message("user", '{"state":{},"questions":{}}'),)
        ),
    ):
        with pytest.raises(ValueError):
            asyncio.run(adapter.acomplete(request))


def test_eval_import_reuses_fixed_direct_transport_without_a_second_owner() -> None:
    from evals.benchmarks import typesafe_decision

    assert typesafe_decision.call_typesafe is call_typesafe
    assert typesafe_decision.parse_choice_answers is parse_choice_answers
    assert typesafe_decision.JEV_MODEL == JEV_MODEL


def test_default_transport_is_call_owned_across_event_loops(monkeypatch) -> None:
    clients: list[httpx.AsyncClient] = []
    client_type = httpx.AsyncClient

    def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": JEV_MODEL, "answers": ANSWERS})

    def make_client(**kwargs) -> httpx.AsyncClient:
        client = client_type(transport=httpx.MockTransport(transport), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    adapter = SystemOneAdapter("typesafe", SecretStr("test-secret"))
    for _ in range(2):
        assert asyncio.run(adapter.acomplete(_request(adapter.model))).stop_reason == "end_turn"
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert all(client.is_closed for client in clients)
