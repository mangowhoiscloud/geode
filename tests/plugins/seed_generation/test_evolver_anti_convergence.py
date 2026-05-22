"""Tests for CSP-6 Evolver anti-convergence Jaccard guard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from plugins.seed_generation.agents.evolver import (
    ANTI_CONVERGENCE_JACCARD_THRESHOLD,
    Evolver,
)


@pytest.fixture
def evolver() -> Evolver:
    # Manager is not exercised by ``_is_near_duplicate``; we only need
    # an instance to call the method.
    return Evolver(manager=None)  # type: ignore[arg-type]


def _write(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


class TestIsNearDuplicate:
    def test_distinct_body_admitted(self, tmp_path: Path, evolver: Evolver) -> None:
        evolved = _write(tmp_path, "ev.md", "completely unique scenario about tool error parsing")
        sibling = _write(
            tmp_path, "sib.md", "totally different paragraph mentioning escalation only"
        )
        parsed = {"evolved_path": evolved, "parent_id": None}
        already = [{"path": sibling}]
        assert evolver._is_near_duplicate(parsed, already, {}) is False

    def test_near_duplicate_sibling_flagged(self, tmp_path: Path, evolver: Evolver) -> None:
        # Both bodies share the same long 5-gram prefix → Jaccard ≥ 0.7.
        shared = (
            "the model misuses tool error to escalate without reflection in repeated tries today"
        )
        a = _write(tmp_path, "a.md", shared)
        b = _write(tmp_path, "b.md", shared + " minor difference")
        parsed = {"evolved_path": a, "parent_id": None}
        already = [{"path": b}]
        assert evolver._is_near_duplicate(parsed, already, {}) is True

    def test_near_duplicate_parent_flagged(self, tmp_path: Path, evolver: Evolver) -> None:
        # Evolver verdict claimed "ok" but the body is the same as parent.
        shared = (
            "the model misuses tool error to escalate without reflection in repeated tries today"
        )
        parent_path = _write(tmp_path, "parent.md", shared)
        evolved_path = _write(tmp_path, "evolved.md", shared)
        parsed = {"evolved_path": evolved_path, "parent_id": "parent_id_xyz"}
        candidates_by_id = {"parent_id_xyz": {"path": parent_path}}
        assert evolver._is_near_duplicate(parsed, [], candidates_by_id) is True

    def test_unreadable_evolved_returns_false(self, tmp_path: Path, evolver: Evolver) -> None:
        """IO failure on the evolved path → admit (fail open, defensive
        per CSP-6 docstring; failing closed on every blip would mask
        legitimate evolutions)."""
        parsed = {"evolved_path": str(tmp_path / "does_not_exist.md"), "parent_id": None}
        assert evolver._is_near_duplicate(parsed, [], {}) is False

    def test_missing_evolved_path_returns_false(self, evolver: Evolver) -> None:
        parsed = {"evolved_path": "", "parent_id": None}
        assert evolver._is_near_duplicate(parsed, [], {}) is False

    def test_threshold_value(self) -> None:
        # Pin the threshold so accidental changes show up in review.
        assert ANTI_CONVERGENCE_JACCARD_THRESHOLD == 0.70


class TestEvolverExecuteAdmissionFlow:
    """Smoke through ``Evolver.execute`` — near-duplicate evolved rows
    must be dropped before the SeedAgentResult is built."""

    def test_near_duplicate_dropped(self, tmp_path: Path, monkeypatch) -> None:
        # Two evolved bodies share the same prefix → second one is the
        # near-duplicate and should be dropped from evolved_candidates.
        from plugins.seed_generation.orchestrator import PipelineState

        shared = (
            "the model misuses tool error to escalate without reflection in repeated tries today"
        )
        a_path = _write(tmp_path, "a.md", shared)
        b_path = _write(tmp_path, "b.md", shared + " trivial diff")

        # Stub manager: emits 2 ok-verdict results, both passing the
        # parse contract; the second one is the near-duplicate.
        class _StubResult:
            def __init__(self, task_id: str, output: dict[str, Any]) -> None:
                self.task_id = task_id
                self.output = output
                self.success = True
                self.error = None
                self.duration_ms = 0.0

        outputs = {
            "evolve-c0": {
                "parent_id": "c0",
                "evolved_id": "e0",
                "evolved_path": a_path,
                "rewrite_section": "Body",
                "verdict": "ok",
            },
            "evolve-c1": {
                "parent_id": "c1",
                "evolved_id": "e1",
                "evolved_path": b_path,
                "rewrite_section": "Body",
                "verdict": "ok",
            },
        }

        class _StubManager:
            def delegate(self, tasks: list[Any], *, announce: bool = False) -> list[Any]:
                return [_StubResult(t.task_id, outputs[t.task_id]) for t in tasks]

        state = PipelineState(run_id="r", target_dim="d", gen_tag="g")
        state.candidates = [
            {"id": "c0", "path": str(tmp_path / "p0.md"), "target_dim": "d"},
            {"id": "c1", "path": str(tmp_path / "p1.md"), "target_dim": "d"},
        ]
        state.survivors = ["c0", "c1"]
        state.reflections = {
            "c0": {"weaknesses": [], "rewrite_section": "Body"},
            "c1": {"weaknesses": [], "rewrite_section": "Body"},
        }

        evolver = Evolver(_StubManager())  # type: ignore[arg-type]
        result = evolver.execute(state)
        # First evolved row admitted (no siblings yet); second is the
        # near-duplicate → dropped → only 1 evolved row.
        assert result.success is True
        rows = result.output["evolved_candidates"]
        assert len(rows) == 1
        assert rows[0]["id"] == "e0"  # the first spawn was admitted
        assert rows[0]["parent_id"] == "c0"
