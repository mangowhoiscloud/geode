"""Tests for ``plugins.seed_generation.agents.meta_reviewer``."""

from __future__ import annotations

import json
from typing import Any

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.meta_reviewer import MetaReviewer
from plugins.seed_generation.orchestrator import PipelineState


def _good_meta() -> dict[str, Any]:
    return {
        "coverage": {"broken_tool_use": 4, "input_hallucination": 3},
        "underrepresented_dims": ["unfaithful_thinking"],
        "overrepresented_dims": ["overrefusal"],
        "next_gen_priors": [
            {"target_dim": "unfaithful_thinking", "weight": 0.4, "rationale": "underrepresented"}
        ],
        "elo_distribution": {"min": 940.0, "p50": 1020.0, "p95": 1180.0},
        "evolution_yield": {"attempted": 5, "successful": 3},
        "session_summary": "Pool well-covered on broken_tool_use; gap on unfaithful_thinking.",
    }


class _StubManager:
    def __init__(
        self,
        *,
        output: Any = None,
        success: bool = True,
        force_unparseable: bool = False,
    ) -> None:
        self.received_tasks: list[SubTask] = []
        self.received_announce: bool | None = None
        self._output = output if output is not None else _good_meta()
        self._success = success
        self._force_unparseable = force_unparseable

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks = list(tasks)
        self.received_announce = announce
        if not tasks:
            return []
        t = tasks[0]
        if not self._success:
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=False,
                    error="forced",
                    duration_ms=10.0,
                )
            ]
        output = {"text": "not-valid-json"} if self._force_unparseable else self._output
        return [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output=output,
                duration_ms=42.0,
            )
        ]


def _state_with_full_pipeline_data(n: int = 5) -> PipelineState:
    state = PipelineState(
        run_id="t-meta",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
    )
    state.candidates = [
        {
            "id": f"c-{i:02d}",
            "path": f"fake-run/candidates/c-{i:02d}.md",
            "target_dim": "broken_tool_use",
            "gen_tag": "gen2",
            "task_id": f"gen-c-{i:02d}",
            "duration_ms": 1000.0,
        }
        for i in range(n)
    ]
    state.reflections = {
        c["id"]: {"strengths": ["a"], "weaknesses": ["b"]} for c in state.candidates
    }
    state.pilot_scores = {
        c["id"]: {"dim_means": {"dim_01": 0.7}, "dim_stderr": {"dim_01": 0.1}, "status": "ok"}
        for c in state.candidates
    }
    state.elo_ratings = {c["id"]: 1000.0 + i * 30 for i, c in enumerate(state.candidates)}
    state.survivors = [c["id"] for c in state.candidates[:3]]
    state.evolved_candidates = [
        {"id": f"{cid}-ev", "parent_id": cid} for cid in state.survivors[:2]
    ]
    return state


def test_meta_reviewer_validates_empty_candidates() -> None:
    state = PipelineState(
        run_id="t",
        target_dim="x",
        gen_tag="gen2",
        candidates_requested=3,
    )
    manager = _StubManager()
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_meta_reviewer_dispatches_single_task() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert len(manager.received_tasks) == 1
    task = manager.received_tasks[0]
    assert task.agent == "seed_meta_reviewer"
    assert task.task_type == "seed-meta-review"


def test_meta_reviewer_merges_report_into_meta_review() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    meta = result.output["meta_review"]
    assert "coverage" in meta
    assert "next_gen_priors" in meta
    assert "session_summary" in meta


def test_meta_reviewer_drops_malformed_payload() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager(output={"partial": "dict"})
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "meta_review_failed"


def test_meta_reviewer_handles_sub_agent_failure() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager(success=False)
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "meta_review_failed"


def test_meta_reviewer_accepts_text_json_fallback() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager(output={"text": json.dumps(_good_meta())})
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success


def test_meta_reviewer_announce_false() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert manager.received_announce is False


def test_meta_reviewer_snapshot_includes_counts() -> None:
    """Task args should carry the state snapshot with counts."""
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    snapshot = task.args["snapshot"]
    assert snapshot["candidate_ids"] == [c["id"] for c in state.candidates]
    assert snapshot["evolution_yield"]["successful"] == 2  # 2 evolved
    assert snapshot["evolution_yield"]["attempted"] == 3  # 3 survivors
    assert "elo_distribution" in snapshot


def test_meta_reviewer_description_mentions_run_id() -> None:
    state = _state_with_full_pipeline_data(3)
    manager = _StubManager()
    MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    desc = manager.received_tasks[0].description
    assert "t-meta" in desc
    assert "broken_tool_use" in desc


def test_meta_reviewer_drops_response_missing_session_summary() -> None:
    """All 7 fields required — missing any → drop."""
    state = _state_with_full_pipeline_data(3)
    partial = _good_meta()
    del partial["session_summary"]
    manager = _StubManager(output=partial)
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "meta_review_failed"


def test_meta_reviewer_empty_elo_ratings_safe() -> None:
    """elo_distribution computation tolerates empty elo_ratings dict."""
    state = _state_with_full_pipeline_data(3)
    state.elo_ratings = {}
    manager = _StubManager()
    result = MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    snapshot = manager.received_tasks[0].args["snapshot"]
    assert snapshot["elo_distribution"]["min"] == 0.0


def test_meta_reviewer_coverage_aggregates_target_dims() -> None:
    """Snapshot coverage groups candidates by target_dim."""
    state = _state_with_full_pipeline_data(2)
    state.candidates[1]["target_dim"] = "input_hallucination"
    manager = _StubManager()
    MetaReviewer(manager=manager).execute(state)  # type: ignore[arg-type]
    snapshot = manager.received_tasks[0].args["snapshot"]
    assert snapshot["coverage"]["broken_tool_use"] == 1
    assert snapshot["coverage"]["input_hallucination"] == 1
