"""ADR-012 S2 — `admire_means` fitness 축 invariants (ux-removed 2026-05-30).

S2 scope: schema + math + ranker hook interface + compute_fitness 2축
재배분 (dim + admire). ux_means 축은 PR-MARGIN-FITNESS-SCALE 에서 제거 —
compute_fitness 의 분기는 dim-only / admire 2축 / bench 3축.
ranker.py 의 실제 ELO + voter panel 호출 wiring 은 S2b (별도 PR).
"""

from __future__ import annotations

import pytest
from core.self_improving.admire_means import (
    ADMIRE_DIM_WEIGHTS,
    CALIBRATION_THRESHOLD,
    compute_admire_aggregate,
)
from core.self_improving.train import (
    FITNESS_ADMIRE_WEIGHT,
    FITNESS_DIM_3AX,
    FITNESS_DIM_WEIGHT,
    compute_fitness,
)

# ---------------------------------------------------------------------------
# 1. Schema constants
# ---------------------------------------------------------------------------


def test_admire_dim_weights_sum_to_one() -> None:
    assert abs(sum(ADMIRE_DIM_WEIGHTS.values()) - 1.0) < 1e-9


def test_admire_dim_weights_exact_2_fields() -> None:
    assert set(ADMIRE_DIM_WEIGHTS) == {"pairwise_win_rate", "human_calibration_corr"}


def test_2_axis_fitness_weights_sum_to_one() -> None:
    assert abs(FITNESS_DIM_WEIGHT + FITNESS_ADMIRE_WEIGHT - 1.0) < 1e-9


def test_3_axis_dim_weight_smaller_than_2_axis_dim_weight() -> None:
    """추가 양의 압력 축(bench)이 활성화되면 dim 비중이 더 감소한다
    (2축 dim 0.70 → 3축 dim 0.55)."""
    assert FITNESS_DIM_3AX < FITNESS_DIM_WEIGHT


def test_calibration_threshold_in_valid_range() -> None:
    """CALIBRATION_THRESHOLD 가 0-1 범위 내 + 절반 이상 (judge 가 절반
    이상 human 과 상관관계 유지해야 dampening 없음)."""
    assert 0.0 < CALIBRATION_THRESHOLD <= 1.0
    assert CALIBRATION_THRESHOLD >= 0.5


def test_calibration_threshold_exact_value() -> None:
    """CALIBRATION_THRESHOLD == 0.667 — Krippendorff 2004 *Content
    Analysis* 2nd ed (p.241) substantial-agreement floor for nominal
    IRR. PR-AR-L4c operator decision: ground via Krippendorff instead
    of the prior magic 0.7. 변경 시 test + docstring + ADR + 새 Krippendorff
    constant 모두 동기 갱신 필요."""
    assert pytest.approx(0.667) == CALIBRATION_THRESHOLD


def test_calibration_dampening_at_exact_threshold_full_signal() -> None:
    """corr == threshold edge case — dampening = min(1.0, 1.0) = 1.0."""
    edge = {"pairwise_win_rate": 1.0, "human_calibration_corr": CALIBRATION_THRESHOLD}
    expected = (
        ADMIRE_DIM_WEIGHTS["pairwise_win_rate"] * 1.0
        + ADMIRE_DIM_WEIGHTS["human_calibration_corr"] * CALIBRATION_THRESHOLD
    )
    assert abs(compute_admire_aggregate(edge) - expected) < 1e-9


# ---------------------------------------------------------------------------
# 2. compute_admire_aggregate
# ---------------------------------------------------------------------------


def test_aggregate_none_returns_neutral_half() -> None:
    assert compute_admire_aggregate(None) == 0.5


def test_aggregate_perfect_calibration_full_signal() -> None:
    """calibration_corr >= threshold 이면 dampening=1.0, win_rate 신호 전달."""
    perfect = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    # weights: 0.70 * (1.0 * 1.0 dampening) + 0.30 * 1.0 = 1.0
    assert abs(compute_admire_aggregate(perfect) - 1.0) < 1e-9


def test_aggregate_zero_calibration_dampens_win_rate() -> None:
    """calibration_corr=0 → dampening=0 → win_rate 신호 무효, calibration
    field 만 영향. weight 0.30 × 0 = 0.0."""
    zero_corr = {"pairwise_win_rate": 1.0, "human_calibration_corr": 0.0}
    # 0.70 * (1.0 * 0.0 dampening) + 0.30 * 0.0 = 0.0
    assert compute_admire_aggregate(zero_corr) == 0.0


def test_aggregate_below_threshold_dampens_proportionally() -> None:
    """calibration_corr < threshold 이면 dampening 비례 감쇠."""
    half = {"pairwise_win_rate": 1.0, "human_calibration_corr": CALIBRATION_THRESHOLD / 2}
    # dampening = 0.5, win_rate*1.0*0.5 = 0.5
    # = 0.70 * 0.5 + 0.30 * (threshold/2)
    expected = ADMIRE_DIM_WEIGHTS["pairwise_win_rate"] * 1.0 * 0.5 + ADMIRE_DIM_WEIGHTS[
        "human_calibration_corr"
    ] * (CALIBRATION_THRESHOLD / 2)
    assert abs(compute_admire_aggregate(half) - expected) < 1e-9


def test_aggregate_above_threshold_does_not_amplify() -> None:
    """calibration_corr > threshold 여도 dampening cap=1.0 (clamp). 가중치
    초과 amplification 방지."""
    above = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    # dampening = min(1.0, 1.0/0.7) = 1.0 (clamp)
    # = 0.70 * 1.0 + 0.30 * 1.0 = 1.0
    assert abs(compute_admire_aggregate(above) - 1.0) < 1e-9


def test_aggregate_missing_field_defaults_neutral() -> None:
    """누락 field 는 neutral 처리 — win_rate default 0.5, corr default threshold."""
    partial = {"pairwise_win_rate": 1.0}
    # corr default = threshold → dampening=1.0
    # = 0.70 * 1.0 * 1.0 + 0.30 * threshold
    expected = (
        ADMIRE_DIM_WEIGHTS["pairwise_win_rate"] * 1.0
        + ADMIRE_DIM_WEIGHTS["human_calibration_corr"] * CALIBRATION_THRESHOLD
    )
    assert abs(compute_admire_aggregate(partial) - expected) < 1e-9


def test_aggregate_clamps_out_of_range() -> None:
    bad = {"pairwise_win_rate": 2.0, "human_calibration_corr": 1.5}
    assert abs(compute_admire_aggregate(bad) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 4. collect_admire_means_from_ranker — replaced by
#    admire_means_from_eval_result in PR-AR-L4c. Coverage moved to
#    tests/autoresearch/test_admire_handoff_consume.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. compute_fitness 3-axis multi-axis
# ---------------------------------------------------------------------------


def test_compute_fitness_both_none_dim_only() -> None:
    """admire + bench 둘 다 None → dim-only fallback."""
    dim_means = {"broken_tool_use": 5.0}
    f_both_none = compute_fitness(dim_means, admire_means=None, bench_means=None)
    f_default = compute_fitness(dim_means)
    assert f_both_none == f_default


def test_compute_fitness_2_axis_with_admire() -> None:
    """admire 만 주어지면 2축 재배분 (dim 0.70 + admire 0.30)."""
    dim_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    f = compute_fitness(dim_means, admire_means=admire)
    base = compute_fitness(dim_means)
    expected = FITNESS_DIM_WEIGHT * base + FITNESS_ADMIRE_WEIGHT * 1.0
    assert abs(f - expected) < 1e-9


def test_compute_fitness_critical_gate_strict_reject_with_admire() -> None:
    """admire 가 perfect 여도 critical dim regress 면 fitness=0."""
    dim_means = {"broken_tool_use": 10.0}
    baseline_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        admire_means=admire,
    )
    assert f == 0.0


def test_compute_fitness_dim_weight_redistributed_when_admire_active() -> None:
    """S2 의 핵심 효과 — admire 활성화 시 dim 비중이 감소. 같은 dim 점수
    + zero admire → 2축 fitness < dim-only fitness (dim 0.70 < 1.0)."""
    dim_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 0.0, "human_calibration_corr": 0.0}
    base = compute_fitness(dim_means)
    f_2axis = compute_fitness(dim_means, admire_means=admire)
    # 2축: base*0.70 + 0*0.30 = base*0.70 < base (dim-only)
    assert f_2axis < base  # dim 비중 감소 직접 검증
    assert abs(f_2axis - base * FITNESS_DIM_WEIGHT) < 1e-9


# ---------------------------------------------------------------------------
# 6. Ranker hook contract — ADR cross-reference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["pairwise_win_rate", "human_calibration_corr"],
)
def test_admire_fields_in_schema(field: str) -> None:
    """schema 의 2 field 가 등록."""
    assert field in ADMIRE_DIM_WEIGHTS
