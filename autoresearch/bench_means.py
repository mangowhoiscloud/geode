"""``bench_means`` fitness 축 — ADR-012 S6 (Path C inspect_ai federation).

S1 의 ``ux_means`` (행동) + S2 의 ``admire_means`` (체감) 옆에 추가되는
**capability** 양의 압력 축. Petri 가 alignment evaluation (안 망가지기)
인 반면, bench 는 real task completion (제대로 함) 의 ground-truth 평가.

**2026-05-21 갱신 — 4 outdated bench 교체 (4 → 7 frontier)**:

원본 S6 (2026-05-21 오전, #1413) 의 4 bench 는 모두 saturated / OpenAI
retire / contamination 으로 outdated. 2026 frontier (Claude Opus 4.5
system card + GPT-5 system card 공통 채택) 으로 7-field schema 갱신.

- SWE-bench → **SWE-bench Pro** (Scale AI): OpenAI 2026-02-23 공식
  retire, saturated + contaminated.
- HumanEval → **제거 + LiveCodeBench**: Top-4 93-95% saturated,
  contamination-free 신규.
- TAU-bench → **τ²-bench** (Sierra 2025): telecom domain 0.993
  saturated, dual-control 후속.
- GAIA → **HLE + OSWorld 분할**: DeepAgent 91.69% saturated. HLE
  (Nature 2026-01) + OSWorld (computer-use) 로 도메인 분리.
- (신규) **GPQA Diamond**: Anthropic + OpenAI 카드 공통 PhD reasoning.
- (신규) **MLE-bench**: self-improving loop 도메인 정합 (ML engineering).

**inspect_ai federation** (Path C, ADR-012 §S6 결정 — **S6b 에서 wiring 예정**):
- Petri 의 alignment scenario + frontier capability bench (7-field) 가
  **같은 inspect_ai run** 안에서 federated 실행하는 설계. Anthropic
  inspect_ai framework 기반 — 단일 subprocess 통합 가능. (S6 본 PR 은
  schema + math + gate 만, 실제 federation wiring 은 S6b 별도 PR.)
- ``baseline.json`` schema 확장 (S6b 예정) — ``dim_means`` (Petri) +
  ``bench_means`` (capability) 별도 field.

**Schema** (7 field, 모두 0.0-1.0 normalized — 2026-05 갱신):

.. code-block:: python

    {
      "swe_bench_pro_pass":   0.45,  # Scale AI SWE-bench Pro pass@1
      "livecodebench_pass1":  0.70,  # LiveCodeBench contam-free
      "tau2_bench_success":   0.85,  # Sierra τ²-bench (telecom)
      "gpqa_diamond":         0.60,  # GPQA Diamond PhD reasoning
      "hle_accuracy":         0.30,  # Humanity's Last Exam
      "osworld_success":      0.35,  # OSWorld computer-use
      "mle_bench_medal":      0.40,  # OpenAI MLE-bench medal rate
    }

**Cross-validation gate** (Goodhart 양방향 방어):
- Petri promote (dim 개선) + bench regress → fooling 의심
- bench promote + Petri critical regress → capability gain at alignment cost
- 두 conflict 모두 ``compute_fitness`` 의 strict-reject (0.0) 발화

**ADR-012 §Decision.2 의 fitness 4축 다축화** (S6 후):
- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.30
- ``ux_means`` (행동 4-field, S1) — 가중치 0.25
- ``admire_means`` (체감 2-field, S2) — 가중치 0.20
- ``bench_means`` (capability 7-field, S6 — 2026-05 갱신) — 가중치 0.25

bench 비중이 0.25 — ground-truth 평가라 dim 과 동등한 권위. dim 비중이
0.40 → 0.30 으로 추가 감소 (양의 압력 면적이 7/23 = 30.4% → 14/30 = 46.7%
로 확장 — 4 outdated bench → 7 frontier bench 교체).

S6 (이 갱신 PR) 은 **schema + math + cross-validation gate** + **2026
frontier 갱신**. 실제 inspect_ai federation 의 multi-eval wiring 은 S6b
(별도 PR).

**Frontier sources** (2026-05):

- OpenAI SWE-bench retire 공지: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- Scale AI SWE-bench Pro: https://labs.scale.com/leaderboard/swe_bench_pro_public
- Sierra τ²-bench: https://sierra.ai/resources/research/tau-squared-bench
- Humanity's Last Exam (Nature 2026-01): https://agi.safe.ai/
- LiveCodeBench (contam-free Python coding)
- GPQA Diamond (NYU 2024)
- OSWorld (2024 frontier computer-use agent benchmark)
- MLE-bench (OpenAI 2024 ML engineering)
- Claude Opus 4.5 system card: https://www.anthropic.com/claude-opus-4-5-system-card
- GPT-5 system card: https://cdn.openai.com/gpt-5-system-card.pdf
"""

from __future__ import annotations

from typing import Any

# Bench field 별 가중치 — 합 1.0. 2026-05 갱신:
# - SWE-bench Pro (Scale AI, contam-free real PR) 가 frontier 코딩 표준 — 0.25
# - LiveCodeBench (algo, contam-free) — 0.15
# - τ²-bench (Sierra dual-control + telecom) — 0.20
# - GPQA Diamond (PhD reasoning) — 0.15
# - HLE (Humanity's Last Exam, frontier ceiling) — 0.10
# - OSWorld (computer-use agent) — 0.10
# - MLE-bench (ML engineering, self-improving 도메인 정합) — 0.05
BENCH_DIM_WEIGHTS: dict[str, float] = {
    "swe_bench_pro_pass": 0.25,
    "livecodebench_pass1": 0.15,
    "tau2_bench_success": 0.20,
    "gpqa_diamond": 0.15,
    "hle_accuracy": 0.10,
    "osworld_success": 0.10,
    "mle_bench_medal": 0.05,
}

assert abs(sum(BENCH_DIM_WEIGHTS.values()) - 1.0) < 1e-9, "BENCH_DIM_WEIGHTS must sum to 1.0"


def compute_bench_aggregate(bench_means: dict[str, float] | None) -> float:
    """7-field weighted sum → 0-1 scalar. ``None`` → 0.5 (neutral, S1/S2 패턴)."""
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

    1. **Petri promote + bench regress** ("alignment-only fooling")
    2. **bench promote + Petri critical regress** ("capability at alignment cost")

    Returns:
        conflict 종류의 문자열 또는 ``None`` (conflict 없음).
    """
    if baseline_dim_means is None or baseline_bench_means is None:
        return None
    if bench_means is None:
        return None

    bench_now = compute_bench_aggregate(bench_means)
    bench_base = compute_bench_aggregate(baseline_bench_means)
    bench_improved = bench_now > bench_base
    bench_regressed = bench_now < bench_base

    dim_aggregate_now = sum(dim_means.values()) / max(1, len(dim_means))
    dim_aggregate_base = sum(baseline_dim_means.values()) / max(1, len(baseline_dim_means))
    petri_improved = dim_aggregate_now < dim_aggregate_base
    critical_regressed = any(
        dim_means.get(dim, 0.0) > baseline_dim_means.get(dim, 0.0) + critical_margin
        for dim in critical_dims
    )

    if petri_improved and bench_regressed:
        return "alignment_only_fooling"

    if bench_improved and critical_regressed:
        return "capability_at_alignment_cost"

    return None


def collect_bench_means_from_inspect_ai(*, _placeholder: bool = True) -> dict[str, float] | None:
    """Collect ``bench_means`` from inspect_ai federation run.

    S6 (이 PR) 는 schema + math + cross-validation gate 만 신설. 실제
    inspect_ai 의 multi-eval API 호출 wiring 은 S6b (별도 PR) — Petri
    scenario set + 7 bench task set 을 한 inspect_ai run 안에서 federated
    실행, 각각의 결과를 별도 field 로 수집.

    2026-05 갱신 후 7 bench 모두 inspect_ai 기반 또는 inspect_ai-compatible
    (SWE-bench Pro / LiveCodeBench / τ²-bench / GPQA / HLE / OSWorld /
    MLE-bench).
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
