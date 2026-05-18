"""Tests for the S8 parent-context offload — Pipeline._persist_state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_pipeline.orchestrator import (
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
