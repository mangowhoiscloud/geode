"""A2 Codex reasoning replay invariants.

Codex backend gpt-5.x family runs with ``store=False`` so the server cannot
resolve reasoning items by id on subsequent turns. The adapter chain must:

1. Capture ``type: reasoning`` typed items from ``response.output_item.done``
   SSE events on the current turn.
2. Surface them on ``AdapterCallResult.reasoning_items``.
3. The legacy bridge forwards them to ``AgenticResponse.codex_reasoning_items``.
4. The next-turn ``build_adapter_request`` reads each assistant message
   dict's ``codex_reasoning_items`` annotation (set by the AgenticLoop on
   the assistant turn that emitted them) and attaches the tuple to that
   :class:`Message`'s ``codex_reasoning_items`` field — preserving the
   per-turn association.
5. ``build_codex_input`` walks the messages and, for each assistant
   Message, inserts the reasoning entries (id-stripped) IMMEDIATELY
   BEFORE the assistant's converted entries — so the next-turn ``input``
   array reads ``user → reasoning → assistant → user → reasoning →
   assistant`` exactly like the legacy provider does.

Without any link in this chain the model loses its chain of thought.
The pre-A2 redesign attempted to flatten reasoning into a single
``provider_options["reasoning_items"]`` tuple and prepend it once at the
head of ``input`` — Codex MCP A2 BLOCKER 3 flagged this as losing
position for multi-assistant histories.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.llm.adapters._openai_common import build_responses_kwargs, translate_codex_response
from core.llm.adapters.base import AdapterCallResult, UsageSummary
from core.llm.adapters.translation import (
    agentic_response_from_adapter_result,
    build_adapter_request,
)


def test_translate_codex_response_extracts_reasoning_items() -> None:
    """SSE-accumulated typed items → AdapterCallResult.reasoning_items."""
    accumulated = [
        SimpleNamespace(
            type="reasoning",
            id="rs_1",
            encrypted_content="blob_1",
            summary=[SimpleNamespace(type="summary_text", text="thought 1")],
        ),
        SimpleNamespace(
            type="function_call",
            id="fc_1",
            call_id="call_1",
            name="search",
            arguments='{"q":"geode"}',
        ),
    ]
    response = SimpleNamespace(
        output_text="response text",
        output=accumulated,
        status="completed",
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )
    result = translate_codex_response(response, accumulated_items=accumulated)
    assert len(result.reasoning_items) == 1
    assert result.reasoning_items[0]["encrypted_content"] == "blob_1"
    assert result.reasoning_summaries == ("thought 1",)
    assert len(result.tool_uses) == 1
    assert result.tool_uses[0]["name"] == "search"


def test_translate_codex_response_function_call_id_prefers_call_id() -> None:
    """Codex MCP A2 BLOCKER 1: ``call_id`` MUST win over ``id`` so the
    next-turn ``function_call_output`` pairs correctly. Pre-fix
    ``id or call_id`` would emit ``fc_*`` and break pairing."""
    accumulated = [
        SimpleNamespace(
            type="function_call",
            id="fc_internal_999",
            call_id="call_durable_42",
            name="search",
            arguments='{"q":"x"}',
        ),
    ]
    response = SimpleNamespace(
        output_text="",
        output=accumulated,
        status="completed",
        usage=SimpleNamespace(input_tokens=0, output_tokens=0),
    )
    result = translate_codex_response(response, accumulated_items=accumulated)
    assert result.tool_uses[0]["id"] == "call_durable_42"


def test_translate_codex_response_no_reasoning() -> None:
    """A non-gpt-5.x response without reasoning items → empty reasoning fields."""
    response = SimpleNamespace(
        output_text="hi",
        output=[],
        status="completed",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    result = translate_codex_response(response, accumulated_items=[])
    assert result.reasoning_items == ()
    assert result.reasoning_summaries == ()


def test_legacy_bridge_forwards_reasoning_items() -> None:
    """AdapterCallResult.reasoning_items → AgenticResponse.codex_reasoning_items."""
    result = AdapterCallResult(
        text="hi",
        usage=UsageSummary(),
        stop_reason="completed",
        reasoning_items=(
            {"type": "reasoning", "encrypted_content": "blob_1"},
            {"type": "reasoning", "encrypted_content": "blob_2"},
        ),
        reasoning_summaries=("thought 1", "thought 2"),
    )
    resp = agentic_response_from_adapter_result(result)
    assert resp.codex_reasoning_items is not None
    assert len(resp.codex_reasoning_items) == 2
    assert resp.codex_reasoning_items[0]["encrypted_content"] == "blob_1"
    assert resp.reasoning_summaries == ["thought 1", "thought 2"]


def test_legacy_bridge_empty_reasoning_to_none() -> None:
    """No reasoning items → AgenticResponse fields stay ``None``."""
    result = AdapterCallResult(text="hi", usage=UsageSummary(), stop_reason="end_turn")
    resp = agentic_response_from_adapter_result(result)
    assert resp.codex_reasoning_items is None
    assert resp.reasoning_summaries is None


def test_build_adapter_request_attaches_reasoning_per_assistant_message() -> None:
    """Assistant messages with ``codex_reasoning_items`` set → per-Message
    ``codex_reasoning_items`` tuple (NOT flattened to provider_options)."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "thinking 1",
            "codex_reasoning_items": [
                {"type": "reasoning", "encrypted_content": "blob_1"},
            ],
        },
        {"role": "user", "content": "go on"},
        {
            "role": "assistant",
            "content": "thinking 2",
            "codex_reasoning_items": [
                {"type": "reasoning", "encrypted_content": "blob_2"},
            ],
        },
    ]
    req = build_adapter_request(
        model="gpt-5.5",
        system="be brief",
        messages=messages,
        tools=[],
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )
    # Per-Message attachment — each assistant Message carries its own
    # reasoning items.
    assert req.messages[1].role == "assistant"
    assert len(req.messages[1].codex_reasoning_items) == 1
    assert req.messages[1].codex_reasoning_items[0]["encrypted_content"] == "blob_1"
    assert req.messages[3].role == "assistant"
    assert req.messages[3].codex_reasoning_items[0]["encrypted_content"] == "blob_2"
    # User messages carry empty tuple (default).
    assert req.messages[0].codex_reasoning_items == ()
    assert req.messages[2].codex_reasoning_items == ()


def test_codex_call_kwargs_replays_reasoning_at_assistant_turn() -> None:
    """``_build_codex_call_kwargs`` (via build_codex_input) prepends
    reasoning items at the matching assistant's ordinal position."""
    from core.llm.adapters.base import AdapterCallRequest, Message

    req = AdapterCallRequest(
        model="gpt-5.5",
        system_prompt="be brief",
        messages=[
            Message(role="user", content="first"),
            Message(
                role="assistant",
                content=[{"type": "text", "text": "answer 1"}],
                codex_reasoning_items=(
                    {"type": "reasoning", "encrypted_content": "blob_prior", "id": "rs_1"},
                ),
            ),
            Message(role="user", content="next"),
        ],
    )
    kwargs = build_responses_kwargs(req, backend="codex", adapter_name="codex-oauth")
    # Sequence: user1, reasoning_for_assistant1, assistant1, user2
    assert kwargs["input"][0] == {"role": "user", "content": "first"}
    assert kwargs["input"][1]["type"] == "reasoning"
    assert kwargs["input"][1]["encrypted_content"] == "blob_prior"
    assert "id" not in kwargs["input"][1]
    assert kwargs["input"][2] == {"role": "assistant", "content": "answer 1"}
    assert kwargs["input"][3] == {"role": "user", "content": "next"}


def test_codex_call_kwargs_no_reasoning_when_empty() -> None:
    """Without prior reasoning, input has no synthetic reasoning entry."""
    from core.llm.adapters.base import AdapterCallRequest, Message

    req = AdapterCallRequest(
        model="gpt-5.5",
        system_prompt="be brief",
        messages=[Message(role="user", content="hello")],
    )
    kwargs = build_responses_kwargs(req, backend="codex", adapter_name="codex-oauth")
    assert kwargs["input"][0] == {"role": "user", "content": "hello"}


def test_codex_reasoning_replay_preserves_empty_summary() -> None:
    """PR-CODEX-MULTITURN-SUMMARY-PRESERVE (2026-05-26) — when a
    reasoning item is captured from a prior turn WITHOUT a summary
    (gpt-5.x default for high-effort reasoning is to omit detailed
    chain-of-thought summaries), the replay MUST still include
    ``summary: []`` per OpenAI Responses API spec. Pre-fix the
    capture path at ``_openai_common.py:617-619`` only added the
    field when truthy — round-tripped items lacked the key and the
    API returned ``"Missing required parameter: 'input[N].summary'"``
    on the retry attempt (smoke 19 evidence:
    vote-m000-openai.openai-codex/dialogue.jsonl turn 2 +
    ~10 voter failures across the ranker phase).
    """
    from core.llm.adapters._openai_common import build_codex_input
    from core.llm.adapters.base import AdapterCallRequest, Message

    # Capture-shape: reasoning item WITHOUT summary key (matches
    # pre-fix output where ``if summary:`` skipped the assignment).
    captured_item_no_summary = {
        "type": "reasoning",
        "encrypted_content": "encrypted_blob_no_summary",
    }
    # Capture-shape: reasoning item with empty summary list (matches
    # post-fix output — explicit ``[]`` instead of missing key).
    captured_item_empty_summary = {
        "type": "reasoning",
        "encrypted_content": "encrypted_blob_empty_summary",
        "summary": [],
    }
    req = AdapterCallRequest(
        model="gpt-5.5",
        system_prompt="",
        messages=[
            Message(role="user", content="q1"),
            Message(
                role="assistant",
                content=[{"type": "text", "text": "a1"}],
                codex_reasoning_items=(captured_item_no_summary,),
            ),
            Message(role="user", content="q2"),
            Message(
                role="assistant",
                content=[{"type": "text", "text": "a2"}],
                codex_reasoning_items=(captured_item_empty_summary,),
            ),
            Message(role="user", content="q3"),
        ],
    )
    inputs = build_codex_input(req)
    # The two reasoning items land just before their assistant entries.
    reasoning_entries = [item for item in inputs if item.get("type") == "reasoning"]
    assert len(reasoning_entries) == 2
    # PR-CODEX-MULTITURN-SUMMARY-PRESERVE — capture-time fix
    # guarantees ``summary`` is always present, even when the input
    # item omitted it (legacy capture) or carried an explicit empty
    # list (post-fix capture). The replay code at
    # ``_openai_common.py:357-360`` just strips the ``id`` field and
    # forwards every other key; the summary must therefore be in the
    # captured shape for it to survive the round-trip.
    #
    # Note: this test exercises the REPLAY path (build_codex_input).
    # The capture-path fix is exercised in
    # ``test_codex_multiturn_reasoning.py``'s extraction tests +
    # the new ``test_reasoning_item_capture_always_has_summary_field``
    # below.
    for entry in reasoning_entries:
        # PR-CODEX-MULTITURN-SUMMARY-PRESERVE (2026-05-26) — strict
        # cross-module contract: every replayed reasoning item MUST
        # carry ``summary`` (empty list or populated, never absent).
        # Both the capture-time fix (``translate_codex_response``)
        # AND the replay-time defensive injection
        # (``build_codex_input.setdefault("summary", [])``) guarantee
        # this. Pre-fix this assertion failed for the legacy
        # captured-dict-missing-summary fixture, exactly the smoke 19
        # failure mode.
        assert "summary" in entry, (
            f"reasoning entry replayed without summary field — "
            f"OpenAI Responses API will 400 with "
            f"'Missing required parameter: input[N].summary'. "
            f"Entry: {entry!r}"
        )
        assert isinstance(entry["summary"], list)


def test_reasoning_item_capture_always_has_summary_field() -> None:
    """PR-CODEX-MULTITURN-SUMMARY-PRESERVE (2026-05-26) — direct test
    of the capture-path fix in ``_openai_common.py``. When the codex
    response carries a reasoning item without a summary, the
    extracted item MUST default ``summary`` to ``[]`` so downstream
    replay can satisfy the OpenAI Responses API requirement.
    """
    from types import SimpleNamespace

    from core.llm.adapters._openai_common import translate_codex_response

    # Reasoning item where summary is None (gpt-5.x high-effort runs
    # may emit ``summary: None`` even when summary="auto" was set —
    # the model decides whether to surface a summary). The capture
    # path must default to ``[]`` so the next-turn replay satisfies
    # the API's required-field invariant.
    reasoning_item = SimpleNamespace(
        type="reasoning",
        encrypted_content="blob_x",
        summary=None,
        id="rs_test_1",
    )
    response = SimpleNamespace(
        output_text="",
        output=[reasoning_item],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        status="completed",
    )
    result = translate_codex_response(response)
    assert len(result.reasoning_items) == 1
    captured = result.reasoning_items[0]
    assert captured["type"] == "reasoning"
    assert captured["encrypted_content"] == "blob_x"
    # The key invariant — summary MUST be present (default empty list)
    # so the next-turn replay can round-trip without 400.
    assert "summary" in captured
    assert captured["summary"] == []


@pytest.mark.parametrize(
    ("tool_choice", "expected"),
    [
        ("auto", "auto"),
        ("none", "none"),
        ("required", "required"),
        ("any", "required"),  # adapter-neutral "any" → "required"
        # AgenticLoop dict shapes (Anthropic-flavored)
        ({"type": "auto"}, "auto"),
        ({"type": "none"}, "none"),
        ({"type": "any"}, "required"),
        # forced tool: Anthropic shape → Codex flat shape
        (
            {"type": "tool", "name": "search"},
            {"type": "function", "name": "search"},
        ),
    ],
)
def test_codex_call_kwargs_tool_choice_translation(
    tool_choice: str | dict, expected: str | dict
) -> None:
    from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec

    req = AdapterCallRequest(
        model="gpt-5.5",
        system_prompt="x",
        messages=[Message(role="user", content="y")],
        tools=[ToolSpec(name="t", description="", input_schema={"type": "object"})],
        tool_choice=tool_choice,
    )
    kwargs = build_responses_kwargs(req, backend="codex", adapter_name="codex-oauth")
    assert kwargs["tool_choice"] == expected


@pytest.mark.parametrize(
    ("tool_choice", "expected"),
    [
        ("auto", "auto"),
        ("none", "none"),
        ("required", "required"),
        ({"type": "auto"}, "auto"),
        ({"type": "none"}, "none"),
        ({"type": "any"}, "required"),
        # forced tool: Anthropic shape → Chat nested shape
        (
            {"type": "tool", "name": "search"},
            {"type": "function", "function": {"name": "search"}},
        ),
    ],
)
def test_chat_tool_choice_translation(tool_choice: str | dict, expected: str | dict) -> None:
    """Chat Completions tool_choice translation (BLOCKER 2 fix).

    PR-OPENAI-RESPONSES (2026-06-13): openai-payg left Chat Completions,
    so the Chat nested shape now lives only on the GLM adapters — this
    pins the same ``normalize("glm", ...)`` path glm_payg/glm_coding_plan
    call (glm_payg.py / glm_coding_plan.py).
    """
    from core.llm.tool_choice import normalize

    assert normalize("glm", tool_choice) == expected
