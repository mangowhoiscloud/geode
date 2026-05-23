"""A2 multi-turn converter invariants — Anthropic content blocks ↔ OpenAI/Codex wire shape.

Pins the round-trip contract that Codex MCP 2026-05-23 BLOCKER 2 flagged:
the AgenticLoop emits assistant turns with ``tool_use`` blocks and user
turns with ``tool_result`` blocks (Anthropic shape). The OpenAI/Codex
adapter route re-encodes these into:

- OpenAI Chat: ``tool_calls`` array on assistant + ``role: tool`` with
  ``tool_call_id`` on user.
- Codex Responses: ``function_call`` / ``function_call_output`` typed
  items in the ``input`` array.

Without this conversion the SDK rejects with 400.
"""

from __future__ import annotations

import json

from core.llm.adapters._openai_common import (
    _convert_assistant_msg_to_chat,
    _convert_assistant_msg_to_responses,
    _convert_user_msg_to_chat,
    _convert_user_msg_to_responses,
    build_codex_input,
    build_messages,
)
from core.llm.adapters.base import AdapterCallRequest, Message

# ── Chat Completions converter ─────────────────────────────────────────────


def test_chat_assistant_text_only() -> None:
    msg = _convert_assistant_msg_to_chat([{"type": "text", "text": "hello"}])
    assert msg == {"role": "assistant", "content": "hello"}


def test_chat_assistant_tool_use() -> None:
    msg = _convert_assistant_msg_to_chat(
        [
            {"type": "text", "text": "calling search"},
            {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "geode"}},
        ]
    )
    assert msg["role"] == "assistant"
    assert msg["content"] == "calling search"
    assert msg["tool_calls"] == [
        {
            "id": "tu_1",
            "type": "function",
            "function": {"name": "search", "arguments": json.dumps({"q": "geode"})},
        }
    ]


def test_chat_assistant_tool_use_only_no_text() -> None:
    """When the assistant turn only emits tool_use, ``content`` is ``None``."""
    msg = _convert_assistant_msg_to_chat(
        [{"type": "tool_use", "id": "tu_1", "name": "x", "input": {}}]
    )
    assert msg["content"] is None
    assert len(msg["tool_calls"]) == 1


def test_chat_user_tool_result_splits_to_tool_role() -> None:
    msgs = _convert_user_msg_to_chat(
        [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "42"},
            {"type": "text", "text": "thanks"},
        ]
    )
    # tool_result → {"role": "tool", "tool_call_id": ..., "content": ...}
    assert msgs[0] == {"role": "tool", "tool_call_id": "tu_1", "content": "42"}
    # trailing text becomes a separate user message
    assert msgs[1] == {"role": "user", "content": "thanks"}


def test_chat_user_tool_result_dict_content_json_encoded() -> None:
    """Dict tool_result content stringifies to JSON for Chat's content field."""
    msgs = _convert_user_msg_to_chat(
        [{"type": "tool_result", "tool_use_id": "tu_1", "content": {"k": "v"}}]
    )
    assert msgs[0]["content"] == json.dumps({"k": "v"})


def test_build_messages_handles_anthropic_content_lists() -> None:
    """End-to-end: AdapterCallRequest with Anthropic-shaped messages."""
    req = AdapterCallRequest(
        model="gpt-5.5",
        system_prompt="be brief",
        messages=[
            Message(role="user", content="search geode"),
            Message(
                role="assistant",
                content=[{"type": "tool_use", "id": "tu_1", "name": "search", "input": {}}],
            ),
            Message(
                role="user",
                content=[{"type": "tool_result", "tool_use_id": "tu_1", "content": "found"}],
            ),
        ],
    )
    msgs = build_messages(req)
    assert msgs[0] == {"role": "system", "content": "be brief"}
    assert msgs[1] == {"role": "user", "content": "search geode"}
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["tool_calls"][0]["id"] == "tu_1"
    assert msgs[3] == {"role": "tool", "tool_call_id": "tu_1", "content": "found"}


# ── Codex Responses converter ──────────────────────────────────────────────


def test_responses_assistant_tool_use_typed_item() -> None:
    items = _convert_assistant_msg_to_responses(
        [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "x"}},
        ]
    )
    # text item comes first (preserving order from Anthropic block stream)
    assert items[0] == {"role": "assistant", "content": "thinking..."}
    assert items[1] == {
        "type": "function_call",
        "call_id": "tu_1",
        "name": "search",
        "arguments": json.dumps({"q": "x"}),
    }


def test_responses_user_tool_result_typed_item() -> None:
    items = _convert_user_msg_to_responses(
        [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"},
        ]
    )
    assert items[0] == {"type": "function_call_output", "call_id": "tu_1", "output": "ok"}


def test_responses_user_tool_result_dict_content_json_encoded() -> None:
    items = _convert_user_msg_to_responses(
        [{"type": "tool_result", "tool_use_id": "tu_1", "content": {"k": "v"}}]
    )
    assert items[0]["output"] == json.dumps({"k": "v"})


def test_build_codex_input_skips_system_prepend() -> None:
    """Codex carries system via ``instructions`` kwarg — build_codex_input must NOT
    prepend a ``role: system`` entry."""
    req = AdapterCallRequest(
        model="gpt-5.5",
        system_prompt="be brief",
        messages=[Message(role="user", content="hi")],
    )
    items = build_codex_input(req)
    assert all(item.get("role") != "system" for item in items)
    assert items[0] == {"role": "user", "content": "hi"}


# ── Per-turn reasoning replay (inline via build_codex_input) ──────────────


def test_build_codex_input_inserts_reasoning_at_assistant_turn() -> None:
    """codex_reasoning_items on an assistant Message prepend at THAT turn."""
    req = AdapterCallRequest(
        model="gpt-5.5",
        messages=[
            Message(role="user", content="first"),
            Message(
                role="assistant",
                content=[{"type": "text", "text": "reply 1"}],
                codex_reasoning_items=(
                    {"type": "reasoning", "encrypted_content": "blob_1", "id": "rs_1"},
                ),
            ),
            Message(role="user", content="second"),
            Message(
                role="assistant",
                content=[{"type": "text", "text": "reply 2"}],
                codex_reasoning_items=({"type": "reasoning", "encrypted_content": "blob_2"},),
            ),
        ],
    )
    items = build_codex_input(req)
    # Sequence: user1, reasoning_1, assistant1, user2, reasoning_2, assistant2
    assert items[0] == {"role": "user", "content": "first"}
    assert items[1]["type"] == "reasoning"
    assert items[1]["encrypted_content"] == "blob_1"
    assert "id" not in items[1]  # id stripped
    assert items[2] == {"role": "assistant", "content": "reply 1"}
    assert items[3] == {"role": "user", "content": "second"}
    assert items[4]["type"] == "reasoning"
    assert items[4]["encrypted_content"] == "blob_2"
    assert items[5] == {"role": "assistant", "content": "reply 2"}


def test_build_codex_input_skips_reasoning_without_encrypted_content() -> None:
    req = AdapterCallRequest(
        model="gpt-5.5",
        messages=[
            Message(
                role="assistant",
                content=[{"type": "text", "text": "reply"}],
                codex_reasoning_items=({"type": "reasoning", "summary": "no blob"},),
            ),
        ],
    )
    items = build_codex_input(req)
    # No reasoning item before assistant — only the assistant entry.
    assert items == [{"role": "assistant", "content": "reply"}]


def test_build_codex_input_no_reasoning_when_empty_tuple() -> None:
    req = AdapterCallRequest(
        model="gpt-5.5",
        messages=[
            Message(
                role="assistant",
                content=[{"type": "text", "text": "reply"}],
            ),
        ],
    )
    items = build_codex_input(req)
    assert items == [{"role": "assistant", "content": "reply"}]
