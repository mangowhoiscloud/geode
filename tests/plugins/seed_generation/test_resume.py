"""Unit tests for :mod:`plugins.seed_generation.resume`.

PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — pin the hydration
+ next-phase contract so a future change to ``PipelineState`` or
``_PHASE_ORDER`` cannot silently break ``audit-seeds resume <run_id>``.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from plugins.seed_generation.checkpointer import write_checkpoint
from plugins.seed_generation.orchestrator import _PHASE_ORDER
from plugins.seed_generation.resume import (
    ResumeError,
    hydrate_state,
    load_ranker_partial_resume,
    next_phase_to_run,
    resolve_resume_target,
)


def _full_snapshot(*, completed_phases: list[str]) -> dict[str, object]:
    return {
        "run_id": "gen1-broken_tool_use",
        "target_dim": "broken_tool_use",
        "gen_tag": "gen1",
        "candidates_requested": 10,
        "max_iterations": 0,
        "current_iteration": 0,
        "completed_phases": completed_phases,
        "candidates": [{"id": "c-1"}, {"id": "c-2"}],
        "reflections": {"c-1": {"role": "critic"}},
        "pilot_scores": {},
        "elo_ratings": {},
        "survivors": [],
        "evolved_candidates": [],
        "meta_review": {},
        "similarity_clusters": [],
        "removed_duplicates": [],
        "usd_spent": 0.42,
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "supervisor_guidance": {"phase_guidance": {"generation": "focus on edge"}},
        "articles_with_reasoning": "",
        "literature_snapshots": {},
        "debate_transcripts": {},
        "pareto_mode": False,
        "target_dims_attribution": [],
        "cohort": "petri_17dim",
    }


def test_next_phase_to_run_with_no_checkpoints(tmp_path: Path) -> None:
    assert next_phase_to_run(tmp_path) == _PHASE_ORDER[0]


def test_next_phase_to_run_after_generator(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        phase="supervisor",
        state_snapshot=_full_snapshot(completed_phases=["supervisor"]),
        duration_ms=1.0,
    )
    write_checkpoint(
        tmp_path,
        phase="literature_review",
        state_snapshot=_full_snapshot(completed_phases=["supervisor", "literature_review"]),
        duration_ms=1.0,
    )
    write_checkpoint(
        tmp_path,
        phase="generator",
        state_snapshot=_full_snapshot(
            completed_phases=["supervisor", "literature_review", "generator"]
        ),
        duration_ms=1.0,
    )
    # next phase = proximity (the first phase with no checkpoint)
    assert next_phase_to_run(tmp_path) == "proximity"


def test_next_phase_to_run_all_complete(tmp_path: Path) -> None:
    for phase in _PHASE_ORDER:
        write_checkpoint(
            tmp_path,
            phase=phase,
            state_snapshot=_full_snapshot(completed_phases=list(_PHASE_ORDER)),
            duration_ms=1.0,
        )
    assert next_phase_to_run(tmp_path) is None


def test_hydrate_state_round_trip(tmp_path: Path) -> None:
    snap = _full_snapshot(completed_phases=["supervisor", "literature_review"])
    snap["run_dir"] = str(tmp_path)
    write_checkpoint(
        tmp_path,
        phase="literature_review",
        state_snapshot=snap,
        duration_ms=42.0,
    )
    state = hydrate_state(tmp_path)
    assert state.run_id == "gen1-broken_tool_use"
    assert state.target_dim == "broken_tool_use"
    assert state.gen_tag == "gen1"
    assert state.candidates_requested == 10
    assert state.completed_phases == ["supervisor", "literature_review"]
    assert len(state.candidates) == 2
    assert state.usd_spent == pytest.approx(0.42)
    assert state.supervisor_guidance["phase_guidance"]["generation"] == "focus on edge"
    assert state.run_dir == tmp_path


def test_hydrate_state_uses_latest_checkpoint(tmp_path: Path) -> None:
    # Earlier checkpoint says only supervisor done; later checkpoint says
    # supervisor + literature_review done. Hydration must read the LATEST
    # (literature_review) — completed_phases reflects the 2-phase state.
    write_checkpoint(
        tmp_path,
        phase="supervisor",
        state_snapshot=_full_snapshot(completed_phases=["supervisor"]),
        duration_ms=1.0,
    )
    write_checkpoint(
        tmp_path,
        phase="literature_review",
        state_snapshot=_full_snapshot(completed_phases=["supervisor", "literature_review"]),
        duration_ms=1.0,
    )
    state = hydrate_state(tmp_path)
    assert state.completed_phases == ["supervisor", "literature_review"]


def test_hydrate_state_no_checkpoints_raises(tmp_path: Path) -> None:
    with pytest.raises(ResumeError, match="nothing to resume"):
        hydrate_state(tmp_path)


def test_hydrate_state_missing_identity_fields_raises(tmp_path: Path) -> None:
    snap = _full_snapshot(completed_phases=["supervisor"])
    snap.pop("run_id")
    write_checkpoint(
        tmp_path,
        phase="supervisor",
        state_snapshot=snap,
        duration_ms=1.0,
    )
    with pytest.raises(ResumeError, match="missing identity fields"):
        hydrate_state(tmp_path)


def test_state_to_json_includes_g4_g5_attribution_fields() -> None:
    """Codex MCP review fix: ``_state_to_json`` must persist
    ``target_dims_attribution`` + ``pareto_mode`` so the resumed
    evolver's HANDOFF pareto-front embedding stays identical to the
    pre-checkpoint run.
    """
    import json as _json

    from plugins.seed_generation.orchestrator import PipelineState, _state_to_json

    state = PipelineState(
        run_id="gen1-broken_tool_use",
        target_dim="broken_tool_use",
        gen_tag="gen1",
        target_dims_attribution=["broken_tool_use", "deception_toward_user"],
        pareto_mode=True,
    )
    payload = _json.loads(_state_to_json(state))
    assert payload["target_dims_attribution"] == [
        "broken_tool_use",
        "deception_toward_user",
    ]
    assert payload["pareto_mode"] is True


def test_state_to_json_round_trip_through_hydrate(tmp_path: Path) -> None:
    """Codex MCP review fix: every field that ``_state_to_json``
    persists must round-trip through ``hydrate_state``. This pins
    the writer ↔ reader parity so a future addition to either side
    cannot silently drop a field on resume.
    """
    import json as _json

    from plugins.seed_generation.checkpointer import write_checkpoint
    from plugins.seed_generation.orchestrator import PipelineState, _state_to_json

    original = PipelineState(
        run_id="gen1-broken_tool_use",
        target_dim="broken_tool_use",
        gen_tag="gen1",
        target_dims_attribution=["broken_tool_use"],
        pareto_mode=True,
        candidates_requested=12,
        candidates=[{"id": "c-1"}],
        completed_phases=["supervisor"],
        run_dir=tmp_path,
    )
    snapshot = _json.loads(_state_to_json(original))
    write_checkpoint(
        tmp_path,
        phase="supervisor",
        state_snapshot=snapshot,
        duration_ms=1.0,
    )
    rehydrated = hydrate_state(tmp_path)
    assert rehydrated.target_dims_attribution == ["broken_tool_use"]
    assert rehydrated.pareto_mode is True
    assert rehydrated.candidates_requested == 12
    assert rehydrated.completed_phases == ["supervisor"]
    assert len(rehydrated.candidates) == 1


def test_resolve_resume_target_returns_state_and_phase(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        phase="supervisor",
        state_snapshot=_full_snapshot(completed_phases=["supervisor"]),
        duration_ms=1.0,
    )
    state, next_phase = resolve_resume_target(tmp_path)
    assert state.run_id == "gen1-broken_tool_use"
    assert next_phase == "literature_review"


def test_load_ranker_partial_resume_filters_completed_prefix(tmp_path: Path) -> None:
    from plugins.seed_generation.checkpointer import write_partial_ranker_checkpoint
    from plugins.seed_generation.tournament import (
        MatchOutcome,
        apply_match,
        initial_ratings,
        plan_matches,
    )

    candidate_ids = ["c-1", "c-2", "c-3", "c-4"]
    match_plan = plan_matches(candidate_ids, rng=random.Random(3))
    first = match_plan[0]
    outcome = MatchOutcome(
        match_id=first.match_id,
        a=first.a,
        b=first.b,
        winner="A",
        votes=("A", "A", "tie"),
        voter_ids=("v1", "v2", "v3"),
    )
    ratings = initial_ratings(candidate_ids)
    apply_match(ratings, outcome)
    write_partial_ranker_checkpoint(
        tmp_path,
        completed_match_ids=[first.match_id],
        partial_ratings=ratings,
        partial_outcomes_serialised=[
            {
                "match_id": outcome.match_id,
                "a": outcome.a,
                "b": outcome.b,
                "winner": outcome.winner,
                "votes": list(outcome.votes),
                "voter_ids": list(outcome.voter_ids),
            }
        ],
        total_matches=len(match_plan),
    )

    resume = load_ranker_partial_resume(
        tmp_path,
        candidate_ids=candidate_ids,
        match_plan=match_plan,
    )
    assert resume.completed_match_ids == (first.match_id,)
    assert resume.ratings == ratings
    assert [match.match_id for match in resume.pending_matches] == [
        match.match_id for match in match_plan[1:]
    ]
    assert len(resume.outcomes) == 1
    assert resume.outcomes[0].match_id == first.match_id


def test_load_ranker_partial_resume_ignores_non_prefix_checkpoint(tmp_path: Path) -> None:
    from plugins.seed_generation.checkpointer import write_partial_ranker_checkpoint
    from plugins.seed_generation.tournament import initial_ratings, plan_matches

    candidate_ids = ["c-1", "c-2", "c-3", "c-4"]
    match_plan = plan_matches(candidate_ids, rng=random.Random(3))
    write_partial_ranker_checkpoint(
        tmp_path,
        completed_match_ids=[match_plan[1].match_id],
        partial_ratings={"c-1": 1200.0},
        partial_outcomes_serialised=[],
        total_matches=len(match_plan),
    )

    resume = load_ranker_partial_resume(
        tmp_path,
        candidate_ids=candidate_ids,
        match_plan=match_plan,
    )
    assert resume.completed_match_ids == ()
    assert resume.ratings == initial_ratings(candidate_ids)
    assert resume.pending_matches == match_plan
