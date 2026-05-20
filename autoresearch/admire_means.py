"""``admire_means`` fitness 축 — ADR-012 S2.

S1 의 ``ux_means`` (행동 metric) 옆에 추가되는 **체감 품질** 양의 압력
축. ``plugins/seed_generation/agents/ranker.py`` 의 ELO + 3-voter
cross-provider panel 인프라를 정책 mutation 평가 채널로 확장 — mutation
의 before/after 응답을 동일 panel 이 pairwise 평가, win-rate 를 fitness
신호로 변환.

**Schema** (2 field, 0.0-1.0):

.. code-block:: python

    {
      "pairwise_win_rate":      0.65,   # mutation 적용 후 응답이 이긴 비율 (3-voter panel)
      "human_calibration_corr": 0.85,   # LLM-judge 점수 와 human L4 라벨 의 상관계수
                                         # (분기 단위 50-100 sample 로 측정, Goodhart 방어)
    }

``human_calibration_corr`` 가 0.7 미만이면 LLM-judge 가 human 기준에서
벗어나는 신호 — Goodhart fooling 위험. ``compute_admire_aggregate`` 가
이 축으로 win-rate 를 가중치 dampen 하는 방식으로 처리.

**ADR-012 §Decision.2 의 fitness 3축 다축화**:

- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.4
- ``ux_means`` (행동 4-field, 양의 압력, S1 신설) — 가중치 0.3
- ``admire_means`` (체감 2-field, 양의 압력, 이 모듈) — 가중치 0.3

S2 (이 PR) 는 **schema + math + ranker hook interface** 만 신설. 실제
ranker.py 의 ELO + voter panel 호출 wiring 은 S2b (별도 PR) —
``collect_admire_means_from_ranker`` 가 placeholder 로 ``None`` 반환,
``compute_fitness`` 의 3축 다축화는 즉시 가동.

**Goodhart 방어 (ADR-012 의 Risks 표)**:
1. judge model 의 주기적 교체 — ``required_diversity_providers`` 규약
   재사용 (PR-COSCI-1)
2. ranker.py 의 3-voter cross-provider panel — single-judge sycophancy
   회피
3. ``human_calibration_corr`` < 0.7 시 win-rate dampening
4. 분기 human L4 batch refresh (S2b 의 calibration pipeline)
"""

from __future__ import annotations

from typing import Any

# Admire field 별 가중치 — 합 1.0. pairwise_win_rate 가 주 신호,
# human_calibration_corr 는 dampening factor 역할.
ADMIRE_DIM_WEIGHTS: dict[str, float] = {
    "pairwise_win_rate": 0.70,
    "human_calibration_corr": 0.30,
}

assert abs(sum(ADMIRE_DIM_WEIGHTS.values()) - 1.0) < 1e-9, "ADMIRE_DIM_WEIGHTS must sum to 1.0"

# Calibration threshold — human_calibration_corr 가 이 값 미만이면 judge
# 가 human 기준에서 drift — pairwise_win_rate 를 dampen.
CALIBRATION_THRESHOLD: float = 0.7


def compute_admire_aggregate(admire_means: dict[str, float] | None) -> float:
    """2-field weighted sum with calibration dampening → 0-1 scalar.

    ``None`` → 0.5 neutral (S1 의 ``ux_means`` 와 동일 패턴 — no-op signal).

    Calibration dampening — ``human_calibration_corr`` < ``CALIBRATION_THRESHOLD``
    (0.7) 이면 LLM-judge 의 ``pairwise_win_rate`` 신호가 human 기준에서
    drift. dampened weight = ``corr / threshold`` (0-1 으로 clamp) 로
    win-rate 의 영향 감쇠. Goodhart fooling 방어의 핵심 메커니즘.
    """
    if admire_means is None:
        return 0.5
    win_rate = max(0.0, min(1.0, admire_means.get("pairwise_win_rate", 0.5)))
    corr = max(0.0, min(1.0, admire_means.get("human_calibration_corr", CALIBRATION_THRESHOLD)))

    # Dampening factor — corr ≥ threshold 이면 1.0 (full weight), 미만이면
    # 비례 감쇠. corr=0 이면 dampening=0 → win_rate 신호가 거의 무효.
    dampening = min(1.0, corr / CALIBRATION_THRESHOLD) if CALIBRATION_THRESHOLD > 0 else 1.0

    return (
        ADMIRE_DIM_WEIGHTS["pairwise_win_rate"] * win_rate * dampening
        + ADMIRE_DIM_WEIGHTS["human_calibration_corr"] * corr
    )


def validate_admire_schema(admire_means: Any) -> bool:
    """Validate ``admire_means`` schema — dict[str, float] in 0-1, 알려진
    field 만. ``None`` 도 valid (no-op signal)."""
    if admire_means is None:
        return True
    if not isinstance(admire_means, dict):
        return False
    known_fields = set(ADMIRE_DIM_WEIGHTS)
    for key, value in admire_means.items():
        if key not in known_fields:
            return False
        if not isinstance(value, int | float):
            return False
        if not (0.0 <= float(value) <= 1.0):
            return False
    return True


def collect_admire_means_from_ranker(
    *,
    _placeholder: bool = True,
) -> dict[str, float] | None:
    """Collect ``admire_means`` from ``plugins/seed_generation/agents/ranker.py``
    의 ELO + 3-voter panel.

    S2 (이 PR) 는 schema + math + hook interface 만 신설. 실제 ranker
    호출 wiring 은 S2b (별도 PR) — mutation 의 before/after 응답을
    ``Ranker._play_match`` 와 같은 패턴으로 panel 에 던지고 win-rate 계산.

    이 함수는 placeholder — S2b 전까지는 ``None`` 반환 (compute_fitness
    가 dim+ux fallback 으로 작동). S2b 머지 후:

    1. mutation 의 before/after 응답 hydrate (M4.0 의 ``eval_response_recorded``)
    2. ``Ranker._build_voter_tasks`` 와 같은 패턴으로 3-voter panel 호출
    3. ELO update (``_play_match`` 의 K-factor=32 같은 패턴)
    4. pairwise_win_rate = wins / (wins + losses)
    5. human_calibration_corr = 분기 단위 L4 batch 와의 Pearson 상관계수

    Args:
        _placeholder: S2b 전까지 ``None`` 반환 강제. test 에서 override 가능.
    """
    if _placeholder:
        return None
    return None  # pragma: no cover — S2b wiring placeholder


__all__ = [
    "ADMIRE_DIM_WEIGHTS",
    "CALIBRATION_THRESHOLD",
    "collect_admire_means_from_ranker",
    "compute_admire_aggregate",
    "validate_admire_schema",
]
