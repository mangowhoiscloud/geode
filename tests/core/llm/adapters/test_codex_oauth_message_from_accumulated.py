"""PR-CODEX-OAUTH-MESSAGE-FROM-ACCUMULATED (Sprint H2, 2026-05-26)
— pin the SSE-message fallback in ``translate_codex_response``.

Root-cause evidence chain (smoke 20/21/22):
  * codex-oauth + gpt-5.x streaming has a documented discrepancy:
    SSE delivers ``response.output_item.done`` events with
    ``type=message role=assistant
    content=[ResponseOutputText(text=…)]`` but the aggregated
    ``stream.get_final_response().output[]`` is empty.
  * Pre-fix ``translate_codex_response`` only read ``text`` from
    ``response.output_text`` (which is empty when ``output[]`` is
    empty) AND only walked ``items_source`` for ``function_call`` +
    ``reasoning`` items — message text was dropped silently.
  * Minimal probe
    (``scripts/probes/probe_codex_oauth_message_recovery.py``)
    with a 25-token prompt ("Say 'hello world'") reproduces the
    empty ``response.output[]`` while SSE delivered the message
    item correctly with text='hello world'.

Fix walks ``items_source`` (which honours ``accumulated_items``
first) for ``type="message"`` items when ``response.output_text``
is empty, concatenates ``content[].text`` from ``output_text`` blocks,
and promotes that into ``result.text``.

Tests pin:
  1. Empty ``response.output_text`` + accumulated message item →
     result.text reflects the SSE-delivered text.
  2. Non-empty ``response.output_text`` is NOT overridden (no-op
     guarantee for healthy responses).
  3. Multiple ``output_text`` blocks in one message concatenate
     in order.
  4. Reasoning + message items in same accumulated list both
     surface correctly (reasoning_items preserved, text recovered).
  5. Function-call items in accumulated list still surface as
     tool_uses (no regression).
"""

from __future__ import annotations

from types import SimpleNamespace

from core.llm.adapters._openai_common import translate_codex_response


def _block(*, type: str, text: str = "") -> SimpleNamespace:
    """Minimal ``ResponseOutputText`` stand-in (SDK shape)."""
    return SimpleNamespace(type=type, text=text)


def _message_item(*blocks: SimpleNamespace) -> SimpleNamespace:
    """Minimal ``type=message`` output item stand-in."""
    return SimpleNamespace(type="message", role="assistant", content=list(blocks))


def _empty_response() -> SimpleNamespace:
    """Stand-in for ``response`` with empty ``output_text`` + ``output``
    — mirrors the codex-oauth + gpt-5.x streaming bug shape."""
    return SimpleNamespace(output_text="", output=[], status="completed", usage=None)


def test_message_text_recovered_from_accumulated_when_response_empty() -> None:
    """The smoke 20/21/22 voter case — final.output empty, SSE delivered
    a message item with text. Pre-fix this returned text='', causing
    100% codex voter failure across 3 smokes."""
    msg = _message_item(_block(type="output_text", text="hello world"))
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.text == "hello world", (
        f"PR-CODEX-OAUTH-MESSAGE-FROM-ACCUMULATED regression: expected "
        f"SSE-delivered message text to be recovered, got {result.text!r}"
    )


def test_message_text_concatenates_multiple_output_text_blocks() -> None:
    """When the assistant message has multiple ``output_text`` blocks
    (rare but allowed by the SDK shape), the fallback concatenates
    them in order — matches the SDK's own ``response.output_text``
    aggregation behaviour."""
    msg = _message_item(
        _block(type="output_text", text="part-A "),
        _block(type="output_text", text="part-B"),
    )
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.text == "part-A part-B"


def test_non_empty_response_output_text_not_overridden() -> None:
    """No-op guarantee — when the server returns a populated
    ``response.output_text`` the fallback is skipped so healthy
    responses are byte-identical to the pre-fix path."""
    response = SimpleNamespace(
        output_text="server-aggregated", output=[], status="completed", usage=None
    )
    msg = _message_item(_block(type="output_text", text="from-sse-different"))
    result = translate_codex_response(response, accumulated_items=[msg])
    assert result.text == "server-aggregated", (
        f"Fallback must NOT override response.output_text — got {result.text!r}"
    )


def test_reasoning_and_message_both_surface() -> None:
    """When SSE delivers both a reasoning item and a message item
    (the common gpt-5.x case), reasoning_items captures the encrypted
    blob and result.text captures the visible message — both paths
    populated from the same accumulated list."""
    reasoning = SimpleNamespace(
        type="reasoning",
        encrypted_content="ENCRYPTED",
        summary=[],
        id="rs_123",
    )
    msg = _message_item(_block(type="output_text", text="visible answer"))
    result = translate_codex_response(_empty_response(), accumulated_items=[reasoning, msg])
    assert result.text == "visible answer"
    assert len(result.reasoning_items) == 1
    assert result.reasoning_items[0]["encrypted_content"] == "ENCRYPTED"
    assert result.reasoning_items[0]["summary"] == []


def test_function_call_items_still_surface_in_tool_uses() -> None:
    """Regression guard — adding the message-fallback walk must not
    drop function_call extraction."""
    func = SimpleNamespace(
        type="function_call",
        call_id="call_x1",
        id="ignored",
        name="my_tool",
        arguments='{"foo": 1}',
    )
    msg = _message_item(_block(type="output_text", text="picked tool"))
    result = translate_codex_response(_empty_response(), accumulated_items=[func, msg])
    assert result.text == "picked tool"
    assert len(result.tool_uses) == 1
    assert result.tool_uses[0]["id"] == "call_x1"
    assert result.tool_uses[0]["name"] == "my_tool"


def test_message_without_output_text_blocks_returns_empty() -> None:
    """Edge case — a message item with no output_text blocks (only,
    say, an annotation-only block) yields empty text, not a crash."""
    msg = SimpleNamespace(
        type="message",
        role="assistant",
        content=[SimpleNamespace(type="annotation_only", text="not-output-text")],
    )
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.text == ""


def test_falls_back_to_response_output_when_accumulated_none() -> None:
    """Non-streaming caller path — ``accumulated_items=None`` makes
    ``items_source`` fall through to ``response.output``. The fallback
    walk still applies to that source when response.output_text empty."""
    msg = _message_item(_block(type="output_text", text="from-response-output"))
    response = SimpleNamespace(output_text="", output=[msg], status="completed", usage=None)
    result = translate_codex_response(response, accumulated_items=None)
    assert result.text == "from-response-output"


def test_refusal_block_extracted_into_text() -> None:
    """SDK ``ResponseOutputMessage.content`` can be ``ResponseOutputText``
    OR ``ResponseOutputRefusal``. Refusal carries visible text in
    ``.refusal``. Pre-fold the refusal path was silently dropped, so a
    streamed refusal would have surfaced as ``text=""`` (transport
    failure classification) instead of the actual model refusal.
    (Codex MCP catch, Sprint H2 2026-05-26.)"""
    refusal_block = SimpleNamespace(type="refusal", refusal="I cannot help with that.")
    msg = SimpleNamespace(type="message", role="assistant", content=[refusal_block])
    result = translate_codex_response(_empty_response(), accumulated_items=[msg])
    assert result.text == "I cannot help with that."


def test_mixed_interleaved_items_all_surface() -> None:
    """Regression guard for the worst-case ordering — multiple message
    items interleaved with reasoning + function_call items. The fix
    must concatenate ALL message text in order, surface ALL reasoning
    + function_call items, and not be confused by item ordering."""
    reasoning_a = SimpleNamespace(
        type="reasoning", encrypted_content="ENC_A", summary=[], id="rs_a"
    )
    msg_a = _message_item(_block(type="output_text", text="alpha "))
    func_a = SimpleNamespace(type="function_call", call_id="call_a", name="tool_a", arguments="{}")
    msg_b = _message_item(_block(type="output_text", text="beta"))
    func_b = SimpleNamespace(type="function_call", call_id="call_b", name="tool_b", arguments="{}")
    items = [reasoning_a, msg_a, func_a, msg_b, func_b]
    result = translate_codex_response(_empty_response(), accumulated_items=items)
    assert result.text == "alpha beta", (
        f"Mixed-interleaved message items must concatenate in order; got {result.text!r}"
    )
    assert len(result.reasoning_items) == 1
    assert len(result.tool_uses) == 2
    assert [t["id"] for t in result.tool_uses] == ["call_a", "call_b"]
