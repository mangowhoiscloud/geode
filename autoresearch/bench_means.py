"""``bench_means`` fitness 축 — ADR-012 §S6 (4축 fitness 의 4번째 축).

S1 의 ``ux_means`` (행동) + S2 의 ``admire_means`` (체감) 옆에 추가되는
**capability** 양의 압력 축. Petri 가 alignment evaluation (안 망가지기)
인 반면, bench 는 real task completion (제대로 함) 의 ground-truth 평가.

ADR-012 §S6 가 schema + math + cross-validation gate 명세, §S6b 가 이
모듈을 호출하는 production wiring 명세. 두 §섹션은 2026-05-23 amendment
(PR-SIL-5THEME C1) 으로 ADR 에 추가됐다 — 이전엔 코드만 4축을 정의하고
ADR 측은 3축 그대로였다.

**2026-05-21 → 2026-05-23 frontier 갱신 history**:

원본 S6 (2026-05-21 오전, #1413) 의 4 bench 는 모두 saturated / OpenAI
retire / contamination 으로 outdated. 2026 frontier (Claude Opus 4.5
system card + GPT-5 system card 공통 채택) 으로 7-field schema 갱신.
2026-05-23 amendment (F1.b) 에서 vanilla LiveCodeBench → LiveCodeBench-Pro
substitution 추가:

- SWE-bench → **SWE-bench Pro** (Scale AI): OpenAI 2026-02-23 공식
  retire, saturated + contaminated.
- HumanEval → **LiveCodeBench-Pro** (F1.b substitution): Top-4 93-95%
  saturated. *Vanilla LiveCodeBench* 가 contamination-defense 후속이었으나
  inspect_ai 생태계에 공식 port 부재 — frontier consensus 는
  ``livecodebench_pro`` (C++ 경쟁 프로그래밍, live-contest scrape +
  time-cutoff windowing, 2026 v2 가 ICPC WF/IOI/Chinese olympiad 추가)
  가 그 niche 를 흡수.
- TAU-bench → **τ²-bench** (Sierra 2025): telecom domain 0.993
  saturated, dual-control 후속.
- GAIA → **HLE + OSWorld 분할**: DeepAgent 91.69% saturated. HLE
  (Nature 2026-01) + OSWorld (computer-use) 로 도메인 분리.
- (신규) **GPQA Diamond**: Anthropic + OpenAI 카드 공통 PhD reasoning.
- (신규) **MLE-bench**: self-improving loop 도메인 정합 (ML engineering).

**inspect_ai federation** (ADR-012 §S6b 의 wiring 명세):
- Petri 의 alignment scenario + frontier capability bench (7-field) 가
  **같은 inspect_ai run** 안에서 또는 **인접 subprocess** 로 실행되는
  설계. Anthropic inspect_ai framework 기반. S6b 의 ``A1 graceful-skip``
  패턴 — Docker / VM 미가용 시 해당 bench 만 skip, ``missing_benches``
  에 등록.
- ``baseline.json schema_version=2`` 의 ``axes.bench_means`` field +
  ``raw`` 의 bench provenance (``bench_stderr`` / ``bench_sample_count``
  / ``bench_rubric_version``) 슬롯에 영속화.

**Schema** (7 field, 모두 0.0-1.0 normalized — 2026-05-23 F1.b 후 확정):

.. code-block:: python

    {
      "swe_bench_pro_pass":          0.45,  # Scale AI / Harbor resolve rate
      "livecodebench_pro_accuracy":  0.70,  # LCB-Pro accuracy (C++ exec)
      "tau2_bench_success":          0.85,  # Sierra τ²-bench (telecom)
      "gpqa_diamond":                0.60,  # GPQA Diamond PhD reasoning
      "hle_accuracy":                0.30,  # Humanity's Last Exam
      "osworld_success":             0.35,  # OSWorld computer-use
      "mle_bench_medal":             0.40,  # OpenAI MLE-bench medal rate
    }

**Cross-validation gate** (Goodhart 양방향 방어):
- Petri promote (dim 개선) + bench regress → ``alignment_only_fooling``
- bench promote + Petri critical regress → ``capability_at_alignment_cost``
- 두 conflict 모두 ``compute_fitness`` 의 strict-reject (0.0) 발화.

**ADR-012 §Decision.2 의 4축 fitness 가중치** (2026-05-23 amendment 후):

- ``dim_means`` (Petri 17-22 dim, 음의 압력) — 0.30
- ``ux_means`` (행동 4-field, S1) — 0.25
- ``admire_means`` (체감 2-field, S2) — 0.20
- ``bench_means`` (capability 7-field, S6) — 0.25

코드 상수 ground-truth: ``autoresearch/train.py`` 의 ``FITNESS_DIM_4AX
/ FITNESS_UX_4AX / FITNESS_ADMIRE_4AX / FITNESS_BENCH_4AX`` (sum=1.0
assert).

**Frontier sources** (2026-05):

- OpenAI SWE-bench retire 공지: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- Scale AI SWE-bench Pro: https://labs.scale.com/leaderboard/swe_bench_pro_public
- Sierra τ²-bench: https://sierra.ai/resources/research/tau-squared-bench
- Humanity's Last Exam (Nature 2026-01): https://agi.safe.ai/
- LiveCodeBench-Pro 논문 (arxiv 2506.11928): https://arxiv.org/abs/2506.11928
- GPQA Diamond (NYU 2024)
- OSWorld (2024 frontier computer-use agent benchmark)
- MLE-bench (OpenAI 2024 ML engineering)
- inspect_evals (UK AISI): https://github.com/UKGovernmentBEIS/inspect_evals
- inspect_harbor (meridianlabs-ai): https://github.com/meridianlabs-ai/inspect_harbor
- Claude Opus 4.5 system card: https://www.anthropic.com/claude-opus-4-5-system-card
- GPT-5 system card: https://cdn.openai.com/gpt-5-system-card.pdf
"""

from __future__ import annotations

from typing import Any

# Bench field 별 가중치 — 합 1.0. 2026-05-23 F1.b 갱신:
# - SWE-bench Pro (Scale AI, Harbor resolve rate) — 0.25
# - LiveCodeBench-Pro (C++ competitive, contam-defended, ICPC/IOI 2026 v2) — 0.15
#   * vanilla LiveCodeBench port 부재 → LCB-Pro substitution (F1.b 결정,
#     B1 grounding survey 결과)
# - τ²-bench (Sierra dual-control + telecom) — 0.20
# - GPQA Diamond (PhD reasoning) — 0.15
# - HLE (Humanity's Last Exam, frontier ceiling) — 0.10
# - OSWorld (computer-use agent) — 0.10
# - MLE-bench (ML engineering, self-improving 도메인 정합) — 0.05
BENCH_DIM_WEIGHTS: dict[str, float] = {
    "swe_bench_pro_pass": 0.25,
    "livecodebench_pro_accuracy": 0.15,
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
