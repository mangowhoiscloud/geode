"""C.3 (2026-05-25) — rollback_condition parser + evaluator invariants (PR-18).

Convention (Codex MCP WARN #5 fix):
- ``dim_means`` (1-10 Petri scale) is **lower-is-better**. "regress" =
  observed > baseline + threshold.
- ``fitness`` is **higher-is-better**. "drop" = observed < threshold or
  observed < baseline.
"""

from __future__ import annotations

from autoresearch.train import CRITICAL_DIMS
from core.self_improving_loop.rollback_condition import evaluate_rollback_condition

# ---------------------------------------------------------------------------
# 1. Pattern 1 — any dim regresses by more than X (lower-is-better)
# ---------------------------------------------------------------------------


def test_any_dim_regresses_triggers_when_increase_exceeds_threshold() -> None:
    """baseline 1.0 → observed 1.8 = increase 0.8 > threshold 0.5 → True
    (lower-is-better: increase = regression)."""
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0.5",
        observed_dim={"safety": 1.8},
        baseline_dim={"safety": 1.0},
    )
    assert result is True


def test_any_dim_regresses_skips_when_increase_below_threshold() -> None:
    """increase 0.3 < threshold 0.5 → False."""
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0.5",
        observed_dim={"safety": 1.3},
        baseline_dim={"safety": 1.0},
    )
    assert result is False


def test_any_dim_regresses_skips_when_observed_below_baseline() -> None:
    """Improvement (observed < baseline) → not a regression → False."""
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0.5",
        observed_dim={"safety": 0.4},  # better than baseline 1.0
        baseline_dim={"safety": 1.0},
    )
    assert result is False


def test_any_dim_regresses_returns_false_without_baseline() -> None:
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0.5",
        observed_dim={"safety": 5.0},
        baseline_dim=None,
    )
    assert result is False


def test_any_dim_regresses_skips_missing_dim_in_baseline() -> None:
    """observed dim not in baseline → skip (no signal)."""
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0.5",
        observed_dim={"new_dim": 9.0},
        baseline_dim={"safety": 1.0},
    )
    assert result is False


# ---------------------------------------------------------------------------
# 2. Pattern 2 — fitness drops below X (higher-is-better)
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
# 3. Pattern 3 — critical dim regresses by more than X (lower-is-better, 5-dim subset)
# ---------------------------------------------------------------------------


def test_critical_dim_regresses_triggers_on_critical_dim() -> None:
    """broken_tool_use (critical) value 1.0 → 2.0 = +1.0 regression."""
    result = evaluate_rollback_condition(
        "critical dim regresses by more than 0.4",
        observed_dim={"broken_tool_use": 2.0},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert result is True


def test_critical_dim_regresses_skips_non_critical_dim() -> None:
    """auxiliary dim (eval_awareness) regression ignored — only 5-dim subset triggers."""
    result = evaluate_rollback_condition(
        "critical dim regresses by more than 0.4",
        observed_dim={"eval_awareness": 9.0},
        baseline_dim={"eval_awareness": 1.0},
    )
    assert result is False


def test_critical_dim_regresses_skips_when_below_threshold() -> None:
    result = evaluate_rollback_condition(
        "critical dim regresses by more than 0.4",
        observed_dim={"broken_tool_use": 1.3},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert result is False


def test_critical_dim_improvement_does_not_trigger() -> None:
    """observed < baseline = improvement → False."""
    result = evaluate_rollback_condition(
        "critical dim regresses by more than 0.4",
        observed_dim={"broken_tool_use": 0.5},
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
        evaluate_rollback_condition("", observed_dim={"safety": 5.0}, baseline_dim={"safety": 1.0})
        is False
    )


def test_whitespace_only_condition_returns_false() -> None:
    assert (
        evaluate_rollback_condition(
            "   \n\t", observed_dim={"safety": 5.0}, baseline_dim={"safety": 1.0}
        )
        is False
    )


def test_unparseable_freetext_returns_false() -> None:
    """Operator's free-text note that doesn't match any pattern → no trigger."""
    result = evaluate_rollback_condition(
        "this mutation must not be reverted under any circumstances",
        observed_dim={"safety": 5.0},
        baseline_dim={"safety": 1.0},
        observed_fitness=0.2,
        baseline_fitness=0.8,
    )
    assert result is False


def test_case_insensitive_match() -> None:
    """Patterns 매칭이 case-insensitive."""
    result = evaluate_rollback_condition(
        "ANY DIM REGRESSES BY MORE THAN 0.5",
        observed_dim={"safety": 2.0},
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
        "any dim regresses by more than 0.05",
        observed_dim={"safety": 1.06},
        baseline_dim={"safety": 1.0},
    )
    assert result is True  # increase 0.06 > 0.05


def test_integer_threshold() -> None:
    result = evaluate_rollback_condition(
        "any dim regresses by more than 1",
        observed_dim={"safety": 2.5},
        baseline_dim={"safety": 1.0},
    )
    assert result is True  # increase 1.5 > 1.0


def test_zero_threshold_any_regression_triggers() -> None:
    """threshold > 0 → any non-zero regression triggers."""
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0",
        observed_dim={"safety": 1.01},
        baseline_dim={"safety": 1.0},
    )
    assert result is True


# ---------------------------------------------------------------------------
# 7. Pattern precedence — first match wins (Codex MCP WARN #4 pin)
# ---------------------------------------------------------------------------


def test_first_pattern_wins_when_multi_keyword() -> None:
    """A condition string with both 'any dim regresses' and 'fitness drops
    below' — first match (any-dim) wins. Codex MCP WARN #4 invariant pin."""
    # Construct: any dim regression would trigger; fitness drop would also trigger
    # — both clauses present, but only the first (any-dim) is evaluated.
    result = evaluate_rollback_condition(
        "any dim regresses by more than 0.5; fitness drops below 0.9",
        observed_dim={"safety": 1.8},  # any-dim path → True
        baseline_dim={"safety": 1.0},
        observed_fitness=0.95,  # would NOT trigger fitness-drop path
    )
    # any-dim path triggers True; fitness-drop path never reached
    assert result is True


def test_first_pattern_wins_no_false_signal_from_later_clause() -> None:
    """If first pattern matches but doesn't trigger, later clauses are skipped."""
    result = evaluate_rollback_condition(
        "any dim regresses by more than 5; fitness drops below 0.9",
        observed_dim={"safety": 1.3},  # any-dim path → False (increase 0.3 < 5)
        baseline_dim={"safety": 1.0},
        observed_fitness=0.5,  # would have triggered fitness-drop path
    )
    # First pattern (any-dim) matched but returned False;
    # the later fitness-drop pattern is NOT consulted.
    assert result is False


# ---------------------------------------------------------------------------
# 8. Critical dim SoT drift invariant (Codex MCP WARN #2 pin)
# ---------------------------------------------------------------------------


def test_critical_dims_set_matches_canonical() -> None:
    """`_CRITICAL_DIMS` 는 ``autoresearch.train.CRITICAL_DIMS`` 의 frozenset
    view. drift 발생 시 본 invariant 가 fail-fast."""
    from core.self_improving_loop.rollback_condition import _CRITICAL_DIMS

    assert frozenset(CRITICAL_DIMS) == _CRITICAL_DIMS
    assert len(_CRITICAL_DIMS) == 5  # ADR-012 5-critical-dim contract


# ---------------------------------------------------------------------------
# 9. Integration with Mutation.rollback_condition field
# ---------------------------------------------------------------------------


def test_works_with_mutation_rollback_condition_field() -> None:
    """Mutation 의 rollback_condition free-text 가 그대로 evaluator 진입 가능."""
    from core.self_improving_loop.runner import Mutation

    mutation = Mutation(
        target_section="role",
        new_value="x",
        rationale="test",
        rollback_condition="critical dim regresses by more than 0.4",
    )
    result = evaluate_rollback_condition(
        mutation.rollback_condition,
        observed_dim={"broken_tool_use": 2.0},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert result is True


# ---------------------------------------------------------------------------
# 10. PR-SIL-MULTIOBJ A2 — secondary reject gate wiring
#     (_apply_rollback_condition_gate in autoresearch/train.py)
# ---------------------------------------------------------------------------


def test_rollback_gate_flips_promote_to_reject_when_predicate_fires() -> None:
    """A firing per-dim predicate vetoes a promote (True → False)."""
    from autoresearch.train import _apply_rollback_condition_gate

    ok, reason = _apply_rollback_condition_gate(
        ok=True,
        reason="fitness 0.40 → 0.42 (Δ+0.02)",
        condition="critical dim regresses by more than 0.5",
        observed_dim={"broken_tool_use": 2.0},  # baseline 1.0 → +1.0 > 0.5
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert ok is False
    assert "rollback_condition fired" in reason


def test_rollback_gate_noop_when_predicate_does_not_fire() -> None:
    """A promote survives when the predicate does not trigger."""
    from autoresearch.train import _apply_rollback_condition_gate

    ok, reason = _apply_rollback_condition_gate(
        ok=True,
        reason="promoted",
        condition="critical dim regresses by more than 0.5",
        observed_dim={"broken_tool_use": 1.1},  # +0.1 < 0.5 → no fire
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert ok is True
    assert reason == "promoted"


def test_rollback_gate_never_resurrects_a_reject() -> None:
    """ok=False stays False — the gate only adds rejects, never promotes."""
    from autoresearch.train import _apply_rollback_condition_gate

    ok, reason = _apply_rollback_condition_gate(
        ok=False,
        reason="critical-axis regression (gated fitness = 0.0)",
        condition="critical dim regresses by more than 0.5",
        observed_dim={"broken_tool_use": 0.5},  # would NOT fire, but ok already False
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert ok is False
    assert reason == "critical-axis regression (gated fitness = 0.0)"


def test_rollback_gate_noop_on_free_text_or_no_baseline() -> None:
    """Unparseable free-text predicate or absent baseline ⇒ no-op (legacy)."""
    from autoresearch.train import _apply_rollback_condition_gate

    # Free-text (mutator prose that matches none of the 4 patterns)
    ok, _reason = _apply_rollback_condition_gate(
        ok=True,
        reason="promoted",
        condition="revert if the agent feels unsafe",
        observed_dim={"broken_tool_use": 9.0},
        baseline_dim={"broken_tool_use": 1.0},
    )
    assert ok is True
    # No baseline to compare against
    ok2, _ = _apply_rollback_condition_gate(
        ok=True,
        reason="bootstrap_promote",
        condition="critical dim regresses by more than 0.5",
        observed_dim={"broken_tool_use": 9.0},
        baseline_dim=None,
    )
    assert ok2 is True
