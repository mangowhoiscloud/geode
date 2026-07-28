"""Unified runtime-hint XML grammar (2026-07-29).

Every per-turn injection lands INSIDE the <dynamic_context> envelope via
``inject_runtime_hints``; the pre-fix behavior appended hints after the
closed envelope, and the mid-run rebuild dropped the preflight hint.
"""

from __future__ import annotations

from core.agent.loop._context import inject_runtime_hints


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
