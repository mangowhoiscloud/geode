"""Tests for the CSP-8 LLM-clustering Proximity agent.

The pre-CSP-8 surface (~590 LOC) targeted the 3-track majority vote
(embedding cosine + 5-gram Jaccard + role overlap) + partial-survive
floor + goal-conditioning. CSP-8 reverted to the paper's single LLM
clustering call (``open-coscientist/nodes/proximity.py``), so this
file is rewritten to pin the new contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plugins.seed_generation.agents.proximity import (
    HIGH_SIMILARITY_DEGREE,
    Proximity,
    _build_candidate_summary,
    _select_removals,
)
from plugins.seed_generation.orchestrator import PipelineState


class _StubSubResult:
    def __init__(self, *, task_id: str, output: dict[str, Any], success: bool = True) -> None:
        self.task_id = task_id
        self.output = output
        self.success = success
        self.error: str | None = None
        self.duration_ms = 0.0


class _StubManager:
    def __init__(self, output: dict[str, Any], *, success: bool = True) -> None:
        self._output = output
        self._success = success
        self.delegated: list[Any] = []

    def delegate(self, tasks: list[Any], *, announce: bool = False) -> list[Any]:
        self.delegated.append((tasks, announce))
        return [
            _StubSubResult(task_id=tasks[0].task_id, output=self._output, success=self._success)
        ]


def _seed_candidate(tmp_path: Path, name: str, body: str = "scenario body") -> dict[str, Any]:
    p = tmp_path / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return {"id": name, "path": str(p), "target_dim": "broken_tool_use"}


def _state_with(tmp_path: Path, *cids: str) -> PipelineState:
    state = PipelineState(run_id="r1", target_dim="broken_tool_use", gen_tag="gen1")
    state.candidates = [_seed_candidate(tmp_path, cid) for cid in cids]
    return state


class TestExecuteDropsHighSimilarity:
    def test_single_cluster_two_high_one_survivor(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "c0", "c1", "c2")
        output = {
            "similarity_clusters": [
                {
                    "cluster_id": "k1",
                    "topic": "tool-error-ambiguity",
                    "similar_hypotheses": [
                        {"candidate_id": "c1", "similarity_degree": "high"},
                        {"candidate_id": "c2", "similarity_degree": "high"},
                    ],
                }
            ]
        }
        proximity = Proximity(_StubManager(output))  # type: ignore[arg-type]
        result = proximity.execute(state)
        assert result.status == "ok"
        assert {c["id"] for c in state.candidates} == {"c0"}
        removed = result.output["removed_duplicates"]
        assert {row["candidate_id"] for row in removed} == {"c1", "c2"}

    def test_medium_low_degrees_dont_drop(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "c0", "c1", "c2")
        output = {
            "similarity_clusters": [
                {
                    "cluster_id": "k1",
                    "topic": "tangential overlap",
                    "similar_hypotheses": [
                        {"candidate_id": "c0", "similarity_degree": "medium"},
                        {"candidate_id": "c1", "similarity_degree": "low"},
                        {"candidate_id": "c2", "similarity_degree": "medium"},
                    ],
                }
            ]
        }
        Proximity(_StubManager(output)).execute(state)  # type: ignore[arg-type]
        assert {c["id"] for c in state.candidates} == {"c0", "c1", "c2"}

    def test_unknown_candidate_id_ignored(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "c0", "c1")
        output = {
            "similarity_clusters": [
                {
                    "cluster_id": "k1",
                    "topic": "x",
                    "similar_hypotheses": [
                        {"candidate_id": "ghost", "similarity_degree": "high"},
                        {"candidate_id": "c1", "similarity_degree": "high"},
                    ],
                }
            ]
        }
        Proximity(_StubManager(output)).execute(state)  # type: ignore[arg-type]
        assert {c["id"] for c in state.candidates} == {"c0"}


class TestExecuteErrorPaths:
    def test_empty_candidates_validation_error(self) -> None:
        state = PipelineState(run_id="r1", target_dim="d", gen_tag="g1")
        result = Proximity(_StubManager({})).execute(state)  # type: ignore[arg-type]
        assert result.status == "error"
        assert result.error_category == "validation"

    def test_single_candidate_trivial_pass(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "only")
        result = Proximity(_StubManager({"unused": "yes"})).execute(state)  # type: ignore[arg-type]
        assert result.status == "ok"
        assert result.output["similarity_clusters"] == []
        assert result.output["removed_duplicates"] == []

    def test_sub_agent_failure_surfaces(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "c0", "c1")
        result = Proximity(_StubManager({}, success=False)).execute(state)  # type: ignore[arg-type]
        assert result.status == "error"
        assert result.error_category == "proximity_failed"

    def test_malformed_payload_missing_field(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "c0", "c1")
        result = Proximity(_StubManager({"wrong_key": []})).execute(state)  # type: ignore[arg-type]
        assert result.status == "error"
        assert result.error_category == "proximity_failed"

    def test_malformed_clusters_not_list(self, tmp_path: Path) -> None:
        state = _state_with(tmp_path, "c0", "c1")
        result = Proximity(_StubManager({"similarity_clusters": "x"})).execute(state)  # type: ignore[arg-type]
        assert result.status == "error"
        assert "must be a list" in (result.error_message or "")


class TestBuildCandidateSummary:
    def test_emits_id_and_excerpt(self, tmp_path: Path) -> None:
        c0 = _seed_candidate(tmp_path, "c0", "First scenario body about ambiguity.")
        c1 = _seed_candidate(tmp_path, "c1", "Second\n\nscenario.")
        summary = _build_candidate_summary([c0, c1])
        assert "- id: c0" in summary
        assert "First scenario body about ambiguity." in summary
        assert "- id: c1" in summary
        assert "Second scenario." in summary  # whitespace-collapsed

    def test_unreadable_path_marker(self, tmp_path: Path) -> None:
        c = {"id": "c0", "path": str(tmp_path / "does_not_exist.md"), "target_dim": "d"}
        summary = _build_candidate_summary([c])
        assert "<body unreadable" in summary

    def test_missing_path_emits_empty_excerpt(self) -> None:
        summary = _build_candidate_summary([{"id": "c0"}])
        assert "- id: c0" in summary
        assert "excerpt:" in summary


class TestSelectRemovals:
    def test_high_degree_only(self) -> None:
        candidates = [{"id": "c0"}, {"id": "c1"}, {"id": "c2"}]
        clusters = [
            {
                "cluster_id": "k1",
                "topic": "x",
                "similar_hypotheses": [
                    {"candidate_id": "c1", "similarity_degree": "high"},
                    {"candidate_id": "c2", "similarity_degree": "medium"},
                ],
            }
        ]
        removed_ids, removed_rows = _select_removals(candidates, clusters)
        assert removed_ids == {"c1"}
        assert len(removed_rows) == 1
        assert removed_rows[0]["cluster_id"] == "k1"

    def test_unknown_id_dropped(self) -> None:
        candidates = [{"id": "c0"}]
        clusters = [
            {
                "cluster_id": "k1",
                "topic": "x",
                "similar_hypotheses": [
                    {"candidate_id": "ghost", "similarity_degree": "high"},
                ],
            }
        ]
        removed_ids, _ = _select_removals(candidates, clusters)
        assert removed_ids == set()

    def test_invalid_degree_dropped(self) -> None:
        candidates = [{"id": "c0"}, {"id": "c1"}]
        clusters = [
            {
                "cluster_id": "k1",
                "topic": "x",
                "similar_hypotheses": [
                    {"candidate_id": "c1", "similarity_degree": "very-high"},
                ],
            }
        ]
        removed_ids, _ = _select_removals(candidates, clusters)
        assert removed_ids == set()

    def test_malformed_cluster_skipped(self) -> None:
        candidates = [{"id": "c0"}]
        clusters = ["not-a-dict", {"similar_hypotheses": "not-a-list"}]
        removed_ids, _ = _select_removals(candidates, clusters)
        assert removed_ids == set()


def test_high_degree_constant_pinned() -> None:
    """Pinned so any future relaxation shows up in review."""
    assert HIGH_SIMILARITY_DEGREE == "high"
