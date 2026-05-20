"""``bench_means`` fitness 축 — ADR-012 S6 (Path C inspect_ai federation).

S1 의 ``ux_means`` (행동) + S2 의 ``admire_means`` (체감) 옆에 추가되는
**capability** 양의 압력 축. Petri 가 alignment evaluation (안 망가지기)
인 반면, bench 는 real task completion (제대로 함) 의 ground-truth 평가.

**inspect_ai federation** (Path C, ADR-012 §S6 결정 — **S6b 에서 wiring 예정**):
- Petri 의 alignment scenario + frontier capability bench (SWE-bench /
  TAU-bench / HumanEval / GAIA) 가 **같은 inspect_ai run** 안에서 federated
  실행하는 설계. 두 평가 모두 Anthropic 의 inspect_ai framework 기반 →
  단일 subprocess 통합 가능. (S6 본 PR 은 schema + math + gate 만, 실제
  federation wiring 은 S6b 별도 PR.)
- ``baseline.json`` schema 확장 (S6b 예정) — ``dim_means`` (Petri) +
  ``bench_means`` (capability) 별도 field. 현재 S6 는 ``compute_fitness``
  의 ``bench_means`` / ``baseline_bench_means`` 인자 까지만 신설하고,
  ``_load_baseline`` / ``_write_baseline`` / ``main()`` 의 인자 전달
  wiring 은 S6b 에서 추가.

**Schema** (4 field, 0.0-1.0 normalized):

.. code-block:: python

    {
      "swe_bench_pass":    0.45,  # Stanford SWE-bench pass@1
      "tau_bench_success": 0.62,  # Anthropic TAU-bench task success
      "humaneval_pass1":   0.85,  # OpenAI HumanEval pass@1
      "gaia_accuracy":     0.38,  # Meta GAIA overall accuracy
    }

**Cross-validation gate** (Goodhart 양방향 방어):
- Petri promote (dim 개선) + bench regress → fooling 의심 (alignment-only
  fooling 가능)
- bench promote + Petri critical regress → capability gain at alignment
  cost (안전성 손상)
- 두 conflict 모두 ``compute_fitness`` 의 strict-reject (0.0) 발화

**ADR-012 §Decision.2 의 fitness 4축 다축화** (S6 후):
- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.30
- ``ux_means`` (행동 4-field, S1) — 가중치 0.25
- ``admire_means`` (체감 2-field, S2) — 가중치 0.20
- ``bench_means`` (capability 4-field, S6) — 가중치 0.25

bench 비중이 0.25 — ground-truth 평가라 dim 과 동등한 권위. dim 비중이
0.40 → 0.30 으로 추가 감소 (양의 압력 면적이 7/23 = 30.4% → 11/27 = 40.7%
로 확장 — 4 bench axis 추가).

S6 (이 PR) 은 **schema + math + cross-validation gate** 만 신설. 실제
inspect_ai federation 의 multi-eval wiring 은 S6b (별도 PR).
"""

from __future__ import annotations

from typing import Any

# Bench field 별 가중치 — 합 1.0. SWE-bench 가 주력 (코드 도메인 핵심),
# TAU-bench 가 보조 (tool-use 정교화), HumanEval/GAIA 가 보충.
BENCH_DIM_WEIGHTS: dict[str, float] = {
    "swe_bench_pass": 0.40,
    "tau_bench_success": 0.30,
    "humaneval_pass1": 0.15,
    "gaia_accuracy": 0.15,
}

assert abs(sum(BENCH_DIM_WEIGHTS.values()) - 1.0) < 1e-9, "BENCH_DIM_WEIGHTS must sum to 1.0"


def compute_bench_aggregate(bench_means: dict[str, float] | None) -> float:
    """4-field weighted sum → 0-1 scalar. ``None`` → 0.5 (neutral, S1/S2 패턴)."""
    if bench_means is None:
        return 0.5
    total = 0.0
    for field, weight in BENCH_DIM_WEIGHTS.items():
        value = bench_means.get(field, 0.5)  # 누락 field neutral
        total += weight * max(0.0, min(1.0, value))
    return total


def validate_bench_schema(bench_means: Any) -> bool:
    """Validate ``bench_means`` — dict[str, float in 0-1], 알려진 field 만.
    ``None`` 도 valid (no-op signal)."""
    if bench_means is None:
        return True
    if not isinstance(bench_means, dict):
        return False
    known_fields = set(BENCH_DIM_WEIGHTS)
    for key, value in bench_means.items():
        if key not in known_fields:
            return False
        if not isinstance(value, int | float):
            return False
        if not (0.0 <= float(value) <= 1.0):
            return False
    return True


def detect_cross_validation_conflict(
    *,
    dim_means: dict[str, float],
    baseline_dim_means: dict[str, float] | None,
    bench_means: dict[str, float] | None,
    baseline_bench_means: dict[str, float] | None,
    critical_dims: tuple[str, ...] = (),
    critical_margin: float = 0.0,
) -> str | None:
    """Petri vs bench 의 cross-validation gate (Goodhart 양방향 방어).

    두 conflict 시나리오 검출:

    1. **Petri promote + bench regress** ("alignment-only fooling"):
       mutation 이 Petri dim 을 개선했지만 bench 점수는 하락 — alignment
       dim 만 마이크로-튜닝하면서 capability 를 손상시켰을 가능성.

    2. **bench promote + Petri critical regress** ("capability at alignment cost"):
       mutation 이 bench 점수를 올렸지만 critical alignment dim 이 악화 —
       capability 향상이 안전성을 손상시켰을 가능성.

    Returns:
        conflict 종류의 문자열 (e.g. "alignment_only_fooling") 또는 ``None``.
        ``None`` 이면 conflict 없음 — fitness 정상 계산.

    Args:
        dim_means: 현재 Petri dim_means
        baseline_dim_means: baseline Petri dim_means (없으면 conflict 감지 skip)
        bench_means: 현재 bench_means
        baseline_bench_means: baseline bench_means
        critical_dims: Petri critical tier 5 dim (autoresearch.train 의 CRITICAL_DIMS)
        critical_margin: critical dim 의 regress 임계값 margin

    Conflict 감지 조건:
    - Petri 개선 = aggregate dim_score 가 baseline 보다 좋음 (낮은 mean 이 좋음)
    - bench 개선 = bench_aggregate 가 baseline 보다 높음
    - 두 신호가 반대면 conflict
    """
    if baseline_dim_means is None or baseline_bench_means is None:
        return None  # baseline 없으면 비교 불가
    if bench_means is None:
        return None  # bench 신호 없으면 cross-validation 불가

    # bench 신호 변화
    bench_now = compute_bench_aggregate(bench_means)
    bench_base = compute_bench_aggregate(baseline_bench_means)
    bench_improved = bench_now > bench_base
    bench_regressed = bench_now < bench_base

    # Petri 신호 변화 — aggregate dim_means 의 mean 비교 (낮을수록 좋음)
    # critical regress 는 별도 detect
    dim_aggregate_now = sum(dim_means.values()) / max(1, len(dim_means))
    dim_aggregate_base = sum(baseline_dim_means.values()) / max(1, len(baseline_dim_means))
    petri_improved = dim_aggregate_now < dim_aggregate_base  # lower mean = better
    critical_regressed = any(
        dim_means.get(dim, 0.0) > baseline_dim_means.get(dim, 0.0) + critical_margin
        for dim in critical_dims
    )

    # Scenario 1: Petri 개선 + bench 악화
    if petri_improved and bench_regressed:
        return "alignment_only_fooling"

    # Scenario 2: bench 개선 + Petri critical 악화
    if bench_improved and critical_regressed:
        return "capability_at_alignment_cost"

    return None


def collect_bench_means_from_inspect_ai(*, _placeholder: bool = True) -> dict[str, float] | None:
    """Collect ``bench_means`` from inspect_ai federation run.

    S6 (이 PR) 는 schema + math + cross-validation gate 만 신설. 실제
    inspect_ai 의 multi-eval API 호출 wiring 은 S6b (별도 PR) — Petri
    scenario set + bench task set 을 한 inspect_ai run 안에서 federated
    실행, 각각의 결과를 별도 field 로 수집.

    이 함수는 placeholder — S6b 전까지는 ``None`` 반환 (compute_fitness
    가 4축 비활성, S2 의 3축 fallback 으로 작동).

    Args:
        _placeholder: S6b 전까지 ``None`` 반환 강제. test 에서 override 가능.
    """
    if _placeholder:
        return None
    return None  # pragma: no cover — S6b wiring placeholder


__all__ = [
    "BENCH_DIM_WEIGHTS",
    "collect_bench_means_from_inspect_ai",
    "compute_bench_aggregate",
    "detect_cross_validation_conflict",
    "validate_bench_schema",
]
