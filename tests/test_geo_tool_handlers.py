from __future__ import annotations

from core.agent.cognitive_state_ctx import set_session_id
from core.observability.session_timeline import (
    SessionEventStore,
    SessionTimeline,
    set_current_session_timeline,
)
from evals.geo import GeoStage, GeoStore, build_geo_handlers


def test_geo_handlers_reject_premature_completion_and_record_vector(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    store = GeoStore(db_path)
    store.start("s-geo", "Audit")
    handlers = build_geo_handlers(store)
    timeline = SessionTimeline("s-geo", db_path=db_path, projection_path=tmp_path / "events.jsonl")
    set_session_id("s-geo")
    set_current_session_timeline(timeline)
    try:
        rejected = handlers["update_geo"](action="complete", completion_kind="diagnostic")
        handlers["update_geo"](
            action="record",
            evidence={
                "stage": GeoStage.FETCH.value,
                "status": "not_measured",
                "numerator": None,
                "denominator": None,
                "finding": "No approved observation exists.",
                "evidence": [],
            },
        )
        handlers["update_geo"](
            action="configure",
            config={
                "workload_digest": "sha256:abc",
                "engine": "engine-a",
                "model": "model-a",
                "locale": "ko-KR",
                "repetitions": 1,
            },
        )
        store.authorize_live("s-geo", "operator-receipt")
        handlers["update_geo"](action="advance", phase="live_observe")
        for stage in tuple(GeoStage)[1:]:
            handlers["update_geo"](
                action="record",
                evidence={
                    "stage": stage.value,
                    "status": "not_measured",
                    "numerator": None,
                    "denominator": None,
                    "finding": "No approved observation exists.",
                    "evidence": [],
                },
            )
        complete = handlers["update_geo"](action="complete", completion_kind="diagnostic")
    finally:
        set_current_session_timeline(None)
        set_session_id("")

    assert "error" in rejected
    assert complete["geo"]["phase"] == "complete"
    events = SessionEventStore(db_path).read("s-geo")
    assert [event.kind for event in events].count("geo.updated") == 9
    assert events[-1].kind == "geo.completed"


def test_geo_handler_cannot_mint_operator_receipts(tmp_path) -> None:
    store = GeoStore(tmp_path / "sessions.db")
    store.start("s-geo", "Audit")
    handlers = build_geo_handlers(store)
    set_session_id("s-geo")
    try:
        result = handlers["update_geo"](
            action="configure",
            config={"approval_ref": "model-invented"},
        )
    finally:
        set_session_id("")

    assert "operator-owned" in result["error"]
    assert "approval_ref" not in store.get("s-geo").config
