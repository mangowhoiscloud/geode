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


def test_persist_survivors_creates_symlink_dir(tmp_path: Path) -> None:
    """``survivors/`` dir holds symlinks to each survivor candidate .md."""
    state = _populated_state(tmp_path)
    cand_path = _seed_candidate_md(tmp_path, "c-00")
    state.candidates = [{"id": "c-00", "path": str(cand_path), "target_dim": "broken_tool_use"}]
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    survivors_dir = tmp_path / "survivors"
    assert survivors_dir.is_dir()
    link = survivors_dir / "c-00.md"
    assert link.is_symlink()
    assert link.resolve() == cand_path.resolve()


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
# P1a — cross-loop session index (defects #2, #3 from 2026-05-19 plan)
# ---------------------------------------------------------------------------


def test_pipeline_appends_session_index(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Pipeline.run() appends one row to ``~/.geode/self-improving-loop/sessions.jsonl``."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
    state = _populated_state(tmp_path)
    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    pipeline.run()
    index = fake_home / ".geode" / "self-improving-loop" / "sessions.jsonl"
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
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
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
