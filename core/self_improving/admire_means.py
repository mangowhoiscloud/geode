"""``admire_means`` fitness 축 — ADR-012 S2.

ADR-012 S2 의 **체감 품질** 양의 압력 축 (S1 ``ux_means`` 행동 축은
PR-MARGIN-FITNESS-SCALE 2026-05-30 에 제거됨).
``plugins/seed_generation/agents/ranker.py`` 의 ELO + 3-voter
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

``human_calibration_corr`` 가 ``KRIPPENDORFF_TENTATIVE_FLOOR`` (0.667,
Krippendorff 2004 *Content Analysis* 2nd ed p.241 의 tentative-
conclusions α floor) 미만이면 LLM-judge 가 human 기준에서 벗어나는
신호 — Goodhart fooling 위험. ``compute_admire_aggregate`` 가 이 축으로
win-rate 를 가중치 dampen 하는 방식으로 처리.

**ADR-012 §Decision.2 의 fitness 2축 다축화** (ux-removed 2026-05-30):

- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.70
- ``admire_means`` (체감 2-field, 양의 압력, 이 모듈) — 가중치 0.30

S2 + PR-AR-L4c (2026-05-26) 로 schema + math + ranker handoff
converter (``admire_means_from_eval_result``) 가 모두 wire. 실제 ranker
``evaluate_mutation_pairwise`` 호출 — 즉 mutation 의 before/after 응답
캡처 → panel dispatch — 는 mutator runner (별도 PR) 가 담당. 본
모듈은 *consumer 측* 변환 + 임시 calibration 프록시 (panel inter-voter
agreement → ``human_calibration_corr``) 만 제공.

**Goodhart 방어 (ADR-012 의 Risks 표)**:
1. judge model 의 주기적 교체 — ``required_diversity_providers`` 규약
   재사용 (PR-COSCI-1)
2. ranker.py 의 3-voter cross-provider panel — single-judge sycophancy
   회피
3. ``human_calibration_corr`` < ``KRIPPENDORFF_TENTATIVE_FLOOR`` 시
   win-rate dampening
4. 분기 human L4 batch refresh (calibration pipeline) — Pearson r
   로 프록시 교체
"""

from __future__ import annotations

# Admire field 별 가중치 — 합 1.0. pairwise_win_rate 가 주 신호,
# human_calibration_corr 는 dampening factor 역할.
ADMIRE_DIM_WEIGHTS: dict[str, float] = {
    "pairwise_win_rate": 0.70,
    "human_calibration_corr": 0.30,
}

assert abs(sum(ADMIRE_DIM_WEIGHTS.values()) - 1.0) < 1e-9, "ADMIRE_DIM_WEIGHTS must sum to 1.0"

# Calibration threshold — human_calibration_corr 가 이 값 미만이면 judge
# 가 human 기준에서 drift — pairwise_win_rate 를 dampen.
#
# PR-AR-L4c (2026-05-26) operator-grounded: Krippendorff 2004
# *Content Analysis* 2nd ed (p.241) — α ≥ 0.667 = *tentative
# conclusions* floor for nominal IRR; α ≥ 0.800 = *reliable / definitive
# conclusions* floor. The threshold is the tentative floor since the
# autoresearch loop is closed-loop with manual rollback paths, not a
# definitive batch decision. Operator-explicit decision to ground the
# constant rather than use a magic number; see memory
# [[feedback-dim-convention-direction]] for the no-magic-number rule.
#
# Note: the metric stored in ``human_calibration_corr`` is currently a
# *proxy* (panel inter-voter agreement, see
# ``derive_inter_voter_agreement``), not Krippendorff α itself. The
# proxy preserves the threshold interpretation but does not chance-
# adjust like α. The proxy will be replaced by Pearson r between
# judge scores and quarterly human L4 labels in a future PR; the
# Krippendorff thresholds keep the same role at that point.
KRIPPENDORFF_TENTATIVE_FLOOR: float = 0.667
"""Krippendorff α floor for *tentative-conclusions* IRR
(Krippendorff 2004 *Content Analysis* 2nd ed, p.241). Used as the
dampening threshold for ``pairwise_win_rate``."""

KRIPPENDORFF_DEFINITIVE_FLOOR: float = 0.800
"""Krippendorff α floor for *reliable / definitive-conclusions* IRR
(same source). Documented for symmetry — a future PR raising the
threshold to 0.8 when human L4 data lands surfaces this constant for
explicit review."""

CALIBRATION_THRESHOLD: float = KRIPPENDORFF_TENTATIVE_FLOOR


def compute_admire_aggregate(admire_means: dict[str, float] | None) -> float:
    """2-field weighted sum with calibration dampening → 0-1 scalar.

    ``None`` → 0.5 neutral (양의 압력 축 부재 시의 no-op signal).

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
