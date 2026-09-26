"""The decision tool hands source-bound data back through the real observer."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import httpx
import pytest
from core.hooks.system import HookEvent, HookSystem
from core.llm.adapters._openai_common import translate_codex_response
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from core.tools.base import ToolContext
from evals.benchmarks import decision_handoff
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL, DecisionHandoffTool
from pydantic import SecretStr

_SOURCE = "주문 A-104 status only, not cancellation. B-209 is unrelated."


class _Adapter:
    name = "mock-subscription"
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


def _result(text: str = '{"intent":"status_only","target":"order_0"}') -> AdapterCallResult:
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(input_tokens=300, output_tokens=0, output_tokens_present=True),
        stop_reason="completed",
        response_model=ROOT_MODEL,
        reasoning_summaries=("private reasoning",),
    )


def _body() -> dict[str, Any]:
    return {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 300, "output_tokens": 0},
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "status_only",
                "probabilities": {"status_only": 0.7, "cancel": 0.1, "refund": 0.1, "other": 0.1},
                "confidence": 0.5,
            },
            "target": {
                "type": "choice",
                "choice": "order_0",
                "probabilities": {"order_0": 0.5, "order_1": 0.3, "none": 0.2},
                "confidence": 0.2,
            },
        },
    }


def _context(hooks: HookSystem) -> ToolContext:
    return ToolContext(
        hooks=hooks,
        session_id="synthetic-session",
        turn_id="turn-1",
        step_id="step-1",
        tool_call_id="decision-tool-1",
        provider="openai",
        source="subscription",
        model=ROOT_MODEL,
        effort="xhigh",
    )


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize(
    "source,order_ids",
    [
        ("주문 E-536이 아니라 F-642의 상태를 알려줘.", ("E-536", "F-642")),
        ("주문E-536은 E-536의 상태, F-642를 확인해.", ("E-536", "F-642")),
        ("E-536, (F-642) / E-536.", ("E-536", "F-642")),
        ("xE-536 XE-536 _E-536 0E-536 E-536x E-536Z E-536_ E-5367", ()),
        ("E-536 F-6420 G-87 AA-104 a-104", ("E-536",)),
        ("Q-731８ Q-731٨ Q-７３１８", ()),
        ("Q-７３１의 상태를 알려줘.", ("Q-７３１",)),
    ],
)
def test_candidate_boundaries_preserve_korean_particles_and_first_source_span(
    arm: Literal["a", "b"], source: str, order_ids: tuple[str, ...]
) -> None:
    mentions = {
        f"order_{index}": {
            "order_id": order_id,
            "start": source.index(order_id),
            "end": source.index(order_id) + len(order_id),
        }
        for index, order_id in enumerate(order_ids)
    }
    target = "order_0" if mentions else "none"
    adapter = _Adapter(_result(json.dumps({"intent": "status_only", "target": target})))
    body = _body()
    body["answers"]["target"].update(
        choice=target,
        probabilities={key: float(key == target) for key in (*mentions, "none")},
    )
    payloads: list[dict[str, Any]] = []
    hooks = HookSystem()

    async def run() -> dict[str, Any]:
        def transport(request: httpx.Request) -> httpx.Response:
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            tool = (
                DecisionHandoffTool(source, arm, adapter=adapter)
                if arm == "a"
                else DecisionHandoffTool(
                    source, arm, client=client, api_key=SecretStr("synthetic-test-key")
                )
            )
            return await tool.aexecute(_tool_context=_context(hooks))

    try:
        output = asyncio.run(run())
        assert output["result"]["target"] == mentions.get(target)
        if arm == "a":
            request = adapter.requests[0]
            assert request.response_schema is not None
            assert request.response_schema["properties"]["target"]["enum"] == [*mentions, "none"]
            content = request.messages[0].content
            assert isinstance(content, str)
            payload = json.loads(
                unescape(content.removeprefix("<decision_input>").removesuffix("</decision_input>"))
            )
        else:
            payload = payloads[0]
        assert payload["state"]["order_mentions"] == mentions
        assert payload["questions"]["target"]["criteria"] == {
            **mentions,
            "none": "No listed order is targeted, or the target is ambiguous.",
        }
    finally:
        hooks.close()


@pytest.mark.parametrize("arm", ["a", "b"])
def test_handler_returns_source_span_and_persists_actual_call(
    arm: Literal["a", "b"], tmp_path: Path
) -> None:
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "events.db")
    hooks.register_sink(HookPersistenceSink(store, session_key="decision", run_id="test"))
    adapter = _Adapter(_result())
    calls: list[dict[str, Any]] = []

    async def run() -> dict[str, Any]:
        def transport(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content))
            assert request.headers["authorization"] == "Bearer synthetic-test-key"
            return httpx.Response(
                200, json=_body(), headers={"x-typesafe-request-id": "synthetic-request-1"}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            tool = (
                DecisionHandoffTool(_SOURCE, arm, adapter=adapter)
                if arm == "a"
                else DecisionHandoffTool(
                    _SOURCE, arm, client=client, api_key=SecretStr("synthetic-test-key")
                )
            )
            assert tool.parameters == {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }
            return await tool.aexecute(_tool_context=_context(hooks))

    try:
        result = asyncio.run(run())["result"]
        assert result["intent"] == "status_only"
        assert result["target"] == {"order_id": "A-104", "start": 3, "end": 8}
        assert _SOURCE[result["target"]["start"] : result["target"]["end"]] == "A-104"
        assert result["source_sha256"] == hashlib.sha256(_SOURCE.encode()).hexdigest()
        assert result["primitives"] == (_body()["answers"] if arm == "b" else None)
        if arm == "a":
            assert len(adapter.requests) == 1 and not calls
            request = adapter.requests[0]
            assert request.model == ROOT_MODEL and request.effort == "xhigh"
            assert request.response_schema is not None
            assert request.response_schema["properties"]["target"]["enum"] == [
                "order_0",
                "order_1",
                "none",
            ]
            content = request.messages[0].content
            assert isinstance(content, str)
            assert content.startswith("<decision_input>") and content.endswith("</decision_input>")
            payload = json.loads(
                unescape(content.removeprefix("<decision_input>").removesuffix("</decision_input>"))
            )
        else:
            assert len(calls) == 1 and not adapter.requests
            payload = calls[0]
        assert payload["state"]["request"] == _SOURCE
        assert set(payload["questions"]) == {"intent", "target"}
        starts = store.read(event_filter=HookEvent.LLM_CALL_STARTED.value)
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(starts) == len(ends) == 1
        start, end = starts[0], ends[0]
        assert start.llm_call_id == end.llm_call_id
        assert start.llm_attempt_id == end.llm_attempt_id
        assert end.session_id == "synthetic-session"
        assert end.turn_id == "turn-1" and end.tool_call_id == "decision-tool-1"
        assert end.payload["purpose"] == "structured_decision"
        assert end.payload["source"] == ("subscription" if arm == "a" else "payg")
        assert end.payload["usage"]["input_tokens"] == 300
        assert end.payload["usage"]["output_tokens"] == 0
        assert end.payload["usage"]["cached_input_tokens"] is None
        assert end.payload["cost_usd"] is None
        if arm == "b":
            assert end.payload["response_id"] == "synthetic-request-1"
        assert all(
            text not in repr(end.payload) + repr(result)
            for text in (_SOURCE, "synthetic-test-key", "private reasoning")
        )
    finally:
        hooks.close()


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("fault", ["model", "target", "shape"])
def test_rejected_decision_keeps_completed_usage(arm: Literal["a", "b"], fault: str) -> None:
    observed: list[dict[str, Any]] = []
    hooks = HookSystem()
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))
    result, body = _result(), _body()
    if fault == "model":
        result = replace(result, response_model="changed-model")
        body["model"] = "changed-model"
    elif fault == "target":
        result = replace(result, text='{"intent":"status_only","target":"A-999"}')
        body["answers"]["target"]["choice"] = "A-999"
    else:
        result = replace(result, text="private malformed reply")
        body["answers"] = "private malformed reply"

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            tool = (
                DecisionHandoffTool(_SOURCE, arm, adapter=_Adapter(result))
                if arm == "a"
                else DecisionHandoffTool(
                    _SOURCE, arm, client=client, api_key=SecretStr("synthetic-test-key")
                )
            )
            return await tool.aexecute(_tool_context=_context(hooks))

    try:
        output = asyncio.run(run())
        assert "error" in output and "result" not in output
        assert "private malformed reply" not in repr(output)
        assert len(observed) == 1
        assert observed[0]["usage"]["input_tokens"] == 300
        assert observed[0]["usage"]["output_tokens"] == 0
        assert observed[0]["error"] is None  # The dispatch completed; its interpretation failed.
    finally:
        hooks.close()


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("fault", ["missing", "outside"])
def test_inbox_rejects_partial_or_out_of_candidate_helper_results_without_losing_usage(
    arm: Literal["a", "b"], fault: str
) -> None:
    values = {"ticket_intent": "status_only", "ticket_target": "order_0"}
    body = _body()
    body["answers"] = {f"ticket_{key}": value for key, value in body["answers"].items()}
    if fault == "missing":
        del values["ticket_target"]
        del body["answers"]["ticket_target"]
    else:
        values["ticket_target"] = "order_missing"
        body["answers"]["ticket_target"]["choice"] = "order_missing"
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            tool = DecisionHandoffTool(
                _SOURCE,
                arm,
                requests={"ticket": _SOURCE},
                adapter=_Adapter(_result(json.dumps(values))) if arm == "a" else None,
                client=client if arm == "b" else None,
                api_key=SecretStr("synthetic-test-key") if arm == "b" else None,
            )
            return await tool.aexecute(_tool_context=_context(hooks))

    try:
        output = asyncio.run(run())
        assert "error" in output and "result" not in output
        assert len(observed) == 1 and observed[0]["usage"]["input_tokens"] == 300
        assert observed[0]["error"] is None
    finally:
        hooks.close()


@pytest.mark.parametrize(
    "status,extra_output,accepted",
    [
        ("completed", "", True),
        ("refusal", "", False),
        ("content_filter", "", False),
        ("incomplete", "", False),
        ("failed", "", False),
        ("in_progress", "", False),
        ("end_turn", "", False),
        ("completed", "tool", False),
        ("completed", "refusal", False),
    ],
)
def test_codex_terminal_status_precedes_json_admission(
    status: str, extra_output: str, accepted: bool
) -> None:
    text = '{"intent":"status_only","target":"order_0"}'
    items: list[dict[str, Any]] = []
    if extra_output == "tool":
        items.append({"type": "function_call", "name": "unexpected_tool", "arguments": "{}"})
    elif extra_output == "refusal":
        items.append({"type": "message", "content": [{"type": "refusal", "refusal": text}]})
    result = translate_codex_response(
        SimpleNamespace(
            status=status,
            model=ROOT_MODEL,
            output_text=text,
            output=items,
            usage=SimpleNamespace(input_tokens=300, output_tokens=0),
        )
    )
    assert result.stop_reason == status
    adapter = _Adapter(result)
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))
    try:
        output = asyncio.run(
            DecisionHandoffTool(_SOURCE, "a", adapter=adapter).aexecute(
                _tool_context=_context(hooks)
            )
        )
        assert ("result" in output) is accepted
        assert ("error" in output) is not accepted
        assert len(adapter.requests) == len(observed) == 1
        assert observed[0]["usage"]["input_tokens"] == 300
        assert observed[0]["usage"]["output_tokens"] == 0
        assert observed[0]["error"] is None
    finally:
        hooks.close()


@pytest.mark.parametrize("fault", ["nan", "sum", "argmax", "keys"])
def test_native_distribution_validation_does_not_hide_consumption(fault: str) -> None:
    body = _body()
    choice = body["answers"]["intent"]
    if fault == "nan":
        choice["confidence"] = float("nan")
    elif fault == "sum":
        choice["probabilities"]["cancel"] = 0.3
    elif fault == "argmax":
        choice["choice"] = "cancel"
    else:
        del choice["probabilities"]["other"]
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(body)))
        ) as client:
            return await DecisionHandoffTool(
                _SOURCE, "b", client=client, api_key=SecretStr("synthetic-test-key")
            ).aexecute(_tool_context=_context(hooks))

    try:
        assert "error" in asyncio.run(run())
        assert len(observed) == 1 and observed[0]["usage"]["input_tokens"] == 300
    finally:
        hooks.close()


@pytest.mark.parametrize("output_tokens", [None, 0, "0", -1, True])
def test_partial_typesafe_usage_preserves_known_sibling(output_tokens: object) -> None:
    body = _body()
    body["usage"] = {"input_tokens": 300, "output_tokens": output_tokens}
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            return await DecisionHandoffTool(
                _SOURCE, "b", client=client, api_key=SecretStr("synthetic-test-key")
            ).aexecute(_tool_context=_context(hooks))

    try:
        assert "result" in asyncio.run(run())  # Semantic data and accounting coverage are distinct.
        assert observed[0]["usage"]["input_tokens"] == 300
        assert observed[0]["usage"]["output_tokens"] == (
            0 if type(output_tokens) is int and output_tokens == 0 else None
        )
    finally:
        hooks.close()


@pytest.mark.parametrize("fault", ["timeout", "cancel", "redirect"])
def test_failed_typesafe_dispatch_is_sanitized_and_not_retried(fault: str) -> None:
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))
    calls: list[httpx.Request] = []

    async def run() -> dict[str, Any]:
        def transport(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if fault == "cancel":
                raise asyncio.CancelledError("private cancellation")
            if fault == "timeout":
                raise httpx.ReadTimeout("private failure", request=request)
            return httpx.Response(302, headers={"Location": "https://other.example.test"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), follow_redirects=True
        ) as client:
            return await DecisionHandoffTool(
                _SOURCE, "b", client=client, api_key=SecretStr("synthetic-test-key")
            ).aexecute(_tool_context=_context(hooks))

    try:
        if fault == "cancel":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(run())
        else:
            output = asyncio.run(run())
            assert "error" in output and "private failure" not in repr(output)
        assert len(calls) == len(observed) == 1
        assert observed[0]["error"] in {"ReadTimeout", "CancelledError", "HTTPStatusError"}
        assert "usage" not in observed[0]
        assert "private" not in repr(observed)
    finally:
        hooks.close()


@pytest.mark.parametrize(
    "request_id,retained",
    [
        ("req_123:abc-456", "req_123:abc-456"),
        ("", None),
        ("unbounded-" + "x" * 128, None),
        ("private customer text", None),
        ("apikey_synthetic_credentials", None),
        ("req-apikey_synthetic_credentials", None),
        ("req-synthetic-test-key", None),
        ("sk-" + "x" * 24, None),
    ],
)
def test_typesafe_request_identity_is_allowlisted_even_on_malformed_body(
    request_id: str, retained: str | None
) -> None:
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    content="private malformed response",
                    headers={"x-typesafe-request-id": request_id, "set-cookie": "private cookie"},
                )
            )
        ) as client:
            return await DecisionHandoffTool(
                _SOURCE, "b", client=client, api_key=SecretStr("synthetic-test-key")
            ).aexecute(_tool_context=_context(hooks))

    try:
        output = asyncio.run(run())
        assert "error" in output
        assert len(observed) == 1
        assert observed[0].get("response_id") == retained
        assert observed[0]["usage"]["input_tokens"] is None
        assert observed[0]["usage"]["output_tokens"] is None
        assert observed[0]["cost_usd"] is None
        assert "private" not in repr(observed) + repr(output)
    finally:
        hooks.close()


@pytest.mark.parametrize("status", [401, 429, 500])
def test_typesafe_http_failure_retains_bounded_support_evidence(status: int) -> None:
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))
    calls = 0

    async def run() -> dict[str, Any]:
        def transport(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                status,
                json={"error": "private provider body"},
                headers={
                    "x-typesafe-request-id": "synthetic-failed-request",
                    "retry-after": "10",
                    "set-cookie": "private cookie",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await DecisionHandoffTool(
                _SOURCE, "b", client=client, api_key=SecretStr("synthetic-test-key")
            ).aexecute(_tool_context=_context(hooks))

    try:
        output = asyncio.run(run())
        assert "error" in output
        assert output["context"]["http_status"] == status
        assert output["context"]["response_id"] == "synthetic-failed-request"
        assert output["context"]["provider"] == "typesafe"
        assert calls == len(observed) == 1  # Retry-After is not automatic retry authority.
        assert observed[0]["error"] == "HTTPStatusError"
        assert "usage" not in observed[0]
        assert "private" not in repr(output) + repr(observed)
    finally:
        hooks.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_subscription_failure_keeps_terminal_observation(cancelled: bool) -> None:
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))
    error = (
        asyncio.CancelledError("private cancellation")
        if cancelled
        else TimeoutError("private transport failure")
    )
    adapter = _Adapter(error)
    tool = DecisionHandoffTool(_SOURCE, "a", adapter=adapter)
    try:
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(tool.aexecute(_tool_context=_context(hooks)))
        else:
            output = asyncio.run(tool.aexecute(_tool_context=_context(hooks)))
            assert "error" in output and "private" not in repr(output)
        assert len(adapter.requests) == len(observed) == 1
        assert observed[0]["error"] == type(error).__name__
        assert "usage" not in observed[0]
        assert "private" not in repr(observed)
    finally:
        hooks.close()


@pytest.mark.parametrize(
    "fault", ["source", "model", "effort", "hooks", "tool_call_id", "user_text"]
)
def test_admission_rejects_route_or_input_rewriting_before_dispatch(fault: str) -> None:
    hooks = HookSystem()
    adapter = _Adapter(_result())
    context = _context(hooks)
    arguments: dict[str, Any] = {"_tool_context": context}
    if fault == "user_text":
        arguments["request"] = "Refund B-209"
    elif fault == "tool_call_id":
        context.tool_call_id = ""
    else:
        setattr(context, fault, None if fault == "hooks" else "different")
    try:
        assert "error" in asyncio.run(
            DecisionHandoffTool(_SOURCE, "a", adapter=adapter).aexecute(**arguments)
        )
        assert adapter.requests == []
    finally:
        hooks.close()


def test_resolved_adapter_is_subscription_only_and_no_target_is_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks = HookSystem()
    adapter = _Adapter(_result('{"intent":"other","target":"none"}'))
    routes: list[tuple[str, str]] = []

    def resolve(provider: str, source: str) -> _Adapter:
        routes.append((provider, source))
        return adapter

    monkeypatch.setattr(decision_handoff, "resolve_for", resolve)
    try:
        result = asyncio.run(
            DecisionHandoffTool("Explain the policy", "a").aexecute(_tool_context=_context(hooks))
        )
        assert result["result"]["target"] is None
        assert result["result"]["intent"] == "other"
        assert routes == [("openai", "subscription")]
        adapter.source = "payg"
        assert "error" in asyncio.run(
            DecisionHandoffTool(_SOURCE, "a", adapter=adapter).aexecute(
                _tool_context=_context(hooks)
            )
        )
        assert len(adapter.requests) == 1
    finally:
        hooks.close()


# ---------------------------------------------------------------------------
# Byte regression: the E2E helper keeps its requests, admission and outputs
# ---------------------------------------------------------------------------

_INBOX_REQUESTS = {
    "q1": "What's the status of A-100?",
    "q2": "Not C-174, I meant D-211. What's its status?",
    "q3": "주문번호 없이 배송 상태가 궁금해요.",
}
_OBSERVED_KEYS = ("adapter", "effort", "error", "model", "provider", "purpose", "source", "usage")


def _inbox_body(*, drift: float = 0.0) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for key, text in _INBOX_REQUESTS.items():
        answers[f"{key}_intent"] = {
            "type": "choice",
            "choice": "status_only",
            "probabilities": {
                "status_only": 0.7 + drift,
                "cancel": 0.1,
                "refund": 0.1,
                "other": 0.1,
            },
            "confidence": 0.6,
        }
        mentions = [*decision_handoff.order_mentions(text), "none"]
        chosen = mentions[-2] if len(mentions) > 1 else "none"
        answers[f"{key}_target"] = {
            "type": "choice",
            "choice": chosen,
            "probabilities": {
                label: (0.9 if label == chosen else 0.1 / (len(mentions) - 1))
                if len(mentions) > 1
                else 1.0
                for label in mentions
            },
            "confidence": 0.8,
        }
    return {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 900, "output_tokens": 0},
        "answers": answers,
    }


def _inbox_values(outside: bool = False) -> str:
    values: dict[str, str] = {}
    for key, text in _INBOX_REQUESTS.items():
        mentions = [*decision_handoff.order_mentions(text), "none"]
        values[f"{key}_intent"] = "status_only"
        values[f"{key}_target"] = mentions[-2] if len(mentions) > 1 else "none"
    if outside:
        values["q1_target"] = "order_9"
    return json.dumps(values)


_HELPER_SCENARIOS: dict[str, tuple[Literal["a", "b"], bool, Any]] = {
    "a-single-ok": ("a", False, _result()),
    "b-single-ok": ("b", False, _body()),
    "a-single-refusal": (
        "a",
        False,
        replace(
            _result(),
            codex_output_items=(
                {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]},
            ),
        ),
    ),
    "a-inbox-ok": ("a", True, _result(_inbox_values())),
    "b-inbox-ok": ("b", True, _inbox_body()),
    "a-inbox-outside": ("a", True, _result(_inbox_values(outside=True))),
    "a-inbox-drift": ("a", True, replace(_result(_inbox_values()), response_model="gpt-6-sol")),
    "b-inbox-sum": ("b", True, _inbox_body(drift=0.02)),
    "b-inbox-503": ("b", True, httpx.Response(503, json={"error": "busy"})),
    "b-inbox-connect": ("b", True, httpx.ConnectError("synthetic outage")),
}


def _helper_bytes(arm: Literal["a", "b"], inbox: bool, outcome: Any) -> bytes:
    hooks = HookSystem()
    observed: list[dict[str, Any]] = []
    hooks.subscribe(HookEvent.LLM_CALL_ENDED, lambda _event, data: observed.append(data))
    bodies: list[bytes] = []

    def transport(request: httpx.Request) -> httpx.Response:
        bodies.append(request.method.encode() + b" " + str(request.url).encode() + b"\n")
        bodies.append(request.content)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, httpx.Response):
            return outcome
        return httpx.Response(200, json=outcome)

    adapter = _Adapter(outcome) if arm == "a" else None
    source = decision_handoff_inbox_source() if inbox else _SOURCE

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            tool = DecisionHandoffTool(
                source,
                arm,
                requests=_INBOX_REQUESTS if inbox else None,
                adapter=adapter,
                client=client if arm == "b" else None,
                api_key=SecretStr("synthetic-test-key") if arm == "b" else None,
            )
            return await tool.aexecute(_tool_context=_context(hooks))

    try:
        output = asyncio.run(run())
    finally:
        hooks.close()
    requests = [
        {
            "model": request.model,
            "effort": request.effort,
            "system_prompt": request.system_prompt,
            "messages": [[message.role, message.content] for message in request.messages],
            "response_schema": request.response_schema,
            "allowed_tool_names": sorted(request.allowed_tool_names or ()),
            "metadata": request.metadata,
        }
        for request in (adapter.requests if adapter is not None else [])
    ]
    events = [{key: data.get(key) for key in _OBSERVED_KEYS} for data in observed]
    return json.dumps(
        {"output": output, "astra": requests, "events": events}, sort_keys=True, default=str
    ).encode() + b"".join(bodies)


def decision_handoff_inbox_source() -> str:
    from evals.benchmarks.decision_handoff_runtime import inbox_request

    return inbox_request(
        [{"id": key, "request": text, "candidates": []} for key, text in _INBOX_REQUESTS.items()]
    )


# sha256 digests recorded at 0a90cf8fe (before 0029) by this same harness.
_PRE_0029_HELPER: dict[str, str] = {
    "a-inbox-drift": "87aea5b565be3a5992cf95a3b6353aa3ba208fff04bcbc07d69e3b6ffe5bed3c",
    "a-inbox-ok": "3dd9a99dbf24d4d4920107b9f501db78efad218fac63627dce0b38040752bdae",
    "a-inbox-outside": "87aea5b565be3a5992cf95a3b6353aa3ba208fff04bcbc07d69e3b6ffe5bed3c",
    "a-single-ok": "3387cb88a73f991ccb6e7e5f9fd7af79416375ee480bdd5f36b861f2c46f513b",
    "a-single-refusal": "7263f38d22799482b84f896f989349c0c44fea12b86f9f29a76c26050907944d",
    "b-inbox-503": "e947f8c353eca01ae6b14974e12d13832bde28613e96766f57bf394d5f4bbfe5",
    "b-inbox-connect": "fac3a49abbf83dd6801a8f5b711ca9a8ec9f97d2a023ae1d36194ddf20d1bf1c",
    "b-inbox-ok": "65bb446e0aed2737b1a05aee36ad5bbfb8d61fa3bfa5f8936f332b30a64d90d7",
    "b-inbox-sum": "d0c9084acec8326cf7b3528dc3c69f94f1c53f2ec80339b82f8c5fe34e46fdfd",
    "b-single-ok": "6e822064b494a58df72f8c2777a2dc218069f736a6667e9ef5ad00c5d1cccd45",
}


def test_helper_requests_admission_and_outputs_are_unchanged() -> None:
    digests = {
        name: hashlib.sha256(_helper_bytes(arm, inbox, outcome)).hexdigest()
        for name, (arm, inbox, outcome) in _HELPER_SCENARIOS.items()
    }
    assert digests == _PRE_0029_HELPER
