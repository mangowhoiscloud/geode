"""Offline SDK wire and durable billing regressions for cache lifecycles."""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from anthropic import AsyncAnthropic
from core.agent.loop._response import _record_usage
from core.hooks import HookEvent, HookSystem
from core.hooks.llm_observation import observe_llm_call
from core.llm.adapters._anthropic_common import build_create_kwargs
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
        assert end.payload["activity_schema_version"] == 11
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
