"""ADR-012 M4.0 — eval_response_recorded RunTranscript event invariants.

Pins:
- ``emit_eval_response_recorded`` writes a single JSONL row to the active
  RunTranscript with the canonical event name + payload schema.
- Outside ``run_transcript_scope`` → no-op returning ``False``.
- ``rollback_flag`` defaults to ``False`` (chosen pile); explicit ``True``
  signals rejected (for M4.1 DPO pack labeling).
- ``axis_scores`` optional — scalar ``fitness_score`` alone is valid.
- bool fitness_score / fitness_score=int → float coerced.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.self_improving_loop.eval_journaling import (
    EVENT_NAME,
    emit_eval_response_recorded,
)
from core.self_improving_loop.run_transcript import (
    RunTranscript,
    run_transcript_scope,
)


@pytest.fixture
def journal_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "transcript.jsonl"


def _read_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# Event name constant --------------------------------------------------------


def test_event_name_is_canonical() -> None:
    """M4.1 reader 가 이 이름으로 filter — 변경하면 downstream 전부 깨짐."""
    assert EVENT_NAME == "eval_response_recorded"


# Emit — no journal scope → no-op --------------------------------------------


def test_emit_outside_scope_returns_false() -> None:
    """ContextVar 부재 시 graceful no-op — 호출자가 try/except 안 필요."""
    result = emit_eval_response_recorded(
        prompt="q",
        response="a",
        fitness_score=0.5,
    )
    assert result is False


# Emit — minimal payload -----------------------------------------------------


def test_emit_writes_minimal_payload(journal_path: Path) -> None:
    journal = RunTranscript(
        session_id="test-session",
        gen_tag="auto-HEAD",
        component="test",
        path=journal_path,
    )
    with run_transcript_scope(journal):
        result = emit_eval_response_recorded(
            prompt="user msg",
            response="agent reply",
            fitness_score=0.82,
        )
    assert result is True
    events = _read_events(journal_path)
    assert len(events) == 1
    rec = events[0]
    assert rec["event"] == "eval_response_recorded"
    assert rec["component"] == "test"
    assert rec["session_id"] == "test-session"
    assert rec["gen_tag"] == "auto-HEAD"
    assert rec["payload"]["prompt"] == "user msg"
    assert rec["payload"]["response"] == "agent reply"
    assert rec["payload"]["fitness_score"] == 0.82
    assert rec["payload"]["rollback_flag"] is False
    assert rec["payload"]["source"] == ""


# Emit — full payload --------------------------------------------------------


def test_emit_writes_full_payload(journal_path: Path) -> None:
    journal = RunTranscript(session_id="s1", gen_tag="auto", component="petri", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(
            prompt="prompt text",
            response="response text",
            fitness_score=0.91,
            axis_scores={
                "dim_means_aggregate": 0.85,
                "ux_means_aggregate": 0.95,
                "admire_means_aggregate": 0.92,
                "bench_means_aggregate": 0.88,
            },
            source="petri_audit",
            rollback_flag=False,
        )
    events = _read_events(journal_path)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["source"] == "petri_audit"
    assert payload["axis_scores"] == {
        "dim_means_aggregate": 0.85,
        "ux_means_aggregate": 0.95,
        "admire_means_aggregate": 0.92,
        "bench_means_aggregate": 0.88,
    }


# Rollback flag signals rejected ---------------------------------------------


def test_rollback_flag_true_persisted(journal_path: Path) -> None:
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(
            prompt="q",
            response="a",
            fitness_score=0.3,
            rollback_flag=True,
        )
    events = _read_events(journal_path)
    assert events[0]["payload"]["rollback_flag"] is True


def test_rollback_flag_default_is_false(journal_path: Path) -> None:
    """Default = False (chosen pile)."""
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(prompt="q", response="a", fitness_score=0.5)
    events = _read_events(journal_path)
    assert events[0]["payload"]["rollback_flag"] is False


# axis_scores optional -------------------------------------------------------


def test_axis_scores_omitted_when_none(journal_path: Path) -> None:
    """``axis_scores=None`` → payload key 자체가 안 나타남 (forward-compat)."""
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(prompt="q", response="a", fitness_score=0.5)
    payload = _read_events(journal_path)[0]["payload"]
    assert "axis_scores" not in payload


def test_axis_scores_empty_dict_omitted(journal_path: Path) -> None:
    """``axis_scores={}`` 도 omit (truthiness check)."""
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(prompt="q", response="a", fitness_score=0.5, axis_scores={})
    payload = _read_events(journal_path)[0]["payload"]
    assert "axis_scores" not in payload


# Type coercion --------------------------------------------------------------


def test_fitness_score_int_coerced_to_float(journal_path: Path) -> None:
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(
            prompt="q",
            response="a",
            fitness_score=1,  # int → float
        )
    payload = _read_events(journal_path)[0]["payload"]
    assert payload["fitness_score"] == 1.0
    assert isinstance(payload["fitness_score"], float)


def test_axis_scores_values_coerced_to_float(journal_path: Path) -> None:
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        emit_eval_response_recorded(
            prompt="q",
            response="a",
            fitness_score=0.5,
            axis_scores={"a": 1, "b": 0},  # ints
        )
    payload = _read_events(journal_path)[0]["payload"]
    assert payload["axis_scores"] == {"a": 1.0, "b": 0.0}


# Multi-event append ---------------------------------------------------------


def test_multiple_emits_append_separate_lines(journal_path: Path) -> None:
    journal = RunTranscript(session_id="s", gen_tag="g", component="c", path=journal_path)
    with run_transcript_scope(journal):
        for i in range(3):
            emit_eval_response_recorded(prompt=f"q{i}", response=f"a{i}", fitness_score=0.5)
    events = _read_events(journal_path)
    assert len(events) == 3
    assert [e["payload"]["prompt"] for e in events] == ["q0", "q1", "q2"]
