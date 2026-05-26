"""PR-CODEX-MULTITURN-PHASE-PRESERVE (Sprint H follow-up, 2026-05-26)
— round-trip preservation of ``ResponseOutputMessage.phase`` across
the Codex Responses API multi-turn replay.

OpenAI Responses API's ``ResponseOutputMessage.phase`` is
``Optional[Literal["commentary", "final_answer"]]``. The same slot
appears on ``EasyInputMessageParam`` (request input), so multi-turn
replay needs to carry the attribution through:

  capture (translate_codex_response)
  → AdapterCallResult.assistant_phase
  → AgenticResponse.assistant_phase (agentic_response_from_adapter_result)
  → AgenticLoop persists ``_assistant_msg["phase"]``
  → adapter_request_from_legacy reads dict m["phase"] → Message.phase
  → build_codex_input → _convert_assistant_msg_to_responses
    emits ``{"role": "assistant", ..., "phase": ...}``

Tests pin each link of the chain.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.llm.adapters._openai_common import (
    _convert_assistant_msg_to_responses,
    build_codex_input,
    translate_codex_response,
)
from core.llm.adapters.base import AdapterCallRequest, Message


def _empty_response() -> SimpleNamespace:
    return SimpleNamespace(output_text="", output=[], status="completed", usage=None)


def _message_item(text: str, *, phase: str | None = None) -> SimpleNamespace:
    block = SimpleNamespace(type="output_text", text=text)
    return SimpleNamespace(type="message", role="assistant", content=[block], phase=phase)


def test_translate_codex_response_captures_phase_from_message_item() -> None:
    """When the Codex response carries a message item with
    ``phase="commentary"``, that attribution lands on
    ``AdapterCallResult.assistant_phase``."""
    msg = _message_item("intermediate thought", phase="commentary")
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.text == "intermediate thought"
    assert result.assistant_phase == "commentary"


def test_translate_codex_response_captures_final_answer_phase() -> None:
    """Same invariant for the ``final_answer`` value."""
    msg = _message_item("the answer is 42", phase="final_answer")
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.assistant_phase == "final_answer"


def test_translate_codex_response_empty_phase_when_message_has_no_phase() -> None:
    """No-op guarantee — message items without ``phase`` produce an
    empty string (back-compat with non-phase-aware responses)."""
    msg = _message_item("vanilla response", phase=None)
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.assistant_phase == ""


def test_translate_codex_response_phase_capture_alongside_populated_text() -> None:
    """Phase capture must work even when ``response.output_text`` was
    already populated by the SDK (no SSE-fallback needed). The phase
    lives on the message item, not on the aggregated text accessor."""
    response = SimpleNamespace(
        output_text="server-aggregated", output=[], status="completed", usage=None
    )
    msg = _message_item("ignored — text already set", phase="final_answer")
    result = translate_codex_response(response, accumulated_items=[msg])
    assert result.text == "server-aggregated"
    assert result.assistant_phase == "final_answer"


def test_convert_assistant_msg_emits_phase_when_set() -> None:
    """The replay path emits ``phase`` on the output dict when the
    caller passes ``phase="commentary"``. Empty (default) skips the
    field — back-compat with every non-Codex caller."""
    items = _convert_assistant_msg_to_responses(
        [{"type": "text", "text": "hello"}], phase="commentary"
    )
    assert len(items) == 1
    assert items[0] == {"role": "assistant", "content": "hello", "phase": "commentary"}


def test_convert_assistant_msg_empty_phase_omits_field() -> None:
    """Empty phase string must not add the field to the output dict."""
    items = _convert_assistant_msg_to_responses([{"type": "text", "text": "hello"}], phase="")
    assert items[0] == {"role": "assistant", "content": "hello"}
    assert "phase" not in items[0]


def test_convert_assistant_msg_string_content_with_phase() -> None:
    """String-shape content path also honours phase."""
    items = _convert_assistant_msg_to_responses("plain string", phase="final_answer")
    assert items == [{"role": "assistant", "content": "plain string", "phase": "final_answer"}]


def test_convert_assistant_msg_text_plus_tool_use_attaches_phase_to_text() -> None:
    """When content has text+tool_use blocks, ``phase`` attaches to
    every text item; tool_use items don't carry phase (server-side
    they're function_calls, no semantic phase)."""
    content = [
        {"type": "text", "text": "I'll search."},
        {"type": "tool_use", "id": "call_1", "name": "search", "input": {"q": "x"}},
    ]
    items = _convert_assistant_msg_to_responses(content, phase="commentary")
    # First item is the text with phase
    assert items[0] == {
        "role": "assistant",
        "content": "I'll search.",
        "phase": "commentary",
    }
    # Second item is function_call — no phase
    assert items[1]["type"] == "function_call"
    assert "phase" not in items[1]


def test_build_codex_input_forwards_phase_from_message() -> None:
    """End-to-end through ``build_codex_input``: a Message with
    ``phase="final_answer"`` flows into the codex input array as
    ``{role: "assistant", phase: "final_answer", ...}``."""
    req = AdapterCallRequest(
        model="gpt-5.5",
        messages=(
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello back", phase="commentary"),
            Message(role="user", content="follow-up"),
        ),
        system_prompt="you are helpful",
    )
    items = build_codex_input(req)
    # First user message
    assert items[0] == {"role": "user", "content": "hi"}
    # Assistant message with phase
    assert items[1] == {
        "role": "assistant",
        "content": "hello back",
        "phase": "commentary",
    }
    # Second user message
    assert items[2] == {"role": "user", "content": "follow-up"}


def test_message_phase_default_empty_for_backcompat() -> None:
    """Existing call sites that construct ``Message(role, content, ...)``
    without ``phase`` get the back-compat empty string default."""
    m = Message(role="assistant", content="hi")
    assert m.phase == ""


def test_phase_survives_checkpoint_resume_cycle(tmp_path) -> None:
    """Codex MCP HIGH catch fold — ``_assistant_msg["phase"]`` must
    survive the SQLite checkpoint/resume cycle. Pre-fold the session
    manager's ``_extract_message_fields`` dropped the sidecar key on
    the way IN (documented but not implemented), so resume saw
    ``phase`` implicitly empty and the next-turn replay lost the
    attribution. The fix folds Codex sidecar keys (``phase`` +
    ``codex_reasoning_items``) into ``metadata`` at extract time and
    un-folds them at ``_row_to_message``."""
    from core.memory.session_manager import _extract_message_fields

    # Extract phase as a top-level msg key
    extracted = _extract_message_fields(
        {"role": "assistant", "content": "first answer", "phase": "final_answer"}
    )
    # Phase should be folded into metadata (JSON-serialised at the column)
    import json as _json

    assert extracted["metadata"] is not None
    parsed_meta = _json.loads(extracted["metadata"])
    assert parsed_meta["phase"] == "final_answer"


def test_codex_reasoning_items_also_survive_checkpoint(tmp_path) -> None:
    """Same fold also rescues ``codex_reasoning_items`` which had been
    silently dropped pre-fold (parallel bug surfaced by the same
    Codex MCP review)."""
    from core.memory.session_manager import _extract_message_fields

    items = [{"type": "reasoning", "encrypted_content": "ENC_A", "summary": []}]
    extracted = _extract_message_fields(
        {
            "role": "assistant",
            "content": "answer",
            "codex_reasoning_items": items,
            "phase": "commentary",
        }
    )
    import json as _json

    assert extracted["metadata"] is not None
    parsed_meta = _json.loads(extracted["metadata"])
    assert parsed_meta["phase"] == "commentary"
    assert parsed_meta["codex_reasoning_items"] == items


def test_round_trip_phase_capture_to_replay() -> None:
    """Full round-trip — phase captured from a Codex response item
    survives back into the next-turn codex input."""
    # Turn 1 simulated capture:
    msg_item = _message_item("first answer", phase="final_answer")
    result = translate_codex_response(_empty_response(), accumulated_items=[msg_item])
    assert result.assistant_phase == "final_answer"

    # AgenticLoop would persist this as _assistant_msg["phase"] in the
    # next-turn messages list. Simulate that via translation:
    next_turn_msg = Message(role="assistant", content=result.text, phase=result.assistant_phase)

    # Turn 2 build_codex_input replay:
    req = AdapterCallRequest(
        model="gpt-5.5",
        messages=(Message(role="user", content="prev?"), next_turn_msg),
    )
    items = build_codex_input(req)
    assert items[1] == {
        "role": "assistant",
        "content": "first answer",
        "phase": "final_answer",
    }
