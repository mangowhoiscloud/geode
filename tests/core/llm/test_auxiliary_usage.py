"""Auxiliary dispatch consumes provider usage before callers discard visible text."""

from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.hooks import HookEvent, HookSystem
from core.llm.adapters.base import (
    AdapterCallResult,
    EmptyModelOutputError,
    TextCompletionResult,
    UsageSummary,
    WebSearchResult,
)
from core.llm.adapters.dispatch import (
    AdapterDispatchError,
    AdapterUnavailableError,
    complete_text_via_adapters,
    web_search_via_adapters,
)
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from evals.platforms.harbor import _summarize_usage


def _observations() -> tuple[HookSystem, list[tuple[HookEvent, dict[str, Any]]]]:
    hooks = HookSystem()
    rows: list[tuple[HookEvent, dict[str, Any]]] = []
    hooks.register_prefix("LLM_CALL", lambda event, data: rows.append((event, dict(data))))
    return hooks, rows


def _adapter(monkeypatch: pytest.MonkeyPatch, call: AsyncMock) -> Any:
    adapter = SimpleNamespace(
        name="codex-oauth",
        provider="openai",
        source="subscription",
        acomplete_text=call,
        aweb_search=call,
    )
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    return adapter


@pytest.mark.parametrize("capability", ["text", "search"])
def test_dispatch_preserves_each_retry_and_unknown_counter(
    monkeypatch: pytest.MonkeyPatch, capability: str
) -> None:
    class ReadError(Exception):
        pass

    usage = UsageSummary(
        input_tokens=30,
        output_tokens=0,
        output_tokens_present=True,
        cached_input_tokens_present=True,
    )
    result = (
        TextCompletionResult(text="NONE", usage=usage)
        if capability == "text"
        else WebSearchResult(query="q", text="result", usage=usage)
    )
    call = AsyncMock(side_effect=[ReadError("transport"), result])
    _adapter(monkeypatch, call)
    hooks, rows = _observations()
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters
    asyncio.run(
        dispatch(
            "private-input",
            model="gpt-5.6-sol",
            hooks=hooks,
            correlation={"session_id": "session-a", "turn_id": "turn-a"},
        )
    )
    assert [event for event, _ in rows] == [
        HookEvent.LLM_CALL_STARTED,
        HookEvent.LLM_CALL_ENDED,
    ] * 2
    first, second = rows[1][1], rows[3][1]
    assert first["llm_call_id"] == second["llm_call_id"]
    assert first["llm_attempt_id"] != second["llm_attempt_id"]
    assert first["error_type"] == "ReadError" and "usage" not in first
    assert second["usage"] == {
        "input_tokens": 30,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "cache_write_1h_tokens": None,
    }
    assert second["source"] == "subscription" and second["effort"] is None
    assert second["cost_usd"] is None  # Token counts are not a subscription invoice.
    assert second["session_id"] == "session-a"
    assert second["purpose"] == ("text_completion" if capability == "text" else "hosted_search")
    assert "private-input" not in repr(rows) and "NONE" not in repr(rows)
    assert call.await_count == 2


@pytest.mark.parametrize("capability", ["text", "search"])
@pytest.mark.parametrize("failure", ["cancel", "completed-empty"])
def test_terminal_failure_retains_identity_and_known_usage(
    monkeypatch: pytest.MonkeyPatch, capability: str, failure: str
) -> None:
    completed = AdapterCallResult(
        text="",
        usage=UsageSummary(input_tokens=13, output_tokens=2, cached_input_tokens_present=True),
        stop_reason="completed",
    )
    error = (
        asyncio.CancelledError("cancel")
        if failure == "cancel"
        else EmptyModelOutputError("empty", completed_result=completed)
    )
    _adapter(monkeypatch, AsyncMock(side_effect=error))
    hooks, rows = _observations()
    dispatch = complete_text_via_adapters if capability == "text" else web_search_via_adapters
    with pytest.raises(
        asyncio.CancelledError if failure == "cancel" else AdapterDispatchError
    ) as caught:
        asyncio.run(
            dispatch(
                "input",
                model="gpt-5.6-sol",
                hooks=hooks,
                correlation={"session_id": "session-failure"},
            )
        )
    assert (caught.value if failure == "cancel" else caught.value.__cause__) is error
    assert len(rows) == 2
    assert rows[1][1]["error_type"] == type(error).__name__
    if failure == "cancel":
        assert "usage" not in rows[1][1]
    else:
        assert rows[1][1]["usage"]["input_tokens"] == 13
        assert rows[1][1]["usage"]["cached_input_tokens"] == 0


def test_unavailable_adapter_is_not_a_dispatched_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: None)
    hooks, rows = _observations()
    with pytest.raises(AdapterUnavailableError):
        asyncio.run(complete_text_via_adapters("input", model="gpt-5.6-sol", hooks=hooks))
    assert rows == []


def test_codex_text_keeps_request_default_and_is_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    adapter = CodexOAuthAdapter()
    completed = AsyncMock(
        return_value=AdapterCallResult(
            text="answer",
            usage=UsageSummary(input_tokens=2, output_tokens=1),
            stop_reason="completed",
        )
    )
    monkeypatch.setattr(adapter, "acomplete", completed)
    monkeypatch.setattr("core.llm.adapters.dispatch._select_adapter", lambda *a, **kw: adapter)
    hooks, rows = _observations()
    asyncio.run(
        complete_text_via_adapters(
            "input", model="gpt-5.6-sol", hooks=hooks, correlation={"session_id": "session-text"}
        )
    )
    request = completed.await_args.args[0]
    assert request.model == "gpt-5.6-sol" and request.effort == "medium"
    assert completed.await_count == 1 and len(rows) == 2
    assert rows[1][1]["usage"]["input_tokens"] == 2
    assert rows[1][1]["effort"] is None  # The capability signature does not expose request effort.


@pytest.mark.parametrize(
    ("purpose", "outcome"),
    [
        ("text_completion", "returned"),
        ("context_compaction", "returned"),
        ("learning_extraction", "returned"),
        ("memory_dreaming", "returned"),
        ("context_exhaustion", "returned"),
        ("learning_extraction", "retry"),
        ("memory_dreaming", "cancelled"),
    ],
)
def test_text_producer_purpose_survives_durable_projection_without_wire_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, purpose: Any, outcome: str
) -> None:
    class ReadError(Exception):
        pass

    result = TextCompletionResult(
        text="private result",
        usage=UsageSummary(input_tokens=23, output_tokens=1, cached_input_tokens_present=True),
    )
    call = AsyncMock(
        side_effect=asyncio.CancelledError()
        if outcome == "cancelled"
        else [ReadError(), result]
        if outcome == "retry"
        else [result]
    )
    _adapter(monkeypatch, call)
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "producer-events.db")
    hooks.register_sink(HookPersistenceSink(store, session_key="synthetic", run_id="producer"))
    try:
        request = complete_text_via_adapters(
            "private prompt",
            system="private system",
            model="gpt-5.6-sol",
            effort="max",
            max_tokens=300,
            hooks=hooks,
            correlation={"session_id": "session-producer"},
            **({"purpose": purpose} if purpose != "text_completion" else {}),
        )
        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(request)
        else:
            asyncio.run(request)
        starts = store.read(event_filter=HookEvent.LLM_CALL_STARTED.value)
        ends = list(reversed(store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)))
        assert len(starts) == len(ends) == call.await_count == (2 if outcome == "retry" else 1)
        usage = _summarize_usage([*starts, *ends])
        assert usage["attempt_pairing_complete"] is True
        assert usage["mapping_anomaly_events"] == 0
        assert {row["purpose"] for row in usage["recorded_attempts"]} == {purpose}
        assert {row["effort"] for row in usage["recorded_attempts"]} == {"max"}
        assert {row.payload["activity_schema_version"] for row in ends} == {11}
        assert usage["input_tokens"] == (23 if outcome == "returned" else None)
        assert usage["cached_input_tokens"] == (0 if outcome == "returned" else None)
        if outcome == "cancelled":
            assert ends[0].payload["error_type"] == "CancelledError"
            assert ends[0].payload["usage"] is None
        for observed_call in call.await_args_list:
            assert observed_call.args == ("private prompt",)
            assert observed_call.kwargs == {
                "system": "private system",
                "model": "gpt-5.6-sol",
                "max_tokens": 300,
                "effort": "max",
            }
    finally:
        hooks.close()


@pytest.mark.parametrize("consumer", ["learning", "compaction", "dreaming"])
def test_native_text_consumers_emit_usage_before_discarding_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, consumer: str
) -> None:
    from core.config import settings
    from core.hooks.llm_extract_learning import make_llm_extract_handler
    from core.memory.dreaming import DreamingService
    from core.memory.session_manager import SessionManager
    from core.orchestration.compaction import compact_conversation

    monkeypatch.setattr(settings, "model", "gpt-5.6-sol")
    monkeypatch.setattr(settings, "learning_extract_model", "gpt-5.6-sol")
    monkeypatch.setattr("core.llm.routing.infer_source", lambda provider, **kwargs: "subscription")
    call = AsyncMock(
        return_value=TextCompletionResult(
            text="NONE",
            usage=UsageSummary(input_tokens=23, output_tokens=1, cached_input_tokens_present=True),
        )
    )
    _adapter(monkeypatch, call)
    hooks, rows = _observations()
    correlation = {"session_id": "session-consumer", "turn_id": "turn-consumer"}
    if consumer == "learning":
        profile = SimpleNamespace(
            add_learned_pattern=lambda *a: pytest.fail("NONE is not a memory")
        )
        _name, handler = make_llm_extract_handler(lambda: profile, hooks=hooks)
        asyncio.run(
            handler(
                HookEvent.TURN_COMPLETED,
                {
                    **correlation,
                    "user_input": "z" * 60,
                    "effort": "max",
                    "termination_reason": "natural",
                },
            )
        )
    else:
        with closing(SessionManager(tmp_path / "auxiliary.db")) as manager:
            messages = [
                {"role": "user" if i % 2 == 0 else "assistant", "content": "message", "seq": i}
                for i in range(14)
            ]
            if consumer == "compaction":
                asyncio.run(
                    compact_conversation(
                        messages,
                        "openai",
                        "gpt-5.6-sol",
                        effort="max",
                        keep_recent=4,
                        session_id="session-consumer",
                        session_manager=manager,
                        hooks=hooks,
                        correlation=correlation,
                    )
                )
            else:
                manager.upsert_messages("session-consumer", messages)
                asyncio.run(
                    DreamingService(session_manager=manager, hooks=hooks).dream_session(
                        "session-consumer", model="gpt-5.6-sol", effort="max"
                    )
                )
    assert call.await_count == 1
    assert len(rows) == 2
    assert rows[1][1]["session_id"] == "session-consumer"
    assert rows[1][1]["usage"]["cached_input_tokens"] == 0
    assert rows[1][1]["usage"]["input_tokens"] == 23
    assert (
        rows[1][1]["purpose"]
        == {
            "learning": "learning_extraction",
            "compaction": "context_compaction",
            "dreaming": "memory_dreaming",
        }[consumer]
    )
    assert rows[1][1]["effort"] == call.await_args.kwargs["effort"] == "max"
    assert "purpose" not in call.await_args.kwargs


@pytest.mark.parametrize("present", [True, False])
@pytest.mark.parametrize("empty", [True, False])
def test_codex_search_retains_final_usage_without_changing_wire(
    monkeypatch: pytest.MonkeyPatch, present: bool, empty: bool
) -> None:
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    usage = (
        SimpleNamespace(
            input_tokens=12, output_tokens=3, input_tokens_details=SimpleNamespace(cached_tokens=0)
        )
        if present
        else None
    )
    final = SimpleNamespace(usage=usage, output=[], output_text="", status="completed")

    class Stream:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get_final_response(self) -> Any:
            return final

        async def __aiter__(self) -> Any:
            if not empty:
                yield SimpleNamespace(
                    type="response.output_item.done",
                    item=SimpleNamespace(
                        type="message", content=[SimpleNamespace(type="output_text", text="hit")]
                    ),
                )

    wire: list[dict[str, Any]] = []

    def stream(**kwargs: Any) -> Stream:
        wire.append(kwargs)
        return Stream()

    adapter = CodexOAuthAdapter()
    monkeypatch.setattr(
        adapter,
        "_get_client",
        lambda model="": SimpleNamespace(responses=SimpleNamespace(stream=stream)),
    )
    if empty:
        with pytest.raises(EmptyModelOutputError) as caught:
            asyncio.run(adapter.aweb_search("query", model="gpt-5.6-sol"))
        result_usage = caught.value.completed_result.usage
    else:
        result_usage = asyncio.run(adapter.aweb_search("query", model="gpt-5.6-sol")).usage
    assert result_usage is not None
    assert result_usage.cached_input_tokens == 0
    assert result_usage.cached_input_tokens_present is present
    assert result_usage.input_tokens_present is present
    assert wire[0]["model"] == "gpt-5.6-sol" and wire[0]["store"] is False
    assert "reasoning" not in wire[0] and "max_output_tokens" not in wire[0]


def test_context_exhausted_notice_has_no_model_call_or_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop.models import _context_exhausted_message
    from core.config import settings

    monkeypatch.setattr(settings, "model", "gpt-5.6-sol")
    monkeypatch.setattr(settings, "openai_credential_source", "api_key")
    call = AsyncMock(
        return_value=TextCompletionResult(text="Automatically reset.", usage=UsageSummary())
    )
    _adapter(monkeypatch, call)
    hooks, rows = _observations()
    try:
        notice = asyncio.run(
            _context_exhausted_message(
                "Continue",
                effort="max",
                hooks=hooks,
                correlation={"session_id": "exhausted-session", "turn_id": "terminal-turn"},
            )
        )
        assert "exhausted" in notice.lower()
        assert "reset" not in notice.lower()
        call.assert_not_awaited()
        assert rows == []
    finally:
        hooks.close()
