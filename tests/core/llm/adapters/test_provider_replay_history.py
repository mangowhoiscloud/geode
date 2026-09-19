"""Provider-native discovery history survives loop projection and resume."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from anthropic.types import Message as AnthropicMessage
from core.agent.conversation import ConversationContext
from core.agent.loop import _guards, _phases, _response
from core.agent.loop.models import TurnState
from core.llm.adapters._anthropic_common import build_messages, translate_response
from core.llm.adapters._openai_common import (
    build_codex_input,
    translate_codex_response,
)
from core.llm.adapters._openai_common import (
    build_messages as build_chat_messages,
)
from core.llm.adapters.translation import (
    agentic_response_from_adapter_result,
    build_adapter_request,
)
from core.llm.agentic_response import AgenticResponse, ToolUseBlock
from core.memory.session_manager import SessionManager, SessionMeta
from core.orchestration.compaction import repair_tool_pairs


def _anthropic_message(*, tool_call: bool = True) -> AnthropicMessage:
    content: list[dict[str, Any]] = [
        {"type": "thinking", "thinking": "Find the tool.", "signature": "test-signature"},
        {"type": "redacted_thinking", "data": "test-redacted"},
        {"type": "text", "text": "Searching."},
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "tool_search_tool_regex",
            "input": {"pattern": "do_work"},
        },
        {
            "type": "tool_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": {
                "type": "tool_search_tool_search_result",
                "tool_references": [{"type": "tool_reference", "tool_name": "do_work"}],
            },
        },
    ]
    if tool_call:
        content.append({"type": "tool_use", "id": "call_1", "name": "do_work", "input": {}})
    else:
        content.append({"type": "text", "text": "Found it."})
    return AnthropicMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5",
            "stop_reason": "tool_use" if tool_call else "end_turn",
            "stop_sequence": None,
            "content": content,
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }
    )


def _openai_response() -> AgenticResponse:
    items = [
        {
            "type": "tool_search_call",
            "id": "ts_1",
            "status": "completed",
            "execution": "server",
            "arguments": {"query": "do work"},
        },
        {
            "type": "tool_search_output",
            "id": "tso_1",
            "status": "completed",
            "execution": "server",
            "tools": [
                {
                    "type": "function",
                    "name": "do_work",
                    "parameters": {"type": "object", "properties": {}},
                    "defer_loading": True,
                }
            ],
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "do_work",
            "arguments": "{}",
            "status": "completed",
        },
    ]
    raw = SimpleNamespace(output_text="", output=items, status="completed", usage=None)
    return agentic_response_from_adapter_result(
        translate_codex_response(raw, accumulated_items=items)
    )


def _assistant_message(response: AgenticResponse) -> dict[str, Any]:
    loop = SimpleNamespace(
        _serialize_content=lambda blocks: _response.serialize_content(None, blocks)
    )
    return _guards._tool_round_assistant_message(loop, response)


def _request(messages: list[dict[str, Any]]) -> Any:
    return build_adapter_request(
        model="claude-haiku-4-5",
        system="system",
        messages=messages,
        tools=[],
        tool_choice="auto",
        max_tokens=100,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )


def _tool_result() -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "done"}],
    }


def test_anthropic_search_replays_full_assistant_order_but_executes_only_local_tool() -> None:
    raw = _anthropic_message()
    normalized = agentic_response_from_adapter_result(translate_response(raw))
    assistant = _assistant_message(normalized)
    req = _request([{"role": "user", "content": "work"}, assistant, _tool_result()])

    assert (
        build_messages(req)[1]["content"]
        == raw.model_dump(mode="json", exclude_none=True)["content"]
    )
    assert [
        (block.id, block.name) for block in normalized.content if isinstance(block, ToolUseBlock)
    ] == [("call_1", "do_work")]
    assert [block["type"] for block in assistant["content"]] == ["text", "tool_use"]


@pytest.mark.parametrize("backend", ["codex", "platform"])
def test_openai_full_search_cycle_preserves_order_and_local_result(backend: str) -> None:
    response = _openai_response()
    req = _request([_assistant_message(response), _tool_result()])
    items = build_codex_input(req, backend=backend)

    assert [item["type"] for item in items] == [
        "tool_search_call",
        "tool_search_output",
        "function_call",
        "function_call_output",
    ]
    assert items[1]["tools"][0]["name"] == "do_work"
    assert items[1]["tools"][0]["defer_loading"] is True
    assert items[2]["call_id"] == items[3]["call_id"] == "call_1"
    assert [block.name for block in response.content if isinstance(block, ToolUseBlock)] == [
        "do_work"
    ]


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_native_replay_survives_session_database_roundtrip(provider: str, tmp_path: Path) -> None:
    response = (
        agentic_response_from_adapter_result(translate_response(_anthropic_message()))
        if provider == "anthropic"
        else _openai_response()
    )
    assistant = _assistant_message(response)
    key = "anthropic_content" if provider == "anthropic" else "codex_output_items"
    manager = SessionManager(db_path=tmp_path / "sessions.db")
    try:
        manager.upsert(
            SessionMeta(session_id="replay", created_at=1.0, updated_at=1.0, status="active")
        )
        manager.upsert_messages("replay", [assistant, _tool_result()])
        restored = manager.get_messages("replay")
    finally:
        manager.close()

    assert key in assistant
    assert restored[0][key] == assistant[key]
    req = _request(restored)
    wire = build_messages(req) if provider == "anthropic" else build_codex_input(req)
    assert "tool_search" in json.dumps(wire)


@pytest.mark.parametrize("backend", ["chat", "platform", "codex"])
def test_anthropic_native_blocks_never_leak_to_other_provider(backend: str) -> None:
    response = agentic_response_from_adapter_result(translate_response(_anthropic_message()))
    req = _request([_assistant_message(response), _tool_result()])
    wire = (
        build_chat_messages(req) if backend == "chat" else build_codex_input(req, backend=backend)
    )
    encoded = json.dumps(wire)

    assert "do_work" in encoded
    assert "call_1" in encoded
    assert "srvtoolu_1" not in encoded
    assert "test-signature" not in encoded
    assert "tool_search_tool_result" not in encoded


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_compaction_repairs_only_local_calls_and_retains_server_search(provider: str) -> None:
    response = (
        agentic_response_from_adapter_result(translate_response(_anthropic_message()))
        if provider == "anthropic"
        else _openai_response()
    )
    assistant = _assistant_message(response)
    repaired = repair_tool_pairs([assistant])

    assert repaired[0] == assistant
    assert [block["tool_use_id"] for block in repaired[1]["content"]] == ["call_1"]
    req = _request(repaired)
    wire = build_messages(req) if provider == "anthropic" else build_codex_input(req)
    assert "tool_search" in json.dumps(wire)


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_interrupted_batch_recovery_never_executes_or_answers_server_tool(provider: str) -> None:
    response = (
        agentic_response_from_adapter_result(translate_response(_anthropic_message()))
        if provider == "anthropic"
        else _openai_response()
    )
    assistant = _assistant_message(response)
    store = SimpleNamespace(recover=Mock())
    loop = SimpleNamespace(
        context=ConversationContext(messages=[assistant]),
        _tool_processor=SimpleNamespace(_executor=SimpleNamespace(_effect_receipts=store)),
        _checkpoint=None,
        _session_id="",
        _save_checkpoint=Mock(return_value=True),
    )

    _phases._repair_incomplete_tool_round(loop, "resume")

    store.recover.assert_not_called()
    assert [block["tool_use_id"] for block in loop.context.messages[1]["content"]] == ["call_1"]
    req = _request(loop.context.messages)
    wire = build_messages(req) if provider == "anthropic" else build_codex_input(req)
    assert "tool_search" in json.dumps(wire)
    assert "tool_execution_interrupted" in json.dumps(wire)


@pytest.mark.parametrize("forced", [False, True])
def test_final_text_turn_retains_anthropic_search_replay(
    forced: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _anthropic_message(tool_call=False)
    response = agentic_response_from_adapter_result(translate_response(raw))
    loop = SimpleNamespace(
        _set_llm_retry_count=Mock(),
        _track_usage_async=AsyncMock(),
        _op_logger=SimpleNamespace(finalize=Mock()),
        _extract_text=lambda value: value.text,
        _serialize_content=lambda blocks: _response.serialize_content(None, blocks),
        context=SimpleNamespace(messages=[]),
        _record_text_only_round=AsyncMock(),
        _tool_processor=SimpleNamespace(tool_log=[]),
    )
    turn = _phases.PreparedTurn("task", [], TurnState(turn_id="turn"), "system", "", "", False)
    monkeypatch.setattr(_guards, "_guard_cost_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(_guards, "_guard_model_refusal", lambda *_a, **_kw: None)
    monkeypatch.setattr(_guards, "_terminal_result", lambda *_a, **_kw: None)
    monkeypatch.setattr(_phases, "assemble_termination", AsyncMock())

    asyncio.run(
        _phases.process_tool_calls(
            loop, turn, response, 0, is_last_round=forced, step_snapshot=None
        )
    )

    req = _request(loop.context.messages)
    assert (
        build_messages(req)[0]["content"]
        == raw.model_dump(mode="json", exclude_none=True)["content"]
    )
