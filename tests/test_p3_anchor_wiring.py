"""PR-11 P3.1 (2026-05-25) — anchor confidence multiplier wiring invariants.

Scope: ``compute_fitness`` 의 anchor_means + anchor_confidence_mode 인자가
실제 fitness scalar 에 multiplier 를 적용하는지. helper 자체의 normalization
math 는 ``tests/core/self_improving_loop/test_p3_anchor_spct.py`` 가 cover —
본 파일은 train.py compute_fitness 의 wiring 만 검증.

Wiring contract:
- mode=False (default) → multiplier=1.0 → fitness 변동 0 (legacy 동일)
- mode=True + anchor_means=None/empty → multiplier=1.0 (graceful)
- mode=True + admirable=10/disappointing=1/needs_attention=1 → multiplier=1.0 (best)
- mode=True + admirable=1/disappointing=10/needs_attention=10 → multiplier=0.7 (worst)
- mode=True + critical regression → return 0.0 (multiplier 무관, strict reject)
- mode=True 가 4 dim_part return branch (dim-only / 2-axis / 3-axis / 4-axis)
  모두에 일관 적용
"""

from __future__ import annotations

import pytest
from autoresearch.train import (
    ANCHOR_DIMS,
    AUXILIARY_DIMS,
    CRITICAL_DIMS,
    DIM_WEIGHTS,
    compute_fitness,
)

# ---------------------------------------------------------------------------
# 1. ANCHOR_DIMS constant
# ---------------------------------------------------------------------------


def test_anchor_dims_constant_matches_helper() -> None:
    """ANCHOR_DIMS 가 anchor_confidence helper 의 dim set 과 일치."""
    from core.self_improving_loop.anchor_confidence import (
        ANCHOR_DIMS_NEGATIVE,
        ANCHOR_DIMS_POSITIVE,
    )

    assert set(ANCHOR_DIMS) == set(ANCHOR_DIMS_POSITIVE) | set(ANCHOR_DIMS_NEGATIVE)


def test_anchor_dims_excluded_from_dim_weights() -> None:
    """anchor 3 는 fitness weight=0 (DIM_WEIGHTS 미포함). multiplier 가
    유일한 anchor 신호 경로."""
    for d in ANCHOR_DIMS:
        assert d not in DIM_WEIGHTS


# ---------------------------------------------------------------------------
# 2. mode=False (legacy backward compat)
# ---------------------------------------------------------------------------


def _make_neutral_dim_means() -> dict[str, float]:
    """모든 critical+auxiliary 1.0 (best score, no penalty)."""
    return dict.fromkeys((*CRITICAL_DIMS, *AUXILIARY_DIMS), 1.0)


def test_mode_off_default_legacy_fitness() -> None:
    """mode=False (default) 일 때 anchor_means 무시. PR-5 fitness 와 동일."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_with_anchor = compute_fitness(
        dim_means,
        anchor_means={"admirable": 10.0, "disappointing": 1.0, "needs_attention": 1.0},
        anchor_confidence_mode=False,
    )
    assert f_legacy == f_with_anchor


def test_mode_off_explicit_false_legacy_fitness() -> None:
    """anchor_means 가 explicit dict 라도 mode=False 면 적용 X."""
    dim_means = _make_neutral_dim_means()
    f_baseline = compute_fitness(dim_means)
    f_anchor_off = compute_fitness(
        dim_means,
        anchor_means={"admirable": 1.0, "disappointing": 10.0, "needs_attention": 10.0},
        anchor_confidence_mode=False,
    )
    assert f_baseline == f_anchor_off


# ---------------------------------------------------------------------------
# 3. mode=True with graceful empty anchor_means
# ---------------------------------------------------------------------------


def test_mode_on_anchor_means_none_graceful() -> None:
    """mode=True 라도 anchor_means=None 이면 multiplier=1.0 → legacy."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_mode_no_anchor = compute_fitness(
        dim_means,
        anchor_means=None,
        anchor_confidence_mode=True,
    )
    assert f_legacy == f_mode_no_anchor


def test_mode_on_anchor_means_empty_graceful() -> None:
    """mode=True + 빈 dict → multiplier=1.0 (anchor 측정 부재 graceful)."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_mode_empty = compute_fitness(
        dim_means,
        anchor_means={},
        anchor_confidence_mode=True,
    )
    assert f_legacy == f_mode_empty


# ---------------------------------------------------------------------------
# 4. mode=True best-case multiplier=1.0
# ---------------------------------------------------------------------------


def test_mode_on_best_anchor_multiplier_max() -> None:
    """admirable=10 / disappointing=1 / needs_attention=1 → multiplier=1.0
    (legacy fitness 동일). best-case 의 backward compat 유지."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_best = compute_fitness(
        dim_means,
        anchor_means={"admirable": 10.0, "disappointing": 1.0, "needs_attention": 1.0},
        anchor_confidence_mode=True,
    )
    assert f_best == pytest.approx(f_legacy, abs=1e-9)


# ---------------------------------------------------------------------------
# 5. mode=True worst-case multiplier=0.7
# ---------------------------------------------------------------------------


def test_mode_on_worst_anchor_multiplier_min() -> None:
    """admirable=1 / disappointing=10 / needs_attention=10 → multiplier=0.7
    (anchor 가 worst → fitness 30% 축소)."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_worst = compute_fitness(
        dim_means,
        anchor_means={"admirable": 1.0, "disappointing": 10.0, "needs_attention": 10.0},
        anchor_confidence_mode=True,
    )
    assert f_worst == pytest.approx(f_legacy * 0.7, rel=1e-6)


def test_mode_on_mid_anchor_multiplier_mid() -> None:
    """admirable=5.5 / disappointing=5.5 / needs_attention=5.5 → normalized 0.5
    → multiplier = 0.7 + 0.3×0.5 = 0.85."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_mid = compute_fitness(
        dim_means,
        anchor_means={"admirable": 5.5, "disappointing": 5.5, "needs_attention": 5.5},
        anchor_confidence_mode=True,
    )
    assert f_mid == pytest.approx(f_legacy * 0.85, rel=1e-6)


# ---------------------------------------------------------------------------
# 6. Critical gate strict-reject overrides multiplier
# ---------------------------------------------------------------------------


def test_critical_regression_returns_zero_regardless_of_anchor() -> None:
    """critical gate (return 0.0) 는 multiplier 무관 strict reject.
    anchor 가 best 라도 fitness=0.0 유지."""
    dim_means = dict.fromkeys((*CRITICAL_DIMS, *AUXILIARY_DIMS), 1.0)
    # Worse on a critical dim (higher = worse for 'cooperation_with_harmful_sysprompt')
    dim_means[CRITICAL_DIMS[0]] = 5.0
    baseline = dict.fromkeys(CRITICAL_DIMS, 1.0)
    f_critical_anchor_best = compute_fitness(
        dim_means,
        baseline_means=baseline,
        anchor_means={"admirable": 10.0, "disappointing": 1.0, "needs_attention": 1.0},
        anchor_confidence_mode=True,
    )
    assert f_critical_anchor_best == 0.0


# ---------------------------------------------------------------------------
# 7. Multiplier applies to all 4 return branches
# ---------------------------------------------------------------------------


def test_multiplier_applies_to_dim_only_branch() -> None:
    """dim-only branch (ux_means/admire_means/bench_means 모두 None)."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    f_worst = compute_fitness(
        dim_means,
        anchor_means={"admirable": 1.0, "disappointing": 10.0, "needs_attention": 10.0},
        anchor_confidence_mode=True,
    )
    assert f_worst == pytest.approx(f_legacy * 0.7, rel=1e-6)


def test_multiplier_applies_to_2_axis_branch() -> None:
    """ux only — UX_FITNESS_DIM_WEIGHT * dim + UX_FITNESS_UX_WEIGHT * ux."""
    dim_means = _make_neutral_dim_means()
    ux = {
        "success_rate": 0.5,
        "token_cost_norm": 0.5,
        "revert_ratio_norm": 0.5,
        "latency_norm": 0.5,
    }
    f_legacy = compute_fitness(dim_means, ux_means=ux)
    f_worst = compute_fitness(
        dim_means,
        ux_means=ux,
        anchor_means={"admirable": 1.0, "disappointing": 10.0, "needs_attention": 10.0},
        anchor_confidence_mode=True,
    )
    assert f_worst == pytest.approx(f_legacy * 0.7, rel=1e-6)


def test_multiplier_applies_to_3_axis_branch() -> None:
    """ux + admire — 3 축 재배분."""
    dim_means = _make_neutral_dim_means()
    ux = {
        "success_rate": 0.5,
        "token_cost_norm": 0.5,
        "revert_ratio_norm": 0.5,
        "latency_norm": 0.5,
    }
    admire = {"pairwise_win_rate": 0.5, "human_calibration_corr": 0.5}
    f_legacy = compute_fitness(dim_means, ux_means=ux, admire_means=admire)
    f_worst = compute_fitness(
        dim_means,
        ux_means=ux,
        admire_means=admire,
        anchor_means={"admirable": 1.0, "disappointing": 10.0, "needs_attention": 10.0},
        anchor_confidence_mode=True,
    )
    assert f_worst == pytest.approx(f_legacy * 0.7, rel=1e-6)


def test_multiplier_applies_to_4_axis_branch() -> None:
    """bench 활성 — 4 축 재배분."""
    dim_means = _make_neutral_dim_means()
    ux = {
        "success_rate": 0.5,
        "token_cost_norm": 0.5,
        "revert_ratio_norm": 0.5,
        "latency_norm": 0.5,
    }
    admire = {"pairwise_win_rate": 0.5, "human_calibration_corr": 0.5}
    bench = {"swe_bench": 0.5, "tau_bench": 0.5}
    f_legacy = compute_fitness(dim_means, ux_means=ux, admire_means=admire, bench_means=bench)
    f_worst = compute_fitness(
        dim_means,
        ux_means=ux,
        admire_means=admire,
        bench_means=bench,
        anchor_means={"admirable": 1.0, "disappointing": 10.0, "needs_attention": 10.0},
        anchor_confidence_mode=True,
    )
    assert f_worst == pytest.approx(f_legacy * 0.7, rel=1e-6)


# ---------------------------------------------------------------------------
# 8. Subset of anchor dims also works (partial measurement graceful)
# ---------------------------------------------------------------------------


def test_partial_anchor_means_subset() -> None:
    """admirable only — helper 가 available dim 만 사용. disappointing/
    needs_attention 부재 시 admirable 단독 normalized → multiplier."""
    dim_means = _make_neutral_dim_means()
    f_legacy = compute_fitness(dim_means)
    # admirable=10 → normalized=1.0 → multiplier = 0.7 + 0.3*1.0 = 1.0
    f_partial = compute_fitness(
        dim_means,
        anchor_means={"admirable": 10.0},
        anchor_confidence_mode=True,
    )
    assert f_partial == pytest.approx(f_legacy, rel=1e-6)


# ---------------------------------------------------------------------------
# 9. _should_promote anchor wiring (Codex MCP catch — promote 결정도 multiplier)
# ---------------------------------------------------------------------------


def test_should_promote_mode_off_legacy_behavior() -> None:
    """mode=False (default) — _should_promote 내부 3 compute_fitness 호출이
    anchor multiplier 적용 안 함. PR-11 이전 동작 유지."""
    from autoresearch.train import _should_promote

    current = _make_neutral_dim_means()
    current["admirable"] = 1.0  # bad anchor — but mode off 라 무영향
    current["disappointing"] = 10.0
    baseline = _make_neutral_dim_means()
    baseline["admirable"] = 10.0  # good anchor — mode off 라 무영향
    # current 가 baseline 보다 raw fitness 같음 (anchor 외 dim 동일) →
    # mode off 라 promote 결정도 동일
    ok, _ = _should_promote(
        current,
        dict.fromkeys(current, 0.0),
        baseline,
        dict.fromkeys(baseline, 0.0),
        anchor_confidence_mode=False,
    )
    # margin floor 0.05 + stderr 0 → current_raw == prior_raw 인데 promotion
    # 은 strict > floor 이어야 → False (legacy 동작)
    assert ok is False


def test_should_promote_mode_on_anchor_breaks_tie() -> None:
    """mode=True — current anchor 가 baseline 보다 좋으면 multiplier 차이로
    promote, 나쁘면 reject. promote 결정도 multiplier-adjusted fitness 로 비교."""
    from autoresearch.train import _should_promote

    current = _make_neutral_dim_means()
    current["admirable"] = 10.0  # best anchor
    current["disappointing"] = 1.0
    current["needs_attention"] = 1.0
    baseline = _make_neutral_dim_means()
    baseline["admirable"] = 1.0  # worst anchor
    baseline["disappointing"] = 10.0
    baseline["needs_attention"] = 10.0
    # raw dim 동일, baseline 의 multiplier 만 0.7 → current_raw > prior_raw*0.7
    # 차이가 0.05 floor 초과해야 promote True
    ok, reason = _should_promote(
        current,
        dict.fromkeys(current, 0.0),
        baseline,
        dict.fromkeys(baseline, 0.0),
        anchor_confidence_mode=True,
    )
    assert ok is True, f"expected promote=True, got reason={reason!r}"


def test_should_promote_mode_on_baseline_better_anchor_blocks() -> None:
    """역방향 — baseline 이 anchor 좋고 current 가 anchor 나쁘면 mode=True
    에서 multiplier 차이로 reject. mode=False 에선 tie 라 reject (legacy)."""
    from autoresearch.train import _should_promote

    current = _make_neutral_dim_means()
    current["admirable"] = 1.0  # worst anchor
    current["disappointing"] = 10.0
    current["needs_attention"] = 10.0
    baseline = _make_neutral_dim_means()
    baseline["admirable"] = 10.0  # best anchor
    baseline["disappointing"] = 1.0
    baseline["needs_attention"] = 1.0
    ok, _ = _should_promote(
        current,
        dict.fromkeys(current, 0.0),
        baseline,
        dict.fromkeys(baseline, 0.0),
        anchor_confidence_mode=True,
    )
    # current_raw*0.7 < prior_raw*1.0 → reject (multiplier 차이로 강하게 reject)
    assert ok is False


def test_should_promote_gated_critical_anchor_independent() -> None:
    """critical regression 시 gated fitness=0.0 → multiplier 무관 reject.
    anchor best 라도 strict-reject."""
    from autoresearch.train import _should_promote

    baseline = _make_neutral_dim_means()
    current = _make_neutral_dim_means()
    current[CRITICAL_DIMS[0]] = 5.0  # critical regression
    current["admirable"] = 10.0  # best anchor (irrelevant for strict reject)
    ok, reason = _should_promote(
        current,
        dict.fromkeys(current, 0.0),
        baseline,
        dict.fromkeys(baseline, 0.0),
        anchor_confidence_mode=True,
    )
    assert ok is False
    assert "critical" in reason.lower() or "regression" in reason.lower()
