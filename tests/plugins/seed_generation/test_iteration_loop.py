"""Tests for CSP-5 iteration loop — asyncio.run(Pipeline.arun()) outer cycle + evolved
candidate promotion + state JSON round-trip."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.orchestrator import (
    _ITERATION_PHASE_ORDER,
    _PHASE_ORDER,
    Pipeline,
    PipelineRegistry,
    PipelineState,
    _state_to_json,
)


class _RecordingAgent(BaseSeedAgent):
    """Stub agent that records the iteration cursor on every invocation."""

    def __init__(self, role: str, output: dict[str, Any] | None = None) -> None:
        super().__init__(role=role, model="stub", source="auto")
        self._output = output or {}
        self.calls: list[int] = []

    async def aexecute(self, state: Any) -> SeedAgentResult:
        self.calls.append(state.current_iteration)
        return SeedAgentResult(role=self.role, output=dict(self._output))


def _build_full_registry(
    *,
    evolver_emits: list[dict[str, Any]] | None = None,
) -> tuple[PipelineRegistry, dict[str, _RecordingAgent]]:
    """Register all 8 roles with stub agents so asyncio.run(Pipeline.arun()) walks
    without raising. ``evolver_emits`` controls what the Evolver writes
    into ``state.evolved_candidates`` — empty list means the iteration
    cycle terminates after meta_reviewer (no candidates to promote)."""
    agents: dict[str, _RecordingAgent] = {}
    role_outputs: dict[str, dict[str, Any]] = {
        "supervisor": {"supervisor_guidance": {"session_summary": "ok"}},
        "generator": {"candidates": [{"id": "c0", "path": "p0", "target_dim": "d"}]},
        "proximity": {},
        "critic": {"reflections": {"c0": {"strengths": [], "weaknesses": []}}},
        "pilot": {"pilot_scores": {"c0": {"dim_means": {}}}},
        "ranker": {"elo_ratings": {"c0": 1000.0}, "survivors": ["c0"]},
        "evolver": {"evolved_candidates": list(evolver_emits or [])},
        "meta_reviewer": {"meta_review": {"coverage": {}}},
    }
    registry = PipelineRegistry()
    for role, payload in role_outputs.items():
        agent = _RecordingAgent(role, payload)
        registry.register(agent)
        agents[role] = agent
    return registry, agents


class TestIterationLoop:
    def test_single_pass_default(self) -> None:
        """max_iterations=0 → asyncio.run(Pipeline.arun()) walks ``_PHASE_ORDER`` once."""
        registry, agents = _build_full_registry()
        state = PipelineState(run_id="r0", target_dim="d", gen_tag="g")
        asyncio.run(Pipeline(state, registry).arun())
        for role in _PHASE_ORDER:
            assert agents[role].calls == [0], (
                f"{role!r} should run once with iteration=0, got {agents[role].calls}"
            )
        assert state.current_iteration == 0

    def test_one_iteration_promotes_evolved(self) -> None:
        """max_iterations=1 + Evolver emits 2 evolved → iteration 1 runs
        the post-meta_reviewer cycle against the evolved candidates."""
        evolved = [
            {"id": "e1", "path": "p_e1", "target_dim": "d", "parent_id": "c0"},
            {"id": "e2", "path": "p_e2", "target_dim": "d", "parent_id": "c0"},
        ]
        registry, agents = _build_full_registry(evolver_emits=evolved)
        state = PipelineState(run_id="r1", target_dim="d", gen_tag="g", max_iterations=1)
        asyncio.run(Pipeline(state, registry).arun())
        # supervisor / generator / proximity stay at one call (iter 0 only).
        assert agents["supervisor"].calls == [0]
        assert agents["generator"].calls == [0]
        assert agents["proximity"].calls == [0]
        # critic / pilot / ranker / evolver / meta_reviewer ran twice.
        for role in _ITERATION_PHASE_ORDER:
            assert agents[role].calls == [0, 1], (
                f"{role!r} should run twice (iter 0 + iter 1), got {agents[role].calls}"
            )
        assert state.current_iteration == 1

    def test_iteration_skipped_when_no_evolved(self) -> None:
        """max_iterations=2 but Evolver yields nothing → no iteration cycles."""
        registry, agents = _build_full_registry(evolver_emits=[])
        state = PipelineState(run_id="r2", target_dim="d", gen_tag="g", max_iterations=2)
        asyncio.run(Pipeline(state, registry).arun())
        for role in _PHASE_ORDER:
            assert agents[role].calls == [0]


class TestPromoteEvolved:
    def test_promote_replaces_candidates_and_clears_ephemera(self) -> None:
        registry = PipelineRegistry()
        state = PipelineState(run_id="r3", target_dim="d", gen_tag="g")
        state.candidates = [{"id": "c0", "path": "p"}]
        state.reflections = {"c0": {"x": 1}}
        state.pilot_scores = {"c0": {"dim_means": {}}}
        state.elo_ratings = {"c0": 1100.0}
        state.survivors = ["c0"]
        state.evolved_candidates = [{"id": "e1", "path": "p_e1", "parent_id": "c0"}]
        pipeline = Pipeline(state, registry)
        promoted = pipeline._promote_evolved_for_iteration()
        assert promoted is True
        assert [c["id"] for c in state.candidates] == ["e1"]  # replaced, not extended
        assert state.evolved_candidates == []
        assert state.reflections == {}
        assert state.pilot_scores == {}
        assert state.elo_ratings == {}
        assert state.survivors == []

    def test_promote_returns_false_when_no_evolved(self) -> None:
        registry = PipelineRegistry()
        state = PipelineState(run_id="r4", target_dim="d", gen_tag="g")
        state.candidates = [{"id": "c0", "path": "p"}]
        pipeline = Pipeline(state, registry)
        assert pipeline._promote_evolved_for_iteration() is False
        assert state.candidates[0]["id"] == "c0"


class TestStateJsonRoundtrip:
    def test_max_iterations_and_cursor_persist(self) -> None:
        state = PipelineState(run_id="r5", target_dim="d", gen_tag="g", max_iterations=3)
        state.current_iteration = 2
        payload = json.loads(_state_to_json(state))
        assert payload["max_iterations"] == 3
        assert payload["current_iteration"] == 2

    def test_defaults_zero(self) -> None:
        state = PipelineState(run_id="r6", target_dim="d", gen_tag="g")
        payload = json.loads(_state_to_json(state))
        assert payload["max_iterations"] == 0
        assert payload["current_iteration"] == 0


class TestPhaseOrderConstants:
    """Pin the constant content — protects against accidental reordering."""

    def test_iteration_order_excludes_supervisor_generator_proximity(self) -> None:
        for role in ("supervisor", "generator", "proximity"):
            assert role not in _ITERATION_PHASE_ORDER

    def test_iteration_order_keeps_review_evolve_meta(self) -> None:
        for role in ("critic", "pilot", "ranker", "evolver", "meta_reviewer"):
            assert role in _ITERATION_PHASE_ORDER
