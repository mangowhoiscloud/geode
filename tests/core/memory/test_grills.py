from __future__ import annotations

import pytest
from core.memory.grills import GrillStatus, GrillStore


def _node(
    node_id: str,
    *,
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": node_id,
        "question": f"Settle {node_id}?",
        "depends_on": depends_on or [],
        "options": [
            {"label": "A", "consequence": "Choose the narrow path."},
            {"label": "B", "consequence": "Choose the broad path."},
        ],
        "recommended": "A",
        "recommendation_reason": "It is reversible.",
    }


def test_grill_store_enforces_dependency_frontier_and_completion(tmp_path) -> None:
    store = GrillStore(tmp_path / "sessions.db")
    started = store.start("s-1", "Choose a rollout")
    assert started.status is GrillStatus.DRAFT

    grill = store.define("s-1", [_node("scope"), _node("rollout", depends_on=["scope"])])
    assert [node.id for node in grill.frontier] == ["scope"]
    with pytest.raises(ValueError, match="not on the current"):
        store.answer("s-1", "rollout", "B")
    with pytest.raises(ValueError, match="unresolved"):
        store.complete("s-1")

    grill = store.answer("s-1", "scope", "A")
    assert [node.id for node in grill.frontier] == ["rollout"]
    store.answer("s-1", "rollout", "B")
    complete = store.complete("s-1")
    assert complete.status is GrillStatus.COMPLETE
    assert complete.unresolved == ()


def test_grill_store_rejects_cycles_and_invalid_recommendations(tmp_path) -> None:
    store = GrillStore(tmp_path / "sessions.db")
    store.start("s-1", "Choose")
    with pytest.raises(ValueError, match="acyclic"):
        store.define("s-1", [_node("a", depends_on=["b"]), _node("b", depends_on=["a"])])
    invalid = _node("a")
    invalid["recommended"] = "missing"
    with pytest.raises(ValueError, match="recommended"):
        store.define("s-1", [invalid])


def test_grill_store_preserves_answered_nodes_and_rejects_stale_writes(tmp_path) -> None:
    store = GrillStore(tmp_path / "sessions.db")
    store.start("s-1", "Choose")
    with pytest.raises(ValueError, match="active grill"):
        store.start("s-1", "Choose something else")
    stale = store.define("s-1", [_node("scope")])

    with pytest.raises(ValueError, match="option labels"):
        store.answer("s-1", "scope", "custom prose")
    answered = store.answer("s-1", "scope", "A")

    rewritten = _node("scope")
    rewritten["question"] = "Rewrite the settled question?"
    with pytest.raises(ValueError, match="cannot change answered"):
        store.define("s-1", [rewritten])
    with pytest.raises(ValueError, match="stale grill"):
        store._update(stale, answers={"scope": "B"})
    assert store.get("s-1") == answered


def test_grill_store_rejects_oversized_model_fields(tmp_path) -> None:
    store = GrillStore(tmp_path / "sessions.db")
    store.start("s-1", "Choose")
    oversized = _node("scope")
    oversized["recommendation_reason"] = "x" * 1001
    with pytest.raises(ValueError, match="recommended"):
        store.define("s-1", [oversized])
