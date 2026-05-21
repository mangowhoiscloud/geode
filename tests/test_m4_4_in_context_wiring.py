"""ADR-012 M4.4 — In-context slot wiring invariants.

Pins:
- ``apply_in_context_slots`` takes ``(messages, system=)`` and returns
  ``(new_messages, new_system)``.
- No-op fast path: when no SoT is configured, returns *identity*
  (same objects, not just equal values) so per-call cost is zero.
- exemplars slot wired: reads M3 few-shot pool, prepends top-K
  ``(user, assistant)`` pairs at head of messages.
- Per-slot graceful: a reader / apply failure on one slot doesn't
  break the LLM call.
- anthropic.py + openai.py agentic_call paths both invoke the
  orchestrator (smoke check via import + grep-style source assertion).
"""

from __future__ import annotations

from typing import Any

import pytest
from core.self_improving_loop.in_context_wiring import apply_in_context_slots

# No-op fast path ------------------------------------------------------------


def test_no_sot_configured_returns_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """No SoT → identical objects returned (zero allocation)."""
    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: None,
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, new_sys = apply_in_context_slots(msgs, system="SYS")
    assert new_msgs is msgs  # identity, not just equality
    assert new_sys == "SYS"


def test_empty_dict_slots_returns_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty dict from the reader → identity (truthiness check)."""
    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {},
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs is msgs


def test_load_failure_returns_identity_and_swallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader exception → identity, no propagation (defensive)."""

    def _boom() -> dict[str, Any]:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        _boom,
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs is msgs


# exemplars slot — M3 substrate wired ---------------------------------------


def test_exemplars_slot_prepends_few_shot_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """When exemplars slot active + pool has entries → ``(user, assistant)``
    pairs land at head of messages."""
    from core.llm.few_shot_pool import FewShotExemplar
    from core.self_improving_loop.in_context_slots import SLOT_EXEMPLARS, InContextSlot

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=2,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.llm.few_shot_pool._load_few_shot_pool_override",
        lambda: [
            FewShotExemplar(
                user_msg="ex1_user",
                assistant_msg="ex1_assistant",
                fitness_delta=0.9,
                source="petri",
            ),
            FewShotExemplar(
                user_msg="ex2_user",
                assistant_msg="ex2_assistant",
                fitness_delta=0.7,
                source="petri",
            ),
        ],
    )
    msgs = [{"role": "user", "content": "real"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    # 2 exemplar pairs (4 messages) + the 1 real message = 5
    assert len(new_msgs) == 5
    assert new_msgs[0]["content"] == "ex1_user"
    assert new_msgs[1]["content"] == "ex1_assistant"
    assert new_msgs[2]["content"] == "ex2_user"
    assert new_msgs[3]["content"] == "ex2_assistant"
    assert new_msgs[4]["content"] == "real"


def test_exemplars_slot_empty_pool_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """exemplars slot configured but pool empty → messages unchanged."""
    from core.self_improving_loop.in_context_slots import SLOT_EXEMPLARS, InContextSlot

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=3,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.llm.few_shot_pool._load_few_shot_pool_override",
        lambda: None,
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs == msgs


def test_exemplars_slot_pool_failure_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """exemplars reader exception → swallowed; other slots / call proceed."""
    from core.self_improving_loop.in_context_slots import SLOT_EXEMPLARS, InContextSlot

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=2,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )

    def _pool_boom() -> Any:
        raise RuntimeError("synthetic pool failure")

    monkeypatch.setattr("core.llm.few_shot_pool._load_few_shot_pool_override", _pool_boom)
    msgs = [{"role": "user", "content": "real"}]
    new_msgs, _ = apply_in_context_slots(msgs)
    assert new_msgs == msgs  # unchanged after failure


# System prompt passthrough --------------------------------------------------


def test_system_passthrough_when_no_slot_targets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """exemplars only mutates messages, never system."""
    from core.llm.few_shot_pool import FewShotExemplar
    from core.self_improving_loop.in_context_slots import SLOT_EXEMPLARS, InContextSlot

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_EXEMPLARS: InContextSlot(
                name=SLOT_EXEMPLARS,
                max_entries=1,
                rank_by="fitness_delta",
                injection_point="system_prompt",
            )
        },
    )
    monkeypatch.setattr(
        "core.llm.few_shot_pool._load_few_shot_pool_override",
        lambda: [FewShotExemplar(user_msg="u", assistant_msg="a", fitness_delta=0.5, source="t")],
    )
    _, new_sys = apply_in_context_slots([], system="ORIG_SYSTEM")
    assert new_sys == "ORIG_SYSTEM"


# Provider wiring smoke ------------------------------------------------------


def test_anthropic_agentic_call_imports_orchestrator() -> None:
    """anthropic.py 의 agentic_call 본문 안에서 ``apply_in_context_slots`` import 가 일어남.

    PR-M4.4 의 wiring claim 을 grep-provable 하게 pin.
    """
    import inspect

    from core.llm.providers import anthropic as _anth

    src = inspect.getsource(_anth.ClaudeAgenticAdapter.agentic_call)
    assert "from core.self_improving_loop.in_context_wiring import apply_in_context_slots" in src
    assert "apply_in_context_slots(messages, system=system)" in src


def test_openai_agentic_call_imports_orchestrator() -> None:
    """openai.py 의 agentic_call 도 같은 wiring path."""
    import inspect

    from core.llm.providers import openai as _oai

    src = inspect.getsource(_oai.OpenAIAgenticAdapter.agentic_call)
    assert "from core.self_improving_loop.in_context_wiring import apply_in_context_slots" in src
    assert "apply_in_context_slots(messages, system=system)" in src


def test_orchestrator_module_public_api() -> None:
    """Only ``apply_in_context_slots`` is exported (single entry point)."""
    import core.self_improving_loop.in_context_wiring as wiring

    assert wiring.__all__ == ["apply_in_context_slots"]


# Stub slots behave as no-ops ----------------------------------------------


def test_stub_slots_do_not_break_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """memory_recall / rubric_excerpts / tool_hints active → no-op (no reader yet).

    Verifies the orchestrator's iteration over stub slots doesn't raise
    or mutate output; their readers land in follow-up PRs.
    """
    from core.self_improving_loop.in_context_slots import (
        SLOT_MEMORY_RECALL,
        SLOT_RUBRIC_EXCERPTS,
        SLOT_TOOL_HINTS,
        InContextSlot,
    )

    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_MEMORY_RECALL: InContextSlot(
                name=SLOT_MEMORY_RECALL,
                max_entries=5,
                rank_by="recency",
                injection_point="system_prompt",
            ),
            SLOT_RUBRIC_EXCERPTS: InContextSlot(
                name=SLOT_RUBRIC_EXCERPTS,
                max_entries=3,
                rank_by="regression_severity",
                injection_point="system_prompt",
            ),
            SLOT_TOOL_HINTS: InContextSlot(
                name=SLOT_TOOL_HINTS,
                max_entries=5,
                rank_by="success_rate",
                injection_point="tool_descriptions",
            ),
        },
    )
    msgs = [{"role": "user", "content": "hi"}]
    new_msgs, new_sys = apply_in_context_slots(msgs, system="S")
    assert new_msgs == msgs
    assert new_sys == "S"
