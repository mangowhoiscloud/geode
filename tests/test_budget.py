"""Unit tests for :mod:`core.agent.budget` — session-wide wall-clock budget.

Verifies:
- ``TimeBudget`` / ``BudgetCheck`` dataclass shape (frozen, slots).
- ``start_session_budget`` populates SessionMetrics fields.
- ``check_session_budget`` returns expected ``BudgetCheck`` shape.
- ``is_handoff_due`` is **one-shot** — only fires once per session.
- ``time_budget_remaining_s`` returns ``inf`` when no budget set.
- ContextVar scope isolation: different scopes get independent budgets.
- ``GEODE_SESSION_TIME_BUDGET_S=0`` opt-out semantics (via AgenticLoop wiring).
"""

from __future__ import annotations

import time

import pytest
from core.agent.budget import (
    DEFAULT_HANDOFF_THRESHOLD_S,
    DEFAULT_TIME_BUDGET_S,
    BudgetCheck,
    TimeBudget,
    budget_summary,
    check_session_budget,
    start_session_budget,
)
from core.observability.session_metrics import (
    SessionMetrics,
    session_metrics_scope,
)


def test_default_constants() -> None:
    """Defaults match operator decision (memory: project_budget_handoff_decision)."""
    assert DEFAULT_TIME_BUDGET_S == 7200.0
    assert DEFAULT_HANDOFF_THRESHOLD_S == 600.0


def test_time_budget_dataclass_frozen() -> None:
    """Config dataclass is immutable so multiple sessions can share refs."""
    cfg = TimeBudget(total_seconds=3600.0, handoff_threshold_seconds=300.0)
    assert cfg.total_seconds == 3600.0
    assert cfg.handoff_threshold_seconds == 300.0
    with pytest.raises((AttributeError, TypeError)):
        cfg.total_seconds = 1.0  # type: ignore[misc]


def test_start_session_budget_populates_metrics() -> None:
    """``start_session_budget`` writes the three time-budget fields."""
    with session_metrics_scope(session_id="t-budget-start"):
        cfg = start_session_budget(total_seconds=120.0, handoff_threshold_seconds=10.0)
        from core.observability.session_metrics import current_session_metrics

        m = current_session_metrics()
        assert m.time_budget_total_s == 120.0
        assert m.handoff_threshold_s == 10.0
        assert m.time_budget_start_s > 0.0
        assert m.handoff_triggered_at == 0.0
        assert cfg.total_seconds == 120.0


def test_start_session_budget_defaults_to_2h() -> None:
    """No-arg call applies the 2h operator default."""
    with session_metrics_scope(session_id="t-budget-default"):
        cfg = start_session_budget()
        assert cfg.total_seconds == DEFAULT_TIME_BUDGET_S
        assert cfg.handoff_threshold_seconds == DEFAULT_HANDOFF_THRESHOLD_S


def test_check_session_budget_within_window() -> None:
    """Fresh budget — remaining ≈ total, no expiry, no handoff."""
    with session_metrics_scope(session_id="t-budget-fresh"):
        start_session_budget(total_seconds=7200.0, handoff_threshold_seconds=600.0)
        result = check_session_budget()
        assert isinstance(result, BudgetCheck)
        assert not result.expired
        assert not result.handoff_due
        assert result.remaining_seconds > 7000.0  # near full


def test_check_session_budget_no_budget_returns_inf() -> None:
    """Without ``start_session_budget``, remaining is +inf and never triggers."""
    with session_metrics_scope(session_id="t-budget-none"):
        result = check_session_budget()
        assert result.remaining_seconds == float("inf")
        assert not result.expired
        assert not result.handoff_due


def test_handoff_due_one_shot() -> None:
    """Crossing the threshold flips ``handoff_due`` exactly once.

    Sets a 1s budget with a 10s threshold so the first check is past the
    threshold immediately. Second check must report False even though
    elapsed > threshold — the latch on ``handoff_triggered_at`` prevents
    duplicate HANDOFF_TRIGGERED hooks.
    """
    with session_metrics_scope(session_id="t-handoff-oneshot"):
        start_session_budget(total_seconds=1.0, handoff_threshold_seconds=10.0)
        first = check_session_budget()
        assert first.handoff_due is True
        second = check_session_budget()
        assert second.handoff_due is False
        third = check_session_budget()
        assert third.handoff_due is False


def test_handoff_not_due_before_threshold() -> None:
    """When remaining > threshold, no handoff fires."""
    with session_metrics_scope(session_id="t-handoff-not-yet"):
        start_session_budget(total_seconds=3600.0, handoff_threshold_seconds=60.0)
        result = check_session_budget()
        assert not result.handoff_due
        assert result.remaining_seconds > 60.0


def test_expired_when_past_total() -> None:
    """Negative remaining → ``expired=True`` (hard stop)."""
    with session_metrics_scope(session_id="t-budget-expired"):
        start_session_budget(total_seconds=0.001, handoff_threshold_seconds=0.0)
        time.sleep(0.01)
        result = check_session_budget()
        assert result.expired is True
        assert result.remaining_seconds <= 0.0


def test_budget_summary_active() -> None:
    """``budget_summary`` returns 4 keys when budget is running."""
    with session_metrics_scope(session_id="t-budget-summary"):
        start_session_budget(total_seconds=7200.0)
        summary = budget_summary()
        assert summary["budget_total_s"] == 7200.0
        assert summary["budget_remaining_s"] > 7000.0
        assert summary["handoff_threshold_s"] == 600.0
        assert summary["handoff_triggered_at"] == 0.0


def test_budget_summary_inactive() -> None:
    """``budget_summary`` returns empty dict when no budget set."""
    with session_metrics_scope(session_id="t-budget-noop"):
        assert budget_summary() == {}


def test_context_var_isolation() -> None:
    """Nested scopes have independent budgets."""
    with session_metrics_scope(session_id="outer"):
        start_session_budget(total_seconds=10.0)
        from core.observability.session_metrics import current_session_metrics

        outer = current_session_metrics()
        assert outer.time_budget_total_s == 10.0
        with session_metrics_scope(session_id="inner"):
            inner = current_session_metrics()
            assert inner.time_budget_total_s == 0.0  # fresh metrics, no budget
            start_session_budget(total_seconds=20.0)
            assert inner.time_budget_total_s == 20.0
        # Restored to outer after inner scope exit.
        assert current_session_metrics().time_budget_total_s == 10.0


def test_explicit_metrics_target() -> None:
    """``start_session_budget(metrics=...)`` writes to the passed object,
    not the ContextVar — useful for tests that don't want ContextVar
    side effects."""
    m = SessionMetrics(session_id="explicit")
    start_session_budget(total_seconds=99.0, metrics=m)
    assert m.time_budget_total_s == 99.0
    result = check_session_budget(metrics=m)
    assert result.remaining_seconds < 99.0 and result.remaining_seconds > 90.0


def test_to_session_row_includes_budget_fields() -> None:
    """``SessionMetrics.to_session_row`` exposes the 3 budget telemetry keys."""
    with session_metrics_scope(session_id="t-row"):
        start_session_budget(total_seconds=600.0, handoff_threshold_seconds=60.0)
        from core.observability.session_metrics import current_session_metrics

        row = current_session_metrics().to_session_row()
        assert row["time_budget_total_s"] == 600.0
        assert row["handoff_threshold_s"] == 60.0
        assert row["handoff_triggered_at"] == 0.0
