"""PR-2 — CognitiveState (C-1) + cognitive-cycle telemetry (C-6) invariants.

This file pins the *structure* and *event taxonomy* that PR-3 → PR-6
will extend. The plan (docs/plans/2026-05-21-cognitive-loop-uplift.md)
splits cognitive uplift into 6 PRs; PR-2's scope is intentionally
narrow:

  C-1  Introduce :class:`CognitiveState` (8 fields). Wire onto
       :class:`AgenticLoop`. Round-end updater populates 4 fields
       deterministically; the remaining 4 (subgoals / hypotheses /
       confidence) have empty defaults and are PR-3 territory.
  C-6  Add 6 ``HookEvent`` members (PERCEIVE / PLAN / ACT /
       OBSERVE / REFLECT / UPDATE_MEMORY) and wire emit points in
       the agentic loop. Every event carries the
       ``cognitive_state`` snapshot in its payload so downstream
       viewers can replay state evolution.

Grep-checkable invariants — a regression here shows up in CI, not
at runtime.
"""

from __future__ import annotations

import inspect

# ---------------------------------------------------------------------------
# C-1 — CognitiveState dataclass
# ---------------------------------------------------------------------------


def test_cognitive_state_has_eight_fields() -> None:
    """Plan Q4 — exactly 8 fields, no more (over-specifying is plan
    creep). Pin the contract so a future PR can't quietly add a 9th
    without an explicit plan amendment."""
    from dataclasses import fields

    from core.agent.cognitive_state import CognitiveState

    field_names = {f.name for f in fields(CognitiveState)}
    expected = {
        "goal",
        "subgoals",
        "observations",
        "hypotheses",
        "confidence",
        "last_action",
        "last_observation",
        "round_count",
    }
    assert field_names == expected, (
        f"CognitiveState field set drifted: "
        f"extra={field_names - expected!r} missing={expected - field_names!r}"
    )


def test_cognitive_state_defaults_are_empty() -> None:
    """Fresh state must be a valid no-op (all fields empty / zero)
    so :class:`AgenticLoop.__init__` can attach one without an
    immediate writer."""
    from core.agent.cognitive_state import CognitiveState

    s = CognitiveState()
    assert s.goal == ""
    assert s.subgoals == []
    assert s.observations == []
    assert s.hypotheses == []
    assert s.confidence is None
    assert s.last_action == ""
    assert s.last_observation == ""
    assert s.round_count == 0


def test_record_round_updates_four_fields() -> None:
    """Round-end updater populates the 4 deterministic fields. The
    remaining 4 (subgoals / hypotheses / confidence + goal which is
    set once at session start) stay unchanged."""
    from core.agent.cognitive_state import CognitiveState

    s = CognitiveState(goal="ship it")
    s.record_round(action="tools: bash", observation="2 tool result(s)")
    assert s.round_count == 1
    assert s.last_action == "tools: bash"
    assert s.last_observation == "2 tool result(s)"
    assert s.observations == ["tools: bash -> 2 tool result(s)"]
    # untouched
    assert s.goal == "ship it"
    assert s.subgoals == []
    assert s.hypotheses == []
    assert s.confidence is None


def test_record_round_caps_observations() -> None:
    """Rolling cap — observation list cannot grow unbounded. Default
    cap = 32. After 35 rounds we keep the most recent 32."""
    from core.agent.cognitive_state import CognitiveState

    s = CognitiveState()
    for i in range(35):
        s.record_round(action=f"act{i}", observation=f"obs{i}", observations_cap=32)
    assert len(s.observations) == 32
    # most-recent kept
    assert s.observations[-1] == "act34 -> obs34"
    # oldest dropped
    assert s.observations[0] == "act3 -> obs3"
    assert s.round_count == 35


def test_to_snapshot_returns_dict_with_eight_keys() -> None:
    """Telemetry payload contract — every cognitive event embeds this
    snapshot, so the key set must match the field set 1:1 (8 keys)."""
    from core.agent.cognitive_state import CognitiveState

    snap = CognitiveState(goal="x").to_snapshot()
    assert set(snap.keys()) == {
        "goal",
        "subgoals",
        "observations",
        "hypotheses",
        "confidence",
        "last_action",
        "last_observation",
        "round_count",
    }
    # list fields are *copies*, not aliases — protect callers from
    # mutating the live state through a snapshot.
    s = CognitiveState()
    snap = s.to_snapshot()
    snap["observations"].append("x")  # type: ignore[union-attr]
    assert s.observations == []


def test_from_snapshot_restores_bounded_state() -> None:
    """Checkpoint resume reconstructs the runtime container from a
    serialized snapshot while keeping list fields bounded."""
    from core.agent.cognitive_state import CognitiveState

    snapshot = {
        "goal": "ship",
        "subgoals": [f"s{i}" for i in range(7)],
        "observations": [f"o{i}" for i in range(35)],
        "hypotheses": [f"h{i}" for i in range(8)],
        "confidence": 1.5,
        "last_action": "tools: read",
        "last_observation": "1 tool result(s)",
        "round_count": 4,
    }

    state = CognitiveState.from_snapshot(snapshot)

    assert state.goal == "ship"
    assert state.subgoals == ["s2", "s3", "s4", "s5", "s6"]
    assert state.observations[0] == "o3"
    assert len(state.observations) == 32
    assert state.hypotheses == ["h3", "h4", "h5", "h6", "h7"]
    assert state.confidence == 1.0
    assert state.last_action == "tools: read"
    assert state.last_observation == "1 tool result(s)"
    assert state.round_count == 4


# ---------------------------------------------------------------------------
# C-6 — 6 cognitive HookEvents
# ---------------------------------------------------------------------------


def test_six_cognitive_hook_events_defined() -> None:
    """The cognitive cycle taxonomy is PERCEIVE / PLAN / ACT /
    OBSERVE / REFLECT / UPDATE_MEMORY. Pin that all 6 exist on the
    enum so PR-3 → PR-6 can register handlers against stable names."""
    from core.hooks.system import HookEvent

    expected = {
        "COGNITIVE_PERCEIVE",
        "COGNITIVE_PLAN",
        "COGNITIVE_ACT",
        "COGNITIVE_OBSERVE",
        "COGNITIVE_REFLECT",
        "COGNITIVE_UPDATE_MEMORY",
    }
    members = {m.name for m in HookEvent}
    missing = expected - members
    assert not missing, f"Missing cognitive HookEvent members: {missing!r}"


def test_cognitive_event_string_values_namespaced() -> None:
    """All 6 must use the ``cognitive_`` prefix so log filters /
    transcript renderers / Petri dashboards can group them with a
    single string match."""
    from core.hooks.system import HookEvent

    for name in (
        "COGNITIVE_PERCEIVE",
        "COGNITIVE_PLAN",
        "COGNITIVE_ACT",
        "COGNITIVE_OBSERVE",
        "COGNITIVE_REFLECT",
        "COGNITIVE_UPDATE_MEMORY",
    ):
        member = HookEvent[name]
        assert member.value.startswith("cognitive_"), (
            f"{name} has non-namespaced value {member.value!r}"
        )


# ---------------------------------------------------------------------------
# Wiring — AgenticLoop attaches state + emits events
# ---------------------------------------------------------------------------


def test_agentic_loop_init_attaches_cognitive_state() -> None:
    """The constructor must create the state container — readers
    (PR-3 reflection, PR-4 episodic) expect ``self.cognitive_state``
    to exist at any point in the loop lifecycle, not be lazy-inited."""
    from core.agent.loop.agent_loop import AgenticLoop

    src = inspect.getsource(AgenticLoop.__init__)
    assert "self.cognitive_state" in src
    assert "CognitiveState()" in src


def test_arun_emits_all_six_cognitive_events() -> None:
    """The agentic loop body must contain emit sites for all 6
    cognitive events. Without this the event taxonomy would be
    declarative-only (knob-vs-deletion anti-pattern from the PR-1
    Codex MCP review)."""
    from core.agent.loop import agent_loop as _agent_loop_mod

    src = inspect.getsource(_agent_loop_mod)
    for member in (
        "COGNITIVE_PERCEIVE",
        "COGNITIVE_PLAN",
        "COGNITIVE_ACT",
        "COGNITIVE_OBSERVE",
        "COGNITIVE_REFLECT",
        "COGNITIVE_UPDATE_MEMORY",
    ):
        assert f"HookEvent.{member}" in src, (
            f"core/agent/loop/agent_loop.py is missing an emit site for "
            f"HookEvent.{member} — every cognitive event member must have "
            "at least one writer or it's a silent declarative knob."
        )


def test_text_only_round_also_calls_record_round() -> None:
    """Codex MCP review #1 (HIGH) catch — text-only completions
    (``stop_reason != "tool_use"``) used to bypass
    ``_run_cognitive_act_observe_cycle`` and therefore
    ``record_round``. The CHANGELOG claim that ``record_round``
    fires "at every round end" was false for natural / forced_text
    / user_clarification_needed completions.

    Pin that ``_record_text_only_round`` exists and is called from
    both text-only return paths so round_count + observations stay
    in lock-step with the actual round count regardless of how the
    round ended."""
    from core.agent.loop import agent_loop as _agent_loop_mod
    from core.agent.loop.agent_loop import AgenticLoop

    # The helper exists and updates round_count + emits REFLECT/UPDATE.
    src = inspect.getsource(AgenticLoop._record_text_only_round)
    assert "self.cognitive_state.record_round(" in src
    assert "HookEvent.COGNITIVE_REFLECT" in src
    assert "HookEvent.COGNITIVE_UPDATE_MEMORY" in src

    # Both text-only return paths call it before ``return``.
    module_src = inspect.getsource(_agent_loop_mod)
    assert module_src.count("await self._record_text_only_round(") >= 2, (
        "Both text-only return paths (user_clarification_needed and "
        "natural/forced_text) must call _record_text_only_round before "
        "returning, or round_count drifts from the actual round count."
    )


def test_arun_emits_cognitive_state_snapshot_in_payload() -> None:
    """Every cognitive event payload must include the
    ``cognitive_state`` snapshot so a downstream viewer can replay
    state evolution without re-parsing the transcript.

    The ``_emit_cognitive`` helper centralises snapshot embedding so
    pin its definition: (a) the dict literal must carry the
    ``cognitive_state`` key, (b) the value must be a fresh
    ``to_snapshot()`` call (NOT a captured reference that could go
    stale across awaits)."""
    from core.agent.loop.agent_loop import AgenticLoop

    src = inspect.getsource(AgenticLoop._emit_cognitive)
    assert '"cognitive_state": self.cognitive_state.to_snapshot()' in src, (
        "_emit_cognitive must embed a fresh cognitive_state snapshot in "
        "every payload — otherwise viewers cannot reconstruct state "
        "evolution across the cognitive cycle."
    )
