"""Hook taxonomy invariants — families, payload contracts, schema version.

Each case pins a measured property rather than restating the code, so the
docstrings carry the population the number came from.
"""

import pytest
from core.hooks.catalog import (
    ACTION_FAMILIES,
    ACTION_FAMILY_ALIASES,
    OBSERVER_SCHEMA_VERSION,
    REQUIRED_PAYLOAD_KEYS,
    action_family,
    required_payload_keys,
)
from core.hooks.system import HookEvent, HookSystem
from core.observability import activity as act
from core.observability import activity_registry as reg


def _declared_action(event: HookEvent) -> str:
    spec = reg._TYPED_ROW_SPECS.get(event)
    cls = spec.row_cls if spec else None
    if cls is None:
        camel = "".join(p.capitalize() for p in event.value.split("_")) + "Row"
        cls = getattr(act, camel, None)
    field = getattr(cls, "model_fields", {}).get("action") if cls else None
    if field is None:
        return event.value.replace("_", ".")
    default = getattr(field, "default", None)
    if isinstance(default, str) and default:
        return default
    args = getattr(getattr(field, "annotation", None), "__args__", ())
    return str(args[0]) if args else event.value.replace("_", ".")


def test_every_event_lands_in_a_declared_family():
    """56 events resolved into 27 first-segments before the fold, 16 of them
    holding a single event. Every event must land in one of the 13 declared
    families or the namespace stops classifying."""
    stray = {
        e.value: action_family(_declared_action(e))
        for e in HookEvent
        if action_family(_declared_action(e)) not in ACTION_FAMILIES
    }
    assert stray == {}


def test_no_family_is_a_singleton():
    """A family holding one event is a namespace that classifies nothing —
    the exact shape the fold removes."""
    counts: dict[str, int] = {}
    for e in HookEvent:
        fam = action_family(_declared_action(e))
        counts[fam] = counts.get(fam, 0) + 1
    assert [f for f, n in counts.items() if n == 1] == []
    assert len(counts) == 13


@pytest.mark.parametrize(
    ("action", "family"),
    [
        ("adapter.dispatch.attempt", "llm"),
        ("prompt.assembled", "llm"),
        ("user.input.received", "turn"),
        ("shutdown.started", "session"),
        ("program.md.unreadable", "policy"),
        ("self.improving.auto.trigger", "improve"),
        ("tool.exec.started", "tool"),
    ],
)
def test_pre_fold_actions_still_resolve(action, family):
    """2,179 rows already on disk carry pre-fold first segments; the alias map
    is what keeps them readable, the same way LEGACY_EVENT_VALUES keeps v1
    event names readable."""
    assert action_family(action) == family


def test_alias_targets_are_declared_families():
    assert set(ACTION_FAMILY_ALIASES.values()) <= ACTION_FAMILIES


def test_contract_lookup_unions_both_registries():
    """The hand-written table covered 4 events and the pydantic details models
    covered 14 more — disjoint sets. The validator read only the first half, so
    14 existing contracts went unenforced."""
    covered = [e for e in HookEvent if required_payload_keys(e)]
    assert len(covered) >= 18
    assert len(covered) > len(REQUIRED_PAYLOAD_KEYS)
    for event, keys in REQUIRED_PAYLOAD_KEYS.items():
        assert keys <= required_payload_keys(event)


def test_dispatch_stamps_the_contract_version():
    """A subscriber that only sees the payload cannot otherwise tell which
    contract it is reading — the hook_events column is invisible to it."""
    seen: dict[str, object] = {}

    def probe(event, data):
        seen.update(data or {})

    hooks = HookSystem()
    hooks.register(HookEvent.USER_INPUT_RECEIVED, probe, name="probe")
    hooks.trigger(HookEvent.USER_INPUT_RECEIVED, {"text": "hi"})
    assert seen["schema_version"] == OBSERVER_SCHEMA_VERSION
    assert seen["text"] == "hi"


def test_caller_supplied_schema_version_is_not_overwritten():
    """setdefault, not assignment — a replayer feeding an archived payload keeps
    the version that payload was written under."""
    seen: dict[str, object] = {}

    def probe(event, data):
        seen.update(data or {})

    hooks = HookSystem()
    hooks.register(HookEvent.USER_INPUT_RECEIVED, probe, name="probe")
    hooks.trigger(HookEvent.USER_INPUT_RECEIVED, {"text": "x", "schema_version": "archived.v0"})
    assert seen["schema_version"] == "archived.v0"


def test_family_filter_matches_pre_fold_rows(tmp_path):
    """The fold is only real if a reader uses it. A SQL ``LIKE 'llm.%'`` would
    miss every ``adapter.``/``prompt.``/``model.``/``reasoning.`` row already on
    disk, so the filter expands through the alias map instead."""
    from core.hooks.catalog import EventRetentionClass
    from core.observability.event_store import HookEventStore, HookEventWrite

    store = HookEventStore(db_path=tmp_path / "e.db")
    for i, action in enumerate(
        ["llm.call.started", "adapter.dispatch.attempt", "prompt.assembled", "tool.exec.started"]
    ):
        store.append(
            HookEventWrite(
                occurred_at=1000.0 + i,
                session_key="s",
                run_id="r",
                event="llm_call_started",
                dispatch_mode="observe",
                status="ok",
                retention_class=EventRetentionClass.STANDARD,
                actor_type="system",
                actor_id="a",
                action=action,
                entity_type="e",
                entity_id="1",
                level="info",
                payload={},
                handler_count=0,
                handler_error_count=0,
                blocked=False,
                block_reason="",
                task_id=None,
            )
        )
    llm = {r.action for r in store.read(family_filter="llm", limit=100)}
    assert llm == {"llm.call.started", "adapter.dispatch.attempt", "prompt.assembled"}
    assert {r.action for r in store.read(family_filter="tool", limit=100)} == {"tool.exec.started"}


def test_alias_map_covers_every_folded_singleton():
    """16 singletons were folded; each one's old segment must still resolve or a
    pre-fold row becomes unreachable by family."""
    assert len(ACTION_FAMILY_ALIASES) == 16
    for old, new in ACTION_FAMILY_ALIASES.items():
        assert action_family(f"{old}.anything") == new
        assert new in ACTION_FAMILIES
