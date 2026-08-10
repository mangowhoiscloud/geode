"""Unified runtime-hint XML grammar (2026-07-29).

Every per-turn injection lands INSIDE the <dynamic_context> envelope via
``inject_runtime_hints``; the pre-fix behavior appended hints after the
closed envelope, and the mid-run rebuild dropped the preflight hint.
"""

from __future__ import annotations

from core.agent.loop._context import (
    goal_continuation_messages,
    inject_runtime_hints,
    render_goal_continuation_hint,
    render_verification_continuation_hint,
)
from core.memory.goals import GoalStatus, ThreadGoal


def test_hints_inserted_inside_envelope() -> None:
    prompt = "STATIC\n\n<dynamic_context>\n\nvolatile\n\n</dynamic_context>"
    out = inject_runtime_hints(prompt, "<plan>p</plan>", "<reflection>r</reflection>")
    body, _, tail = out.rpartition("</dynamic_context>")
    assert "<plan>p</plan>" in body
    assert "<reflection>r</reflection>" in body
    assert tail.strip() == ""


def test_no_envelope_appends_plainly() -> None:
    out = inject_runtime_hints("override spawn base", "<plan>p</plan>")
    assert out.endswith("<plan>p</plan>")


def test_empty_and_non_str_hints_are_dropped() -> None:
    prompt = "S\n\n<dynamic_context>\n\nd\n\n</dynamic_context>"
    assert inject_runtime_hints(prompt, "", None) == prompt


def test_verification_continuation_is_a_bounded_system_hint() -> None:
    hint = render_verification_continuation_hint("Repair <unsafe> & retry.")
    assert hint == (
        "<verification_continuation>\n"
        "Repair &lt;unsafe&gt; &amp; retry.\n"
        "</verification_continuation>"
    )


def test_goal_continuation_keeps_objective_as_escaped_data() -> None:
    goal = ThreadGoal(
        session_id="s-1",
        goal_id="g-1",
        objective="Finish <all> & verify",
        status=GoalStatus.ACTIVE,
        token_budget=100,
        tokens_used=25,
        time_used_seconds=1.0,
        created_at=0.0,
        updated_at=0.0,
    )

    hint = render_goal_continuation_hint(goal)

    assert "user-provided data" in hint
    assert "Finish &lt;all&gt; &amp; verify" in hint
    assert "<remaining_tokens>75</remaining_tokens>" in hint
    assert "new automatic continuation turn" in hint
    assert goal_continuation_messages(hint) == [{"role": "user", "content": hint}]
    assert goal_continuation_messages("") == []


def test_reflection_str_payload_parsed() -> None:
    # OpenAI-family adapters deliver tool_use input as a raw JSON string —
    # reflection must parse it (3/3 live reflections were dropped pre-fix).
    from types import SimpleNamespace

    from core.agent.loop._reflection import _extract_reflection_input

    result = SimpleNamespace(
        tool_uses=(
            {"name": "record_reflection", "input": '{"hypotheses": ["a"], "confidence": 0.6}'},
        )
    )
    assert _extract_reflection_input(result) == {"hypotheses": ["a"], "confidence": 0.6}
