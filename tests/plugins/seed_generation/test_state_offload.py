"""Tests for the S8 parent-context offload — Pipeline._persist_state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
)


class _NoopAgent(BaseSeedAgent):
    """Concrete agent that returns success without touching state.

    Used by tests that only exercise the orchestrator's persistence
    boundary, not the agent logic.
    """

    def __init__(self, role: str) -> None:
        super().__init__(role=role, model="dummy")

    def execute(self, state: Any) -> SeedAgentResult:
        return SeedAgentResult(role=self.role)


def _populated_state(run_dir: Path) -> PipelineState:
    state = PipelineState(
        run_id="t-offload",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=3,
        run_dir=run_dir,
    )
    state.candidates = [{"id": "c-00", "path": "x", "target_dim": "broken_tool_use"}]
    state.reflections = {"c-00": {"strengths": ["a"]}}
    state.pilot_scores = {"c-00": {"dim_means": {"d": 0.5}}}
    state.elo_ratings = {"c-00": 1010.0}
    state.survivors = ["c-00"]
    state.evolved_candidates = [{"id": "c-00-ev", "parent_id": "c-00"}]
    state.meta_review = {"coverage": {"broken_tool_use": 1}}
    state.usd_spent = 0.42
    return state


def _registry_with_noop_agents() -> PipelineRegistry:
    reg = PipelineRegistry()
    for role in (
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ):
        reg.register(_NoopAgent(role))
    return reg


def test_persist_state_writes_state_json(tmp_path: Path) -> None:
    state = _populated_state(tmp_path)
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    state_path = tmp_path / "state.json"
    assert state_path.is_file()
    blob = json.loads(state_path.read_text(encoding="utf-8"))
    assert blob["run_id"] == "t-offload"
    assert blob["survivors"] == ["c-00"]
    assert blob["evolved_candidates"][0]["id"] == "c-00-ev"
    assert blob["meta_review"]["coverage"]["broken_tool_use"] == 1


def test_persist_state_includes_cost_rollup(tmp_path: Path) -> None:
    state = _populated_state(tmp_path)
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    blob = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert blob["usd_spent"] == 0.42


def test_persist_state_omitted_when_run_dir_unset(tmp_path: Path) -> None:
    state = _populated_state(tmp_path)
    state.run_dir = None
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    # No state.json written
    assert not (tmp_path / "state.json").exists()


def test_persist_state_path_fields_coerced_to_strings(tmp_path: Path) -> None:
    state = _populated_state(tmp_path)
    state.pool_path_in = tmp_path / "pool_in"
    state.pool_path_out = tmp_path / "pool_out"
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    blob = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert isinstance(blob["pool_path_in"], str)
    assert isinstance(blob["pool_path_out"], str)
    assert isinstance(blob["run_dir"], str)


def test_persist_state_excludes_runtime_only_fields(tmp_path: Path) -> None:
    """Runtime-only fields (e.g. former budget_guard) are not persisted.

    PR 1 removed BudgetGuard; this test still pins the rule that the
    JSON offload only carries serializable data, not runtime-attached
    helper objects.
    """
    state = _populated_state(tmp_path)
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    blob = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "budget_guard" not in blob


# ---------------------------------------------------------------------------
# P0b — cross-loop handoff (defect #13 from 2026-05-19 self-improving-loop plan)
# ---------------------------------------------------------------------------


def _seed_candidate_md(run_dir: Path, cid: str) -> Path:
    """Create a fake candidate body file under <run_dir>/candidates/."""
    cand_dir = run_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    path = cand_dir / f"{cid}.md"
    path.write_text(f"# {cid}\n\nbody for {cid}\n", encoding="utf-8")
    return path


def test_persist_survivors_writes_survivors_json(tmp_path: Path) -> None:
    """Pipeline.run() emits ``<run_dir>/survivors.json`` with metadata."""
    state = _populated_state(tmp_path)
    cand_path = _seed_candidate_md(tmp_path, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    survivors_path = tmp_path / "survivors.json"
    assert survivors_path.is_file()
    blob = json.loads(survivors_path.read_text(encoding="utf-8"))
    assert blob["gen_tag"] == "gen2"
    assert blob["target_dim"] == "broken_tool_use"
    assert blob["run_id"] == "t-offload"
    rows = blob["survivors"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["id"] == "c-00"
    assert rows[0]["path"] == str(cand_path)
    assert rows[0]["elo_rating"] == 1010.0
    assert rows[0]["pilot"] == {"dim_means": {"d": 0.5}}


def test_persist_survivors_creates_file_copy_dir(tmp_path: Path) -> None:
    """CSP-7: ``survivors/`` dir holds FILE COPIES (was symlinks) of each
    survivor candidate .md so the directory is self-contained on a
    cross-machine clone."""
    state = _populated_state(tmp_path)
    cand_path = _seed_candidate_md(tmp_path, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    survivors_dir = tmp_path / "survivors"
    assert survivors_dir.is_dir()
    copy = survivors_dir / "c-00.md"
    assert copy.is_file() and not copy.is_symlink()
    # Content equality — copy carries the same bytes as the source candidate.
    assert copy.read_bytes() == cand_path.read_bytes()


def test_persist_survivors_pool_path_out_targets_directory(tmp_path: Path) -> None:
    """state.pool_path_out points at the symlink dir (inspect-petri consumer)."""
    state = _populated_state(tmp_path)
    cand_path = _seed_candidate_md(tmp_path, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    assert state.pool_path_out == tmp_path / "survivors"
    # Stamp happens before _persist_state, so state.json carries the path.
    blob = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert blob["pool_path_out"] == str(tmp_path / "survivors")


def test_persist_survivors_omitted_when_run_dir_unset(tmp_path: Path) -> None:
    """Survivors export is skipped when run_dir is None (parity with state.json)."""
    state = _populated_state(tmp_path)
    state.run_dir = None
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    assert not (tmp_path / "survivors.json").exists()
    assert not (tmp_path / "survivors").exists()
    assert state.pool_path_out is None


def test_persist_survivors_handles_missing_elo_and_pilot(tmp_path: Path) -> None:
    """A survivor without elo_rating/pilot_score yields null entries, not KeyError."""
    state = _populated_state(tmp_path)
    cand_path = _seed_candidate_md(tmp_path, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    state.survivors = ["c-00", "c-missing"]
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    blob = json.loads((tmp_path / "survivors.json").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in blob["survivors"]}
    assert rows["c-missing"]["elo_rating"] is None
    assert rows["c-missing"]["pilot"] is None
    assert rows["c-missing"]["path"] is None
    # Only c-00 has a real candidate body, so only one symlink exists.
    symlinks = list((tmp_path / "survivors").iterdir())
    assert len(symlinks) == 1
    assert symlinks[0].name == "c-00.md"


def test_persist_survivors_clears_stale_symlinks(tmp_path: Path) -> None:
    """A second run with different survivors replaces, not accumulates, symlinks."""
    state = _populated_state(tmp_path)
    cand_a = _seed_candidate_md(tmp_path, "c-old")
    cand_b = _seed_candidate_md(tmp_path, "c-new")
    state.candidates = [
        {"id": "c-old", "path": str(cand_a), "target_dim": "broken_tool_use"},
        {"id": "c-new", "path": str(cand_b), "target_dim": "broken_tool_use"},
    ]
    state.survivors = ["c-old"]
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    # Second run with a different survivor set.
    state.survivors = ["c-new"]
    pipeline.run()
    survivors_dir = tmp_path / "survivors"
    names = sorted(p.name for p in survivors_dir.iterdir())
    assert names == ["c-new.md"]


# ---------------------------------------------------------------------------
# CSP-7 — latest_pointer.json (replaces pre-CSP-7 symlink pair, 2026-05-22)
# ---------------------------------------------------------------------------


def _patch_state_root(monkeypatch: Any, root: Path) -> Path:
    """Redirect ``core.paths`` STATE_* constants at ``root`` for the test."""
    import core.paths as cp

    monkeypatch.setattr(cp, "STATE_ROOT", root)
    monkeypatch.setattr(cp, "STATE_SELF_IMPROVING_LOOP_DIR", root / "self-improving-loop")
    monkeypatch.setattr(cp, "STATE_SEED_GENERATION_DIR", root / "seed-generation")
    monkeypatch.setattr(
        cp,
        "STATE_LATEST_POINTER_PATH",
        root / "self-improving-loop" / "latest_pointer.json",
    )
    return root


def test_persist_survivors_writes_latest_pointer(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """CSP-7: ``state/self-improving-loop/latest_pointer.json`` carries
    the seed_pool path (was: latest_seed_pool symlink)."""
    state_root = _patch_state_root(monkeypatch, tmp_path / "state")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = _populated_state(run_dir)
    cand_path = _seed_candidate_md(run_dir, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    Pipeline(state=state, registry=_registry_with_noop_agents()).run()
    pointer = state_root / "self-improving-loop" / "latest_pointer.json"
    assert pointer.is_file()
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["run_id"] == state.run_id
    assert payload["gen_tag"] == state.gen_tag
    # seed_pool stored as absolute (run_dir outside STATE_ROOT in this fixture).
    assert payload["seed_pool"].endswith("/survivors")
    assert Path(payload["seed_pool"]).resolve() == (run_dir / "survivors").resolve()


def test_persist_survivors_pointer_moves_forward(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """A second run rewrites the pointer to the new survivors dir (was:
    symlink retarget)."""
    state_root = _patch_state_root(monkeypatch, tmp_path / "state")

    run_a = tmp_path / "runA"
    run_a.mkdir()
    state_a = _populated_state(run_a)
    cand_a = _seed_candidate_md(run_a, "c-00")
    state_a.candidates = [{"id": "c-00", "path": str(cand_a), "target_dim": "broken_tool_use"}]
    Pipeline(state=state_a, registry=_registry_with_noop_agents()).run()

    run_b = tmp_path / "runB"
    run_b.mkdir()
    state_b = _populated_state(run_b)
    cand_b = _seed_candidate_md(run_b, "c-00")
    state_b.candidates = [{"id": "c-00", "path": str(cand_b), "target_dim": "broken_tool_use"}]
    Pipeline(state=state_b, registry=_registry_with_noop_agents()).run()

    pointer = state_root / "self-improving-loop" / "latest_pointer.json"
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert Path(payload["seed_pool"]).resolve() == (run_b / "survivors").resolve()


def test_persist_survivors_pointer_swallows_oserror(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Pointer-write failure must not break the run (best-effort handoff)."""
    state_root = _patch_state_root(monkeypatch, tmp_path / "state")
    original_write = Path.write_text

    def _selective_write(self: Path, *a: Any, **kw: Any) -> int:
        if self.name == "latest_pointer.json":
            raise OSError("simulated pointer-write failure")
        return original_write(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", _selective_write)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = _populated_state(run_dir)
    cand_path = _seed_candidate_md(run_dir, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    Pipeline(state=state, registry=_registry_with_noop_agents()).run()  # must not raise
    # Canonical handoff (state.pool_path_out + survivors_dir copies) stays intact.
    assert state.pool_path_out == run_dir / "survivors"
    assert (run_dir / "survivors" / "c-00.md").is_file()
    # Pointer file was not created because every write raised.
    assert not (state_root / "self-improving-loop" / "latest_pointer.json").exists()


# ---------------------------------------------------------------------------
# P1a — cross-loop session index (defects #2, #3 from 2026-05-19 plan)
# ---------------------------------------------------------------------------


def test_pipeline_appends_session_index(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Pipeline.run() appends one row to ``state/self-improving-loop/sessions.jsonl``
    (CSP-7: was ``~/.geode/self-improving-loop/sessions.jsonl``)."""
    state_root = _patch_state_root(monkeypatch, tmp_path / "state")
    state = _populated_state(tmp_path)
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    index = state_root / "self-improving-loop" / "sessions.jsonl"
    assert index.is_file()
    lines = index.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["session_id"] == state.run_id
    assert row["gen_tag"] == state.gen_tag
    assert row["component"] == "seed-generation"
    assert row["target_dim"] == state.target_dim
    assert row["survivors"] == len(state.survivors)
    assert row["usd_spent"] == round(state.usd_spent, 6)
    assert row["started_at"] <= row["ended_at"]


def test_pipeline_session_index_swallows_oserror(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Index-append OSError must not break the run."""
    _patch_state_root(monkeypatch, tmp_path / "state")
    original_mkdir = Path.mkdir

    def _selective_mkdir(self: Path, *a: Any, **kw: Any) -> None:
        if "self-improving-loop" in str(self):
            raise OSError("simulated")
        return original_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", _selective_mkdir)
    state = _populated_state(tmp_path)
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()  # Must NOT raise.
    # State persistence (other paths) still works.
    assert (tmp_path / "state.json").is_file()


# ---------------------------------------------------------------------------
# G4 — meta_review persist + latest_meta_review.json symlink (2026-05-20)
# ---------------------------------------------------------------------------


def test_persist_meta_review_writes_standalone_json(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Pipeline.run() emits ``<run_dir>/meta_review.json`` when state.meta_review is set."""
    _patch_state_root(monkeypatch, tmp_path / "state")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = _populated_state(run_dir)
    Pipeline(state=state, registry=_registry_with_noop_agents()).run()
    meta_review_path = run_dir / "meta_review.json"
    assert meta_review_path.is_file()
    blob = json.loads(meta_review_path.read_text(encoding="utf-8"))
    assert blob == state.meta_review


def test_persist_meta_review_skipped_when_empty(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """No meta_review → no standalone file (bootstrap / failed meta phase)."""
    _patch_state_root(monkeypatch, tmp_path / "state")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = _populated_state(run_dir)
    state.meta_review = {}
    Pipeline(state=state, registry=_registry_with_noop_agents()).run()
    assert not (run_dir / "meta_review.json").exists()


def test_persist_meta_review_writes_pointer(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """CSP-7: latest_pointer.json's ``meta_review`` key points at this
    run's meta_review.json (was: latest_meta_review.json symlink)."""
    state_root = _patch_state_root(monkeypatch, tmp_path / "state")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = _populated_state(run_dir)
    Pipeline(state=state, registry=_registry_with_noop_agents()).run()
    pointer = state_root / "self-improving-loop" / "latest_pointer.json"
    assert pointer.is_file()
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert "meta_review" in payload
    assert Path(payload["meta_review"]).resolve() == (run_dir / "meta_review.json").resolve()


def test_persist_meta_review_pointer_moves_forward(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """A second run rewrites the pointer's meta_review key (was symlink retarget)."""
    state_root = _patch_state_root(monkeypatch, tmp_path / "state")

    run_a = tmp_path / "runA"
    run_a.mkdir()
    state_a = _populated_state(run_a)
    Pipeline(state=state_a, registry=_registry_with_noop_agents()).run()

    run_b = tmp_path / "runB"
    run_b.mkdir()
    state_b = _populated_state(run_b)
    state_b.meta_review = {"coverage": {"d2": 1}, "next_gen_priors": []}
    Pipeline(state=state_b, registry=_registry_with_noop_agents()).run()

    pointer = state_root / "self-improving-loop" / "latest_pointer.json"
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert Path(payload["meta_review"]).resolve() == (run_b / "meta_review.json").resolve()
