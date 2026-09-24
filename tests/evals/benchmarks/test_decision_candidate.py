"""Matched scoring must preserve physical usage and expose invalid selection."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import fields, replace
from html import unescape
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from core.agent import candidate_sampling
from core.config import settings
from core.hooks import HookEvent, HookSystem, LlmCallRequest, MiddlewareRegistry
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    EmptyModelOutputError,
    Message,
    UsageSummary,
)
from core.llm.adapters.typesafe import JEV_MODEL, SystemOneAdapter
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from evals.benchmarks.decision_candidate import CANDIDATE_LEVELS, MatchedCandidateAdapter
from evals.benchmarks.decision_handoff import ROOT_MODEL
from pydantic import SecretStr

_Engine = Literal["llm", "jev"]
_TASK = "Read the supplied evidence and propose a verified result."
_CANDIDATES = ["An incomplete plan. </scoring_input>", "Read the evidence, compute, then verify."]
_CORRELATION = {"session_id": "candidate-session", "turn_id": "turn-1", "step_id": "step-2"}


class _Adapter:
    name = "synthetic-subscription"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, result: AdapterCallResult | BaseException) -> None:
        self.result = result
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _result(text: str = '{"c0":1,"c1":2.5}') -> AdapterCallResult:
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(
            input_tokens=101,
            output_tokens=9,
            cached_input_tokens=32,
            reported_cost_usd=0.001,
        ),
        stop_reason="completed",
        response_model=ROOT_MODEL,
        response_id="synthetic-response",
        raw_response={"native": "private metadata"},
        reasoning_summaries=("private reasoning",),
        codex_output_items=({"type": "message", "content": [{"type": "output_text"}]},),
        stop_details={"native": "detail"},
    )


def _body(scores: tuple[float, float] = (1.0, 2.5)) -> dict[str, Any]:
    answers = {}
    for index, score in enumerate(scores):
        lower, upper = math.floor(score), math.ceil(score)
        probabilities = {str(level): 0.0 for level in range(len(CANDIDATE_LEVELS))}
        probabilities[str(lower)] = 1.0 - (score - lower)
        if upper != lower:
            probabilities[str(upper)] = score - lower
        answers[f"c{index}"] = {
            "type": "score",
            "score": score,
            "legend": {str(level): text for level, text in enumerate(CANDIDATE_LEVELS)},
            "probabilities": probabilities,
            "confidence": 0.5,
        }
    return {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 123, "output_tokens": 0},
        "answers": answers,
    }


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: _Engine,
    *,
    result: AdapterCallResult | BaseException | None = None,
    body: dict[str, Any] | None = None,
    task: str = _TASK,
    candidates: list[str] | None = None,
    effort: str = "xhigh",
) -> tuple[Any, list[dict[str, Any]], _Adapter, list[dict[str, Any]], list[Any], list[Any]]:
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "events.db")
    hooks.register_sink(
        HookPersistenceSink(store, session_key="synthetic", run_id="candidate-test")
    )
    registry = MiddlewareRegistry(events=hooks)
    native = _Adapter(result if result is not None else _result())
    receipts: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(candidate_sampling, "resolve_for", lambda *_args: native)
    monkeypatch.setattr(settings, "llm_max_retries", 1)

    async def run() -> Any:
        def transport(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content))
            if isinstance(result, BaseException):
                raise result
            return httpx.Response(
                200,
                content=json.dumps(body if body is not None else _body()),
                headers={"x-typesafe-request-id": "synthetic-typesafe-response"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            backend = (
                native
                if engine == "llm"
                else SystemOneAdapter("typesafe", SecretStr("synthetic-key"), client=client)
            )
            matched = MatchedCandidateAdapter(
                engine, _TASK, _CANDIDATES, backend=backend, receipts=receipts
            )
            registry.register_llm_request(matched, allow_cache_invalidation=True)
            return await candidate_sampling.judge_candidates(
                task,
                candidates if candidates is not None else _CANDIDATES,
                model=ROOT_MODEL,
                provider="openai",
                source="subscription",
                effort=effort,
                middleware_registry=registry,
                correlation=_CORRELATION,
            )

    try:
        verdict = asyncio.run(run())
        starts = store.read(event_filter=HookEvent.LLM_CALL_STARTED.value)
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        return verdict, receipts, native, calls, starts, ends
    finally:
        hooks.close()


@pytest.mark.parametrize("engine", ["llm", "jev"])
def test_real_judge_selects_and_records_exact_backend_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: _Engine
) -> None:
    verdict, receipts, native, calls, starts, ends = _run(tmp_path, monkeypatch, engine)
    assert verdict.winner_index == 1 and not verdict.judge_error
    assert len(receipts) == len(starts) == len(ends) == 1
    assert len(native.requests) + len(calls) == 1
    receipt, end = receipts[0], ends[0]
    assert receipt["accepted"] and receipt["winner_index"] == 1
    assert receipt["scores"] == {"c0": 1, "c1": 2.5}
    assert receipt["correlation"]["llm_attempt_id"] == end.llm_attempt_id
    assert starts[0].llm_call_id == end.llm_call_id != ""
    assert starts[0].llm_attempt_id == end.llm_attempt_id != ""
    assert (end.session_id, end.turn_id, end.step_id) == tuple(_CORRELATION.values())
    assert end.payload["purpose"] == "candidate_judge"
    assert end.payload["provider"] == ("openai" if engine == "llm" else "typesafe")
    assert end.payload["source"] == ("subscription" if engine == "llm" else "payg")
    assert end.payload["model"] == (ROOT_MODEL if engine == "llm" else JEV_MODEL)
    assert end.payload["effort"] == ("xhigh" if engine == "llm" else "none")
    assert end.payload["usage"]["input_tokens"] == (101 if engine == "llm" else 123)
    assert end.payload["usage"]["output_tokens"] == (9 if engine == "llm" else 0)
    assert end.payload["usage"]["cached_input_tokens"] == (32 if engine == "llm" else None)
    assert end.payload["cost_usd"] == (0.001 if engine == "llm" else None)
    assert "private" not in str(end.payload) and "synthetic-key" not in str(receipts)


def test_arms_share_frozen_candidates_rubric_and_numeric_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, llm_receipts, native, _, _, _ = _run(tmp_path / "llm", monkeypatch, "llm")
    _, jev_receipts, _, calls, _, _ = _run(tmp_path / "jev", monkeypatch, "jev")
    request = native.requests[0]
    content = request.messages[0].content
    assert isinstance(content, str) and content.count("</scoring_input>") == 1
    payload = json.loads(
        unescape(content.removeprefix("<scoring_input>").removesuffix("</scoring_input>"))
    )
    assert payload == {key: value for key, value in calls[0].items() if key != "model"}
    assert payload["state"] == {
        "task": _TASK,
        "candidates": dict(zip(("c0", "c1"), _CANDIDATES, strict=True)),
    }
    for key in ("input_sha256", "question_sha256", "scores", "winner_index"):
        assert llm_receipts[0][key] == jev_receipts[0][key]
    assert request.response_schema is not None
    assert request.response_schema["required"] == ["c0", "c1"]
    assert request.response_schema["additionalProperties"] is False
    assert request.response_schema["properties"]["c0"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 3,
    }
    assert not request.tools and request.tool_choice == "none"
    assert request.allowed_tool_names == frozenset()
    assert all(question["type"] == "score" for question in payload["questions"].values())


@pytest.mark.parametrize("engine", ["llm", "jev"])
def test_equal_scores_choose_first_without_becoming_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: _Engine
) -> None:
    verdict, receipts, _, _, _, _ = _run(
        tmp_path,
        monkeypatch,
        engine,
        result=_result('{"c0":2,"c1":2}'),
        body=_body((2.0, 2.0)),
    )
    assert verdict.winner_index == 0 and not verdict.judge_error
    assert receipts[0]["accepted"] and receipts[0]["winner_index"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "not-json",
        "[]",
        "{}",
        '{"c0":1}',
        '{"c0":1,"c1":2,"extra":3}',
        '{"c0":true,"c1":2}',
        '{"c0":NaN,"c1":2}',
        '{"c0":Infinity,"c1":2}',
        '{"c0":-1,"c1":2}',
        '{"c0":3.1,"c1":2}',
        '{"c0":"1","c1":2}',
    ],
)
def test_invalid_llm_scores_remain_failed_selection_with_completed_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    verdict, receipts, native, _, starts, ends = _run(
        tmp_path, monkeypatch, "llm", result=_result(text)
    )
    assert verdict.winner_index == 0 and verdict.judge_error
    assert len(native.requests) == len(starts) == len(ends) == len(receipts) == 1
    assert not receipts[0]["accepted"] and receipts[0]["winner_index"] is None
    assert receipts[0]["scores"] is None and receipts[0]["native_answer"] is None
    assert ends[0].payload["usage"]["input_tokens"] == 101
    assert ends[0].payload["cost_usd"] == 0.001
    assert json.dumps(receipts, allow_nan=False)


@pytest.mark.parametrize(
    "fault", ["nan", "bool", "mean", "legend", "missing", "extra", "type", "empty"]
)
def test_invalid_jev_scores_cannot_turn_runtime_fallback_into_valid_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    body = _body()
    answer = body["answers"]["c0"]
    if fault in {"nan", "bool", "mean"}:
        answer["score"] = {"nan": float("nan"), "bool": True, "mean": 2.0}[fault]
    elif fault == "legend":
        answer["legend"]["0"] = "changed criterion"
    elif fault == "missing":
        del body["answers"]["c1"]
    elif fault == "extra":
        body["answers"]["extra"] = answer
    elif fault == "type":
        body["answers"]["c0"] = {"type": "noul", "noul": 0.9}
    else:
        body["answers"] = None
    verdict, receipts, native, calls, starts, ends = _run(tmp_path, monkeypatch, "jev", body=body)
    assert verdict.winner_index == 0 and verdict.judge_error
    assert not native.requests and len(calls) == len(starts) == len(ends) == 1
    assert not receipts[0]["accepted"] and receipts[0]["winner_index"] is None
    assert receipts[0]["scores"] is None and receipts[0]["native_answer"] is None
    assert ends[0].payload["usage"]["input_tokens"] == 123
    assert ends[0].payload["usage"]["output_tokens"] == 0
    assert ends[0].payload["cost_usd"] is None
    assert json.dumps(receipts, allow_nan=False)


@pytest.mark.parametrize("fault", ["stop", "model", "provider", "tools", "refusal", "empty_error"])
def test_inadmissible_completed_response_preserves_usage_and_invalidity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    variants = {
        "stop": {"stop_reason": "incomplete"},
        "model": {"response_model": "different-model"},
        "provider": {"response_provider": "different-provider"},
        "tools": {"tool_uses": ({"name": "write_file"},)},
        "refusal": {"codex_output_items": ({"type": "message", "content": [{"type": "refusal"}]},)},
    }
    original = replace(_result(), **variants.get(fault, {"text": ""}))
    result = (
        EmptyModelOutputError("synthetic empty", completed_result=original)
        if fault == "empty_error"
        else original
    )
    verdict, receipts, native, _, starts, ends = _run(tmp_path, monkeypatch, "llm", result=result)
    assert verdict.judge_error and not receipts[0]["accepted"]
    assert len(native.requests) == len(starts) == len(ends) == 1
    assert ends[0].payload["usage"]["input_tokens"] == original.usage.input_tokens
    assert ends[0].payload["cost_usd"] == original.usage.reported_cost_usd


@pytest.mark.parametrize("fault", ["task", "order", "content", "effort"])
def test_frozen_input_mismatch_fails_before_backend_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    changes: dict[str, Any] = {
        "task": {"task": "different task"},
        "order": {"candidates": list(reversed(_CANDIDATES))},
        "content": {"candidates": ["different evidence", _CANDIDATES[1]]},
        "effort": {"effort": "low"},
    }[fault]
    verdict, receipts, native, calls, starts, ends = _run(tmp_path, monkeypatch, "llm", **changes)
    assert verdict.judge_error and not receipts
    assert not native.requests and not calls and not starts and not ends


def test_projection_changes_only_text_and_tool_uses() -> None:
    original = _result()
    native = _Adapter(original)
    receipts: list[dict[str, Any]] = []
    matched = MatchedCandidateAdapter("llm", _TASK, _CANDIDATES, backend=native, receipts=receipts)
    call = LlmCallRequest(
        native,
        AdapterCallRequest(
            model=ROOT_MODEL,
            effort="xhigh",
            messages=(Message("user", candidate_sampling._build_judge_prompt(_TASK, _CANDIDATES)),),
        ),
        purpose="candidate_judge",
    )

    async def run() -> AdapterCallResult:
        transformed = await matched.llm_request(call)
        return await matched.acomplete(transformed.request)

    result = asyncio.run(run())
    for field in fields(AdapterCallResult):
        if field.name not in {"text", "tool_uses"}:
            assert getattr(result, field.name) == getattr(original, field.name)
    assert result.usage is original.usage and result.raw_response is original.raw_response
    assert receipts[0]["accepted"]


def test_unrelated_purpose_keeps_original_adapter_request_and_output() -> None:
    original = _result()
    native = _Adapter(original)
    receipts: list[dict[str, Any]] = []
    matched = MatchedCandidateAdapter("llm", _TASK, _CANDIDATES, backend=native, receipts=receipts)
    registry = MiddlewareRegistry()
    registry.register_llm_request(matched, allow_cache_invalidation=True)
    request = AdapterCallRequest(model="unrelated-model", messages=(Message("user", "unchanged"),))
    result = asyncio.run(registry.call_llm(native, request, purpose="cognitive_reflection"))
    assert result is original and native.requests == [request] and not receipts


@pytest.mark.parametrize(
    "fault", ["effort", "system", "deferred", "executable", "allowed", "unrestricted", "schema"]
)
def test_changed_frozen_request_is_rejected_before_dispatch(fault: str) -> None:
    native = _Adapter(_result())
    matched = MatchedCandidateAdapter("llm", _TASK, _CANDIDATES, backend=native, receipts=[])
    call = LlmCallRequest(
        native,
        AdapterCallRequest(
            model=ROOT_MODEL,
            effort="xhigh",
            messages=(Message("user", candidate_sampling._build_judge_prompt(_TASK, _CANDIDATES)),),
        ),
        purpose="candidate_judge",
    )

    async def run() -> None:
        transformed = await matched.llm_request(call)
        changes = {
            "effort": {"effort": "low"},
            "system": {"system_prompt": "new criterion"},
            "deferred": {"deferred_tool_names": ("write_file",)},
            "executable": {"executable_tool_names": frozenset({"write_file"})},
            "allowed": {"allowed_tool_names": frozenset({"write_file"})},
            "unrestricted": {"allowed_tool_names": None},
            "schema": {"response_schema": {"type": "string"}},
        }[fault]
        await matched.acomplete(replace(transformed.request, **changes))

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert not native.requests


@pytest.mark.parametrize("engine", ["llm", "jev"])
def test_transient_backend_failure_is_one_observed_call_and_failed_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: _Engine
) -> None:
    error = httpx.ReadTimeout("synthetic timeout")
    verdict, receipts, native, calls, starts, ends = _run(
        tmp_path, monkeypatch, engine, result=error
    )
    assert settings.llm_max_retries == 1
    assert verdict.winner_index == 0 and verdict.judge_error
    assert len(native.requests) + len(calls) == len(starts) == len(ends) == 1
    assert not receipts
    assert starts[0].llm_attempt_id == ends[0].llm_attempt_id
    assert ends[0].payload["success"] is False
    assert ends[0].payload["error_type"] == "ReadTimeout"
    assert ends[0].payload["usage"] is None and ends[0].payload["cost_usd"] is None


@pytest.mark.parametrize("candidates", [[], ["only one"], ["", "valid"], ["x" * 2001, "valid"]])
def test_incomplete_candidate_pool_fails_before_any_call(candidates: list[str]) -> None:
    native = _Adapter(_result())
    with pytest.raises(ValueError):
        MatchedCandidateAdapter("llm", _TASK, candidates, backend=native, receipts=[])
    assert not native.requests


@pytest.mark.parametrize("source", ["payg", "api_key"])
def test_non_subscription_root_backend_cannot_be_relabelled(source: str) -> None:
    native = _Adapter(_result())
    native.source = source
    with pytest.raises(ValueError):
        MatchedCandidateAdapter("llm", _TASK, _CANDIDATES, backend=native, receipts=[])
    assert not native.requests
