"""PR-HOOKEVENT-RESERVE (2026-05-26) — autoresearch mutation lifecycle
event namespace reservation.

Two concurrent sprints need a shared event taxonomy before they start
emitting:

1. autoresearch attribution sprint Phase G (PR-SOT-REVERT-ON-REJECT,
   PR-SOT-REVERT-ON-AUDIT-FAIL) — emits ``MUTATION_PROPOSED`` at
   ``runner.py:_invoke_autoresearch`` entry, ``MUTATION_APPLIED`` at
   SoT write, ``MUTATION_REJECTED`` / ``MUTATION_REVERTED`` at the
   ``_should_promote=False`` branch of ``train.py:2407-2455``, and
   ``BASELINE_PROMOTED`` at ``_write_baseline``.

2. observability central SoT sprint PR-5 + PR-10 — wildcard firehose
   captures every event into ``events`` SQLite, autoresearch indexer
   joins by ``mutation_id`` against ``state/autoresearch/mutations.jsonl``.

This file pins the 5 enum members + their string values so a future
rename / reorder breaks here, forcing a conscious cross-sprint update
of both emit sites and downstream listeners.
"""

from __future__ import annotations


def test_mutation_baseline_events_exist() -> None:
    """All 5 reserved members must be present on the HookEvent enum.

    Pre-reservation the writers would race: attribution sprint picks
    one name, observability sprint picks another, both ship to develop
    at near-simultaneous wallclock times, and the firehose subscriber
    fails to capture half the events because the value drifted."""
    from core.hooks.system import HookEvent

    expected = {
        "MUTATION_PROPOSED",
        "MUTATION_APPLIED",
        "MUTATION_REJECTED",
        "MUTATION_REVERTED",
        "BASELINE_PROMOTED",
    }
    members = {m.name for m in HookEvent}
    missing = expected - members
    assert not missing, f"Missing mutation/baseline HookEvent members: {missing!r}"


def test_mutation_event_string_values_namespaced() -> None:
    """All 4 mutation lifecycle events must use the ``mutation_``
    prefix so the wildcard listener + obs-indexer can group them with
    a single ``startswith("mutation_")`` filter, and so docs / Petri
    dashboards render them as one taxonomy."""
    from core.hooks.system import HookEvent

    for name in (
        "MUTATION_PROPOSED",
        "MUTATION_APPLIED",
        "MUTATION_REJECTED",
        "MUTATION_REVERTED",
    ):
        member = HookEvent[name]
        assert member.value.startswith("mutation_"), (
            f"{name} value {member.value!r} must use 'mutation_' prefix "
            "so the wildcard subscriber's startswith filter groups them."
        )


def test_baseline_promoted_string_value_explicit() -> None:
    """``BASELINE_PROMOTED`` is the *outcome* of a mutation, not a
    mutation lifecycle stage. Pin the literal value so downstream
    consumers (Pareto archive writer, baseline.json writer, hub
    dashboard) can hard-code the string without an enum import."""
    from core.hooks.system import HookEvent

    assert HookEvent.BASELINE_PROMOTED.value == "baseline_promoted"


def test_reserved_values_distinct_from_existing_pipeline_events() -> None:
    """The new 5 must not collide with the 4 existing
    ``PIPELINE_*`` / ``NODE_*`` / ``MODEL_PROMOTED`` event values.
    Pre-PR-HOOKEVENT-RESERVE the autoresearch sprint considered
    naming ``BASELINE_PROMOTED`` as ``MODEL_PROMOTED``, but that
    name is already taken (line 80) for the pipeline-level retrain
    promotion. Pinning the distinction avoids the rename collision."""
    from core.hooks.system import HookEvent

    new_values = {
        HookEvent.MUTATION_PROPOSED.value,
        HookEvent.MUTATION_APPLIED.value,
        HookEvent.MUTATION_REJECTED.value,
        HookEvent.MUTATION_REVERTED.value,
        HookEvent.BASELINE_PROMOTED.value,
    }
    existing_values = {
        HookEvent.PIPELINE_STARTED.value,
        HookEvent.PIPELINE_ENDED.value,
        HookEvent.MODEL_PROMOTED.value,
    }
    assert new_values.isdisjoint(existing_values), (
        f"Reserved mutation/baseline values collide with existing: {new_values & existing_values}"
    )
