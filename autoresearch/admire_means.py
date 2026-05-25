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

``human_calibration_corr`` 가 ``KRIPPENDORFF_TENTATIVE_FLOOR`` (0.667,
Krippendorff 2004 *Content Analysis* 2nd ed p.241 의 tentative-
conclusions α floor) 미만이면 LLM-judge 가 human 기준에서 벗어나는
신호 — Goodhart fooling 위험. ``compute_admire_aggregate`` 가 이 축으로
win-rate 를 가중치 dampen 하는 방식으로 처리.

**ADR-012 §Decision.2 의 fitness 3축 다축화**:

- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.4
- ``ux_means`` (행동 4-field, 양의 압력, S1 신설) — 가중치 0.3
- ``admire_means`` (체감 2-field, 양의 압력, 이 모듈) — 가중치 0.3

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


def derive_inter_voter_agreement(*, wins: int, losses: int, ties: int) -> float:
    """Compute panel inter-voter agreement as the
    ``human_calibration_corr`` proxy.

    PR-AR-L4c (2026-05-26) — full Krippendorff α over a 3-voter panel
    of binary verdicts is overkill, so this returns a *proxy* that
    follows the same monotone signal. The interpretation thresholds
    used by ``compute_admire_aggregate`` (``KRIPPENDORFF_TENTATIVE_FLOOR``
    = 0.667 for tentative conclusions) are Krippendorff α thresholds;
    the metric here is not Krippendorff α itself.

    Formula (two-factor):

        majority_share = max(wins, losses) / (wins + losses)
        decisive_share = (wins + losses) / max(1, wins + losses + ties)
        agreement      = majority_share * decisive_share

    Why two factors:

    - ``majority_share`` measures how strongly the decisive voters
      agreed with each other. 3-of-3 → 1.0; 2-of-3 → 2/3.
    - ``decisive_share`` measures how much of the panel actually
      reached a decision. Ties + failures shrink the denominator —
      Codex MCP review §3 caught the pre-fix case where
      ``wins=1, losses=0, ties=2`` returned 1.0 despite only one
      voter being decisive (degenerate single-vote unanimity).

    Sample values:

    - 3 wins, 0 losses, 0 ties → 1.0 * 1.0 = **1.0** (unanimous)
    - 2 wins, 1 loss, 0 ties → 2/3 * 1.0 ≈ **0.667** (canonical
      "tentative conclusions" floor)
    - 1 win, 0 losses, 2 ties → 1.0 * 1/3 ≈ **0.333** (low-confidence
      decisive vote, penalized)
    - 2 wins, 2 losses, 0 ties → 0.5 * 1.0 = **0.5** (even split)
    - 0 decisive of 3 voters → fallback to ``KRIPPENDORFF_TENTATIVE_FLOOR``

    The proxy will be replaced by quarterly human-labeled
    ``human_calibration_corr`` (Pearson r) once that batch lands;
    the same Krippendorff thresholds keep their interpretation.

    Args:
        wins: decisive votes for the after-mutation response.
        losses: decisive votes for the before-mutation response.
        ties: votes that reported no clear winner. Used to penalize
            low panel-decisiveness via ``decisive_share``.

    Returns:
        Agreement in ``[0.0, 1.0]``;
        ``KRIPPENDORFF_TENTATIVE_FLOOR`` (0.667) when every voter
        tied (no decisive signal — neutral fallback at the
        tentative-conclusions threshold).
    """
    decisive = wins + losses
    if decisive == 0:
        # No decisive signal — neutral fallback at the threshold so
        # ``compute_admire_aggregate``'s dampener treats it as the
        # minimum tentative-conclusions reading.
        return KRIPPENDORFF_TENTATIVE_FLOOR
    total = wins + losses + ties
    majority_share = max(wins, losses) / decisive
    decisive_share = decisive / max(1, total)
    return majority_share * decisive_share


def admire_means_from_eval_result(
    result: Any,
) -> dict[str, float]:
    """Convert a ``plugins.seed_generation.mutation_eval.MutationEvalResult``
    into the autoresearch ``admire_means`` dict shape.

    Cross-module handoff contract (PR-RANKER-MUTATION-EVAL + PR-AR-L4c,
    2026-05-26):

    - ``pairwise_win_rate`` — verbatim from
      ``MutationEvalResult.pairwise_win_rate``. Field name parity with
      ``ADMIRE_DIM_WEIGHTS`` is pinned by both sides.
    - ``human_calibration_corr`` — ``derive_inter_voter_agreement``
      proxy until quarterly human L4 batch lands.

    The autoresearch caller is responsible for invoking
    ``evaluate_mutation_pairwise`` (with before/after responses + voter
    panel + SubAgentManager) and forwarding its result here. The
    actual before/after capture lives in the mutator runner
    (``core/self_improving_loop/runner.py``); this PR only wires the
    autoresearch consumer side, so the runner-level invocation is a
    follow-up PR (audit 2× cost + response capture infrastructure).

    Args:
        result: A ``MutationEvalResult`` (typed via ``Any`` to avoid
            the seed-gen → autoresearch import dependency — the
            handoff boundary is data-only, not code-only).

    Returns:
        ``admire_means`` dict ready for ``compute_admire_aggregate``
        or for forwarding to ``compute_fitness(admire_means=...)``.
    """
    win_rate = float(result.pairwise_win_rate)
    calibration = derive_inter_voter_agreement(
        wins=int(result.wins),
        losses=int(result.losses),
        ties=int(result.ties),
    )
    return {
        "pairwise_win_rate": win_rate,
        "human_calibration_corr": calibration,
    }


__all__ = [
    "ADMIRE_DIM_WEIGHTS",
    "CALIBRATION_THRESHOLD",
    "KRIPPENDORFF_DEFINITIVE_FLOOR",
    "KRIPPENDORFF_TENTATIVE_FLOOR",
    "admire_means_from_eval_result",
    "compute_admire_aggregate",
    "derive_inter_voter_agreement",
    "validate_admire_schema",
]
