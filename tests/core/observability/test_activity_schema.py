"""PR-COMM-1 (S2 scope) — ActivityRow schema + HookEvent registry tests.

Pins invariants from
``docs/plans/2026-05-24-hookevent-activity-schema.md`` §5.2.

* I1: Tier 1 envelope (``ActivityRowBase``) + 11 group base classes.
* I2: 21 lifecycle concrete classes have correct ``action`` /
  ``entity_type`` literals.
* I3: ``TypedActivityRow`` discriminated union dispatches by ``action``.
* I4: ``GenericActivityRow`` accepts any ``action`` (escape hatch).
* I5: All HookEvent values produce a row via ``map_hook_to_activity``
  (typed → concrete subclass; non-lifecycle → generic).
"""

from __future__ import annotations

import pytest
from core.hooks.system import HookEvent
from core.observability.activity import (
    ActivityRowBase,
    GenericActivityRow,
    LifecycleFailedDetails,
    LifecycleRetriedDetails,
    LifecycleStartedDetails,
    LLMCallFailedRow,
    LLMCallRetriedRow,
    SessionStartedRow,
    SubAgentCompletedRow,
    SubAgentStartedRow,
    TypedActivityRow,
)
from core.observability.activity_registry import (
    HOOK_EVENT_TO_ROW_BUILDER,
    map_hook_to_activity,
)
from pydantic import TypeAdapter, ValidationError

# ---------------------------------------------------------------------------
# I1 — envelope fields enforced
# ---------------------------------------------------------------------------


def test_i1_envelope_requires_classification_quintuple() -> None:
    """``actor_type`` / ``actor_id`` / ``action`` / ``entity_type`` /
    ``entity_id`` are the paperclip activity_log quintuple. Skipping
    any must raise (envelope is ``extra="forbid"`` + non-optional)."""
    with pytest.raises(ValidationError):
        ActivityRowBase(  # type: ignore[call-arg]
            ts=1.0,
            run_id="r1",
            # actor_type missing
            actor_id="x",
            action="x.y",
            entity_type="t",
            entity_id="i",
        )


def test_i1_envelope_actor_type_literal_enforced() -> None:
    """``actor_type`` must be one of the 4 paperclip literals."""
    with pytest.raises(ValidationError):
        ActivityRowBase(
            ts=1.0,
            run_id="r1",
            actor_type="random",  # type: ignore[arg-type]
            actor_id="x",
            action="x.y",
            entity_type="t",
            entity_id="i",
        )


# ---------------------------------------------------------------------------
# I2 — concrete classes pin action + entity_type literals
# ---------------------------------------------------------------------------


def test_i2_session_started_has_dotted_action() -> None:
    row = SessionStartedRow(
        ts=1.0,
        run_id="r1",
        actor_type="orchestrator",
        actor_id="session",
        entity_id="sess-1",
        details=LifecycleStartedDetails(identifier="sess-1"),
    )
    assert row.action == "session.started"
    assert row.entity_type == "session"


def test_i2_subagent_started_has_task_entity() -> None:
    row = SubAgentStartedRow(
        ts=1.0,
        run_id="r1",
        actor_type="agent",
        actor_id="gen-gen1-001",
        entity_id="gen-gen1-001",
        details=LifecycleStartedDetails(identifier="gen-gen1-001"),
    )
    assert row.action == "subagent.started"
    assert row.entity_type == "task"


def test_i2_failed_rows_default_to_error_level() -> None:
    """Group C ``LifecycleFailedRow`` subclasses must default
    ``level="error"`` so a generic ``tail -F | jq 'select(.level==\"error\")'``
    catches every failure event."""
    row = LLMCallFailedRow(
        ts=1.0,
        run_id="r1",
        actor_type="agent",
        actor_id="s1",
        entity_id="call-1",
        details=LifecycleFailedDetails(error_type="rate_limit", message="429"),
    )
    assert row.level == "error"


def test_i2_retried_row_defaults_to_warn_level() -> None:
    """``LLMCallRetriedRow`` (group D) defaults to ``warn`` — a
    retry is not yet a failure but warrants attention."""
    row = LLMCallRetriedRow(
        ts=1.0,
        run_id="r1",
        actor_type="agent",
        actor_id="s1",
        entity_id="call-1",
        details=LifecycleRetriedDetails(attempt=2, reason="rate_limit"),
    )
    assert row.level == "warn"


# ---------------------------------------------------------------------------
# I3 — discriminated union dispatch
# ---------------------------------------------------------------------------


def test_i3_discriminator_dispatches_to_correct_subclass() -> None:
    """openclaw ``NormalizedEventSchema`` parity — ``action`` is the
    discriminator, pydantic picks the correct concrete subclass at
    ``model_validate`` time."""
    adapter = TypeAdapter(TypedActivityRow)
    validated = adapter.validate_python(
        {
            "ts": 1.0,
            "run_id": "r1",
            "actor_type": "agent",
            "actor_id": "gen-gen1-001",
            "action": "subagent.completed",
            "entity_id": "gen-gen1-001",
            "details": {"duration_ms": 1234.5, "success": True},
        }
    )
    assert isinstance(validated, SubAgentCompletedRow)
    assert validated.details.duration_ms == 1234.5  # type: ignore[union-attr]


def test_i3_discriminator_raises_on_unknown_action() -> None:
    """``TypedActivityRow`` is the closed union (no generic member);
    unknown ``action`` raises so callers can fall back to
    ``GenericActivityRow``."""
    adapter = TypeAdapter(TypedActivityRow)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "ts": 1.0,
                "run_id": "r1",
                "actor_type": "system",
                "actor_id": "x",
                "action": "misc.event",
                "entity_type": "misc",
                "entity_id": "x",
                "details": {},
            }
        )


# ---------------------------------------------------------------------------
# I4 — generic escape hatch
# ---------------------------------------------------------------------------


def test_i4_generic_accepts_arbitrary_action() -> None:
    """``GenericActivityRow.action`` is open ``str`` — any
    non-lifecycle event lands without forcing a per-event Literal."""
    row = GenericActivityRow(
        ts=1.0,
        run_id="r1",
        actor_type="system",
        actor_id="x",
        action="misc.event",
        entity_type="misc",
        entity_id="x",
        details={"foo": "bar"},
    )
    assert row.action == "misc.event"
    assert row.details == {"foo": "bar"}


# ---------------------------------------------------------------------------
# I5 — all 74 HookEvent values produce a row
# ---------------------------------------------------------------------------


# Superset payload carrying every *required* details field across all
# concrete rows (lifecycle + K-group). Feeding this guarantees each typed
# builder succeeds and returns its concrete class — empty/partial payloads
# correctly fail-soft to GenericActivityRow, which the dedicated fallback
# test below exercises.
_SUPERSET_PAYLOAD = {
    "task_id": "t1",
    "session_id": "s1",
    "call_id": "c1",
    "tool_call_id": "tc1",
    "turn_id": "tn1",
    "handoff_id": "h1",
    "adapter_name": "anthropic",
    "baseline_path": "/baselines/b.json",
    "total_cost_usd": 1.0,
    "limit_usd": 2.0,
    "server_name": "geode-mcp",
    "mutation_id": "m1",
    "tool_name": "run_bash",
    "name": "rule1",
    "trigger_id": "tg1",
}


def test_i5_all_hookevents_produce_a_row() -> None:
    """Every HookEvent now has a typed builder (PR-OBS-CONTRACT closed the
    44 K-group fall-throughs; PR-HITL-APPROVAL-FSM added the 45th;
    PR-MEMORY-LIFECYCLE the 46th). With a well-formed payload each maps to
    its concrete row — never GenericActivityRow, never raises."""
    all_events = list(HookEvent)
    assert len(all_events) >= 65, f"expected at least 65 HookEvents, got {len(all_events)}"

    typed_count = 0
    for event in all_events:
        row = map_hook_to_activity(event, dict(_SUPERSET_PAYLOAD), run_id="r1")
        assert isinstance(row, ActivityRowBase)
        if event in HOOK_EVENT_TO_ROW_BUILDER:
            typed_count += 1
            assert not isinstance(row, GenericActivityRow), (
                f"{event.value} has a registry entry but mapped to GenericActivityRow "
                f"under a well-formed payload"
            )

    # 100% typed coverage. +MEMORY_PROMOTION_PROPOSED (PR-MEMORY-LIFECYCLE) → 65.
    assert typed_count == 65, f"expected 65 typed events (full coverage), got {typed_count}"
    assert len(HOOK_EVENT_TO_ROW_BUILDER) == 65, "every HookEvent must have a registry entry"


def test_i5_registry_action_matches_concrete_action_literal() -> None:
    """Every registry entry's row class must declare an ``action``
    literal matching the dotted-name convention. Drift between the
    builder map and the concrete subclass would silently produce rows
    with mismatched ``action`` values."""
    for event, builder in HOOK_EVENT_TO_ROW_BUILDER.items():
        row = builder(dict(_SUPERSET_PAYLOAD), "r1")
        # Each builder returns a row whose action attribute is the
        # subclass Literal; we verify it's non-empty + dotted. (Lifecycle
        # rows use hand-picked dotted names that don't derive mechanically
        # from the enum value, e.g. SESSION_STARTED → "session.started".)
        assert row.action, f"{event.value} produced empty action"
        assert "." in row.action, f"{event.value} action {row.action!r} is not dotted"


# ---------------------------------------------------------------------------
# K1-K3 — K-group typed coverage (PR-OBS-CONTRACT, 2026-06-13)
# ---------------------------------------------------------------------------

# Representative real payloads keyed by emit-site audit
# (docs/plans/2026-05-24-hookevent-activity-schema.md, updated). Each mirrors
# the actual ``trigger`` data dict the emit site sends.
_KGROUP_REAL_PAYLOADS: dict[str, dict[str, object]] = {
    "ADAPTER_DISPATCH_ATTEMPT": {
        "adapter_name": "anthropic",
        "provider": "anthropic",
        "source": "router",
        "capability": "agentic",
        "outcome": "ok",
        "elapsed_ms": 812.4,
    },
    "BASELINE_PROMOTED": {
        "baseline_path": "/b/new.json",
        "prior_baseline_path": "/b/old.json",
        "run_id": "run-9",
        "reason": "gate_approved",
        "ts": 1.0,
    },
    "MUTATION_REJECTED": {
        "mutation_id": "mut-3",
        "target_kind": "prompt",
        "target_path": "program.md",
        "run_id": "run-9",
        "reason": "margin_below_floor",
        "ts": 2.0,
    },
    "COST_LIMIT_EXCEEDED": {"total_cost_usd": 5.0, "limit_usd": 5.0},
    "MCP_SERVER_FAILED": {"server_name": "geode-mcp", "error": "ECONNREFUSED"},
    "MODEL_SWITCHED": {
        "from_model": "claude-opus-4-8",
        "to_model": "claude-fable-5",
        "reason": "operator",
        "purged_ack_count": 1,
    },
    "REASONING_METRICS": {
        "total_rounds": 7,
        "thinking_tokens": 1200,
        "output_tokens": 900,
        "thinking_ratio": 0.57,
        "tool_calls_total": 4,
        "empty_rounds": 0,
        "cost_usd": 0.12,
        "cost_per_tool_call": 0.03,
        "overthinking_detected": False,
    },
    "SELF_IMPROVING_AUTO_TRIGGER_RUNNER_ERROR": {
        "trigger_id": "auto-1",
        "detail": "RuntimeError('boom')",
        "ts": 3.0,
    },
    "TOOL_APPROVAL_DENIED": {
        "tool_name": "run_bash",
        "safety_level": "write",
        "permission_level": "HITL",
        "decision": "denied",
        "latency_ms": 40.0,
    },
}


def test_k1_real_payloads_roundtrip_through_discriminated_union() -> None:
    """Each K-group event built from its real emit payload must (a) produce
    its concrete typed class and (b) survive a serialize → re-parse roundtrip
    through the ``TypedActivityRow`` discriminated union, landing back on the
    same class. This pins the action discriminator against drift."""
    adapter: TypeAdapter[object] = TypeAdapter(TypedActivityRow)
    for event_name, payload in _KGROUP_REAL_PAYLOADS.items():
        event = HookEvent[event_name]
        row = map_hook_to_activity(event, dict(payload), run_id="r1")
        assert not isinstance(row, GenericActivityRow), (
            f"{event_name} should map to a concrete typed row, got generic"
        )
        # Roundtrip: dump → re-validate via the union → same concrete class.
        reparsed = adapter.validate_python(row.model_dump())
        assert type(reparsed) is type(row), (
            f"{event_name}: union re-parse landed on {type(reparsed).__name__}, "
            f"expected {type(row).__name__}"
        )


def test_k2_raw_user_content_never_persists_to_timeline() -> None:
    """Privacy contract: raw ``user_input`` strings, cognitive-state
    snapshots, and full tool results must NOT appear in the row details —
    only derived scalars (``input_len``) / declared fields survive."""
    secret = "my bank password is hunter2"

    user_row = map_hook_to_activity(
        HookEvent.USER_INPUT_RECEIVED,
        {"session_id": "s1", "user_input": secret},
        run_id="r1",
    )
    user_details = user_row.details.model_dump()  # type: ignore[union-attr]
    assert "user_input" not in user_details
    assert user_details["input_len"] == len(secret)
    assert secret not in str(user_details)

    cog_row = map_hook_to_activity(
        HookEvent.COGNITIVE_PERCEIVE,
        {"session_id": "s1", "user_input": secret, "cognitive_state": {"plan": secret}},
        run_id="r1",
    )
    cog_details = cog_row.details.model_dump()  # type: ignore[union-attr]
    assert "cognitive_state" not in cog_details
    assert "user_input" not in cog_details
    assert secret not in str(cog_details)

    tr_row = map_hook_to_activity(
        HookEvent.TOOL_RESULT_TRANSFORM,
        {
            "tool_name": "run_bash",
            "tool_input": {"cmd": secret},
            "result": secret,
            "has_error": False,
        },
        run_id="r1",
    )
    tr_details = tr_row.details.model_dump()  # type: ignore[union-attr]
    assert tr_details == {"tool_name": "run_bash", "has_error": False}
    assert secret not in str(tr_details)


def test_k3_payload_divergence_degrades_gracefully() -> None:
    """Events with multiple emit sites that send *different* key sets
    (MEMORY_SAVED tool-vs-CLI; RULE_UPDATED carries no ``paths``) must
    build cleanly via field defaults — an accepted, documented divergence."""
    # CLI memory_handler omits ``persistent``.
    cli_mem = map_hook_to_activity(HookEvent.MEMORY_SAVED, {"key": "k"}, run_id="r1")
    assert cli_mem.details.model_dump() == {"key": "k", "persistent": False}  # type: ignore[union-attr]

    # RULE_UPDATED carries only ``name`` (no ``paths``).
    rule = map_hook_to_activity(HookEvent.RULE_UPDATED, {"name": "n"}, run_id="r1")
    assert rule.details.model_dump() == {"name": "n", "paths": ()}  # type: ignore[union-attr]


def test_k4_fallback_path_also_scrubs_raw_content() -> None:
    """The privacy contract must hold on the FAIL-SOFT path too: when a
    privacy-sensitive event's typed builder fails (here COGNITIVE_PERCEIVE
    with a non-coercible ``round``), the generic fallback row must still
    drop raw ``user_input`` / ``cognitive_state`` — a builder failure must
    not leak what the typed row would have dropped (Codex review BLOCKER)."""
    secret = "raw private prompt body"
    row = map_hook_to_activity(
        HookEvent.COGNITIVE_PERCEIVE,
        {
            "session_id": "s1",
            "user_input": secret,
            "cognitive_state": {"plan": secret},
            "round": "not-an-int",  # forces ValidationError -> generic fallback
        },
        run_id="r1",
    )
    assert isinstance(row, GenericActivityRow), "bad payload should fail-soft to generic"
    payload = row.details
    assert "_fallback_reason" in payload, "forced-generic must be distinguishable"
    assert "user_input" not in payload
    assert "cognitive_state" not in payload
    assert secret not in str(payload), "raw content must not survive the fallback path"
    # The derived signal is preserved even on the fallback path.
    assert payload.get("input_len") == len(secret)


def test_k5_fallback_reason_never_echoes_field_values() -> None:
    """`_fallback_reason` must describe WHY a builder failed (error type +
    field loc) WITHOUT echoing the offending VALUE — pydantic's
    `str(ValidationError)` embeds `input_value=...`, which would carry raw
    content into the persisted row (Codex review BLOCKER #2). The secret is
    the value of the field (`input_len`) that fails int-parsing; the reason
    must name the field but not its value."""
    secret = "SENSITIVE-VALUE-1234"
    row = map_hook_to_activity(
        HookEvent.USER_INPUT_RECEIVED,
        {"session_id": "s1", "input_len": secret},  # wrong type -> ValidationError
        run_id="r1",
    )
    assert isinstance(row, GenericActivityRow)
    reason = row.details["_fallback_reason"]
    # The reason carries the failing field name + error type, never the value.
    assert "input_len" in reason
    assert "int_parsing" in reason
    assert secret not in reason, "fallback reason must not echo the raw field value"
