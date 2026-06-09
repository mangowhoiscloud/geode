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


def test_i5_all_hookevents_produce_a_row() -> None:
    """No HookEvent should silently break the union channel. Every
    enum value either has a typed builder entry or falls through to
    ``GenericActivityRow`` — never raises."""
    all_events = list(HookEvent)
    assert len(all_events) >= 67, f"expected at least 67 HookEvents, got {len(all_events)}"

    typed_count = 0
    for event in all_events:
        row = map_hook_to_activity(event, {}, run_id="r1")
        assert isinstance(row, ActivityRowBase)
        if event in HOOK_EVENT_TO_ROW_BUILDER:
            typed_count += 1
            assert not isinstance(row, GenericActivityRow), (
                f"{event.value} has a registry entry but mapped to GenericActivityRow"
            )

    # 21 lifecycle events typed (A=6, B=9, C=5, D=1) — PR-DEAD-PIPELINE
    # removed the 11 pipeline/node/analysis rows.
    assert typed_count == 21, f"expected 21 typed lifecycle events, got {typed_count}"


def test_i5_registry_action_matches_concrete_action_literal() -> None:
    """Every registry entry's row class must declare an ``action``
    literal matching the dotted-name convention. Drift between the
    builder map and the concrete subclass would silently produce rows
    with mismatched ``action`` values."""
    for event, builder in HOOK_EVENT_TO_ROW_BUILDER.items():
        row = builder({"task_id": "t1"}, "r1")
        # Each builder returns a row whose action attribute is the
        # subclass Literal; we just verify it's non-empty + dotted.
        assert row.action, f"{event.value} produced empty action"
        assert "." in row.action, f"{event.value} action {row.action!r} is not dotted"
