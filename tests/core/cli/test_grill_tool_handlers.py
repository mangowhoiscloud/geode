from __future__ import annotations

from core.agent.cognitive_state_ctx import set_session_id
from core.cli.tool_handlers.grill import _build_grill_handlers
from core.memory.grills import GrillStore
from core.observability.session_timeline import (
    SessionEventStore,
    SessionTimeline,
    set_current_session_timeline,
)


def test_grill_handlers_record_typed_transitions(tmp_path) -> None:
    db_path = tmp_path / "sessions.db"
    store = GrillStore(db_path)
    store.start("s-grill", "Choose")
    handlers = _build_grill_handlers(store)
    timeline = SessionTimeline(
        "s-grill", db_path=db_path, projection_path=tmp_path / "events.jsonl"
    )
    set_session_id("s-grill")
    set_current_session_timeline(timeline)
    try:
        defined = handlers["update_grill"](
            action="define",
            nodes=[
                {
                    "id": "scope",
                    "question": "Choose scope?",
                    "depends_on": [],
                    "options": [
                        {"label": "narrow", "consequence": "Lower risk"},
                        {"label": "broad", "consequence": "More coverage"},
                    ],
                    "recommended": "narrow",
                    "recommendation_reason": "It is reversible.",
                }
            ],
        )
        rejected = handlers["update_grill"](action="complete")
        handlers["update_grill"](action="answer", node_id="scope", answer="narrow")
        complete = handlers["update_grill"](action="complete")
    finally:
        set_current_session_timeline(None)
        set_session_id("")

    assert defined["grill"]["frontier"] == ["scope"]
    assert "error" in rejected
    assert complete["grill"]["status"] == "complete"
    events = SessionEventStore(db_path).read("s-grill")
    assert [event.kind for event in events] == [
        "grill.updated",
        "grill.updated",
        "grill.completed",
    ]
