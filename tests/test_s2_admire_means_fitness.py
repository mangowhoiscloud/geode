"""ADR-012 S2 — `admire_means` fitness 축 + 3축 다축화 invariants.

S2 scope: schema + math + ranker hook interface + compute_fitness 3축
재배분. ranker.py 의 실제 ELO + voter panel 호출 wiring 은 S2b (별도 PR).
"""

from __future__ import annotations

import pytest
from autoresearch.admire_means import (
    ADMIRE_DIM_WEIGHTS,
    CALIBRATION_THRESHOLD,
    collect_admire_means_from_ranker,
    compute_admire_aggregate,
    validate_admire_schema,
)
from autoresearch.train import (
    FITNESS_ADMIRE_WEIGHT,
    FITNESS_DIM_WEIGHT,
    FITNESS_UX_WEIGHT,
    UX_FITNESS_DIM_WEIGHT,
    UX_FITNESS_UX_WEIGHT,
    compute_fitness,
)
from autoresearch.ux_means import UX_DIM_WEIGHTS

# ---------------------------------------------------------------------------
# 1. Schema constants
# ---------------------------------------------------------------------------


def test_admire_dim_weights_sum_to_one() -> None:
    assert abs(sum(ADMIRE_DIM_WEIGHTS.values()) - 1.0) < 1e-9


def test_admire_dim_weights_exact_2_fields() -> None:
    assert set(ADMIRE_DIM_WEIGHTS) == {"pairwise_win_rate", "human_calibration_corr"}


def test_3_axis_fitness_weights_sum_to_one() -> None:
    assert abs(FITNESS_DIM_WEIGHT + FITNESS_UX_WEIGHT + FITNESS_ADMIRE_WEIGHT - 1.0) < 1e-9


def test_3_axis_dim_weight_smaller_than_2_axis_dim_weight() -> None:
    """S2 신설로 dim 비중이 0.70 → 0.40 으로 감소 (양의 압력 두 축 추가)."""
    assert FITNESS_DIM_WEIGHT < UX_FITNESS_DIM_WEIGHT


def test_calibration_threshold_in_valid_range() -> None:
    """CALIBRATION_THRESHOLD 가 0-1 범위 내 + 절반 이상 (judge 가 절반
    이상 human 과 상관관계 유지해야 dampening 없음)."""
    assert 0.0 < CALIBRATION_THRESHOLD <= 1.0
    assert CALIBRATION_THRESHOLD >= 0.5


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
# 3. validate_admire_schema
# ---------------------------------------------------------------------------


def test_validate_none() -> None:
    assert validate_admire_schema(None) is True


def test_validate_valid_dict() -> None:
    assert validate_admire_schema({"pairwise_win_rate": 0.6}) is True


def test_validate_rejects_unknown_field() -> None:
    assert validate_admire_schema({"unknown": 0.5}) is False


def test_validate_rejects_out_of_range() -> None:
    assert validate_admire_schema({"pairwise_win_rate": 1.5}) is False


def test_validate_rejects_non_numeric() -> None:
    assert validate_admire_schema({"pairwise_win_rate": "high"}) is False


def test_validate_rejects_non_dict() -> None:
    assert validate_admire_schema([0.6, 0.8]) is False


# ---------------------------------------------------------------------------
# 4. collect_admire_means_from_ranker — S2b placeholder
# ---------------------------------------------------------------------------


def test_collect_returns_none_in_s2() -> None:
    """S2 (이 PR) 단계 — ranker.py 의 ELO + voter panel 실제 호출은 S2b.
    이 함수는 ``None`` 반환으로 compute_fitness 가 2축 fallback (S1 동일)."""
    assert collect_admire_means_from_ranker() is None


# ---------------------------------------------------------------------------
# 5. compute_fitness 3-axis multi-axis
# ---------------------------------------------------------------------------


def test_compute_fitness_both_none_dim_only() -> None:
    """ux + admire 둘 다 None → dim-only fallback (S1 backwards compat)."""
    dim_means = {"broken_tool_use": 5.0}
    f_both_none = compute_fitness(dim_means, ux_means=None, admire_means=None)
    f_default = compute_fitness(dim_means)
    assert f_both_none == f_default


def test_compute_fitness_ux_only_uses_2_axis_weights() -> None:
    """ux 만 주어지면 S1 의 0.7/0.3 (backwards compat) — 3축 재배분 아님."""
    dim_means = {"broken_tool_use": 5.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    f = compute_fitness(dim_means, ux_means=ux, admire_means=None)
    base = compute_fitness(dim_means)
    expected = base * UX_FITNESS_DIM_WEIGHT + 1.0 * UX_FITNESS_UX_WEIGHT
    assert abs(f - expected) < 1e-9


def test_compute_fitness_3_axis_with_admire() -> None:
    """ux + admire 모두 → 3축 재배분 (0.4/0.3/0.3)."""
    dim_means = {"broken_tool_use": 5.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    f = compute_fitness(dim_means, ux_means=ux, admire_means=admire)
    base = compute_fitness(dim_means)
    expected = FITNESS_DIM_WEIGHT * base + FITNESS_UX_WEIGHT * 1.0 + FITNESS_ADMIRE_WEIGHT * 1.0
    assert abs(f - expected) < 1e-9


def test_compute_fitness_admire_only_with_neutral_ux() -> None:
    """admire 만 주어지면 ux 는 neutral 0.5 로 처리 + 3축 활성화."""
    dim_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    f = compute_fitness(dim_means, ux_means=None, admire_means=admire)
    base = compute_fitness(dim_means)
    expected = (
        FITNESS_DIM_WEIGHT * base
        + FITNESS_UX_WEIGHT * 0.5  # neutral
        + FITNESS_ADMIRE_WEIGHT * 1.0
    )
    assert abs(f - expected) < 1e-9


def test_compute_fitness_critical_gate_strict_reject_with_admire() -> None:
    """admire+ux 가 perfect 여도 critical dim regress 면 fitness=0."""
    dim_means = {"broken_tool_use": 10.0}
    baseline_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        ux_means=ux,
        admire_means=admire,
    )
    assert f == 0.0


def test_compute_fitness_dim_weight_redistributed_when_admire_active() -> None:
    """S2 의 핵심 효과 — admire 활성화 시 dim 비중이 감소. 같은 dim 점수
    + perfect ux/admire → 3축 fitness < 2축 (S1) fitness (dim 0.4 < 0.7)."""
    dim_means = {"broken_tool_use": 5.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 0.0)  # zero ux to isolate dim weight effect
    admire = {"pairwise_win_rate": 0.0, "human_calibration_corr": 0.0}
    base = compute_fitness(dim_means)
    f_3axis = compute_fitness(dim_means, ux_means=ux, admire_means=admire)
    f_2axis = compute_fitness(dim_means, ux_means=ux)
    # 3축: base*0.4 + 0*0.3 + 0*0.3 = base*0.4
    # 2축: base*0.7 + 0*0.3 = base*0.7
    assert f_3axis < f_2axis  # dim 비중 감소 직접 검증
    assert abs(f_3axis - base * FITNESS_DIM_WEIGHT) < 1e-9
    assert abs(f_2axis - base * UX_FITNESS_DIM_WEIGHT) < 1e-9


# ---------------------------------------------------------------------------
# 6. Ranker hook contract — ADR cross-reference
# ---------------------------------------------------------------------------


def test_collect_admire_means_signature_matches_s1_pattern() -> None:
    """S1 의 collect_ux_means_from_sources 와 동일 시그니처 패턴 —
    ``_placeholder=True`` 기본값, ``None`` 반환."""
    import inspect

    sig = inspect.signature(collect_admire_means_from_ranker)
    assert "_placeholder" in sig.parameters


@pytest.mark.parametrize(
    "field",
    ["pairwise_win_rate", "human_calibration_corr"],
)
def test_admire_fields_in_schema(field: str) -> None:
    """schema 의 2 field 가 등록."""
    assert field in ADMIRE_DIM_WEIGHTS
