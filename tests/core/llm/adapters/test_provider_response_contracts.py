"""Provider stop, replay, structured-output and context-management contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from core.agent.loop import _guards, _phases, _response
from core.agent.loop.models import TerminationReason, TurnState
from core.llm.adapters._anthropic_common import build_create_kwargs, translate_response
from core.llm.adapters._openai_common import (
    _is_openai_strict_compatible,
    build_chat_completion_kwargs,
    build_codex_input,
    build_responses_kwargs,
    translate_chat_response,
)
from core.llm.adapters.base import AdapterCallRequest, AdapterCallResult, UsageSummary
from core.llm.adapters.glm_coding_plan import GlmCodingPlanAdapter
from core.llm.adapters.glm_payg import GlmPaygAdapter
from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter
from core.llm.adapters.translation import (
    agentic_response_from_adapter_result,
    build_adapter_request,
)
from core.llm.agentic_response import AgenticResponse, parse_chat_reasoning_replay
from core.llm.errors import LLMRequestValidationError, ModelSourceUnavailableError
from core.llm.fallback import classify_retry_error, provider_retry_policy, run_with_retry_policy
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from core.memory.session_manager import SessionManager, SessionMeta


def _request(messages: list[dict[str, Any]], model: str) -> AdapterCallRequest:
    return build_adapter_request(
        model=model,
        system="",
        messages=messages,
        tools=[],
        tool_choice="auto",
        max_tokens=128,
        temperature=None,
        thinking_budget=0,
        effort="low",
    )


def _loop() -> SimpleNamespace:
    return SimpleNamespace(
        _set_llm_retry_count=Mock(),
        _track_usage_async=AsyncMock(),
        _op_logger=SimpleNamespace(finalize=Mock()),
        _extract_text=lambda value: value.text,
        _serialize_content=lambda blocks: _response.serialize_content(None, blocks),
        context=SimpleNamespace(messages=[]),
        _record_text_only_round=AsyncMock(),
        _tool_processor=SimpleNamespace(tool_log=[]),
    )


@pytest.mark.parametrize("category", ["cyber", None, {"unexpected": "payload"}])
def test_anthropic_refusal_reaches_guard_without_dispatch(
    category: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category=category, explanation="private"),
        content=[
            SimpleNamespace(type="text", text="partial output"),
            SimpleNamespace(type="tool_use", id="call", name="shell", input={}),
        ],
        usage=None,
    )
    response = agentic_response_from_adapter_result(translate_response(raw))
    assert response.stop_reason == "refusal"
    assert response.content == []
    assert response.stop_details == {
        "type": "refusal",
        "category": "cyber" if category == "cyber" else None,
    }
    terminal = Mock(return_value="refused")
    monkeypatch.setattr(_guards, "_terminal_result", terminal)
    assert _guards._guard_model_refusal(_loop(), response, messages=[], round_idx=0) == "refused"
    assert terminal.call_args.args[1] is TerminationReason.MODEL_REFUSAL
    assert "private" not in str(terminal.call_args)
    assert "partial output" not in str(terminal.call_args)


@pytest.mark.parametrize(
    "stop,expected",
    [
        ("completed", "end_turn"),
        ("length", "max_tokens"),
        ("max_tokens", "max_tokens"),
        ("incomplete", "incomplete"),
        ("content_filter", "refusal"),
    ],
)
def test_non_tool_stop_semantics(stop: str, expected: str) -> None:
    result = AdapterCallResult(text="", stop_reason=stop, usage=UsageSummary())
    assert agentic_response_from_adapter_result(result).stop_reason == expected


def test_completed_codex_calls_still_continue() -> None:
    result = AdapterCallResult(
        text="",
        usage=UsageSummary(),
        stop_reason="completed",
        tool_uses=({"id": "c", "name": "read_file", "input": {}},),
    )
    assert agentic_response_from_adapter_result(result).stop_reason == "tool_use"


@pytest.mark.parametrize(
    "provider,source,model,fields",
    [
        ("glm", "glm-payg", "glm-5", {"reasoning_content": "original reasoning"}),
        ("glm", "glm-coding-plan", "glm-5", {"reasoning_content": "original reasoning"}),
        (
            "openrouter",
            "openrouter-payg",
            "anthropic/claude-fable-5",
            {
                "reasoning": "summary",
                "reasoning_details": [
                    {"type": "reasoning.text", "text": "first", "signature": "signed", "index": 0},
                    {"type": "reasoning.encrypted", "data": "opaque", "index": 1},
                ],
            },
        ),
    ],
)
def test_chat_replay_survives_tool_result_and_database_resume(
    provider: str,
    source: str,
    model: str,
    fields: dict[str, Any],
    tmp_path: Path,
) -> None:
    raw = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id="call", function=SimpleNamespace(name="read_file", arguments="{}")
                        )
                    ],
                    **fields,
                ),
            )
        ],
        usage=None,
    )
    result = translate_chat_response(raw, provider=provider, adapter_name=source, model=model)
    response = agentic_response_from_adapter_result(result)
    assistant = _guards._tool_round_assistant_message(_loop(), response)
    messages = [
        assistant,
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call", "content": "done"}],
        },
    ]
    manager = SessionManager(db_path=tmp_path / "sessions.db")
    try:
        manager.upsert(
            SessionMeta(session_id="chat", created_at=1.0, updated_at=1.0, status="active")
        )
        manager.upsert_messages("chat", messages)
        restored = manager.get_messages("chat")
    finally:
        manager.close()
    assert restored[0]["chat_reasoning"] == assistant["chat_reasoning"]
    checkpoint_dir = tmp_path / "checkpoint"
    SessionCheckpoint(checkpoint_dir).save(
        SessionState(session_id="chat", messages=messages), strict_messages=True
    )
    resumed = SessionCheckpoint(checkpoint_dir).load("chat")
    assert resumed is not None
    assert resumed.messages[0]["chat_reasoning"] == assistant["chat_reasoning"]
    assert resumed.messages[0]["chat_reasoning"]["fields"] == fields
    request = _request(restored, model)
    wire = build_chat_completion_kwargs(
        request, provider=provider, adapter_name=source, model=model
    )["messages"]
    assert {key: wire[0][key] for key in fields} == fields
    assert wire[1] == {"role": "tool", "tool_call_id": "call", "content": "done"}
    assert "reasoning_details" not in json.dumps(build_codex_input(request))
    for changed in ({"provider": "other"}, {"adapter_name": "other"}, {"model": "other"}):
        route = {"provider": provider, "adapter_name": source, "model": model, **changed}
        changed_wire = build_chat_completion_kwargs(request, **route)["messages"]
        assert all(key not in changed_wire[0] for key in fields)


def test_malformed_chat_sequence_is_not_partially_replayed() -> None:
    assert (
        parse_chat_reasoning_replay(
            {
                "provider": "openrouter",
                "source": "openrouter-payg",
                "model": "m",
                "fields": {"reasoning_details": [{"type": "reasoning.text"}, "malformed"]},
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "adapter,model,wire_model",
    [
        (GlmPaygAdapter(), "glm-5", "glm-5"),
        (GlmCodingPlanAdapter(), "glm-5", "glm-5"),
        (
            OpenRouterPaygAdapter(),
            "openrouter/anthropic/claude-fable-5",
            "anthropic/claude-fable-5",
        ),
    ],
)
def test_concrete_chat_adapters_capture_and_replay_on_next_request(
    adapter: Any,
    model: str,
    wire_model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content="",
                    reasoning_content="private native state",
                    tool_calls=[
                        SimpleNamespace(
                            id="call",
                            function=SimpleNamespace(name="read_file", arguments="{}"),
                        )
                    ],
                ),
            )
        ],
        usage=None,
    )
    create = AsyncMock(return_value=raw)
    monkeypatch.setattr(
        adapter,
        "_get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    if isinstance(adapter, GlmCodingPlanAdapter):
        with pytest.raises(ModelSourceUnavailableError, match="GEODE"):
            asyncio.run(adapter.acomplete(_request([], model)))
        create.assert_not_called()
        return
    result = asyncio.run(adapter.acomplete(_request([], model)))
    assert result.chat_reasoning is not None
    assert result.chat_reasoning["source"] == adapter.name
    assert result.chat_reasoning["provider"] == adapter.provider
    assert result.chat_reasoning["model"] == wire_model
    assistant = _guards._tool_round_assistant_message(
        _loop(), agentic_response_from_adapter_result(result)
    )
    messages = [
        assistant,
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call", "content": "done"}],
        },
    ]
    asyncio.run(adapter.acomplete(_request(messages, model)))
    assert create.call_args.kwargs["messages"][0]["reasoning_content"] == "private native state"


def test_terminal_chat_response_retains_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    replay = parse_chat_reasoning_replay(
        {
            "provider": "glm",
            "source": "glm-payg",
            "model": "glm-5",
            "fields": {"reasoning_content": "original"},
        }
    )
    response = AgenticResponse(chat_reasoning=replay)
    loop = _loop()
    turn = _phases.PreparedTurn("task", [], TurnState(turn_id="t"), "system", "", "", False)
    monkeypatch.setattr(_guards, "_guard_cost_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(_guards, "_terminal_result", lambda *_a, **_kw: None)
    monkeypatch.setattr(_phases, "assemble_termination", AsyncMock())
    asyncio.run(
        _phases.process_tool_calls(loop, turn, response, 0, is_last_round=False, step_snapshot=None)
    )
    assert loop.context.messages[0]["chat_reasoning"] == replay


@pytest.mark.parametrize("model", ["openrouter/auto", "openrouter/free"])
def test_dynamic_openrouter_model_never_replays_native_reasoning(model: str) -> None:
    fields = {"reasoning_content": "upstream-specific state"}
    raw = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content="answer", **fields)
            )
        ],
        usage=None,
    )
    result = translate_chat_response(
        raw, provider="openrouter", adapter_name="openrouter-payg", model=model
    )
    assert result.chat_reasoning is None
    request = _request(
        [
            {
                "role": "assistant",
                "content": "answer",
                "chat_reasoning": {
                    "provider": "openrouter",
                    "source": "openrouter-payg",
                    "model": model,
                    "fields": fields,
                },
            }
        ],
        model,
    )
    wire = build_chat_completion_kwargs(
        request, provider="openrouter", adapter_name="openrouter-payg", model=model
    )
    assert "reasoning_content" not in wire["messages"][0]


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string"},
        {"anyOf": [_object({})]},
        _object({"x": {"allOf": [{"type": "string"}]}}),
        _object({"x": {"oneOf": [{"type": "string"}]}}),
        {**_object({}), "$defs": {"open": {"type": "object", "properties": {}}}},
        _object({"x": {"type": ["object", "null"], "properties": {}}}),
    ],
)
def test_strict_classifier_rejects_unsupported_shapes(schema: dict[str, Any]) -> None:
    assert not _is_openai_strict_compatible(schema)


@pytest.mark.parametrize("backend", ["platform", "codex"])
def test_strict_nested_anyof_and_recursive_defs(backend: str) -> None:
    schema = _object({"node": {"$ref": "#/$defs/node"}})
    schema["$defs"] = {
        "node": _object({"next": {"anyOf": [{"$ref": "#/$defs/node"}, {"type": "null"}]}})
    }
    req = AdapterCallRequest(model="gpt-6-astra", messages=(), response_schema=schema)
    assert (
        build_responses_kwargs(req, backend=backend, adapter_name="test")["text"]["format"][
            "strict"
        ]
        is True
    )
    additive = AdapterCallRequest(
        model="gpt-6-astra", messages=(), response_schema={"type": "object", "properties": {}}
    )
    assert (
        build_responses_kwargs(additive, backend=backend, adapter_name="test")["text"]["format"][
            "strict"
        ]
        is False
    )


@pytest.mark.parametrize("backend", ["platform", "codex"])
@pytest.mark.parametrize("schema", [{"type": "string"}, {"type": "object", "anyOf": [_object({})]}])
def test_invalid_response_schema_root_fails_before_request(
    backend: str, schema: dict[str, Any]
) -> None:
    with pytest.raises(LLMRequestValidationError, match="object root"):
        build_responses_kwargs(
            AdapterCallRequest(model="gpt-6-astra", messages=(), response_schema=schema),
            backend=backend,
            adapter_name="test",
        )


def test_invalid_response_schema_does_not_retry_or_switch_models() -> None:
    attempted: list[str] = []

    async def call(model: str) -> None:
        attempted.append(model)
        build_responses_kwargs(
            AdapterCallRequest(model=model, messages=(), response_schema={"type": "string"}),
            backend="platform",
            adapter_name="openai-payg",
        )

    with pytest.raises(LLMRequestValidationError) as caught:
        asyncio.run(
            run_with_retry_policy(
                ["gpt-6-astra", "gpt-5.6-sol"],
                call,
                policy=provider_retry_policy(max_attempts=3),
            )
        )
    assert classify_retry_error(caught.value) == "bad_request"
    assert attempted == ["gpt-6-astra"]


@pytest.mark.parametrize(
    "model", ["claude-opus-4-5", "claude-sonnet-4-5", "claude-sonnet-4-5-20250929"]
)
def test_45_context_editing_does_not_enable_compaction(model: str) -> None:
    kwargs = build_create_kwargs(AdapterCallRequest(model=model, messages=()))
    assert [edit["type"] for edit in kwargs["extra_body"]["context_management"]["edits"]] == [
        "clear_tool_uses_20250919"
    ]
    assert "compact-2026-01-12" not in kwargs["extra_headers"]["anthropic-beta"]


@pytest.mark.parametrize("model", ["claude-opus-4-6", "claude-sonnet-4-6", "claude-fable-5"])
def test_compaction_capability_remains_enabled(model: str) -> None:
    kwargs = build_create_kwargs(AdapterCallRequest(model=model, messages=()))
    assert [edit["type"] for edit in kwargs["extra_body"]["context_management"]["edits"]] == [
        "clear_tool_uses_20250919",
        "compact_20260112",
    ]
