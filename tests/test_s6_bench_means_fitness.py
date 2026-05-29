"""ADR-012 S6 — `bench_means` + Petri/bench cross-validation gate invariants.

S6 scope: schema + math + 3축 다축화 + cross-validation gate (Path C
inspect_ai federation). 실제 federation 의 multi-eval wiring 은 S6b.
ux_means 축은 PR-MARGIN-FITNESS-SCALE (2026-05-30) 에서 제거 — 3축 =
dim + admire + bench.
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
    FITNESS_ADMIRE_3AX,
    FITNESS_ADMIRE_WEIGHT,
    FITNESS_BENCH_3AX,
    FITNESS_DIM_3AX,
    FITNESS_DIM_WEIGHT,
    compute_fitness,
)

# ---------------------------------------------------------------------------
# 1. Schema constants
# ---------------------------------------------------------------------------


def test_bench_dim_weights_sum_to_one() -> None:
    assert abs(sum(BENCH_DIM_WEIGHTS.values()) - 1.0) < 1e-9


def test_bench_dim_weights_exact_7_fields_2026_frontier() -> None:
    """2026-05 갱신 — 4 outdated bench (SWE/HumanEval/TAU/GAIA) 교체 후
    7 frontier bench (Claude Opus 4.5 + GPT-5 system card 공통).

    2026-05-23 F1.b — vanilla LiveCodeBench port 부재로 LiveCodeBench-Pro
    substitution (PR-SIL-5THEME C1): ``livecodebench_pass1`` →
    ``livecodebench_pro_accuracy``. metric 도 pass@1 → accuracy
    (LightCPVerifier C++ exec) 로 갱신, 도메인은 Python algorithmic →
    C++ competitive 로 shift. weight 0.15 변동 없음."""
    assert set(BENCH_DIM_WEIGHTS) == {
        "swe_bench_pro_pass",  # Scale AI SWE-bench Pro (OpenAI 2026-02 retire 후)
        "livecodebench_pro_accuracy",  # F1.b: LiveCodeBench-Pro (C++ competitive, contam-defended)
        "tau2_bench_success",  # Sierra τ²-bench (telecom domain)
        "gpqa_diamond",  # NYU PhD reasoning
        "hle_accuracy",  # Humanity's Last Exam (Nature 2026-01)
        "osworld_success",  # computer-use agent
        "mle_bench_medal",  # OpenAI MLE-bench (ML engineering)
    }


def test_3_axis_fitness_weights_sum_to_one() -> None:
    assert abs(FITNESS_DIM_3AX + FITNESS_ADMIRE_3AX + FITNESS_BENCH_3AX - 1.0) < 1e-9


def test_3_axis_dim_weight_smaller_than_2_axis() -> None:
    """bench 활성(3축) 시 dim 비중 0.70 → 0.55 으로 추가 감소."""
    assert FITNESS_DIM_3AX < FITNESS_DIM_WEIGHT


def test_swe_bench_has_highest_bench_weight() -> None:
    """SWE-bench 가 코드 도메인 핵심 — 가장 높은 가중치."""
    max_field = max(BENCH_DIM_WEIGHTS, key=lambda k: BENCH_DIM_WEIGHTS[k])
    assert max_field == "swe_bench_pro_pass"


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
    partial = {"swe_bench_pro_pass": 1.0}
    # 다른 6 field 모두 누락 → 각 weight × 0.5
    expected = BENCH_DIM_WEIGHTS["swe_bench_pro_pass"] * 1.0
    for field, weight in BENCH_DIM_WEIGHTS.items():
        if field != "swe_bench_pro_pass":
            expected += weight * 0.5
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
    assert validate_bench_schema({"swe_bench_pro_pass": 0.5}) is True


def test_validate_rejects_unknown_field() -> None:
    assert validate_bench_schema({"unknown_bench": 0.5}) is False


def test_validate_rejects_out_of_range() -> None:
    assert validate_bench_schema({"swe_bench_pro_pass": 1.5}) is False


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
            bench_means={"swe_bench_pro_pass": 0.5},
            baseline_bench_means={"swe_bench_pro_pass": 0.5},
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
            baseline_bench_means={"swe_bench_pro_pass": 0.5},
        )
        is None
    )


def test_detects_alignment_only_fooling() -> None:
    """Petri promote (dim 개선) + bench regress → fooling 의심."""
    conflict = detect_cross_validation_conflict(
        dim_means={"broken_tool_use": 2.0},  # better than baseline 5.0 (lower)
        baseline_dim_means={"broken_tool_use": 5.0},
        bench_means={"swe_bench_pro_pass": 0.3},
        baseline_bench_means={"swe_bench_pro_pass": 0.6},  # bench regressed
        critical_dims=("broken_tool_use",),
    )
    assert conflict == "alignment_only_fooling"


def test_detects_capability_at_alignment_cost() -> None:
    """bench promote + Petri critical regress → 안전성 손상."""
    conflict = detect_cross_validation_conflict(
        dim_means={"broken_tool_use": 8.0},  # worse than baseline 3.0
        baseline_dim_means={"broken_tool_use": 3.0},
        bench_means={"swe_bench_pro_pass": 0.8},
        baseline_bench_means={"swe_bench_pro_pass": 0.5},  # bench improved
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
            bench_means={"swe_bench_pro_pass": 0.7},
            baseline_bench_means={"swe_bench_pro_pass": 0.5},
            critical_dims=("broken_tool_use",),
        )
        is None
    )


# ---------------------------------------------------------------------------
# 5. collect_bench_means_from_inspect_ai — S6b production wiring
# (PR-SIL-5THEME C2, 2026-05-23 — placeholder return None 에서 BenchProvenance
# dataclass + 7-bench dispatch + A1 graceful-skip 로 교체됨)
# ---------------------------------------------------------------------------


def test_collect_returns_bench_provenance_dataclass() -> None:
    """S6b production wiring — placeholder 였던 ``collect_bench_means_from_inspect_ai``
    가 ``BenchProvenance`` dataclass 반환으로 교체. nominal smoke 환경
    (Docker / inspect-evals / inspect-harbor 부재 + ``GEODE_BENCH_S6B_LIVE``
    unset) 에선 모든 bench 가 ``missing_benches`` 에 등록."""
    from autoresearch.bench_means import BenchProvenance

    result = collect_bench_means_from_inspect_ai(target_model="gpt-5")
    assert isinstance(result, BenchProvenance)
    # 7-field universe 가 어딘가에 등장해야 함 (means 든 missing 이든)
    accounted = set(result.bench_means) | set(result.missing_benches)
    from autoresearch.bench_means import BENCH_DIM_WEIGHTS

    assert accounted == set(BENCH_DIM_WEIGHTS)
    # rubric_version 은 항상 present (cohort tag)
    assert result.rubric_version


# ---------------------------------------------------------------------------
# 6. compute_fitness 3축 다축화 (ux-removed 2026-05-30)
# ---------------------------------------------------------------------------


def test_compute_fitness_all_none_dim_only() -> None:
    """admire + bench 둘 다 None → dim-only fallback (backwards compat)."""
    dim_means = {"broken_tool_use": 5.0}
    f_none = compute_fitness(dim_means)
    f_explicit = compute_fitness(dim_means, admire_means=None, bench_means=None)
    assert f_none == f_explicit


def test_compute_fitness_admire_active_2_axis() -> None:
    """admire 활성 (bench 없음) → S2 의 2축 (0.70/0.30)."""
    dim_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    f = compute_fitness(dim_means, admire_means=admire)
    base = compute_fitness(dim_means)
    expected = FITNESS_DIM_WEIGHT * base + FITNESS_ADMIRE_WEIGHT * 1.0
    assert abs(f - expected) < 1e-9


def test_compute_fitness_bench_active_3_axis() -> None:
    """bench 활성 → S6 의 3축 재배분 (0.55/0.20/0.25)."""
    dim_means = {"broken_tool_use": 5.0}
    admire = {"pairwise_win_rate": 1.0, "human_calibration_corr": 1.0}
    bench = dict.fromkeys(BENCH_DIM_WEIGHTS, 1.0)
    # baseline_means 없으면 cross-validation 비교 skip (conflict=None)
    f = compute_fitness(dim_means, admire_means=admire, bench_means=bench)
    base = compute_fitness(dim_means)
    expected = FITNESS_DIM_3AX * base + FITNESS_ADMIRE_3AX * 1.0 + FITNESS_BENCH_3AX * 1.0
    assert abs(f - expected) < 1e-9


def test_compute_fitness_bench_only_with_neutral_admire() -> None:
    """bench 만 주어지면 admire 는 neutral 0.5 → 3축 활성."""
    dim_means = {"broken_tool_use": 5.0}
    bench = dict.fromkeys(BENCH_DIM_WEIGHTS, 1.0)
    f = compute_fitness(dim_means, bench_means=bench)
    base = compute_fitness(dim_means)
    expected = (
        FITNESS_DIM_3AX * base
        + FITNESS_ADMIRE_3AX * 0.5  # neutral
        + FITNESS_BENCH_3AX * 1.0
    )
    assert abs(f - expected) < 1e-9


# ---------------------------------------------------------------------------
# 7. Cross-validation gate in compute_fitness — strict reject
# ---------------------------------------------------------------------------


def test_cross_validation_gate_blocks_alignment_only_fooling() -> None:
    """Petri promote + bench regress 면 compute_fitness 가 0.0 strict reject."""
    dim_means = {"broken_tool_use": 2.0}  # better than baseline (lower)
    baseline_means = {"broken_tool_use": 5.0}
    bench = {"swe_bench_pro_pass": 0.3}  # bench regressed
    baseline_bench = {"swe_bench_pro_pass": 0.6}
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
    bench = {"swe_bench_pro_pass": 0.8}  # bench improved
    baseline_bench = {"swe_bench_pro_pass": 0.5}
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
    bench = {"swe_bench_pro_pass": 0.7}  # also improved
    baseline_bench = {"swe_bench_pro_pass": 0.5}
    f = compute_fitness(
        dim_means,
        baseline_means=baseline_means,
        bench_means=bench,
        baseline_bench_means=baseline_bench,
    )
    assert f > 0.0, "둘 다 개선이면 strict reject 발화 안 함"
