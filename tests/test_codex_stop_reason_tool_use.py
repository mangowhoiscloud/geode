"""Regression pin for PR-CODEX-STOP-REASON-TOOL-USE (2026-05-28).

The Codex backend at ``chatgpt.com/backend-api/codex`` returns
``status="completed"`` for EVERY successful response, regardless of
whether the model emitted ``function_call`` items. The legacy
``normalize_openai_responses`` derived ``stop_reason`` from
``has_function_calls`` — the new
``core/llm/adapters/translation.py:_translate_stop_reason`` initially
only looked at the provider string, so ``"completed"`` mapped to
``"end_turn"``. The agent loop then terminated the turn (treating the
response as text-only), appended the assistant message with
``tool_use`` blocks BUT skipped tool execution. The next turn's input
carried a ``function_call`` with no matching ``function_call_output``
and the Codex backend rejected with ``"No tool output found for
function call call_XXXX"`` 400.

The fix gates the translation on ``has_tool_uses``: presence of
``tool_uses`` always wins, regardless of provider string.

Symptom reproduction was direct from the operator's serve log:

    08:51:54.087  codex-oauth resp_input shape: ...
        [3]function_call keys=['arguments', 'call_id', 'name', 'type']
        [4]function_call keys=['arguments', 'call_id', 'name', 'type']
        [5]user content=str(34)   ← function_call_output should be here
    08:51:55.116  codex-oauth: responses.stream failed err='No tool
        output found for function call call_cVsJdIt2d3TgMtn1i7UHqs2O'
"""

from __future__ import annotations

from core.llm.adapters.base import AdapterCallResult, UsageSummary
from core.llm.adapters.translation import (
    _translate_stop_reason,
    agentic_response_from_adapter_result,
)


def _make_result(*, stop_reason: str, tool_uses: tuple = ()) -> AdapterCallResult:
    return AdapterCallResult(
        text="here's a tool call" if tool_uses else "plain text response",
        usage=UsageSummary(input_tokens=10, output_tokens=20),
        stop_reason=stop_reason,
        tool_uses=tool_uses,
        raw_response=None,
    )


# ---------------------------------------------------------------------------
# _translate_stop_reason — direct contract
# ---------------------------------------------------------------------------


def test_translate_stop_reason_codex_completed_with_tool_uses_is_tool_use() -> None:
    """The core fix: Codex returns ``"completed"`` AND tool_uses are
    non-empty → must be ``"tool_use"`` so the loop executes tools."""
    assert _translate_stop_reason("completed", has_tool_uses=True) == "tool_use"


def test_translate_stop_reason_codex_completed_without_tool_uses_is_end_turn() -> None:
    """Pure text response from Codex (``"completed"``, no tool_uses) →
    ``"end_turn"`` so the loop terminates naturally."""
    assert _translate_stop_reason("completed", has_tool_uses=False) == "end_turn"


def test_translate_stop_reason_anthropic_tool_use_string_with_tool_uses_works() -> None:
    """Happy path — Anthropic ``"tool_use"`` string + non-empty tool_uses."""
    assert _translate_stop_reason("tool_use", has_tool_uses=True) == "tool_use"


def test_translate_stop_reason_provider_says_tool_use_but_empty_is_end_turn(caplog) -> None:  # type: ignore[no-untyped-def]
    """**Mirror anti-pattern** — provider sends ``"tool_use"`` /
    ``"tool_calls"`` but the adapter forgot to extract ``tool_uses``.

    Frontier pattern (paperclip + hermes audit, 2026-05-28): content is
    the source of truth. Without ``tool_uses`` to execute, treating the
    response as ``"tool_use"`` would spin the agent loop with no work.
    We instead terminate with ``"end_turn"`` and log a WARN flagging
    the likely adapter extraction bug.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="core.llm.adapters.translation"):
        assert _translate_stop_reason("tool_use", has_tool_uses=False) == "end_turn"
        assert _translate_stop_reason("tool_calls", has_tool_uses=False) == "end_turn"
    matching = [r for r in caplog.records if "tool_uses is empty" in r.message]
    assert len(matching) == 2, (
        f"Expected 2 WARN records flagging the adapter extraction bug, got "
        f"{len(matching)}. Visible records: {[m.message for m in caplog.records]}"
    )


def test_translate_stop_reason_openai_chat_tool_calls_works() -> None:
    """OpenAI Chat Completions ``"tool_calls"`` finish_reason mapping
    (happy path with non-empty tool_uses)."""
    assert _translate_stop_reason("tool_calls", has_tool_uses=True) == "tool_use"


def test_translate_stop_reason_openai_stop_with_tool_uses_is_tool_use() -> None:
    """Content-first invariant: OpenAI returning ``"stop"`` alongside
    non-empty tool_uses still surfaces as ``"tool_use"``. Mirrors the
    legacy ``has_function_calls`` precedence."""
    assert _translate_stop_reason("stop", has_tool_uses=True) == "tool_use"


def test_translate_stop_reason_anthropic_end_turn_no_tool_uses_is_end_turn() -> None:
    """Standard terminal-text-response case."""
    assert _translate_stop_reason("end_turn", has_tool_uses=False) == "end_turn"


def test_translate_stop_reason_unknown_provider_string_without_tool_uses_is_end_turn() -> None:
    """Anything not recognised + no tool_uses → conservative end_turn."""
    assert _translate_stop_reason("something_weird", has_tool_uses=False) == "end_turn"
    assert _translate_stop_reason("", has_tool_uses=False) == "end_turn"


# ---------------------------------------------------------------------------
# agentic_response_from_adapter_result — end-to-end through the bridge
# ---------------------------------------------------------------------------


def test_bridge_codex_completed_with_tool_uses_yields_tool_use_stop_reason() -> None:
    """The exact production scenario: adapter returned
    ``stop_reason="completed"`` (Codex backend) and a non-empty
    ``tool_uses`` tuple (one or more function_call items extracted
    from the SSE stream). The bridge must surface
    ``AgenticResponse.stop_reason="tool_use"`` so AgenticLoop's
    ``while stop_reason == "tool_use":`` keeps the loop alive and
    executes the tool."""
    result = _make_result(
        stop_reason="completed",
        tool_uses=({"id": "call_abc", "name": "read", "input": '{"path": "/tmp/x"}'},),
    )
    response = agentic_response_from_adapter_result(result)
    assert response.stop_reason == "tool_use", (
        f"Bridge surfaced stop_reason={response.stop_reason!r} for a "
        f"Codex 'completed' response with tool_uses — the agent loop "
        f"will terminate the turn without executing the tool, the "
        f"assistant message will be persisted with a tool_use but no "
        f"matching tool_result, and the next turn's input will be "
        f"rejected by the Codex backend with 'No tool output found "
        f"for function call' 400."
    )
    # The ToolUseBlock must also be present in content so the next-turn
    # input builder can emit the matching function_call entry.
    tool_use_blocks = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
    assert len(tool_use_blocks) == 1, (
        f"Expected exactly 1 ToolUseBlock; got {len(tool_use_blocks)} "
        f"(content={response.content!r})"
    )
    assert tool_use_blocks[0].id == "call_abc"


def test_bridge_codex_completed_without_tool_uses_yields_end_turn() -> None:
    """Pure text response from Codex stays end_turn — the loop terminates
    naturally, no spurious extra LLM call."""
    result = _make_result(stop_reason="completed")
    response = agentic_response_from_adapter_result(result)
    assert response.stop_reason == "end_turn"
