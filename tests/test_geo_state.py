from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.observability.session_timeline import SessionEventStore, SessionTimeline
from geode_product.geo_state import GeoPhase, GeoStage, GeoStore
from geode_product.slash_commands import build_geo_prompt


def _evidence(stage: GeoStage, *, status: str = "measured") -> dict[str, object]:
    if status == "not_measured":
        return {
            "stage": stage.value,
            "status": status,
            "numerator": None,
            "denominator": None,
            "finding": "No approved observation exists.",
            "evidence": [],
        }
    return {
        "stage": stage.value,
        "status": status,
        "numerator": 1,
        "denominator": 2,
        "finding": "One of two frozen checks passed.",
        "evidence": ["receipt.json#/checks/0"],
    }


def test_geo_store_preserves_vector_denominators_and_phase_gates(tmp_path) -> None:
    store = GeoStore(tmp_path / "sessions.db")
    run = store.start("s-1", "Audit example.test")
    assert run.phase is GeoPhase.PREFLIGHT

    with pytest.raises(ValueError, match="explicitly record F"):
        store.advance("s-1", "offline_measure")
    run = store.record("s-1", _evidence(GeoStage.FETCH))
    assert run.measurements["F"].denominator == 2
    run = store.advance("s-1", "offline_measure")
    assert run.phase is GeoPhase.OFFLINE_MEASURE

    store.record("s-1", _evidence(GeoStage.RETRIEVAL, status="not_measured"))
    with pytest.raises(ValueError, match="frozen config"):
        store.advance("s-1", "live_observe")
    store.configure(
        "s-1",
        {
            "workload_digest": "sha256:abc",
            "engine": "engine-a",
            "model": "model-a",
            "locale": "ko-KR",
            "repetitions": 3,
        },
    )
    store.authorize_live("s-1", "operator-receipt-1")
    live = store.advance("s-1", "live_observe")
    assert live.phase is GeoPhase.LIVE_OBSERVE
    with pytest.raises(ValueError, match="only a trusted preregistration"):
        store.configure("s-1", {"model": "model-b"})
    preregistered = store.preregister_experiment("s-1", "prereg-receipt-1")
    assert preregistered.config["preregistration_ref"] == "prereg-receipt-1"
    store.record("s-1", _evidence(GeoStage.OUTCOME, status="not_measured"))
    assert store.advance("s-1", "experiment").phase is GeoPhase.EXPERIMENT
    with pytest.raises(ValueError, match="cannot be configured"):
        store.configure("s-1", {"model": "model-c"})


def test_geo_completion_requires_explicit_seven_stage_vector(tmp_path) -> None:
    store = GeoStore(tmp_path / "sessions.db")
    store.start("s-1", "Audit example.test")
    store.record("s-1", _evidence(GeoStage.FETCH))
    with pytest.raises(ValueError, match="experiment phase"):
        store.complete("s-1")
    store.advance("s-1", "offline_measure")
    for stage in (GeoStage.RETRIEVAL, GeoStage.CITATION, GeoStage.PLACEMENT, GeoStage.ABSORPTION):
        store.record("s-1", _evidence(stage, status="not_measured"))
    store.record("s-1", _evidence(GeoStage.QUALITY, status="not_measured"))
    store.configure(
        "s-1",
        {
            "workload_digest": "sha256:abc",
            "engine": "engine-a",
            "model": "model-a",
            "locale": "ko-KR",
            "repetitions": 3,
        },
    )
    store.authorize_live("s-1", "operator-receipt-1")
    store.advance("s-1", "live_observe")
    store.record("s-1", _evidence(GeoStage.OUTCOME, status="not_measured"))
    store.preregister_experiment("s-1", "prereg-receipt-1")
    store.advance("s-1", "experiment")
    store.record("s-1", _evidence(GeoStage.QUALITY, status="not_measured"))
    complete = store.complete("s-1")
    assert complete.phase is GeoPhase.COMPLETE
    assert complete.missing_stages == ()
    assert complete.to_dict()["vector"]["R"]["status"] == "not_measured"


def test_geo_rejects_measurement_without_denominator_or_locator(tmp_path) -> None:
    store = GeoStore(tmp_path / "sessions.db")
    store.start("s-1", "Audit")
    invalid = _evidence(GeoStage.FETCH)
    invalid["denominator"] = None
    with pytest.raises(ValueError, match="integer numerator"):
        store.record("s-1", invalid)


def test_geo_rejects_later_measurement_during_preflight_and_terminal_mutation(
    tmp_path,
) -> None:
    store = GeoStore(tmp_path / "sessions.db")
    store.start("s-1", "Audit")
    with pytest.raises(ValueError, match="preflight may record only F"):
        store.record("s-1", _evidence(GeoStage.RETRIEVAL))
    store.record("s-1", _evidence(GeoStage.FETCH))
    store.advance("s-1", "offline_measure")
    for stage in tuple(GeoStage)[1:-1]:
        store.record("s-1", _evidence(stage, status="not_measured"))
    store.configure(
        "s-1",
        {
            "workload_digest": "sha256:abc",
            "engine": "engine-a",
            "model": "model-a",
            "locale": "ko-KR",
            "repetitions": 1,
        },
    )
    store.authorize_live("s-1", "operator-receipt-1")
    store.advance("s-1", "live_observe")
    store.record("s-1", _evidence(GeoStage.OUTCOME, status="not_measured"))
    store.preregister_experiment("s-1", "prereg-receipt-1")
    store.advance("s-1", "experiment")
    store.record("s-1", _evidence(GeoStage.QUALITY, status="not_measured"))
    store.complete("s-1")
    with pytest.raises(ValueError, match="completed again"):
        store.complete("s-1")
    with pytest.raises(ValueError, match="cannot advance"):
        store.advance("s-1", "offline_measure")


def test_geo_store_rejects_stale_phase_and_evidence_writes(tmp_path) -> None:
    store = GeoStore(tmp_path / "sessions.db")
    stale = store.start("s-1", "Audit")
    with pytest.raises(ValueError, match="active GEO"):
        store.start("s-1", "Audit another target")
    recorded = store.record("s-1", _evidence(GeoStage.FETCH))

    with pytest.raises(ValueError, match="stale GEO"):
        store._update(stale, phase=GeoPhase.OFFLINE_MEASURE)
    assert store.get("s-1") == recorded


def test_geo_operator_slash_receipts_are_correlated_and_model_inaccessible(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "sessions.db"
    store = GeoStore(db_path)
    store.start("s-1", "Audit")
    store.record("s-1", _evidence(GeoStage.FETCH))
    store.advance("s-1", "offline_measure")
    store.record("s-1", _evidence(GeoStage.RETRIEVAL, status="not_measured"))
    store.configure(
        "s-1",
        {
            "workload_digest": "sha256:abc",
            "engine": "engine-a",
            "model": "model-a",
            "locale": "ko-KR",
            "repetitions": 3,
        },
    )
    timeline = SessionTimeline("s-1", db_path=db_path, projection_path=tmp_path / "events.jsonl")
    loop = SimpleNamespace(
        _session_id="s-1",
        _timeline=timeline,
        _control_state_renderers={},
        _prompt_dirty=False,
    )
    monkeypatch.setattr(
        "core.cli.commands.skills.build_skill_prompt",
        lambda _registry, name, arguments="": f"{name}:{arguments}",
    )
    assert (
        build_geo_prompt("approve-live operator-1", skill_registry=None, agentic_ref=loop)
        == "geo:Audit"
    )
    assert store.advance("s-1", "live_observe").phase is GeoPhase.LIVE_OBSERVE
    assert (
        build_geo_prompt("preregister prereg-1", skill_registry=None, agentic_ref=loop)
        == "geo:Audit"
    )

    run = store.get("s-1")
    assert run is not None
    assert run.config["approval_ref"] == "operator-1"
    assert run.config["preregistration_ref"] == "prereg-1"
    events = SessionEventStore(db_path).read("s-1")
    assert [event.kind for event in events] == ["geo.updated", "geo.updated"]
    assert all(event.turn_id for event in events)
