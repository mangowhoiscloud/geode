"""ADR-012 S1 — `ux_means` fitness 축 invariants.

S1 의 minimal scope: schema + normalize + compute_fitness 다축화.
실제 4 source (RunLog/LLMUsage/git/OTel) 의 wiring 은 S1b (별도 PR).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from autoresearch.train import (
    UX_FITNESS_DIM_WEIGHT,
    UX_FITNESS_UX_WEIGHT,
    compute_fitness,
)
from autoresearch.ux_means import (
    UX_DIM_WEIGHTS,
    collect_ux_means_from_sources,
    compute_ux_aggregate,
    normalize_ux_field,
    validate_ux_schema,
)

# ---------------------------------------------------------------------------
# 1. Schema constants
# ---------------------------------------------------------------------------


def test_ux_dim_weights_sum_to_one() -> None:
    """4-field 가중치 합 == 1.0 (assert in module-level)."""
    assert abs(sum(UX_DIM_WEIGHTS.values()) - 1.0) < 1e-9


def test_ux_dim_weights_exact_4_fields() -> None:
    """schema 의 4 field 정확히."""
    assert set(UX_DIM_WEIGHTS) == {
        "success_rate",
        "token_cost_norm",
        "revert_ratio_norm",
        "latency_norm",
    }


def test_fitness_axis_weights_sum_to_one() -> None:
    """``compute_fitness`` 의 dim/ux 가중치 합 == 1.0."""
    assert abs(UX_FITNESS_DIM_WEIGHT + UX_FITNESS_UX_WEIGHT - 1.0) < 1e-9


def test_fitness_dim_weight_dominates_for_s1() -> None:
    """S1 단계 (admire_means 신설 전) 에서 dim 이 우세 — ux 의 양의 압력이
    적용되지만 17-dim 의 음의 압력이 여전히 주축. S2 신설 시 재배분."""
    assert UX_FITNESS_DIM_WEIGHT > UX_FITNESS_UX_WEIGHT


# ---------------------------------------------------------------------------
# 2. normalize_ux_field
# ---------------------------------------------------------------------------


def test_normalize_no_invert_clamps_to_unit() -> None:
    assert normalize_ux_field(0.5, budget=1.0, invert=False) == 0.5
    assert normalize_ux_field(-1.0, budget=1.0, invert=False) == 0.0
    assert normalize_ux_field(2.0, budget=1.0, invert=False) == 1.0


def test_normalize_invert_lower_is_better() -> None:
    """token_cost / latency 처럼 lower-is-better 인 metric → invert."""
    # value=0 → 1.0 (best)
    assert normalize_ux_field(0.0, budget=10.0, invert=True) == 1.0
    # value=budget → 0.0 (worst)
    assert normalize_ux_field(10.0, budget=10.0, invert=True) == 0.0
    # value=half → 0.5
    assert normalize_ux_field(5.0, budget=10.0, invert=True) == 0.5


def test_normalize_invert_with_zero_budget() -> None:
    """budget=0 + invert=True → degenerate. value=0 만 양호 (1.0), 외 0.0."""
    assert normalize_ux_field(0.0, budget=0.0, invert=True) == 1.0
    assert normalize_ux_field(1.0, budget=0.0, invert=True) == 0.0


# ---------------------------------------------------------------------------
# 3. compute_ux_aggregate
# ---------------------------------------------------------------------------


def test_aggregate_none_returns_neutral_half() -> None:
    """``None`` ux_means → 0.5 neutral (no-op signal)."""
    assert compute_ux_aggregate(None) == 0.5


def test_aggregate_all_perfect_returns_one() -> None:
    perfect = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    assert abs(compute_ux_aggregate(perfect) - 1.0) < 1e-9


def test_aggregate_all_zero_returns_zero() -> None:
    zero = dict.fromkeys(UX_DIM_WEIGHTS, 0.0)
    assert compute_ux_aggregate(zero) == 0.0


def test_aggregate_weighted_sum() -> None:
    """success_rate=1.0 (weight 0.4) + 나머지 0.0 → 0.4."""
    partial = {"success_rate": 1.0}
    # 나머지는 누락 → neutral 0.5
    expected = (
        UX_DIM_WEIGHTS["success_rate"] * 1.0
        + UX_DIM_WEIGHTS["token_cost_norm"] * 0.5
        + UX_DIM_WEIGHTS["revert_ratio_norm"] * 0.5
        + UX_DIM_WEIGHTS["latency_norm"] * 0.5
    )
    assert abs(compute_ux_aggregate(partial) - expected) < 1e-9


def test_aggregate_clamps_out_of_range() -> None:
    """범위 밖 값은 0-1 로 clamp."""
    bad = dict.fromkeys(UX_DIM_WEIGHTS, 2.0)
    assert abs(compute_ux_aggregate(bad) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 4. validate_ux_schema
# ---------------------------------------------------------------------------


def test_validate_none() -> None:
    assert validate_ux_schema(None) is True


def test_validate_valid_dict() -> None:
    assert validate_ux_schema({"success_rate": 0.5}) is True


def test_validate_rejects_non_dict() -> None:
    assert validate_ux_schema([1.0, 2.0]) is False
    assert validate_ux_schema("not a dict") is False


def test_validate_rejects_unknown_field() -> None:
    assert validate_ux_schema({"unknown_field": 0.5}) is False


def test_validate_rejects_out_of_range() -> None:
    assert validate_ux_schema({"success_rate": 1.5}) is False
    assert validate_ux_schema({"success_rate": -0.1}) is False


def test_validate_rejects_non_numeric() -> None:
    assert validate_ux_schema({"success_rate": "high"}) is False


# ---------------------------------------------------------------------------
# 5. compute_fitness multi-axis
# ---------------------------------------------------------------------------


def test_compute_fitness_dim_only_when_ux_none() -> None:
    """``ux_means is None`` → dim-only fallback (현재 behavior 보존)."""
    dim_means = {"broken_tool_use": 5.0, "overrefusal": 2.0}
    f_none = compute_fitness(dim_means, ux_means=None)
    f_default = compute_fitness(dim_means)
    assert f_none == f_default


def test_compute_fitness_with_perfect_ux_increases() -> None:
    """ux_means 가 모두 1.0 → fitness 증가."""
    dim_means = {"broken_tool_use": 5.0}
    base = compute_fitness(dim_means)
    with_ux = compute_fitness(
        dim_means,
        ux_means=dict.fromkeys(UX_DIM_WEIGHTS, 1.0),
    )
    # dim*0.7 + ux*0.3 = base*0.7 + 1.0*0.3
    assert with_ux > base * 0.65  # base*0.7 - epsilon < with_ux
    expected = base * UX_FITNESS_DIM_WEIGHT + 1.0 * UX_FITNESS_UX_WEIGHT
    assert abs(with_ux - expected) < 1e-9


def test_compute_fitness_with_zero_ux_decreases() -> None:
    """ux_means 가 모두 0 → fitness 감소 (dim*0.7 + 0*0.3 < dim)."""
    dim_means = {"broken_tool_use": 5.0}
    base = compute_fitness(dim_means)
    with_zero_ux = compute_fitness(
        dim_means,
        ux_means=dict.fromkeys(UX_DIM_WEIGHTS, 0.0),
    )
    expected = base * UX_FITNESS_DIM_WEIGHT
    assert abs(with_zero_ux - expected) < 1e-9


def test_compute_fitness_ux_does_not_bypass_critical_gate() -> None:
    """ux_means 가 perfect 여도 critical dim regress 면 fitness=0
    (strict-reject 보존)."""
    dim_means = {"broken_tool_use": 10.0}  # high = bad
    baseline_means = {"broken_tool_use": 5.0}  # current is much worse
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        ux_means=dict.fromkeys(UX_DIM_WEIGHTS, 1.0),
    )
    assert f == 0.0


# ---------------------------------------------------------------------------
# 6. collect_ux_means_from_sources — graceful when mutations.jsonl empty
# ---------------------------------------------------------------------------


def test_collect_returns_none_when_ledger_absent(tmp_path: Path) -> None:
    """PR-AR-L4a (2026-05-26) — collector graceful no-op contract.

    Pre-PR-AR-L4a the function was a hardcoded ``return None`` placeholder.
    Post-wiring it reads ``mutations.jsonl``; when the file is absent
    (fresh checkout, before first audit) it still returns ``None`` so
    ``compute_fitness`` falls back to dim-only fitness."""
    missing = tmp_path / "no-mutations.jsonl"
    assert not missing.exists()
    assert collect_ux_means_from_sources(log_path=missing) is None


# ---------------------------------------------------------------------------
# 7. ADR cross-reference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,expected_lower_is_better",
    [
        ("success_rate", False),  # 높을수록 좋음 — invert 불필요
        ("token_cost_norm", True),  # normalize 시 invert 처리됨 → field 자체는 0-1 (높을수록 좋음)
        ("revert_ratio_norm", True),
        ("latency_norm", True),
    ],
)
def test_ux_fields_semantic_doc(field: str, expected_lower_is_better: bool) -> None:
    """각 field 의 semantic: 정규화 후 모두 "높을수록 좋음" 으로 통일.
    원본 metric 의 방향 (token_cost / latency / revert_ratio 는 lower-is-better)
    는 normalize_ux_field 의 invert=True 로 처리."""
    # field 가 schema 에 등록
    assert field in UX_DIM_WEIGHTS
