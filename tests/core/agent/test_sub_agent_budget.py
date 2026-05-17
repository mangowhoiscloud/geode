"""Unit tests for ``core.agent.sub_agent_budget``."""

from __future__ import annotations

import pytest
from core.agent.sub_agent_budget import (
    BudgetExceededError,
    BudgetGuard,
    SubAgentBudget,
)


class _StubPrice:
    """Force ``calculate_cost`` to a deterministic per-token rate for tests."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, rate_per_token: float) -> None:
        def _calc(model: str, *, input_tokens: int, output_tokens: int) -> float:
            return (input_tokens + output_tokens) * rate_per_token

        monkeypatch.setattr(
            "core.llm.token_tracker.calculate_cost",
            _calc,
        )


def test_budget_zero_when_constructed() -> None:
    guard = BudgetGuard("agent-x", soft_usd=0.10, hard_usd=0.50)
    assert guard.budget.usd_spent == 0.0
    assert guard.budget.prompt_tokens == 0
    assert guard.budget.completion_tokens == 0
    assert guard.budget.remaining_usd == 0.50


def test_record_accumulates_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    _StubPrice(monkeypatch, rate_per_token=0.001)
    guard = BudgetGuard("agent-x", soft_usd=10.0, hard_usd=20.0)
    after_first = guard.record_usage(
        model="claude-sonnet-4-6", prompt_tokens=100, completion_tokens=50
    )
    assert after_first == pytest.approx(0.150, abs=1e-6)
    after_second = guard.record_usage(
        model="claude-sonnet-4-6", prompt_tokens=200, completion_tokens=100
    )
    assert after_second == pytest.approx(0.450, abs=1e-6)
    assert guard.budget.prompt_tokens == 300
    assert guard.budget.completion_tokens == 150


def test_soft_warn_callback_fires_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _StubPrice(monkeypatch, rate_per_token=0.01)
    seen: list[SubAgentBudget] = []
    guard = BudgetGuard(
        "agent-x",
        soft_usd=0.10,
        hard_usd=1.00,
        on_soft_warn=seen.append,
    )
    guard.record_usage(model="m", prompt_tokens=5, completion_tokens=5)  # 0.10
    assert len(seen) == 1
    assert seen[0].soft_warned is True
    # Second crossing should NOT fire again
    guard.record_usage(model="m", prompt_tokens=5, completion_tokens=5)  # 0.20
    assert len(seen) == 1


def test_hard_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _StubPrice(monkeypatch, rate_per_token=0.01)
    guard = BudgetGuard("agent-x", soft_usd=0.50, hard_usd=1.00)
    with pytest.raises(BudgetExceededError) as exc_info:
        guard.record_usage(model="m", prompt_tokens=60, completion_tokens=60)  # 1.20
    assert exc_info.value.agent_id == "agent-x"
    assert exc_info.value.hard_usd == 1.00
    assert exc_info.value.usd_spent > 1.00


def test_constructor_rejects_inverted_caps() -> None:
    with pytest.raises(ValueError):
        BudgetGuard("agent-x", soft_usd=1.0, hard_usd=0.5)


def test_fraction_used() -> None:
    guard = BudgetGuard("agent-x", soft_usd=0.1, hard_usd=2.0)
    assert guard.budget.fraction_used() == 0.0
    # forge usd_spent for fraction check
    guard.budget.usd_spent = 1.0
    assert guard.budget.fraction_used() == 0.5
    guard.budget.usd_spent = 3.0
    assert guard.budget.fraction_used() == 1.0
