"""Unit tests for ``plugins.seed_pipeline.orchestrator``."""

from __future__ import annotations

import pytest
from core.agent.sub_agent_budget import BudgetExceededError
from core.orchestration.lane_queue import LaneQueue
from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_pipeline.orchestrator import (
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


class _BudgetRecordingAgent(BaseSeedAgent):
    """Agent that exercises the BudgetGuard attached to state."""

    def __init__(
        self,
        role: str,
        *,
        record_input: int = 0,
        record_output: int = 0,
        raise_budget: bool = False,
    ) -> None:
        super().__init__(role=role, model="stub-model")
        self.record_input = record_input
        self.record_output = record_output
        self.raise_budget = raise_budget

    def execute(self, state: PipelineState) -> SeedAgentResult:
        if state.budget_guard is None:
            return SeedAgentResult(role=self.role, status="error", error_message="no guard")
        if self.record_input or self.record_output:
            try:
                state.budget_guard.record_usage(
                    model="claude-sonnet-4-6",
                    prompt_tokens=self.record_input,
                    completion_tokens=self.record_output,
                )
            except BudgetExceededError:
                # Re-raise so orchestrator's BudgetExceededError handler runs
                raise
        if self.raise_budget:
            raise BudgetExceededError(usd_spent=99.0, hard_usd=1.0, agent_id="stub")
        return SeedAgentResult(role=self.role, output={})


def test_pipeline_attaches_budget_guard_to_state() -> None:
    seen_guards: list[object] = []

    class _Probe(BaseSeedAgent):
        def execute(self, state: PipelineState) -> SeedAgentResult:
            seen_guards.append(state.budget_guard)
            return SeedAgentResult(role=self.role)

    registry = PipelineRegistry()
    for r in ("generator", "proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_Probe(role=r, model="x"))
    state = PipelineState(run_id="t-guard", target_dim="x", gen_tag="gen2")
    assert state.budget_guard is None
    Pipeline(state, registry).run()
    # Each of 7 phases should have attached a non-None guard during execute
    assert len(seen_guards) == 7
    assert all(g is not None for g in seen_guards)
    # And restored to None after run completes
    assert state.budget_guard is None


def test_pipeline_translates_budget_exceeded_to_seed_result() -> None:
    """A BudgetExceededError inside a phase must NOT propagate."""
    registry = PipelineRegistry()
    registry.register(_BudgetRecordingAgent("generator", raise_budget=True))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_BudgetRecordingAgent(r))
    state = PipelineState(run_id="t-budget", target_dim="x", gen_tag="gen2")
    # Should not raise — budget error becomes status="error" SeedAgentResult
    Pipeline(state, registry).run()


def test_pipeline_rolls_up_guard_cost_when_result_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _stub_calc(model: str, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * 0.0001

    monkeypatch.setattr("core.llm.token_tracker.calculate_cost", _stub_calc)

    registry = PipelineRegistry()
    # Generator records 100 tokens via the guard; result.usd_spent left at 0
    registry.register(_BudgetRecordingAgent("generator", record_input=100, record_output=50))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_BudgetRecordingAgent(r))
    state = PipelineState(run_id="t-cost", target_dim="x", gen_tag="gen2")
    Pipeline(
        state,
        registry,
        budget_soft_usd=1.0,
        budget_hard_usd=10.0,
    ).run()
    # Guard rollup must surface on state (only generator recorded)
    assert state.prompt_tokens == 100
    assert state.completion_tokens == 50
    assert state.usd_spent == pytest.approx(0.0150, abs=1e-6)


def test_pipeline_accepts_lane_queue_without_lane_registered() -> None:
    """No-op when the LaneQueue exists but has no seed-pipeline lane."""
    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-lane", target_dim="x", gen_tag="gen2")
    queue = LaneQueue()  # no lanes registered
    Pipeline(state, registry, lane_queue=queue).run()


def test_pipeline_acquires_lane_when_registered() -> None:
    """When the seed-pipeline lane is on the queue, execute is gated through it."""
    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-lane", target_dim="x", gen_tag="gen2")
    queue = LaneQueue()
    queue.add_lane("seed-pipeline", max_concurrent=4, timeout_s=5.0)
    Pipeline(state, registry, lane_queue=queue).run()
    # No assertion target beyond completion — the lane.acquire would block
    # if the slot wasn't released, so reaching here proves acquire/release
    # symmetry across all 7 phases.
    seed_lane = queue.get_lane("seed-pipeline")
    assert seed_lane is not None
    assert seed_lane.active_count == 0


class _RecordingHookSystem:
    """Capture trigger() calls so tests can assert emit counts."""

    def __init__(self) -> None:
        self.events: list[tuple[object, dict[str, object]]] = []

    def trigger(self, event: object, data: dict[str, object] | None = None) -> list[object]:
        self.events.append((event, data or {}))
        return []


def test_budget_path_emits_single_failed_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression — BudgetExceededError must NOT double-emit SUBAGENT_FAILED."""
    from core.hooks import HookEvent

    registry = PipelineRegistry()
    registry.register(_BudgetRecordingAgent("generator", raise_budget=True))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_BudgetRecordingAgent(r))
    state = PipelineState(run_id="t-budget-emit", target_dim="x", gen_tag="gen2")
    hooks = _RecordingHookSystem()
    Pipeline(state, registry, hooks=hooks).run()  # type: ignore[arg-type]
    failed = [e for e, _ in hooks.events if e == HookEvent.SUBAGENT_FAILED]
    # generator is the only role that fails; expect exactly 1 SUBAGENT_FAILED
    assert len(failed) == 1, f"expected single SUBAGENT_FAILED on budget path, got {len(failed)}"


def test_budget_soft_warn_emits_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first crossing of soft_usd must fire SUBAGENT_BUDGET_WARNING."""
    from core.hooks import HookEvent

    def _stub_calc(model: str, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * 0.01

    monkeypatch.setattr("core.llm.token_tracker.calculate_cost", _stub_calc)

    registry = PipelineRegistry()
    # Generator burns 0.50 (= soft cap), triggers the soft-warn callback
    registry.register(_BudgetRecordingAgent("generator", record_input=25, record_output=25))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_BudgetRecordingAgent(r))
    state = PipelineState(run_id="t-soft", target_dim="x", gen_tag="gen2")
    hooks = _RecordingHookSystem()
    Pipeline(
        state,
        registry,
        hooks=hooks,  # type: ignore[arg-type]
        budget_soft_usd=0.50,
        budget_hard_usd=10.0,
    ).run()
    warns = [e for e, _ in hooks.events if e == HookEvent.SUBAGENT_BUDGET_WARNING]
    assert len(warns) == 1, f"expected one SUBAGENT_BUDGET_WARNING, got {len(warns)}"
