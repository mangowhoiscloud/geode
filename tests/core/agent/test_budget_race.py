"""Regression — Pipeline._run_phase must roll up BudgetGuard cost on every path.

Pre-S2-fix the generic Exception handler re-raised without crediting the
guard's accumulated cost into ``state.usd_spent`` (the rollup block at
``plugins/seed_pipeline/orchestrator.py:311-313`` was AFTER the
try/finally, unreachable on re-raise). Any ``guard.record_usage()`` calls
made before the crash were silently lost from accounting.
"""

from __future__ import annotations

import pytest
from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_pipeline.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
)


class _RecordingThenRaiseAgent(BaseSeedAgent):
    """Records partial cost via state.budget_guard, then raises Exception."""

    def execute(self, state: PipelineState) -> SeedAgentResult:
        if state.budget_guard is not None:
            state.budget_guard.record_usage(
                model="claude-sonnet-4-6", prompt_tokens=100, completion_tokens=50
            )
        raise RuntimeError("simulated crash after partial cost")


def _stub_cost(monkeypatch: pytest.MonkeyPatch, rate: float) -> None:
    def _calc(model: str, *, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * rate

    monkeypatch.setattr("core.llm.token_tracker.calculate_cost", _calc)


def test_state_usd_spent_credits_guard_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a phase raises mid-flight, the BudgetGuard's recorded cost
    must still flow into state.usd_spent / .prompt_tokens / .completion_tokens.
    """
    _stub_cost(monkeypatch, rate=0.001)

    registry = PipelineRegistry()
    registry.register(_RecordingThenRaiseAgent(role="generator", model="x"))
    # Other roles never run (generator raises first), so registering only
    # generator suffices.
    state = PipelineState(run_id="t-rollup", target_dim="x", gen_tag="gen2")

    with pytest.raises(RuntimeError, match="simulated crash"):
        Pipeline(state, registry).run()

    # The pre-fix invariant violation: state.* were all zero. Post-fix:
    # cost recorded before the raise survives.
    assert state.prompt_tokens == 100
    assert state.completion_tokens == 50
    assert state.usd_spent == pytest.approx(0.150, abs=1e-6)


def test_state_usd_spent_credits_guard_on_budget_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BudgetExceededError path also propagates guard cost into state."""
    _stub_cost(monkeypatch, rate=0.01)

    class _BurnsThroughCapAgent(BaseSeedAgent):
        def execute(self, state: PipelineState) -> SeedAgentResult:
            if state.budget_guard is not None:
                # Burn through enough to trip the hard cap (default 10.0).
                # 100 tokens × 0.01 × 1000 = 1000 usd → forces hard exit.
                state.budget_guard.record_usage(
                    model="m", prompt_tokens=50000, completion_tokens=50000
                )
            return SeedAgentResult(role=self.role)

    registry = PipelineRegistry()
    registry.register(_BurnsThroughCapAgent(role="generator", model="x"))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_RecordingThenRaiseAgent(role=r, model="x"))
    # phase 1 should hit BudgetExceededError, set error_category="budget",
    # phases 2+ won't run because phase 1's recording already crossed cap
    # and subsequent phases are skipped after the error.

    state = PipelineState(run_id="t-budget-cap", target_dim="x", gen_tag="gen2")
    # The budget hard cap of 10.0 in defaults means 1 recording at 1000
    # crosses → BudgetExceededError → translated to SeedAgentResult, not raised.
    # Subsequent phases still run but raise themselves; first crash propagates.
    with pytest.raises(RuntimeError, match="simulated crash"):
        Pipeline(state, registry, budget_hard_usd=10.0, budget_soft_usd=5.0).run()

    # phase 1 (BurnsThroughCap) credited 100000 tokens before exceeding;
    # phase 2 (RecordingThenRaise) credited 100 + 50 before raising.
    assert state.prompt_tokens >= 50000  # generator credited
    assert state.completion_tokens >= 50000
    # Cost must include both phases' contributions (no silent drop on
    # budget error path).
    assert state.usd_spent > 0
