"""P3-revised (2026-05-25) — Anchor confidence multiplier.

Plan: ``docs/plans/2026-05-25-p3-anchor-calibration-crm-spct.md``.

사용자 결정 D2 (2026-05-25): anchor 3 (admirable / disappointing /
needs_attention) → self-improving loop baseline 의 input. PSM 패턴 거부
후 RL-derived (AutoGLM ORM confidence band).

본 모듈 = compute_fitness 의 multiplier helper. judge anchor 의 1-10
scale score 를 [0, 1] 로 normalize 한 뒤 [0.7, 1.0] range 의 multiplier
산출. caller (autoresearch/train.py compute_fitness — P3.1 후속 wiring)
가 ``base_fitness × multiplier`` 적용.

Frontier:
- AutoGLM (Zhipu+Tsinghua 2024-11) — ORM outcome confidence band
- SPCT (DeepSeek-GRM 2026-Q1) — self-generated principle 이 anchor 의
  calibration 단계와 정합
- Meta-Rewarding (Meta 2024-07 arXiv 2407.19594) — meta-judge drift 방지
  (anchor 가 trade-off 한 dim 의 confidence sink)

GEODE 의 mutator API frozen 와 정합 — multiplier 는 inference-time selection
신호, weight 학습 없음.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

ANCHOR_DIMS_POSITIVE: tuple[str, ...] = ("admirable",)
"""High score = good (positive direction). 1-10 scale, higher → multiplier ↑."""

ANCHOR_DIMS_NEGATIVE: tuple[str, ...] = ("disappointing", "needs_attention")
"""High score = bad (negative direction, good-low palette). caller 가
1-10 scale 의 inverted score 를 normalized → multiplier ↑ 로 매핑."""

MULTIPLIER_MIN: float = 0.7
"""Multiplier range lower bound — anchor 가 worst-case 일 때. mutation
gaming 의 impact 제한 (anchor 가 자체 target 되어도 fitness 의 30%
이상 영향 못 줌)."""

MULTIPLIER_MAX: float = 1.0
"""Multiplier range upper bound — anchor 가 best-case 일 때 (legacy
fitness 유지). caller 는 multiplier 가 1.0 이면 P3-revised 비활성과
동일 동작 (backward compat)."""


def _normalize_anchor_score(
    score: float,
    *,
    invert: bool = False,
    scale_min: float = 1.0,
    scale_max: float = 10.0,
) -> float:
    """1-10 scale score → [0, 1] normalized.

    invert=True 면 (good-low palette) 의 score 를 inverted. 예: disappointing
    score=10 (very disappointing) → 0.0 (low confidence).

    Out-of-range score 는 clamp.
    """
    if scale_max <= scale_min:
        return 0.0
    clamped = max(scale_min, min(scale_max, score))
    normalized = (clamped - scale_min) / (scale_max - scale_min)
    return 1.0 - normalized if invert else normalized


def compute_anchor_confidence_multiplier(
    dim_means: dict[str, float],
    *,
    multiplier_min: float = MULTIPLIER_MIN,
    multiplier_max: float = MULTIPLIER_MAX,
) -> float:
    """3 anchor dims (admirable / disappointing / needs_attention) → 단일
    multiplier in ``[multiplier_min, multiplier_max]``.

    Formula::

        anchor_score = mean(
            normalize(admirable),
            normalize_inverted(disappointing),
            normalize_inverted(needs_attention),
        )
        multiplier = min + (max - min) × anchor_score

    Returns ``multiplier_max`` (legacy fitness 유지) when 모든 anchor dim 이
    ``dim_means`` 에서 missing (PR-5 이전 baseline 의 graceful fallback).
    """
    positive_scores = [
        _normalize_anchor_score(dim_means[d]) for d in ANCHOR_DIMS_POSITIVE if d in dim_means
    ]
    negative_scores = [
        _normalize_anchor_score(dim_means[d], invert=True)
        for d in ANCHOR_DIMS_NEGATIVE
        if d in dim_means
    ]
    all_scores = positive_scores + negative_scores
    if not all_scores:
        log.debug(
            "anchor_confidence: no anchor dims found in dim_means; "
            "defaulting to multiplier_max=%s (legacy fitness 유지)",
            multiplier_max,
        )
        return multiplier_max
    anchor_score = sum(all_scores) / len(all_scores)
    multiplier = multiplier_min + (multiplier_max - multiplier_min) * anchor_score
    # Defensive clamp (anchor_score 가 0..1 range 외일 가능성 mitigate)
    return max(multiplier_min, min(multiplier_max, multiplier))


__all__ = [
    "ANCHOR_DIMS_NEGATIVE",
    "ANCHOR_DIMS_POSITIVE",
    "MULTIPLIER_MAX",
    "MULTIPLIER_MIN",
    "compute_anchor_confidence_multiplier",
]
