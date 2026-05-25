"""C.3 (2026-05-25) — rollback_condition parser + evaluator invariants (PR-18).

Scope:
- 4 supported patterns × parser + evaluator
- free-text fallback → False
- missing baseline/fitness → False (graceful)
- threshold parsing (positive / negative / decimals)
- critical dim subset enforcement
"""

from __future__ import annotations

from core.self_improving_loop.rollback_condition import evaluate_rollback_condition

# ---------------------------------------------------------------------------
# 1. Pattern 1 — any dim drops more than X
# ---------------------------------------------------------------------------


def test_any_dim_drops_triggers_when_drop_exceeds_threshold() -> None:
    """baseline 1.0 → observed 0.4 = drop 0.6 > threshold 0.5 → True."""
    result = evaluate_rollback_condition(
        "any dim drops more than 0.5",
        observed_dim={"safety": 0.4},
        baseline_dim={"safety": 1.0},
    )
    assert result is True


def test_any_dim_drops_skips_when_drop_below_threshold() -> None:
    """drop 0.3 < threshold 0.5 → False."""
    result = evaluate_rollback_condition(
        "any dim drops more than 0.5",
        observed_dim={"safety": 0.7},
        baseline_dim={"safety": 1.0},
    )
    assert result is False


def test_any_dim_drops_skips_when_observed_above_baseline() -> None:
    """Improvement (observed > baseline) → not a drop → False."""
    result = evaluate_rollback_condition(
        "any dim drops more than 0.5",
        observed_dim={"safety": 1.5},
        baseline_dim={"safety": 1.0},
    )
    assert result is False


def test_any_dim_drops_returns_false_without_baseline() -> None:
    result = evaluate_rollback_condition(
        "any dim drops more than 0.5",
        observed_dim={"safety": 0.4},
        baseline_dim=None,
    )
    assert result is False


def test_any_dim_drops_skips_missing_dim_in_baseline() -> None:
    """observed dim not in baseline → skip (no signal)."""
    result = evaluate_rollback_condition(
        "any dim drops more than 0.5",
        observed_dim={"new_dim": 0.0},
        baseline_dim={"safety": 1.0},
    )
    assert result is False


# ---------------------------------------------------------------------------
# 2. Pattern 2 — fitness drops below X
# ---------------------------------------------------------------------------


def test_fitness_drops_below_triggers() -> None:
    result = evaluate_rollback_condition(
        "fitness drops below 0.3",
        observed_dim={},
        observed_fitness=0.2,
    )
    assert result is True


def test_fitness_drops_below_skips_when_above() -> None:
    result = evaluate_rollback_condition(
        "fitness drops below 0.3",
        observed_dim={},
        observed_fitness=0.5,
    )
    assert result is False


def test_fitness_drops_returns_false_without_fitness() -> None:
    result = evaluate_rollback_condition(
        "fitness drops below 0.3",
        observed_dim={},
        observed_fitness=None,
    )
    assert result is False


# ---------------------------------------------------------------------------
# 3. Pattern 3 — critical dim drops more than X
# ---------------------------------------------------------------------------


def test_critical_dim_drops_triggers_on_critical_dim() -> None:
    """broken_tool_use (critical) drop > threshold → True."""
    result = evaluate_rollback_condition(
        "critical dim drops more than 0.4",
        observed_dim={"broken_tool_use": 0.3},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert result is True


def test_critical_dim_drops_skips_non_critical_dim() -> None:
    """auxiliary dim (eval_awareness) drop ignored — even huge drop."""
    result = evaluate_rollback_condition(
        "critical dim drops more than 0.4",
        observed_dim={"eval_awareness": 0.0},
        baseline_dim={"eval_awareness": 1.0},
    )
    assert result is False


def test_critical_dim_drops_skips_when_drop_below_threshold() -> None:
    result = evaluate_rollback_condition(
        "critical dim drops more than 0.4",
        observed_dim={"broken_tool_use": 0.7},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert result is False


# ---------------------------------------------------------------------------
# 4. Pattern 4 — rollback if fitness regression
# ---------------------------------------------------------------------------


def test_fitness_regression_triggers() -> None:
    result = evaluate_rollback_condition(
        "rollback if fitness regression",
        observed_dim={},
        observed_fitness=0.4,
        baseline_fitness=0.6,
    )
    assert result is True


def test_fitness_regression_skips_when_observed_equal_baseline() -> None:
    result = evaluate_rollback_condition(
        "rollback if fitness regression",
        observed_dim={},
        observed_fitness=0.6,
        baseline_fitness=0.6,
    )
    assert result is False


def test_fitness_regression_skips_when_observed_better() -> None:
    result = evaluate_rollback_condition(
        "rollback if fitness regression",
        observed_dim={},
        observed_fitness=0.8,
        baseline_fitness=0.6,
    )
    assert result is False


def test_fitness_regression_returns_false_without_baseline_fitness() -> None:
    result = evaluate_rollback_condition(
        "rollback if fitness regression",
        observed_dim={},
        observed_fitness=0.4,
        baseline_fitness=None,
    )
    assert result is False


# ---------------------------------------------------------------------------
# 5. Free-text + edge cases
# ---------------------------------------------------------------------------


def test_empty_condition_returns_false() -> None:
    assert (
        evaluate_rollback_condition("", observed_dim={"safety": 0.4}, baseline_dim={"safety": 1.0})
        is False
    )


def test_whitespace_only_condition_returns_false() -> None:
    assert (
        evaluate_rollback_condition(
            "   \n\t", observed_dim={"safety": 0.4}, baseline_dim={"safety": 1.0}
        )
        is False
    )


def test_unparseable_freetext_returns_false() -> None:
    """Operator's free-text note that doesn't match any pattern → no trigger."""
    result = evaluate_rollback_condition(
        "this mutation must not be reverted under any circumstances",
        observed_dim={"safety": 0.4},
        baseline_dim={"safety": 1.0},
        observed_fitness=0.2,
        baseline_fitness=0.8,
    )
    assert result is False


def test_case_insensitive_match() -> None:
    """Patterns 매칭이 case-insensitive."""
    result = evaluate_rollback_condition(
        "ANY DIM DROPS MORE THAN 0.5",
        observed_dim={"safety": 0.3},
        baseline_dim={"safety": 1.0},
    )
    assert result is True


def test_pattern_embedded_in_longer_text() -> None:
    """Operator 가 패턴을 longer note 안에 embed — 여전히 매칭."""
    result = evaluate_rollback_condition(
        "Reviewer note: rollback if fitness regression — please verify",
        observed_dim={},
        observed_fitness=0.4,
        baseline_fitness=0.6,
    )
    assert result is True


# ---------------------------------------------------------------------------
# 6. Threshold parsing edge cases
# ---------------------------------------------------------------------------


def test_decimal_threshold() -> None:
    result = evaluate_rollback_condition(
        "any dim drops more than 0.05",
        observed_dim={"safety": 0.94},
        baseline_dim={"safety": 1.0},
    )
    assert result is True  # drop 0.06 > 0.05


def test_integer_threshold() -> None:
    result = evaluate_rollback_condition(
        "any dim drops more than 1",
        observed_dim={"safety": -0.5},
        baseline_dim={"safety": 1.0},
    )
    assert result is True  # drop 1.5 > 1.0


def test_zero_threshold_any_drop_triggers() -> None:
    """drop > 0 → any non-zero drop triggers."""
    result = evaluate_rollback_condition(
        "any dim drops more than 0",
        observed_dim={"safety": 0.99},
        baseline_dim={"safety": 1.0},
    )
    assert result is True


# ---------------------------------------------------------------------------
# 7. Integration with Mutation.rollback_condition field
# ---------------------------------------------------------------------------


def test_works_with_mutation_rollback_condition_field() -> None:
    """Mutation 의 rollback_condition free-text 가 그대로 evaluator 진입 가능."""
    from core.self_improving_loop.runner import Mutation

    mutation = Mutation(
        target_section="role",
        new_value="x",
        rationale="test",
        rollback_condition="critical dim drops more than 0.4",
    )
    result = evaluate_rollback_condition(
        mutation.rollback_condition,
        observed_dim={"broken_tool_use": 0.3},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert result is True
