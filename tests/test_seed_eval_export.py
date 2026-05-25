"""PR-SEEDS-EVAL-EXPORT — converter invariants.

Pins:
- ``export_run_to_evals`` produces one ``.eval`` per non-empty phase.
- Each produced ``.eval`` is valid per ``scripts/validate_petri_bundle.py``
  (status='success', non-empty results.scores with metrics).
- ``listing.json`` gains an entry for every produced file.
- Bundle_sync integration runs the export when env knob is unset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plugins.seed_generation.eval_export import PHASE_TASKS, export_run_to_evals

# ---------------------------------------------------------------------------
# Fixtures — a minimal but multi-phase seed-gen run
# ---------------------------------------------------------------------------


def _write_run(run_dir: Path) -> Path:
    """Write a state.json + survivors.json + meta_review.json that
    exercises 7 of the 8 phases (supervisor stays empty)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": run_dir.name,
        "target_dim": "redundant_tool_invocation",
        "gen_tag": "gen-test",
        "candidates_requested": 2,
        "candidates": [
            {
                "id": "c-001",
                "path": str(run_dir / "candidates/c-001.md"),
                "target_dim": "redundant_tool_invocation",
                "duration_ms": 1.0,
            },
            {
                "id": "c-002",
                "path": str(run_dir / "candidates/c-002.md"),
                "target_dim": "redundant_tool_invocation",
                "duration_ms": 2.0,
            },
        ],
        "reflections": {
            "c-001": {
                "candidate_id": "c-001",
                "strengths": ["a"],
                "weaknesses": ["b"],
                "discrimination_estimate": 0.6,
                "judge_risk": "low",
            },
            "c-002": {
                "candidate_id": "c-002",
                "strengths": ["c"],
                "weaknesses": ["d"],
                "discrimination_estimate": 0.4,
                "judge_risk": "med",
            },
        },
        "pilot_scores": {
            "c-001": {
                "candidate_id": "c-001",
                "dim_means": {"redundant_tool_invocation": 2.5},
                "status": "ok",
            }
        },
        "similarity_clusters": [
            {"cluster_id": "cluster-0", "topic": "x", "similar_hypotheses": []}
        ],
        "elo_ratings": {"c-001": 1010, "c-002": 990},
        "survivors": ["c-001", "c-002"],
        "evolved_candidates": [
            {"id": "c-001-e", "parent_id": "c-001", "notes": "evolved", "duration_ms": 0.0}
        ],
        "supervisor_guidance": {},
        "meta_review": {
            "coverage": {"redundant_tool_invocation": 2, "broken_tool_use": 0},
            "underrepresented_dims": ["broken_tool_use"],
            "overrepresented_dims": [],
            "next_gen_priors": [{"target_dim": "broken_tool_use", "weight": 0.5, "rationale": "x"}],
            "elo_distribution": {"min": 990, "p50": 1000, "p95": 1010},
            "evolution_yield": {"attempted": 1, "successful": 1},
            "session_summary": "summary",
        },
    }
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "survivors.json").write_text(
        json.dumps({"survivors": [{"id": "c-001", "elo_rating": 1010, "pilot": None}]}),
        encoding="utf-8",
    )
    (run_dir / "meta_review.json").write_text(json.dumps(state["meta_review"]), encoding="utf-8")
    (run_dir / "candidates").mkdir(exist_ok=True)
    (run_dir / "candidates/c-001.md").write_text("seed body 1", encoding="utf-8")
    (run_dir / "candidates/c-002.md").write_text("seed body 2", encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_export_produces_one_eval_per_nonempty_phase(tmp_path: Path) -> None:
    src = _write_run(tmp_path / "gen-test-run")
    dest = tmp_path / "logs"
    written = export_run_to_evals(src, dest)

    # 7 phases populated: generator, proximity, critic, pilot, ranker,
    # evolver, meta_reviewer (supervisor skipped — guidance empty).
    assert len(written) == 7
    listing = json.loads((dest / "listing.json").read_text(encoding="utf-8"))
    tasks = {listing[p.name]["task"] for p in written}
    expected = {
        f"seed-generation/{phase}"
        for phase in (
            "generator",
            "proximity",
            "critic",
            "pilot",
            "ranker",
            "evolver",
            "meta_reviewer",
        )
    }
    assert tasks == expected


def test_each_eval_passes_validator_shape(tmp_path: Path) -> None:
    pytest.importorskip("inspect_ai")
    from inspect_ai.log import read_eval_log

    src = _write_run(tmp_path / "gen-shape-run")
    dest = tmp_path / "logs"
    written = export_run_to_evals(src, dest)

    for path in written:
        log_obj = read_eval_log(str(path))
        # Validator-critical invariants — see scripts/validate_petri_bundle.py.
        assert log_obj.status == "success"
        assert log_obj.results is not None
        scores = log_obj.results.scores
        assert scores, f"{path.name}: results.scores empty"
        for score in scores:
            assert score.metrics, f"{path.name}: score {score.name} has empty metrics"


def test_listing_json_gains_entry_per_eval(tmp_path: Path) -> None:
    src = _write_run(tmp_path / "gen-listing-run")
    dest = tmp_path / "logs"
    written = export_run_to_evals(src, dest)

    listing_path = dest / "listing.json"
    assert listing_path.is_file()
    listing = json.loads(listing_path.read_text(encoding="utf-8"))
    for path in written:
        assert path.name in listing, f"{path.name} missing from listing.json"
        entry = listing[path.name]
        assert entry.get("status") == "success"
        assert "task" in entry and entry["task"].startswith("seed-generation/")


def test_phase_task_names_match_constant() -> None:
    # Defensive — PHASE_TASKS is the public name-map; both halves of
    # the converter (export + UI) read it. If it drifts the validator
    # entry's ``task`` field stops matching what the SPA expects.
    for phase, task in PHASE_TASKS.items():
        assert task == f"seed-generation/{phase}"


def test_empty_run_skips_all_phases(tmp_path: Path) -> None:
    src = tmp_path / "empty-run"
    src.mkdir()
    (src / "state.json").write_text(
        json.dumps({"run_id": "empty-run", "target_dim": "x", "gen_tag": "g"}),
        encoding="utf-8",
    )
    dest = tmp_path / "logs"
    assert export_run_to_evals(src, dest) == []
    assert not (dest / "listing.json").is_file()


def test_missing_state_json_returns_empty(tmp_path: Path) -> None:
    src = tmp_path / "no-state"
    src.mkdir()
    assert export_run_to_evals(src, tmp_path / "logs") == []
