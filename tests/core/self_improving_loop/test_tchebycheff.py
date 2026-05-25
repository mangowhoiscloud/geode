"""A.2 (2026-05-25) — Tchebycheff scalarization invariants (PR-23).

Scope:
- compute_tchebycheff: empty inputs / single dim / multi-dim / weights /
  missing dim graceful / ideal point match (scalar = 0) / negation invariant
- compute_ideal_point: empty / single / multi-vector / dim union
- pareto front advantage over linear (concave region reachable)
"""

from __future__ import annotations

import pytest
from core.self_improving_loop.tchebycheff import (
    compute_ideal_point,
    compute_tchebycheff,
)

# ---------------------------------------------------------------------------
# 1. compute_tchebycheff — basic shape
# ---------------------------------------------------------------------------


def test_tchebycheff_empty_inputs_returns_zero() -> None:
    assert compute_tchebycheff({}, {}, {}) == 0.0


def test_tchebycheff_single_dim_at_ideal_returns_zero() -> None:
    """fitness == ideal → scalar = 0 (best possible)."""
    result = compute_tchebycheff(
        fitness_dim={"safety": 1.0},
        weights={"safety": 1.0},
        ideal_point={"safety": 1.0},
    )
    assert result == 0.0


def test_tchebycheff_single_dim_below_ideal_returns_negative() -> None:
    """fitness < ideal → scalar negative (further from ideal)."""
    result = compute_tchebycheff(
        fitness_dim={"safety": 0.7},
        weights={"safety": 1.0},
        ideal_point={"safety": 1.0},
    )
    assert result == pytest.approx(-0.3)


def test_tchebycheff_max_d_picks_worst_dim() -> None:
    """multi-dim — scalar 는 worst dim 의 (weighted) gap 의 음수."""
    result = compute_tchebycheff(
        fitness_dim={"a": 0.9, "b": 0.5},
        weights={"a": 1.0, "b": 1.0},
        ideal_point={"a": 1.0, "b": 1.0},
    )
    # gaps: a=0.1, b=0.5; max=0.5 → scalar = -0.5
    assert result == pytest.approx(-0.5)


def test_tchebycheff_weights_scale_gaps() -> None:
    """가중치가 dim gap 을 scale — heavier weight = higher penalty."""
    result = compute_tchebycheff(
        fitness_dim={"a": 0.9, "b": 0.5},
        weights={"a": 10.0, "b": 1.0},  # a heavily weighted
        ideal_point={"a": 1.0, "b": 1.0},
    )
    # gaps: a=10*0.1=1.0, b=1*0.5=0.5; max=1.0 → scalar = -1.0
    assert result == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# 2. compute_tchebycheff — edge cases
# ---------------------------------------------------------------------------


def test_tchebycheff_missing_ideal_skips_dim() -> None:
    """ideal 에 없는 dim → contribution skip."""
    result = compute_tchebycheff(
        fitness_dim={"safety": 0.7, "helpfulness": 0.3},
        weights={"safety": 1.0, "helpfulness": 1.0},
        ideal_point={"safety": 1.0},  # no helpfulness
    )
    # only safety counted: gap 0.3 → scalar -0.3
    assert result == pytest.approx(-0.3)


def test_tchebycheff_missing_weight_defaults_to_one() -> None:
    """weight 미지정 dim → 1.0 default."""
    result = compute_tchebycheff(
        fitness_dim={"safety": 0.5},
        weights={},  # no weights
        ideal_point={"safety": 1.0},
    )
    assert result == pytest.approx(-0.5)


def test_tchebycheff_no_overlap_returns_zero() -> None:
    """fitness 와 ideal 의 dim 교집합이 empty → 0.0 (no signal)."""
    result = compute_tchebycheff(
        fitness_dim={"a": 0.5},
        weights={"a": 1.0},
        ideal_point={"b": 1.0},  # different dim
    )
    assert result == 0.0


# ---------------------------------------------------------------------------
# 3. compute_ideal_point — per-dim max
# ---------------------------------------------------------------------------


def test_ideal_point_empty_input() -> None:
    assert compute_ideal_point([]) == {}


def test_ideal_point_single_vector() -> None:
    result = compute_ideal_point([{"a": 0.5, "b": 0.3}])
    assert result == {"a": 0.5, "b": 0.3}


def test_ideal_point_multi_vector_max_per_dim() -> None:
    """Per-dim max across all vectors."""
    vectors = [
        {"a": 0.5, "b": 0.3},
        {"a": 0.8, "b": 0.2},
        {"a": 0.6, "b": 0.7},
    ]
    result = compute_ideal_point(vectors)
    assert result == {"a": 0.8, "b": 0.7}


def test_ideal_point_dim_union() -> None:
    """Vectors with different dim sets → union with each dim's observed max."""
    vectors = [
        {"a": 0.5},
        {"b": 0.3},
        {"a": 0.7, "c": 0.1},
    ]
    result = compute_ideal_point(vectors)
    assert result == {"a": 0.7, "b": 0.3, "c": 0.1}


# ---------------------------------------------------------------------------
# 4. Pareto-front advantage — concave region reachability
# ---------------------------------------------------------------------------


def test_tchebycheff_reaches_concave_region() -> None:
    """linear scalarization 으로는 unreachable 한 concave point 가
    Tchebycheff 로는 unique max 가 됨.

    Setup: 3 Pareto points forming a *concave* front segment.
    - A = (1.0, 0.0)
    - B = (0.5, 0.5)  ← concave (linear scalarization 으로 도달 불가)
    - C = (0.0, 1.0)
    With uniform weights, linear sum 은 모두 같음 (A=B=C=1.0). Tchebycheff
    는 B 를 unique max (closest to ideal (1.0, 1.0)).
    """
    ideal = {"x": 1.0, "y": 1.0}
    weights = {"x": 1.0, "y": 1.0}
    score_a = compute_tchebycheff({"x": 1.0, "y": 0.0}, weights, ideal)
    score_b = compute_tchebycheff({"x": 0.5, "y": 0.5}, weights, ideal)
    score_c = compute_tchebycheff({"x": 0.0, "y": 1.0}, weights, ideal)
    # A: max(0, 1) = 1.0 → -1.0
    # B: max(0.5, 0.5) = 0.5 → -0.5
    # C: max(1, 0) = 1.0 → -1.0
    assert score_b > score_a  # B beats A
    assert score_b > score_c  # B beats C
    assert score_a == pytest.approx(score_c)  # extreme points tie


# ---------------------------------------------------------------------------
# 5. Integration — pipeline with archive
# ---------------------------------------------------------------------------


def test_pipeline_with_archive_entries() -> None:
    """compute_ideal_point + compute_tchebycheff — archive 기반 selection."""
    archive_fitness = [
        {"safety": 0.9, "helpfulness": 0.5},
        {"safety": 0.6, "helpfulness": 0.8},
    ]
    ideal = compute_ideal_point(archive_fitness)
    assert ideal == {"safety": 0.9, "helpfulness": 0.8}

    # Candidate: balanced compromise
    candidate = {"safety": 0.75, "helpfulness": 0.7}
    score = compute_tchebycheff(candidate, {"safety": 1.0, "helpfulness": 1.0}, ideal)
    # gaps: 0.15, 0.10; max=0.15 → -0.15
    assert score == pytest.approx(-0.15)
