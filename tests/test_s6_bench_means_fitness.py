"""ADR-012 S6 — `bench_means` + Petri/bench cross-validation gate invariants.

S6 scope: schema + math + 4축 다축화 + cross-validation gate (Path C
inspect_ai federation). 실제 federation 의 multi-eval wiring 은 S6b.
"""

from __future__ import annotations

from autoresearch.bench_means import (
    BENCH_DIM_WEIGHTS,
    collect_bench_means_from_inspect_ai,
    compute_bench_aggregate,
    detect_cross_validation_conflict,
    validate_bench_schema,
)
from autoresearch.train import (
    FITNESS_ADMIRE_4AX,
    FITNESS_ADMIRE_WEIGHT,
    FITNESS_BENCH_4AX,
    FITNESS_DIM_4AX,
    FITNESS_DIM_WEIGHT,
    FITNESS_UX_4AX,
    FITNESS_UX_WEIGHT,
    UX_FITNESS_DIM_WEIGHT,
    UX_FITNESS_UX_WEIGHT,
    compute_fitness,
)
from autoresearch.ux_means import UX_DIM_WEIGHTS

# ---------------------------------------------------------------------------
# 1. Schema constants
# ---------------------------------------------------------------------------


def test_bench_dim_weights_sum_to_one() -> None:
    assert abs(sum(BENCH_DIM_WEIGHTS.values()) - 1.0) < 1e-9


def test_bench_dim_weights_exact_4_fields() -> None:
    assert set(BENCH_DIM_WEIGHTS) == {
        "swe_bench_pass",
        "tau_bench_success",
        "humaneval_pass1",
        "gaia_accuracy",
    }


def test_4_axis_fitness_weights_sum_to_one() -> None:
    assert (
        abs(FITNESS_DIM_4AX + FITNESS_UX_4AX + FITNESS_ADMIRE_4AX + FITNESS_BENCH_4AX - 1.0) < 1e-9
    )


def test_4_axis_dim_weight_smaller_than_3_axis() -> None:
    """4축 신설로 dim 비중 0.40 → 0.30 으로 추가 감소."""
    assert FITNESS_DIM_4AX < FITNESS_DIM_WEIGHT


def test_swe_bench_has_highest_bench_weight() -> None:
    """SWE-bench 가 코드 도메인 핵심 — 가장 높은 가중치."""
    max_field = max(BENCH_DIM_WEIGHTS, key=lambda k: BENCH_DIM_WEIGHTS[k])
    assert max_field == "swe_bench_pass"


# ---------------------------------------------------------------------------
# 2. compute_bench_aggregate
# ---------------------------------------------------------------------------


def test_aggregate_none_returns_neutral_half() -> None:
    assert compute_bench_aggregate(None) == 0.5


def test_aggregate_all_perfect_returns_one() -> None:
    perfect = dict.fromkeys(BENCH_DIM_WEIGHTS, 1.0)
    assert abs(compute_bench_aggregate(perfect) - 1.0) < 1e-9


def test_aggregate_all_zero_returns_zero() -> None:
    zero = dict.fromkeys(BENCH_DIM_WEIGHTS, 0.0)
    assert compute_bench_aggregate(zero) == 0.0


def test_aggregate_missing_fields_default_neutral() -> None:
    """누락 field 는 neutral 0.5."""
    partial = {"swe_bench_pass": 1.0}
    expected = (
        BENCH_DIM_WEIGHTS["swe_bench_pass"] * 1.0
        + BENCH_DIM_WEIGHTS["tau_bench_success"] * 0.5
        + BENCH_DIM_WEIGHTS["humaneval_pass1"] * 0.5
        + BENCH_DIM_WEIGHTS["gaia_accuracy"] * 0.5
    )
    assert abs(compute_bench_aggregate(partial) - expected) < 1e-9


def test_aggregate_clamps_out_of_range() -> None:
    bad = dict.fromkeys(BENCH_DIM_WEIGHTS, 2.0)
    assert abs(compute_bench_aggregate(bad) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 3. validate_bench_schema
# ---------------------------------------------------------------------------


def test_validate_none() -> None:
    assert validate_bench_schema(None) is True


def test_validate_valid_dict() -> None:
    assert validate_bench_schema({"swe_bench_pass": 0.5}) is True


def test_validate_rejects_unknown_field() -> None:
    assert validate_bench_schema({"unknown_bench": 0.5}) is False


def test_validate_rejects_out_of_range() -> None:
    assert validate_bench_schema({"swe_bench_pass": 1.5}) is False


def test_validate_rejects_non_dict() -> None:
    assert validate_bench_schema([0.5]) is False


# ---------------------------------------------------------------------------
# 4. Cross-validation gate — Goodhart 양방향 방어
# ---------------------------------------------------------------------------


def test_no_conflict_when_baselines_missing() -> None:
    """baseline 없으면 cross-validation 비교 불가 → None."""
    assert (
        detect_cross_validation_conflict(
            dim_means={"broken_tool_use": 1.0},
            baseline_dim_means=None,
            bench_means={"swe_bench_pass": 0.5},
            baseline_bench_means={"swe_bench_pass": 0.5},
            critical_dims=("broken_tool_use",),
        )
        is None
    )


def test_no_conflict_when_bench_means_missing() -> None:
    """bench 신호 없으면 cross-validation 불가."""
    assert (
        detect_cross_validation_conflict(
            dim_means={"broken_tool_use": 1.0},
            baseline_dim_means={"broken_tool_use": 2.0},
            bench_means=None,
            baseline_bench_means={"swe_bench_pass": 0.5},
        )
        is None
    )


def test_detects_alignment_only_fooling() -> None:
    """Petri promote (dim 개선) + bench regress → fooling 의심."""
    conflict = detect_cross_validation_conflict(
        dim_means={"broken_tool_use": 2.0},  # better than baseline 5.0 (lower)
        baseline_dim_means={"broken_tool_use": 5.0},
        bench_means={"swe_bench_pass": 0.3},
        baseline_bench_means={"swe_bench_pass": 0.6},  # bench regressed
        critical_dims=("broken_tool_use",),
    )
    assert conflict == "alignment_only_fooling"


def test_detects_capability_at_alignment_cost() -> None:
    """bench promote + Petri critical regress → 안전성 손상."""
    conflict = detect_cross_validation_conflict(
        dim_means={"broken_tool_use": 8.0},  # worse than baseline 3.0
        baseline_dim_means={"broken_tool_use": 3.0},
        bench_means={"swe_bench_pass": 0.8},
        baseline_bench_means={"swe_bench_pass": 0.5},  # bench improved
        critical_dims=("broken_tool_use",),
    )
    assert conflict == "capability_at_alignment_cost"


def test_no_conflict_when_both_aligned() -> None:
    """Petri 와 bench 가 같은 방향 (둘 다 개선 or 둘 다 악화) → no conflict."""
    # 둘 다 개선
    assert (
        detect_cross_validation_conflict(
            dim_means={"broken_tool_use": 2.0},
            baseline_dim_means={"broken_tool_use": 5.0},
            bench_means={"swe_bench_pass": 0.7},
            baseline_bench_means={"swe_bench_pass": 0.5},
            critical_dims=("broken_tool_use",),
        )
        is None
    )


# ---------------------------------------------------------------------------
# 5. collect_bench_means_from_inspect_ai — S6b placeholder
# ---------------------------------------------------------------------------


def test_collect_returns_none_in_s6() -> None:
    """S6 (이 PR) — inspect_ai federation 실제 wiring 은 S6b. placeholder."""
    assert collect_bench_means_from_inspect_ai() is None


# ---------------------------------------------------------------------------
# 6. compute_fitness 4축 다축화
# ---------------------------------------------------------------------------


def test_compute_fitness_all_none_dim_only() -> None:
    """셋 다 None → dim-only fallback (backwards compat)."""
    dim_means = {"broken_tool_use": 5.0}
    f_none = compute_fitness(dim_means)
    f_explicit = compute_fitness(dim_means, ux_means=None, admire_means=None, bench_means=None)
    assert f_none == f_explicit


def test_compute_fitness_ux_only_2_axis() -> None:
    """ux 만 → S1 의 2축 (0.7/0.3, backwards compat)."""
    dim_means = {"broken_tool_use": 5.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    f = compute_fitness(dim_means, ux_means=ux)
    base = compute_fitness(dim_means)
    expected = base * UX_FITNESS_DIM_WEIGHT + 1.0 * UX_FITNESS_UX_WEIGHT
    assert abs(f - expected) < 1e-9


def test_compute_fitness_admire_active_3_axis() -> None:
    """admire 활성 (bench 없음) → S2 의 3축 (0.4/0.3/0.3)."""
    dim_means = {"broken_tool_use": 5.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    f = compute_fitness(dim_means, ux_means=ux, admire_means=admire)
    base = compute_fitness(dim_means)
    expected = FITNESS_DIM_WEIGHT * base + FITNESS_UX_WEIGHT * 1.0 + FITNESS_ADMIRE_WEIGHT * 1.0
    assert abs(f - expected) < 1e-9


def test_compute_fitness_bench_active_4_axis() -> None:
    """bench 활성 → S6 의 4축 재배분 (0.30/0.25/0.20/0.25)."""
    dim_means = {"broken_tool_use": 5.0}
    ux = dict.fromkeys(UX_DIM_WEIGHTS, 1.0)
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    bench = dict.fromkeys(BENCH_DIM_WEIGHTS, 1.0)
    # baseline_means 없으면 cross-validation 비교 skip (conflict=None)
    f = compute_fitness(dim_means, ux_means=ux, admire_means=admire, bench_means=bench)
    base = compute_fitness(dim_means)
    expected = (
        FITNESS_DIM_4AX * base
        + FITNESS_UX_4AX * 1.0
        + FITNESS_ADMIRE_4AX * 1.0
        + FITNESS_BENCH_4AX * 1.0
    )
    assert abs(f - expected) < 1e-9


def test_compute_fitness_bench_only_with_neutral_ux_admire() -> None:
    """bench 만 주어지면 ux/admire 는 neutral 0.5 → 4축 활성."""
    dim_means = {"broken_tool_use": 5.0}
    bench = dict.fromkeys(BENCH_DIM_WEIGHTS, 1.0)
    f = compute_fitness(dim_means, bench_means=bench)
    base = compute_fitness(dim_means)
    expected = (
        FITNESS_DIM_4AX * base
        + FITNESS_UX_4AX * 0.5  # neutral
        + FITNESS_ADMIRE_4AX * 0.5
        + FITNESS_BENCH_4AX * 1.0
    )
    assert abs(f - expected) < 1e-9


# ---------------------------------------------------------------------------
# 7. Cross-validation gate in compute_fitness — strict reject
# ---------------------------------------------------------------------------


def test_cross_validation_gate_blocks_alignment_only_fooling() -> None:
    """Petri promote + bench regress 면 compute_fitness 가 0.0 strict reject."""
    dim_means = {"broken_tool_use": 2.0}  # better than baseline (lower)
    baseline_means = {"broken_tool_use": 5.0}
    bench = {"swe_bench_pass": 0.3}  # bench regressed
    baseline_bench = {"swe_bench_pass": 0.6}
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        bench_means=bench,
        baseline_bench_means=baseline_bench,
    )
    assert f == 0.0, "alignment_only_fooling conflict → strict reject"


def test_cross_validation_gate_blocks_capability_at_alignment_cost() -> None:
    """bench promote + Petri critical regress → 0.0 strict reject."""
    dim_means = {"broken_tool_use": 8.0}  # worse than baseline 3.0
    baseline_means = {"broken_tool_use": 3.0}
    bench = {"swe_bench_pass": 0.8}  # bench improved
    baseline_bench = {"swe_bench_pass": 0.5}
    # baseline critical regress 가 일반 critical gate 도 발화 — 본 test 는
    # bench cross-validation 의 명시적 conflict 검출도 같이 작동함을 검증.
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        bench_means=bench,
        baseline_bench_means=baseline_bench,
    )
    assert f == 0.0


def test_no_cross_validation_when_signals_aligned() -> None:
    """Petri 와 bench 가 같은 방향 → fitness 정상 계산."""
    dim_means = {"broken_tool_use": 2.0}  # improved
    baseline_means = {"broken_tool_use": 5.0}
    bench = {"swe_bench_pass": 0.7}  # also improved
    baseline_bench = {"swe_bench_pass": 0.5}
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        bench_means=bench,
        baseline_bench_means=baseline_bench,
    )
    assert f > 0.0, "둘 다 개선이면 strict reject 발화 안 함"
