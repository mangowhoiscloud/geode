"""Auxiliary response interpretation must not erase physical dispatch accounting."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from core.agent import candidate_sampling
from core.agent.cognitive_state import CognitiveState
from core.agent.loop import _reflection
from core.hooks import HookEvent, HookSystem, LlmCallRequest, MiddlewareRegistry
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    EmptyModelOutputError,
    UsageSummary,
)
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink

_CORRELATION = {"session_id": "synthetic-session", "turn_id": "turn-1", "step_id": "step-1"}


class _Adapter:
    name = "synthetic"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.FIXED

    def __init__(self, outcome: AdapterCallResult | BaseException) -> None:
        self.outcome = outcome
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _result(purpose: str, outcome: str, cache: int | None = 0) -> AdapterCallResult:
    name = "record_reflection" if purpose == "cognitive_reflection" else "select_candidate"
    payload: Any = (
        {"hypotheses": ["synthetic belief"], "confidence": 0.5}
        if purpose == "cognitive_reflection"
        else {"winner_index": 1, "reason": "synthetic preference"}
    )
    if outcome == "malformed":
        payload = "not-json"
    return AdapterCallResult(
        text="private returned content",
        usage=UsageSummary(
            input_tokens=100,
            output_tokens=0,
            output_tokens_present=True,
            cached_input_tokens=cache or 0,
            cached_input_tokens_present=cache is not None,
            reasoning_tokens=0,
            reasoning_tokens_present=True,
            reported_cost_usd=0,
        ),
        stop_reason="end_turn",
        tool_uses=() if outcome == "declined" else ({"name": name, "input": payload},),
        raw_response={"private": "raw provider payload"},
    )


def _registry(tmp_path: Path) -> tuple[MiddlewareRegistry, HookSystem, HookEventStore]:
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "synthetic-events.db")
    hooks.register_sink(HookPersistenceSink(store, session_key="synthetic", run_id="aux-test"))
    return MiddlewareRegistry(events=hooks), hooks, store


async def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    purpose: str,
    adapter: _Adapter,
    registry: MiddlewareRegistry,
) -> Any:
    module = _reflection if purpose == "cognitive_reflection" else candidate_sampling

    async def dispatch(models: list[str], callback: Any) -> tuple[Any, str]:
        return await callback(models[0]), models[0]

    monkeypatch.setattr(module, "call_with_failover", dispatch)
    monkeypatch.setattr(module, "resolve_for", lambda *_args: adapter)
    if purpose == "cognitive_reflection":
        state = CognitiveState(hypotheses=["previous belief"])
        await _reflection.reflect_async(
            state,
            [{"content": "private tool content"}],
            model="gpt-5.6-sol",
            max_tokens=333,
            provider="openai",
            source="subscription",
            middleware_registry=registry,
            correlation=_CORRELATION,
        )
        return state
    return await candidate_sampling.judge_candidates(
        "private task",
        ["private candidate 0", "private candidate 1"],
        model="gpt-5.6-sol",
        max_tokens=333,
        provider="openai",
        source="subscription",
        middleware_registry=registry,
        correlation=_CORRELATION,
    )


@pytest.mark.parametrize("purpose", ["cognitive_reflection", "candidate_judge"])
@pytest.mark.parametrize("outcome", ["success", "declined", "malformed"])
@pytest.mark.parametrize("cache", [None, 0, 40])
def test_completed_auxiliary_dispatch_survives_interpretation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purpose: str, outcome: str, cache: int | None
) -> None:
    registry, hooks, store = _registry(tmp_path)
    adapter = _Adapter(_result(purpose, outcome, cache))
    try:
        result = asyncio.run(_invoke(monkeypatch, purpose, adapter, registry))
        starts = store.read(event_filter=HookEvent.LLM_CALL_STARTED.value)
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(starts) == len(ends) == len(adapter.requests) == 1
        start, end = starts[0], ends[0]
        assert start.llm_call_id == end.llm_call_id != ""
        assert start.llm_attempt_id == end.llm_attempt_id != ""
        assert (end.session_id, end.turn_id, end.step_id) == tuple(_CORRELATION.values())
        assert end.payload["success"] is True
        assert end.payload["purpose"] == purpose
        assert end.payload["effort"] == adapter.requests[0].effort == "medium"
        assert end.payload["source"] == "subscription"
        assert adapter.requests[0].thinking_budget == 0
        assert adapter.requests[0].max_tokens == 333
        assert adapter.requests[0].tool_choice == "auto"
        assert end.payload["usage"] == {
            "input_tokens": 100,
            "output_tokens": 0,
            "cached_input_tokens": cache,
            "reasoning_tokens": 0,
            "cache_write_tokens": None,
        }
        assert end.payload["cost_usd"] == 0
        assert "private" not in str(end.payload)
        if purpose == "cognitive_reflection":
            assert result.hypotheses == (
                ["synthetic belief"] if outcome == "success" else ["previous belief"]
            )
        else:
            assert result.winner_index == (1 if outcome == "success" else 0)
            assert bool(result.judge_error) is (outcome != "success")
    finally:
        hooks.close()


@pytest.mark.parametrize("purpose", ["cognitive_reflection", "candidate_judge"])
@pytest.mark.parametrize("failure", ["error", "cancel", "empty"])
def test_auxiliary_failed_dispatch_has_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purpose: str, failure: str
) -> None:
    registry, hooks, store = _registry(tmp_path)
    error = (
        asyncio.CancelledError("private cancellation")
        if failure == "cancel"
        else EmptyModelOutputError("private empty", completed_result=_result(purpose, "declined"))
        if failure == "empty"
        else RuntimeError("private exception")
    )
    adapter = _Adapter(error)
    try:
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError) as caught:
                asyncio.run(_invoke(monkeypatch, purpose, adapter, registry))
            assert caught.value is error
        else:
            asyncio.run(_invoke(monkeypatch, purpose, adapter, registry))
        starts = store.read(event_filter=HookEvent.LLM_CALL_STARTED.value)
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(starts) == len(ends) == len(adapter.requests) == 1
        assert starts[0].llm_attempt_id == ends[0].llm_attempt_id
        assert ends[0].payload["success"] is False
        assert ends[0].payload["error_type"] == type(error).__name__
        if failure == "empty":
            assert ends[0].payload["usage"]["input_tokens"] == 100
        else:
            assert ends[0].payload["usage"] is None
        assert "private" not in str(ends[0].payload)
    finally:
        hooks.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_dispatch_exception_survives_terminal_observer_cancellation(
    tmp_path: Path, cancel: bool
) -> None:
    registry, hooks, store = _registry(tmp_path)
    error = asyncio.CancelledError("private adapter cancel") if cancel else RuntimeError("private")

    async def observer(_event: HookEvent, _data: dict[str, Any]) -> None:
        raise asyncio.CancelledError("private observer cancellation")

    hooks.register(HookEvent.LLM_CALL_ENDED, observer, name="synthetic-cancel")
    try:
        with pytest.raises(type(error)) as caught:
            asyncio.run(
                registry.call_llm(
                    _Adapter(error),
                    AdapterCallRequest(model="synthetic", messages=()),
                    correlation=_CORRELATION,
                    purpose="candidate_judge",
                )
            )
        assert caught.value is error
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(ends) == 1
        assert ends[0].payload["error_type"] == type(error).__name__
        assert ends[0].payload["success"] is False
        assert "private" not in str(ends[0].payload)
    finally:
        hooks.close()


@pytest.mark.parametrize("mode", ["short_circuit", "post_cancel", "transform"])
def test_middleware_observation_is_at_actual_terminal(tmp_path: Path, mode: str) -> None:
    registry, hooks, store = _registry(tmp_path)
    completed = _result("candidate_judge", "success")
    adapter = _Adapter(completed)
    cancellation = asyncio.CancelledError("private middleware cancellation")

    class Middleware:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            return request.with_request(
                replace(request.request, model="effective-model", effort="low")
            )

        async def llm_execution(self, request: LlmCallRequest, next_call: Any) -> AdapterCallResult:
            if mode == "short_circuit":
                return completed
            await next_call(request)
            raise cancellation

    if mode == "transform":
        registry.register_llm_request(Middleware())
    else:
        registry.register_llm_execution(Middleware())
    try:
        call = registry.call_llm(
            adapter,
            AdapterCallRequest(model="original", messages=()),
            correlation=_CORRELATION,
            purpose="candidate_judge",
        )
        if mode == "post_cancel":
            with pytest.raises(asyncio.CancelledError) as caught:
                asyncio.run(call)
            assert caught.value is cancellation
        else:
            assert asyncio.run(call) is completed
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(ends) == len(adapter.requests) == (0 if mode == "short_circuit" else 1)
        if ends:
            assert ends[0].payload["success"] is True
            if mode == "transform":
                assert ends[0].payload["model"] == "effective-model"
                assert ends[0].payload["effort"] == "low"
    finally:
        hooks.close()


def test_auxiliary_dispatch_ids_are_fresh_and_single_candidate_is_unobserved(
    tmp_path: Path,
) -> None:
    registry, hooks, store = _registry(tmp_path)
    completed = _result("candidate_judge", "success")
    adapter = _Adapter(replace(completed, usage=replace(completed.usage, reported_cost_usd=None)))
    try:
        for _ in range(2):
            asyncio.run(
                registry.call_llm(
                    adapter,
                    AdapterCallRequest(model="synthetic", messages=()),
                    correlation=_CORRELATION,
                    purpose="candidate_judge",
                )
            )
        asyncio.run(
            candidate_sampling.judge_candidates(
                "private task",
                ["only one"],
                model="synthetic",
                middleware_registry=registry,
                correlation=_CORRELATION,
            )
        )
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(ends) == len(adapter.requests) == 2
        assert len({row.llm_call_id for row in ends}) == 2
        assert len({row.llm_attempt_id for row in ends}) == 2
        assert all(row.payload["cost_usd"] is None for row in ends)
    finally:
        hooks.close()
