"""Offline SDK wire and durable billing regressions for cache lifecycles."""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from anthropic import AsyncAnthropic
from core.agent.loop._response import _record_usage
from core.hooks import HookEvent, HookSystem
from core.hooks.llm_observation import _completed_attempt_payload, observe_llm_call
from core.llm.adapters._anthropic_common import build_create_kwargs, translate_response
from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
from core.llm.adapters.base import AdapterCallRequest, Message, UsageSummary
from core.llm.adapters.translation import agentic_response_from_adapter_result
from core.llm.errors import LLMRequestValidationError
from core.llm.providers.anthropic import apply_messages_cache_control, validate_cache_controls
from core.llm.token_tracker import TokenTracker
from core.llm.usage_store import UsageRecord, UsageStore
from core.observability.activity import LLMCallUsageDetails
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from evals.platforms.harbor import _summarize_usage


def _request(messages: tuple[Message, ...]) -> AdapterCallRequest:
    return AdapterCallRequest(
        model="claude-opus-5-5",
        system_prompt="Stable rules\n<dynamic_context>mutable tail</dynamic_context>",
        messages=messages,
        max_tokens=64,
    )


@pytest.mark.parametrize("long_write", [None, 0, 600])
def test_sdk_cache_ttl_reaches_loop_budget_durable_event_and_harbor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, long_write: int | None
) -> None:
    tracker = TokenTracker()
    usage_store = UsageStore(tmp_path / "usage")
    monkeypatch.setattr("core.llm.token_tracker.get_tracker", lambda: tracker)
    monkeypatch.setattr("core.llm.usage_store.get_usage_store", lambda: usage_store)
    store = HookEventStore(tmp_path / "events.db")
    hooks = HookSystem()
    hooks.register_sink(HookPersistenceSink(store, session_key="cache-test", run_id="cache-test"))
    wires: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.content))
        usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 1000,
        }
        if long_write is not None:
            usage["cache_creation"] = {
                "ephemeral_5m_input_tokens": 1000 - long_write,
                "ephemeral_1h_input_tokens": long_write,
            }
        return httpx.Response(
            200,
            json={
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "content": [{"type": "text", "text": "fixture"}],
                "usage": usage,
            },
        )

    async def run() -> None:
        async with AsyncAnthropic(
            api_key="offline-fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            adapter = AnthropicPaygAdapter()
            with patch.object(adapter, "_get_client", return_value=client):
                result = await observe_llm_call(
                    lambda: adapter.acomplete(_request((Message(role="user", content="hi"),))),
                    hooks=hooks,
                    correlation={"session_id": "cache-test"},
                    model="claude-opus-5-5",
                    provider="anthropic",
                    adapter=adapter.name,
                    purpose="agentic_loop",
                    source="payg",
                    cost_estimator=tracker.calculate_cost,
                )
            assert result.usage.cache_write_1h_tokens == long_write
            assert result.usage.reported_cost_usd is None
            _record_usage(
                SimpleNamespace(model="claude-opus-5-5", _quiet=True),
                agentic_response_from_adapter_result(result),
            )

    try:
        asyncio.run(run())
    finally:
        hooks.close()
    assert len(wires) == 1
    expected = (100 * 4 + 20 * 20 + 300 * 0.2 + 1000 * 5 + (long_write or 0) * 3) / 1e6
    assert tracker.accumulator.total_cost_usd == pytest.approx(expected)
    assert tracker.accumulator.calls[0].cache_creation_1h_tokens == long_write
    persisted = next(usage_store.usage_dir.glob("*.jsonl")).read_text().splitlines()
    assert len(persisted) == 1
    assert UsageRecord.from_json(persisted[0]).cache_creation_1h_tokens == long_write
    with closing(HookEventStore(tmp_path / "events.db")) as reopened:
        rows = reopened.read()
        end = next(row for row in rows if row.event == HookEvent.LLM_CALL_ENDED.value)
        assert end.payload["usage"]["cache_write_1h_tokens"] == long_write
        assert end.payload["cost_usd"] == pytest.approx(expected)
        assert end.payload["activity_schema_version"] == 12
        projected = _summarize_usage(rows)
        assert projected["recorded_attempts"][0]["usage"]["cache_write_1h_tokens"] == long_write
        assert projected["cached_input_tokens"] == 300  # Harbor cache metric remains reads only.


def test_marker_budget_and_signed_replay_survive_actual_sdk_serialization() -> None:
    native = {"type": "thinking", "thinking": "", "signature": "opaque-fixture"}
    redacted = {"type": "redacted_thinking", "data": "opaque-fixture"}
    marked = {"type": "text", "text": "earlier", "cache_control": {"type": "ephemeral"}}
    request = replace(
        _request(
            (
                Message(role="user", content=[marked]),
                Message(role="assistant", content="", anthropic_content=(native,)),
                Message(role="user", content="second"),
                Message(role="assistant", content="", anthropic_content=(redacted,)),
                Message(role="user", content="last"),
            )
        ),
        provider_options={"cache_message_breakpoints": 99},
    )
    before = deepcopy(request)
    wires: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        )

    async def run() -> None:
        async with AsyncAnthropic(
            api_key="offline-fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            await client.messages.create(**build_create_kwargs(request))

    asyncio.run(run())
    assert request == before
    assert len(wires) == 1
    wire = wires[0]
    assert validate_cache_controls(system=wire["system"], messages=wire["messages"]) == 4
    assert wire["messages"][1]["content"][0] == native
    assert wire["messages"][3]["content"][0] == redacted


@pytest.mark.parametrize(
    "invalid",
    [
        {
            "type": "thinking",
            "thinking": "",
            "signature": "opaque",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "text", "cache_control": {"type": "ephemeral", "ttl": "24h"}},
    ],
)
def test_invalid_explicit_markers_fail_before_dispatch(invalid: dict) -> None:
    with pytest.raises(LLMRequestValidationError):
        build_create_kwargs(_request((Message(role="user", content=[invalid]),)))


def test_existing_tool_slots_and_ttl_order_are_counted_without_mutation() -> None:
    long = {"type": "text", "text": "long", "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    messages = [
        {"role": "user", "content": "before"},
        {"role": "user", "content": [long]},
        {"role": "user", "content": "after"},
    ]
    before = deepcopy(messages)
    shaped = apply_messages_cache_control(messages, reserved_breakpoints=2)
    assert messages == before
    assert shaped[0]["content"] == "before"  # No 5m marker before the caller's 1h marker.
    assert shaped[1]["content"][0] == long
    tool = {"name": "lookup", "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    assert validate_cache_controls(tools=[tool], system=[long], messages=shaped) == 4
    with pytest.raises(LLMRequestValidationError, match="precede"):
        validate_cache_controls(
            tools=[{**tool, "cache_control": {"type": "ephemeral"}}], system=[long], messages=[]
        )
    with pytest.raises(LLMRequestValidationError, match="at most 4"):
        apply_messages_cache_control([{"role": "user", "content": [long]}] * 4)


@pytest.mark.parametrize("value", [-1, 1001, True])
def test_invalid_ttl_subcounts_cannot_lower_estimated_cost(value: int) -> None:
    with pytest.raises(ValueError):
        LLMCallUsageDetails(cache_write_tokens=1000, cache_write_1h_tokens=value)
    with pytest.raises(ValueError, match="subset"):
        UsageSummary(cache_write_tokens=1000, cache_write_1h_tokens=value)
    with pytest.raises(ValueError, match="subset"):
        TokenTracker().calculate_cost(
            "claude-opus-5-5", 0, 0, cache_creation_tokens=1000, cache_creation_1h_tokens=value
        )


@pytest.mark.parametrize("long_write", [-1, 3, True])
def test_reported_cost_cannot_bypass_ttl_subset_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, long_write: int
) -> None:
    store = UsageStore(tmp_path / "usage")
    monkeypatch.setattr("core.llm.usage_store.get_usage_store", lambda: store)
    tracker = TokenTracker()
    with pytest.raises(ValueError, match="subset"):
        tracker.record(
            "claude-opus-5-5",
            0,
            0,
            cache_creation_tokens=2,
            cache_creation_1h_tokens=long_write,
            reported_cost_usd=0,
        )
    assert tracker.accumulator.calls == []
    assert store.get_recent_records() == []


def test_reported_zero_cost_keeps_valid_ttl_split_without_estimated_charge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = UsageStore(tmp_path / "usage")
    monkeypatch.setattr("core.llm.usage_store.get_usage_store", lambda: store)
    tracker = TokenTracker()
    usage = tracker.record(
        "claude-opus-5-5",
        0,
        0,
        cache_creation_tokens=2,
        cache_creation_1h_tokens=1,
        reported_cost_usd=0,
    )
    assert usage.cost_usd == 0
    assert tracker.accumulator.total_cost_usd == 0
    record = UsageStore(store.usage_dir).get_recent_records()[0]
    assert record.cache_creation_tokens == 2
    assert record.cache_creation_1h_tokens == 1
    assert record.cost_usd == 0


def test_compaction_cache_marker_preserves_the_existing_beta_block() -> None:
    block = {"type": "compaction", "content": "summary", "cache_control": {"type": "ephemeral"}}
    request = _request((Message(role="assistant", content="", anthropic_content=(block,)),))
    assert build_create_kwargs(request)["messages"][0]["content"][0] == block


def test_sdk_stream_preserves_one_hour_usage() -> None:
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 1000,
                    "cache_creation": {
                        "ephemeral_1h_input_tokens": 600,
                        "ephemeral_5m_input_tokens": 400,
                    },
                },
            },
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        },
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    async def run() -> None:
        async with AsyncAnthropic(
            api_key="offline-fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            adapter = AnthropicPaygAdapter()
            with patch.object(adapter, "_get_client", return_value=client):
                result = [
                    event
                    async for event in adapter.astream(
                        _request((Message(role="user", content="hi"),))
                    )
                ]
            usage = next(event.payload for event in result if event.kind == "usage")
            assert usage["cache_write_tokens"] == 1000
            assert usage["cache_write_1h_tokens"] == 600

    asyncio.run(run())


def _compaction_usage() -> dict[str, Any]:
    def iteration(
        kind: str, inputs: int, outputs: int, reads: int, writes: int, hour: int
    ) -> dict[str, Any]:
        return {
            "type": kind,
            "model": "claude-opus-5-5",
            "input_tokens": inputs,
            "output_tokens": outputs,
            "cache_read_input_tokens": reads,
            "cache_creation_input_tokens": writes,
            "cache_creation": {
                "ephemeral_1h_input_tokens": hour,
                "ephemeral_5m_input_tokens": writes - hour,
            },
        }

    return {
        "input_tokens": 23700,
        "output_tokens": 1100,
        "cache_read_input_tokens": 350,
        "cache_creation_input_tokens": 1030,
        "cache_creation": {"ephemeral_1h_input_tokens": 610, "ephemeral_5m_input_tokens": 420},
        "output_tokens_details": {"thinking_tokens": 7},
        "iterations": [
            iteration("compaction", 180000, 3500, 200, 100, 40),
            iteration("message", 23000, 1000, 300, 1000, 600),
            iteration("compaction", 400, 10, 0, 0, 0),
            iteration("message", 700, 100, 50, 30, 10),
        ],
    }


def _compaction_message(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "msg_compaction",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "content": [{"type": "text", "text": "continued"}],
        "usage": usage,
    }


@pytest.mark.parametrize("beta", [False, True])
def test_compaction_iterations_replace_top_level_usage_without_double_counting(beta: bool) -> None:
    from anthropic.types import Message as SDKMessage
    from anthropic.types.beta import BetaMessage

    message = (BetaMessage if beta else SDKMessage).model_validate(
        _compaction_message(_compaction_usage())
    )
    result = translate_response(message)
    assert result.raw_response is message
    assert result.usage.input_tokens == 204100
    assert result.usage.output_tokens == 4610
    assert result.usage.cached_input_tokens == 550
    assert result.usage.cache_write_tokens == 1130
    assert result.usage.cache_write_1h_tokens == 650
    assert result.usage.input_tokens_present and result.usage.output_tokens_present
    assert result.usage.cached_input_tokens_present and result.usage.cache_write_tokens_present
    # Compaction iterations have no thinking breakdown; seven is not a request total.
    assert not result.usage.reasoning_tokens_present


@pytest.mark.parametrize(
    "missing,field,present",
    [
        ("input_tokens", "input_tokens", "input_tokens_present"),
        ("output_tokens", "output_tokens", "output_tokens_present"),
        ("cache_read_input_tokens", "cached_input_tokens", "cached_input_tokens_present"),
        ("cache_creation_input_tokens", "cache_write_tokens", "cache_write_tokens_present"),
    ],
)
def test_missing_compaction_counter_is_unknown_not_a_partial_total(
    missing: str, field: str, present: str
) -> None:
    from anthropic.types import Message as SDKMessage

    usage = _compaction_usage()
    del usage["iterations"][0][missing]
    result = translate_response(SDKMessage.model_validate(_compaction_message(usage)))
    assert getattr(result.usage, present) is False
    assert getattr(result.usage, field) == 0  # Compatibility value; presence is unknown.
    if missing == "cache_creation_input_tokens":
        assert result.usage.cache_write_1h_tokens is None


@pytest.mark.parametrize("missing_index,expected", [(0, None), (2, 650)])
def test_compaction_cache_ttl_requires_every_nonzero_write_split(
    missing_index: int, expected: int | None
) -> None:
    from anthropic.types import Message as SDKMessage

    usage = _compaction_usage()
    del usage["iterations"][missing_index]["cache_creation"]
    result = translate_response(SDKMessage.model_validate(_compaction_message(usage)))
    assert result.usage.cache_write_tokens == 1130
    assert result.usage.cache_write_1h_tokens == expected


def test_replayed_compaction_without_new_iteration_uses_top_level_usage() -> None:
    from anthropic.types import Message as SDKMessage

    usage = _compaction_usage()
    usage["iterations"] = [row for row in usage["iterations"] if row["type"] == "message"]
    result = translate_response(SDKMessage.model_validate(_compaction_message(usage)))
    assert result.usage.input_tokens == 23700
    assert result.usage.output_tokens == 1100
    assert result.usage.cached_input_tokens == 350
    assert result.usage.cache_write_tokens == 1030
    assert result.usage.cache_write_1h_tokens == 610
    assert result.usage.reasoning_tokens == 7 and result.usage.reasoning_tokens_present


@pytest.mark.parametrize("kind", ["advisor_message", "fallback_message", "message"])
def test_compaction_does_not_assign_mixed_model_iterations_one_tariff(kind: str) -> None:
    from anthropic.types import Message as SDKMessage

    usage = _compaction_usage()
    usage["iterations"][1].update(type=kind, model="claude-haiku-4-5-20251001")
    message = SDKMessage.model_validate(_compaction_message(usage))
    result = translate_response(message)
    assert result.raw_response is message
    assert not result.usage.input_tokens_present and not result.usage.output_tokens_present
    projected = _completed_attempt_payload(
        result, "claude-opus-5-5", cost_estimator=TokenTracker().calculate_cost
    )
    assert projected["cost_usd"] is None


def test_compaction_rejects_invalid_ttl_split_even_when_aggregate_would_fit() -> None:
    from anthropic.types import Message as SDKMessage

    usage = _compaction_usage()
    usage["iterations"][0]["cache_creation"]["ephemeral_1h_input_tokens"] = 101
    with pytest.raises(ValueError, match="subset of cache writes"):
        translate_response(SDKMessage.model_validate(_compaction_message(usage)))


@pytest.mark.parametrize(
    "streaming,model,base_url,compacted",
    [
        (False, "claude-opus-5-5", "https://api.anthropic.com", True),
        (True, "claude-opus-5-5", "https://api.anthropic.com", True),
        (True, "custom-model", "https://compat.invalid", False),
        (True, "claude-opus-4-5", "https://api.anthropic.com", False),
    ],
    ids=["native-completion", "native-stream", "custom-stream", "clearing-only-stream"],
)
def test_sdk_adapter_preserves_compaction_and_stable_stream_usage(
    streaming: bool, model: str, base_url: str, compacted: bool
) -> None:
    usage = _compaction_usage()
    if not compacted:
        usage.pop("iterations")
    request = replace(_request((Message(role="user", content="hi"),)), model=model)
    start_usage = {"input_tokens": 0, "output_tokens": 0} if compacted else usage
    events = [
        {
            "type": "message_start",
            "message": {
                **_compaction_message(start_usage),
                "model": model,
                "content": [],
                "stop_reason": None,
            },
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": usage,
        },
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if streaming:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
        return httpx.Response(200, json={**_compaction_message(usage), "model": model})

    async def run() -> None:
        async with AsyncAnthropic(
            api_key="offline-fixture",
            base_url=base_url,
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            adapter = AnthropicPaygAdapter()
            with patch.object(adapter, "_get_client", return_value=client):
                if streaming:
                    result = [event async for event in adapter.astream(request)]
                    actual = next(event.payload for event in result if event.kind == "usage")
                    assert result[-1].payload["usage"] == actual
                else:
                    response = await adapter.acomplete(request)
                    actual = asdict(response.usage)
            assert (
                actual["input_tokens"],
                actual["output_tokens"],
                actual["cached_input_tokens"],
                actual["cache_write_tokens"],
                actual["cache_write_1h_tokens"],
            ) == ((204100, 4610, 550, 1130, 650) if compacted else (23700, 1100, 350, 1030, 610))
            if compacted:
                projected = _completed_attempt_payload(
                    SimpleNamespace(usage=UsageSummary(**actual)),
                    "claude-opus-5-5",
                    cost_estimator=TokenTracker().calculate_cost,
                )
                assert projected["cost_usd"] == pytest.approx(
                    (204100 * 4 + 4610 * 20 + 550 * 0.2 + 1130 * 5 + 650 * 3) / 1e6
                )
            else:
                assert actual["reasoning_tokens"] == 7 and actual["reasoning_tokens_present"]

    asyncio.run(run())
    assert len(requests) == 1
    sent = requests[0]
    kwargs = build_create_kwargs(request, base_url=base_url)
    headers = kwargs.pop("extra_headers", {})
    extra_body = kwargs.pop("extra_body", {})
    expected = {**kwargs, **extra_body}
    if streaming:
        expected["stream"] = True
    assert json.loads(sent.content) == expected
    assert sent.url.path == "/v1/messages"
    assert sent.url.host == httpx.URL(base_url).host
    assert dict(sent.url.params) == ({"beta": "true"} if streaming and compacted else {})
    assert sent.headers.get("anthropic-beta") == headers.get("anthropic-beta")
