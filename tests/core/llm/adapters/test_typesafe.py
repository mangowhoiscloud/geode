"""Public SystemOne routes; all provider traffic is an in-memory fake transport."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import httpx
import pytest
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.adapters.typesafe import (
    JEV_MODEL,
    OPENROUTER_JEV_MODEL,
    SystemOneAdapter,
    call_typesafe,
    parse_choice_answers,
    parse_systemone_answers,
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
SCORE_QUESTION = {
    "type": "score",
    "instructions": {"question": "How complete is the supplied evidence?"},
    "criteria": ["Missing", {"description": "Partial", "examples": ["One source"]}, ["Complete"]],
}
SCORE_ANSWER = {
    "type": "score",
    "score": 1.4,
    "legend": {
        "0": SCORE_QUESTION["criteria"][0],
        "1": SCORE_QUESTION["criteria"][1],
        "2": SCORE_QUESTION["criteria"][2],
    },
    "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5},
    "confidence": 0.3,
}
NOUL_QUESTION = {"type": "noul", "instructions": "Does the evidence contain the requested value?"}
NOUL_ANSWER = {"type": "noul", "noul": 0.75}
MIXED_QUESTIONS = {**QUESTIONS, "completeness": SCORE_QUESTION, "present": NOUL_QUESTION}
MIXED_ANSWERS = {**ANSWERS, "completeness": SCORE_ANSWER, "present": NOUL_ANSWER}


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


def test_mixed_primitive_answers_preserve_typed_fields_and_structured_legend() -> None:
    assert parse_systemone_answers(json.dumps(MIXED_ANSWERS), MIXED_QUESTIONS) == MIXED_ANSWERS
    with pytest.raises(ValueError, match="choice questions"):
        parse_choice_answers(json.dumps(MIXED_ANSWERS), MIXED_QUESTIONS)


@pytest.mark.parametrize("provider", ["typesafe", "openrouter"])
def test_mixed_questions_use_one_transport_call_and_preserve_native_usage(provider: str) -> None:
    seen = []

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert body["questions"] == MIXED_QUESTIONS
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "provider": "TypeSafe",
                "answers": MIXED_ANSWERS,
                "usage": {"input_tokens": 360, "output_tokens": 0},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = SystemOneAdapter(provider, SecretStr("test-secret"), client=client)
            request = replace(
                _request(adapter.model),
                messages=(
                    Message("user", json.dumps({"state": {}, "questions": MIXED_QUESTIONS})),
                ),
            )
            return await adapter.acomplete(request)

    result = asyncio.run(run())
    assert len(seen) == 1 and result.stop_reason == "end_turn"
    assert parse_systemone_answers(result.text, MIXED_QUESTIONS) == MIXED_ANSWERS
    assert result.usage.input_tokens == 360 and result.usage.input_tokens_present
    assert result.usage.output_tokens == 0 and result.usage.output_tokens_present
    assert not result.usage.cached_input_tokens_present
    assert result.usage.reported_cost_usd is None


def test_invalid_score_admission_does_not_erase_completed_call_usage() -> None:
    def transport(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": JEV_MODEL,
                "answers": {**MIXED_ANSWERS, "completeness": {**SCORE_ANSWER, "score": 0.1}},
                "usage": {"input_tokens": 360, "output_tokens": 0},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await call_typesafe(
                client, SecretStr("test-secret"), {"state": {}, "questions": MIXED_QUESTIONS}
            )

    result = asyncio.run(run())
    with pytest.raises(ValueError, match="score does not match"):
        parse_systemone_answers(result.text, MIXED_QUESTIONS)
    assert result.usage.input_tokens == 360 and result.usage.input_tokens_present
    assert result.usage.output_tokens == 0 and result.usage.output_tokens_present
    assert not result.usage.cached_input_tokens_present
    assert result.usage.reported_cost_usd is None


@pytest.mark.parametrize("levels", [2, 10])
@pytest.mark.parametrize("top", [False, True])
def test_score_range_tracks_requested_level_count(levels: int, top: bool) -> None:
    criteria = [f"Level {index}" for index in range(levels)]
    chosen = levels - 1 if top else 0
    answer = {
        "type": "score",
        "score": chosen,
        "confidence": 1,
        "legend": dict(enumerate(criteria)),
        "probabilities": {str(index): int(index == chosen) for index in range(levels)},
    }
    result = parse_systemone_answers(
        json.dumps({"score": answer}), {"score": {**SCORE_QUESTION, "criteria": criteria}}
    )
    assert result["score"]["score"] == chosen


@pytest.mark.parametrize(
    "criteria", [None, {"true": ["Observed"], "false": {"description": "Absent"}}]
)
@pytest.mark.parametrize("probability", [0, 0.5, 1])
def test_noul_optional_criteria_and_numeric_boundaries(criteria: Any, probability: float) -> None:
    question = {**NOUL_QUESTION}
    if criteria is not None:
        question["criteria"] = criteria
    answer = {"type": "noul", "noul": probability}
    assert parse_systemone_answers(json.dumps({"q": answer}), {"q": question}) == {"q": answer}


@pytest.mark.parametrize(
    "invalid", [True, False, "0.5", None, float("nan"), float("inf"), -float("inf"), -0.1, 1.1]
)
@pytest.mark.parametrize(
    "kind,field",
    [
        ("choice", "confidence"),
        ("choice", "probabilities"),
        ("score", "confidence"),
        ("score", "probabilities"),
        ("noul", "noul"),
    ],
)
def test_primitive_probabilities_are_strict_finite_numbers(
    kind: str, field: str, invalid: Any
) -> None:
    question, original = {
        "choice": (QUESTIONS["decision"], ANSWERS["decision"]),
        "score": (SCORE_QUESTION, SCORE_ANSWER),
        "noul": (NOUL_QUESTION, NOUL_ANSWER),
    }[kind]
    answer = deepcopy(original)
    if field == "probabilities":
        answer[field][next(iter(answer[field]))] = invalid
    else:
        answer[field] = invalid
    with pytest.raises(ValueError):
        parse_systemone_answers(json.dumps({"q": answer}), {"q": question})


@pytest.mark.parametrize(
    "invalid", [True, False, "1.4", None, float("nan"), float("inf"), -0.1, 2.1, 0.4]
)
def test_score_rejects_invalid_or_inconsistent_expected_value(invalid: Any) -> None:
    answer = {**SCORE_ANSWER, "score": invalid}
    with pytest.raises(ValueError):
        parse_systemone_answers(json.dumps({"q": answer}), {"q": SCORE_QUESTION})


@pytest.mark.parametrize(
    "field,value",
    [
        ("legend", {"0": "Missing", "1": "Changed", "2": ["Complete"]}),
        ("legend", ["Missing", "Partial", "Complete"]),
        ("legend", {"0": "Missing"}),
        ("probabilities", {"0": 0.5, "1": 0.5}),
        ("probabilities", {"0": 0.1, "1": 0.4, "2": 0.4}),
        ("probabilities", {"0": 0.1, "1": 0.4, "2": 0.5, "3": 0}),
        ("probabilities", [0.1, 0.4, 0.5]),
    ],
)
def test_score_requires_exact_requested_legend_and_normalized_levels(
    field: str, value: Any
) -> None:
    with pytest.raises(ValueError):
        parse_systemone_answers(
            json.dumps({"q": {**SCORE_ANSWER, field: value}}), {"q": SCORE_QUESTION}
        )


def test_score_legend_does_not_equate_boolean_and_integer_descriptions() -> None:
    question = {**SCORE_QUESTION, "criteria": [{"count": 1}, "Many"]}
    answer = {
        "type": "score",
        "score": 0,
        "legend": {"0": {"count": True}, "1": "Many"},
        "probabilities": {"0": 1, "1": 0},
        "confidence": 1,
    }
    with pytest.raises(ValueError, match="legend"):
        parse_systemone_answers(json.dumps({"q": answer}), {"q": question})


@pytest.mark.parametrize("kind", ["choice", "score", "noul"])
@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "type", "shape", "missing_question", "extra_question"]
)
def test_answers_reject_wrong_fields_types_and_question_ids(kind: str, mutation: str) -> None:
    question, original = {
        "choice": (QUESTIONS["decision"], ANSWERS["decision"]),
        "score": (SCORE_QUESTION, SCORE_ANSWER),
        "noul": (NOUL_QUESTION, NOUL_ANSWER),
    }[kind]
    answer = deepcopy(original)
    if mutation == "missing":
        del answer[kind]
    elif mutation == "extra":
        answer["confidence" if kind == "noul" else "rationale"] = 0.5
    elif mutation == "type":
        answer["type"] = "score" if kind != "score" else "choice"
    payload = {"q": [answer] if mutation == "shape" else answer}
    if mutation == "missing_question":
        payload = {}
    elif mutation == "extra_question":
        payload["extra"] = answer
    with pytest.raises(ValueError):
        parse_systemone_answers(json.dumps(payload), {"q": question})


@pytest.mark.parametrize(
    "choice,probabilities",
    [
        ("unknown", {"supported": 0.8, "unknown": 0.2}),
        ("other", {"supported": 0.8, "unknown": 0.2}),
        ("supported", {"supported": 0.8}),
        ("supported", {"supported": 0.8, "unknown": 0.1}),
        ("supported", {}),
    ],
)
def test_choice_wrapper_keeps_selection_and_distribution_guards(
    choice: str, probabilities: dict[str, float]
) -> None:
    with pytest.raises(ValueError):
        parse_choice_answers(
            json.dumps(
                {
                    "decision": {
                        **ANSWERS["decision"],
                        "choice": choice,
                        "probabilities": probabilities,
                    }
                }
            ),
            QUESTIONS,
        )


@pytest.mark.parametrize(
    "question",
    [
        None,
        {},
        {"type": "noul"},
        {**NOUL_QUESTION, "type": "generate"},
        {**NOUL_QUESTION, "instructions": True},
        {**NOUL_QUESTION, "extra": "field"},
        {**NOUL_QUESTION, "criteria": None},
        {**NOUL_QUESTION, "criteria": {"yes": "True", "no": "False"}},
        {**NOUL_QUESTION, "criteria": {"true": "Yes"}},
        {**QUESTIONS["decision"], "criteria": {}},
        {**QUESTIONS["decision"], "criteria": ["supported", "unknown"]},
        {**QUESTIONS["decision"], "criteria": {"bad": True}},
        {**QUESTIONS["decision"], "criteria": {str(index): None for index in range(256)}},
        {**SCORE_QUESTION, "criteria": ["Only"]},
        {**SCORE_QUESTION, "criteria": ["Level"] * 11},
        {**SCORE_QUESTION, "criteria": {"0": "Low", "1": "High"}},
        {**SCORE_QUESTION, "criteria": [None, "High"]},
        {**SCORE_QUESTION, "criteria": ["Low", {"bad": float("nan")}]},
    ],
)
@pytest.mark.parametrize("direct", [False, True])
def test_question_contract_rejects_malformed_input_before_http(question: Any, direct: bool) -> None:
    seen = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("invalid questions must not reach HTTP")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            payload = {"state": {}, "questions": {"q": question}}
            if direct:
                await call_typesafe(client, SecretStr("test-secret"), payload)
            else:
                adapter = SystemOneAdapter("typesafe", SecretStr("test-secret"), client=client)
                request = replace(
                    _request(adapter.model), messages=(Message("user", json.dumps(payload)),)
                )
                await adapter.acomplete(request)

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert seen == []


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


def test_explicit_tolerances_relax_evaluation_parsing_without_changing_runtime_default() -> None:
    from core.llm.adapters.typesafe import (
        STRICT_PROBABILITY_TOLERANCE,
        parse_choice_answers,
        parse_systemone_answers,
    )

    questions = {
        "verdict": {"type": "choice", "instructions": "Pick one.", "criteria": {"a": "A", "b": "B"}}
    }
    rounded = json.dumps(
        {
            "verdict": {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": 0.6, "b": 0.39},
                "confidence": 0.2,
            }
        }
    )
    assert STRICT_PROBABILITY_TOLERANCE == 1e-5
    with pytest.raises(ValueError, match="distribution"):
        parse_choice_answers(rounded, questions)
    assert parse_choice_answers(rounded, questions, sum_tolerance=0.025)["verdict"]["choice"] == "a"
    score_questions = {
        "s": {"type": "score", "instructions": "Rate.", "criteria": ["low", "mid", "high"]}
    }
    shifted = json.dumps(
        {
            "s": {
                "type": "score",
                "score": 1.02,
                "legend": {"0": "low", "1": "mid", "2": "high"},
                "probabilities": {"0": 0.2, "1": 0.6, "2": 0.2},
                "confidence": 0.3,
            }
        }
    )
    with pytest.raises(ValueError, match="score does not match"):
        parse_systemone_answers(shifted, score_questions)
    assert (
        parse_systemone_answers(shifted, score_questions, score_tolerance=0.03)["s"]["score"]
        == 1.02
    )
    for bad in (0, -0.01, 0.051, float("nan"), True):
        with pytest.raises(ValueError, match="tolerance"):
            parse_systemone_answers(shifted, score_questions, score_tolerance=bad)
