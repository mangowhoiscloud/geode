"""IPC conversation turns must share the loop's history and usage boundaries."""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.tool_executor import ToolExecutor
from core.config import settings
from core.hooks import HookEvent, HookSystem
from core.llm import token_tracker, usage_store
from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    TextCompletionResult,
    UsageSummary,
)
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from core.server.ipc_server.poller import CLIPoller


class _Client:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def get_capability(self) -> tuple[bool, int]:
        return False, 120

    def send_json_threadsafe(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)

    async def send_json_async(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)

    async def drain_pending_sends(self) -> None:
        pass


@pytest.mark.parametrize("cache", [None, 0, 6], ids=["missing", "zero", "positive"])
def test_short_ipc_prompt_preserves_history_and_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache: int | None
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEODE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GEODE_FAST_CHAT", "1")
    monkeypatch.setattr(settings, "judgment_engine", "llm")
    monkeypatch.setattr(settings, "judge_model", "")
    usage = UsageSummary(
        input_tokens=10,
        output_tokens=3,
        cached_input_tokens=cache or 0,
        cached_input_tokens_present=cache is not None,
        cache_write_tokens=2,
        reported_cost_usd=0.125,
    )
    judge_usage = UsageSummary(
        input_tokens=7,
        output_tokens=2,
        cached_input_tokens=0,
        cached_input_tokens_present=True,
        cache_write_tokens=0,
        cache_write_tokens_present=True,
        reported_cost_usd=0.0625,
    )

    async def complete(request: AdapterCallRequest) -> AdapterCallResult:
        if request.response_schema and request.response_schema.get("title") == "TurnVerification":
            assert request.model == "gpt-5.6-sol"
            assert not request.tools
            assert "Hello." in str(request.messages)
            return AdapterCallResult(
                text=json.dumps(
                    {
                        "passed": True,
                        "score": 1.0,
                        "reflection": {
                            "observation": "The candidate greets the user with Hello.",
                            "lesson": "A greeting needs no external action.",
                            "next_check": "Retain the greeting as the final response.",
                        },
                    }
                ),
                usage=judge_usage,
                stop_reason="end_turn",
            )
        assert request.response_schema is None
        return AdapterCallResult(text="Hello.", usage=usage, stop_reason="end_turn")

    adapter = SimpleNamespace(
        name="test-adapter",
        provider="openai",
        source="payg",
        acomplete=AsyncMock(side_effect=complete),
        acomplete_text=AsyncMock(return_value=TextCompletionResult(text="Hello.", usage=usage)),
    )
    # Fake only provider boundaries, including the removed shortcut's old route.
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    tracker = token_tracker.TokenTracker()
    ledger = usage_store.UsageStore(tmp_path / "usage")
    monkeypatch.setattr(token_tracker, "get_tracker", lambda: tracker)
    monkeypatch.setattr(usage_store, "get_usage_store", lambda: ledger)
    hooks = HookSystem()
    with closing(HookEventStore(tmp_path / "calls.db")) as store:
        hooks.register_sink(HookPersistenceSink(store, session_key="ipc", run_id="ipc"))
        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(action_handlers={}, auto_approve=True, hitl_level=0),
            config=AgenticLoopConfig(
                session_id="ipc-accounting",
                source="payg",
                allowed_tool_names=set(),
            ),
            model="gpt-5.6-sol",
            provider="openai",
            hooks=hooks,
            quiet=True,
        )
        loop._new_adapter = adapter
        client = _Client()
        poller = CLIPoller(services=cast(Any, SimpleNamespace(lane_queue=None)))
        try:
            result = asyncio.run(
                poller._process_message_async(
                    {"type": "prompt", "text": "Hello", "_client": client},
                    loop,
                    None,
                    loop._session_id,
                )
            )
            assert result is not None and result["termination"] == "natural"
            assert result["text"] == "Hello." and result["rounds"] == 1
            assert adapter.acomplete.await_count == 2
            assert adapter.acomplete.await_args_list[0].args[0].response_schema is None
            assert (
                adapter.acomplete.await_args_list[1].args[0].response_schema["title"]
                == "TurnVerification"
            )
            adapter.acomplete_text.assert_not_awaited()
            assert [message["role"] for message in loop.context.messages] == ["user", "assistant"]
            assert loop.context.messages[0]["content"] == "Hello"
            starts = store.read(
                session_id=loop._session_id, event_filter=HookEvent.LLM_CALL_STARTED.value
            )
            ends = store.read(
                session_id=loop._session_id, event_filter=HookEvent.LLM_CALL_ENDED.value
            )
            assert len(starts) == len(ends) == 2
            assert {event.llm_attempt_id for event in starts} == {
                event.llm_attempt_id for event in ends
            }
            assert all(event.turn_id == loop._turn_id for event in ends)
            by_purpose = {event.payload["purpose"]: event for event in ends}
            assert set(by_purpose) == {"agentic_loop", "turn_verification"}
            generation = by_purpose["agentic_loop"].payload
            judgment = by_purpose["turn_verification"].payload
            assert generation["usage"]["cached_input_tokens"] == cache
            assert generation["usage"]["cache_write_tokens"] == 2
            assert generation["cost_usd"] == 0.125
            assert judgment["usage"]["cached_input_tokens"] == 0
            assert judgment["usage"]["cache_write_tokens"] == 0
            assert judgment["cost_usd"] == 0.0625
            assert len(tracker.accumulator.calls) == 2
            assert tracker.accumulator.total_input_tokens == 17
            assert tracker.accumulator.total_output_tokens == 5
            assert tracker.accumulator.total_cache_read_tokens == (cache or 0)
            assert tracker.accumulator.total_cache_creation_tokens == 2
            assert tracker.accumulator.total_cost_usd == 0.1875
            records = ledger.get_recent_records()
            assert len(records) == 2
            assert all(record.session == loop._session_id for record in records)
            assert records[0].cache_read_tokens == records[0].cache_creation_tokens == 0
            assert records[0].input_tokens == 7 and records[0].output_tokens == 2
            assert records[0].cost_usd == 0.0625
            assert records[1].cache_read_tokens == (cache or 0)
            assert records[1].cache_creation_tokens == 2
            assert records[1].cost_usd == 0.125
            tokens = [event for event in client.events if event["type"] == "tokens"]
            assert len(tokens) == 2
            assert tokens[0]["cache_read_tokens"] == (cache or 0)
            assert tokens[0]["cache_write_tokens"] == 2
            assert tokens[0]["cost"] == 0.125
            assert tokens[1]["cache_read_tokens"] == tokens[1]["cache_write_tokens"] == 0
            assert tokens[1]["cost"] == 0.0625
            assert loop._quiet is True
        finally:
            hooks.close()
