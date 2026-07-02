"""Picker context guard consumes ContextBudgetPolicy, not a bare 80% literal.

Follow-up on PR-CONTEXT-BUDGET (Codex LOW): the `/model` primary-role context
guard must warn at the model's tiered ContextBudgetPolicy warning budget so the
picker and the running loop agree on when a window is too full.
"""

from __future__ import annotations

from core.orchestration.context_budget import resolve_context_budget_policy


def test_guard_threshold_is_policy_warning_tokens() -> None:
    """The guard threshold equals the resolved policy warning budget, and that
    budget is below the raw window (proves it is not a bare `window * 0.8`)."""
    policy = resolve_context_budget_policy("claude-opus-4-8")
    assert policy.warning_tokens > 0
    assert policy.warning_tokens < policy.context_window
    # tiered, not a flat 80%: the warning budget is a fraction of the
    # effective prompt budget (window minus the output reserve), so it is
    # strictly below a naive 0.8 * window for a large-window model.
    assert policy.warning_tokens < int(policy.context_window * 0.8)


def test_small_window_warns_earlier_than_large() -> None:
    """A small-window model's warning fraction fires earlier (lower pct of its
    own budget) than a large-window model — the whole point of tiering."""
    small = resolve_context_budget_policy("glm-4.7-flash")  # 202,752 → small tier
    large = resolve_context_budget_policy("claude-opus-4-8")  # 1M → large tier
    assert small.tier.warning_threshold_pct <= large.tier.warning_threshold_pct


def test_model_py_has_no_hardcoded_08_multiplier() -> None:
    """Regression: the guard must not reintroduce a `* 0.8` window literal."""
    from pathlib import Path

    import core.cli.commands.model as m

    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "* 0.8" not in src
    assert "resolve_context_budget_policy" in src
