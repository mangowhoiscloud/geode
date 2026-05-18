"""Unit tests for ``plugins.seed_generation.orchestrator``."""

from __future__ import annotations

import pytest
from core.orchestration.lane_queue import LaneQueue
from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
)


class _StubAgent(BaseSeedAgent):
    def __init__(self, role: str, output: dict[str, object] | None = None) -> None:
        super().__init__(role=role, model="stub-model")
        self._output = output or {}
        self.invocations = 0

    def execute(self, state: PipelineState) -> SeedAgentResult:
        self.invocations += 1
        return SeedAgentResult(
            role=self.role, output=self._output, prompt_tokens=10, completion_tokens=5
        )


def _make_registry_with_all_stubs() -> tuple[PipelineRegistry, dict[str, _StubAgent]]:
    """Register a stub for every required phase role."""
    roles = ["generator", "proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"]
    agents = {r: _StubAgent(r) for r in roles}
    registry = PipelineRegistry()
    for a in agents.values():
        registry.register(a)
    return registry, agents


def test_pipeline_runs_all_seven_phases_in_order() -> None:
    registry, agents = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-1", target_dim="broken_tool_use", gen_tag="gen2")
    Pipeline(state, registry).run()
    for role, agent in agents.items():
        assert agent.invocations == 1, f"role={role} not invoked"


def test_pipeline_merges_phase_output_into_state() -> None:
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator", output={"candidates": [{"id": "c1"}, {"id": "c2"}]}))
    # Register remaining 6 as no-ops to let run() complete
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_StubAgent(r))
    state = PipelineState(run_id="t-2", target_dim="overrefusal", gen_tag="gen2")
    Pipeline(state, registry).run()
    assert len(state.candidates) == 2
    assert state.candidates[0]["id"] == "c1"


def test_pipeline_rolls_up_cost() -> None:
    registry, agents = _make_registry_with_all_stubs()
    # Each stub returns 10 prompt + 5 completion tokens, 0 usd
    state = PipelineState(run_id="t-3", target_dim="logic", gen_tag="gen2")
    Pipeline(state, registry).run()
    assert state.prompt_tokens == 10 * 7
    assert state.completion_tokens == 5 * 7
    assert state.usd_spent == 0.0


def test_missing_role_raises() -> None:
    registry = PipelineRegistry()
    # Only register first 2 — third phase will fail
    registry.register(_StubAgent("generator"))
    registry.register(_StubAgent("proximity"))
    state = PipelineState(run_id="t-4", target_dim="x", gen_tag="gen2")
    with pytest.raises(RuntimeError, match="critic"):
        Pipeline(state, registry).run()


def test_unknown_output_keys_are_warned_not_merged() -> None:
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator", output={"candidates": [], "garbage_key": 1}))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_StubAgent(r))
    state = PipelineState(run_id="t-5", target_dim="x", gen_tag="gen2")
    Pipeline(state, registry).run()
    # state should not have a `garbage_key` attribute
    assert not hasattr(state, "garbage_key")


def test_registry_register_replace_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator"))
    with caplog.at_level("WARNING"):
        registry.register(_StubAgent("generator"))
    assert any("re-registering" in r.message for r in caplog.records)


def test_registry_list_roles() -> None:
    registry, _ = _make_registry_with_all_stubs()
    roles = sorted(registry.list_roles())
    assert roles == sorted(
        ["generator", "proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"]
    )


class _CostReportingAgent(BaseSeedAgent):
    """Stub agent that sets cost on its SeedAgentResult directly.

    PR 1 (2026-05-18) — replaces the pre-removal _BudgetRecordingAgent
    that exercised the BudgetGuard attached to state. Cost is now
    rolled up from result.* (the orchestrator's only cost surface),
    no guard / hard-cap layer.
    """

    def __init__(
        self,
        role: str,
        *,
        usd: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        super().__init__(role=role, model="stub-model")
        self.usd = usd
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def execute(self, state: PipelineState) -> SeedAgentResult:
        return SeedAgentResult(
            role=self.role,
            output={},
            usd_spent=self.usd,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


def test_pipeline_rolls_up_result_cost_into_state() -> None:
    """Cost on result.* should sum into state.* across all phases."""
    registry = PipelineRegistry()
    registry.register(
        _CostReportingAgent("generator", usd=0.05, prompt_tokens=100, completion_tokens=50)
    )
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_CostReportingAgent(r))
    state = PipelineState(run_id="t-cost", target_dim="x", gen_tag="gen2")
    Pipeline(state, registry).run()
    assert state.prompt_tokens == 100
    assert state.completion_tokens == 50
    assert state.usd_spent == pytest.approx(0.05, abs=1e-6)


def test_pipeline_accepts_lane_queue_without_lane_registered() -> None:
    """No-op when the LaneQueue exists but has no seed-generation lane."""
    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-lane", target_dim="x", gen_tag="gen2")
    queue = LaneQueue()  # no lanes registered
    Pipeline(state, registry, lane_queue=queue).run()


def test_pipeline_acquires_lane_when_registered() -> None:
    """When the seed-generation lane is on the queue, execute is gated through it."""
    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-lane", target_dim="x", gen_tag="gen2")
    queue = LaneQueue()
    queue.add_lane("seed-generation", max_concurrent=4, timeout_s=5.0)
    Pipeline(state, registry, lane_queue=queue).run()
    # No assertion target beyond completion — the lane.acquire would block
    # if the slot wasn't released, so reaching here proves acquire/release
    # symmetry across all 7 phases.
    seed_lane = queue.get_lane("seed-generation")
    assert seed_lane is not None
    assert seed_lane.active_count == 0


class _RecordingHookSystem:
    """Capture trigger() calls so tests can assert emit counts."""

    def __init__(self) -> None:
        self.events: list[tuple[object, dict[str, object]]] = []

    def trigger(self, event: object, data: dict[str, object] | None = None) -> list[object]:
        self.events.append((event, data or {}))
        return []
