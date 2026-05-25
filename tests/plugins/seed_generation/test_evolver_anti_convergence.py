"""Tests for CSP-6 Evolver anti-convergence Jaccard guard."""

from __future__ import annotations

import asyncio
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


class TestCheckNearDuplicate:
    def test_distinct_body_admitted(self, tmp_path: Path, evolver: Evolver) -> None:
        evolved = _write(tmp_path, "ev.md", "completely unique scenario about tool error parsing")
        sibling = _write(
            tmp_path, "sib.md", "totally different paragraph mentioning escalation only"
        )
        parsed = {"evolved_path": evolved, "parent_id": None}
        already = [{"id": "e0", "path": sibling}]
        is_dup, score, _against = evolver._check_near_duplicate(parsed, already, {})
        assert is_dup is False
        assert 0.0 <= score < ANTI_CONVERGENCE_JACCARD_THRESHOLD

    def test_near_duplicate_sibling_flagged(self, tmp_path: Path, evolver: Evolver) -> None:
        # Identical bodies → Jaccard 1.0 ≥ 0.90.
        shared = (
            "the model misuses tool error to escalate without reflection in repeated tries today"
        )
        a = _write(tmp_path, "a.md", shared)
        b = _write(tmp_path, "b.md", shared)
        parsed = {"evolved_path": a, "parent_id": None}
        already = [{"id": "e0", "path": b}]
        is_dup, score, against = evolver._check_near_duplicate(parsed, already, {})
        assert is_dup is True
        assert score >= ANTI_CONVERGENCE_JACCARD_THRESHOLD
        assert against == "sibling:e0"

    def test_near_duplicate_parent_flagged(self, tmp_path: Path, evolver: Evolver) -> None:
        # Evolver verdict claimed "ok" but the body is the same as parent.
        shared = (
            "the model misuses tool error to escalate without reflection in repeated tries today"
        )
        parent_path = _write(tmp_path, "parent.md", shared)
        evolved_path = _write(tmp_path, "evolved.md", shared)
        parsed = {"evolved_path": evolved_path, "parent_id": "parent_id_xyz"}
        candidates_by_id = {"parent_id_xyz": {"path": parent_path}}
        is_dup, score, against = evolver._check_near_duplicate(parsed, [], candidates_by_id)
        assert is_dup is True
        assert score >= ANTI_CONVERGENCE_JACCARD_THRESHOLD
        assert against == "parent:parent_id_xyz"

    def test_smoke14_replay_admitted_after_threshold_bump(
        self, tmp_path: Path, evolver: Evolver
    ) -> None:
        """Replay smoke 14 iter-2 evolver shape: a single-bullet rewrite
        of a ~3000-char parent yields Jaccard ≈ 0.84, which the
        original 0.70 threshold falsely rejected but 0.90 admits.

        This pins PR-EVOLVER-JACCARD-OBS's empirical claim. The
        archive at ``.audit/smoke-archives/smoke-14-1779674544/``
        documents the actual measurement (0.8437). Here we use a
        compact body but the same characteristic: ~85% of the
        5-grams overlap.
        """
        # 50 unique words shared between parent + evolved; the evolved
        # replaces 5 of them with synonyms → ~85% 5-gram overlap.
        base = (
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet "
            "kilo lima mike november oscar papa quebec romeo sierra tango "
            "uniform victor whiskey xray yankee zulu one two three four "
            "five six seven eight nine ten eleven twelve thirteen fourteen "
            "fifteen sixteen seventeen eighteen nineteen twenty alpha bravo charlie"
        )
        diverged = base.replace(
            "alpha bravo charlie delta echo",
            "WORDA WORDB WORDC WORDD WORDE",
        )
        parent_path = _write(tmp_path, "parent.md", base)
        evolved_path = _write(tmp_path, "evolved.md", diverged)
        parsed = {"evolved_path": evolved_path, "parent_id": "p"}
        candidates_by_id = {"p": {"path": parent_path}}
        is_dup, score, _against = evolver._check_near_duplicate(parsed, [], candidates_by_id)
        # Compliant single-section rewrite — admitted by 0.90 threshold,
        # rejected by old 0.70. Score documented here so a future
        # threshold tweak surfaces the empirical anchor.
        assert is_dup is False, f"score={score:.4f} should admit at 0.90"
        assert 0.70 <= score < 0.90, f"score={score:.4f} should sit in the 0.70-0.90 band"

    def test_unreadable_evolved_returns_admitting(
        self, tmp_path: Path, evolver: Evolver
    ) -> None:
        """IO failure on the evolved path → admit (fail open, defensive
        per CSP-6 docstring; failing closed on every blip would mask
        legitimate evolutions)."""
        parsed = {"evolved_path": str(tmp_path / "does_not_exist.md"), "parent_id": None}
        is_dup, score, against = evolver._check_near_duplicate(parsed, [], {})
        assert is_dup is False
        assert score == 0.0
        assert against == ""

    def test_missing_evolved_path_returns_admitting(self, evolver: Evolver) -> None:
        parsed = {"evolved_path": "", "parent_id": None}
        is_dup, score, against = evolver._check_near_duplicate(parsed, [], {})
        assert is_dup is False
        assert score == 0.0
        assert against == ""

    def test_threshold_value(self) -> None:
        # PR-EVOLVER-JACCARD-OBS raised the threshold 0.70 → 0.90;
        # pinned here so future drift surfaces in review with the
        # rationale (single-section ±20% prompt mathematically requires
        # the looser bound). Smoke 14 iter-2 measurement: 0.8437.
        assert ANTI_CONVERGENCE_JACCARD_THRESHOLD == 0.90


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
        b_path = _write(tmp_path, "b.md", shared)  # identical → Jaccard 1.0, certain dup hit

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
            async def adelegate(self, tasks, *, announce: bool = True) -> list:
                """Async sibling for Phase-C tests."""
                return self.delegate(tasks, announce=announce)

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
        result = asyncio.run(evolver.aexecute(state))
        # First evolved row admitted (no siblings yet); second is the
        # near-duplicate → dropped → only 1 evolved row.
        assert result.success is True
        rows = result.output["evolved_candidates"]
        assert len(rows) == 1
        assert rows[0]["id"] == "e0"  # the first spawn was admitted
        assert rows[0]["parent_id"] == "c0"
