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
