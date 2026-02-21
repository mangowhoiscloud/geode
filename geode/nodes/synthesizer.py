"""Layer 5: Synthesizer — Final narrative + cause classification.

Cause classification uses a Decision Tree (code-based, NOT LLM).
Narrative generation uses Claude Opus.

Decision Tree: architecture-v6 §13.9.2
CAUSE_TO_ACTION: architecture-v6 §13.9.3
"""

from __future__ import annotations

from geode.llm.client import call_llm_json
from geode.llm.prompts import SYNTHESIZER_SYSTEM, SYNTHESIZER_USER
from geode.state import (
    ActionLiteral,
    CauseLiteral,
    GeodeState,
    SynthesisResult,
)
from geode.ui.console import console

# ---------------------------------------------------------------------------
# CAUSE_TO_ACTION mapping (architecture-v6 §13.9.3 — 그대로)
# ---------------------------------------------------------------------------

CAUSE_TO_ACTION: dict[CauseLiteral, ActionLiteral] = {
    "undermarketed": "marketing_boost",
    "conversion_failure": "marketing_boost",  # + monetization_pivot
    "monetization_misfit": "monetization_pivot",
    "niche_gem": "platform_expansion",
    "timing_mismatch": "timing_optimization",
    "discovery_failure": "community_activation",
}

CAUSE_DESCRIPTIONS: dict[str, str] = {
    "undermarketed": "IP 파워 대비 마케팅/노출 절대 부족 — 마케팅 예산 증액",
    "conversion_failure": "유저 획득 + 수익화 모두 IP 대비 미달 — 퍼널 + 과금 동시 개선",
    "monetization_misfit": "유저는 잘 오는데 돈이 안 됨 — 과금 모델/가격 전략 재설계",
    "niche_gem": "품질 좋으나 확장 미진출 상태 — 플랫폼 확장, 타겟 프로모션",
    "timing_mismatch": "IP 인지도 있었으나 출시 타이밍 실패 — 리런치/리마스터 이벤트 권장",
    "discovery_failure": "복합 요인에 의한 발견 실패 — 종합 전략 수립 필요",
}

ACTION_DESCRIPTIONS: dict[str, str] = {
    "marketing_boost": "마케팅 예산 증액 및 채널 다양화",
    "monetization_pivot": "과금 모델 및 가격 전략 재설계",
    "platform_expansion": "신규 플랫폼 출시 또는 지역 확장",
    "timing_optimization": "리런치, 리마스터 또는 시즌 이벤트",
    "community_activation": "커뮤니티 이벤트 및 UGC 활성화",
}


# ---------------------------------------------------------------------------
# Decision Tree: Cause Classification (architecture-v6 §13.9.2 — 그대로)
# ---------------------------------------------------------------------------


def _classify_cause(
    d_score: float,
    e_score: float,
    f_score: float,
    release_timing_issue: bool = False,
) -> tuple[CauseLiteral, str]:
    """D-E-F 프로파일 기반 저평가 원인 분류 (6개 유형).

    | 원인 코드           | D-E-F 프로파일               |
    |---------------------|------------------------------|
    | timing_mismatch     | D>=3 + release_timing_issue  |
    | conversion_failure  | D>=3, E>=3                   |
    | undermarketed       | D>=3, E<3                    |
    | monetization_misfit | D<=2, E>=3                   |
    | niche_gem           | D<=2, E<=2, F>=3             |
    | discovery_failure   | D<=2, E<=2, F<=2             |
    """
    cause: CauseLiteral

    # 타이밍 이슈가 있고 D가 높으면 timing_mismatch
    if release_timing_issue and d_score >= 3:
        cause = "timing_mismatch"
        return cause, CAUSE_DESCRIPTIONS[cause]

    # D>=3: 마케팅/노출 부족 계열
    if d_score >= 3:
        if e_score >= 3:
            cause = "conversion_failure"
            return cause, CAUSE_DESCRIPTIONS[cause]
        cause = "undermarketed"
        return cause, CAUSE_DESCRIPTIONS[cause]

    # D<=2: 유저는 오는 계열
    if e_score >= 3:
        cause = "monetization_misfit"
        return cause, CAUSE_DESCRIPTIONS[cause]

    if f_score >= 3:
        cause = "niche_gem"
        return cause, CAUSE_DESCRIPTIONS[cause]

    cause = "discovery_failure"
    return cause, CAUSE_DESCRIPTIONS[cause]


def _detect_timing_issue(monolake: dict) -> bool:
    """release_timing_issue 판별 휴리스틱.

    게임이 존재했으나 오래 전이고 타이밍 관련 실패 징후가 있는 경우.
    """
    last_game: int = monolake.get("last_game_year", 0)
    active: int = monolake.get("active_game_count", 0)
    metacritic: int = monolake.get("metacritic_score", 0)

    # 게임이 존재했고, 비활성이며, 메타크리틱 중간 이상 (품질 문제는 아님)
    return last_game > 0 and active == 0 and metacritic >= 60


# ---------------------------------------------------------------------------
# Synthesizer Node
# ---------------------------------------------------------------------------


def _extract_def_scores(evaluations: dict) -> tuple[int, int, int]:
    """Extract D/E/F scores from evaluations, rounded to int per §13.9.2."""
    hv = evaluations.get("hidden_value")
    d = round(hv.axes.get("d_score", 3.0)) if hv else 3
    e = round(hv.axes.get("e_score", 3.0)) if hv else 3
    f = round(hv.axes.get("f_score", 3.0)) if hv else 3
    return d, e, f


def _build_dry_run_synthesis(
    state: GeodeState,
    cause: CauseLiteral,
    action: ActionLiteral,
    cause_desc: str,
) -> SynthesisResult:
    """Build a dry-run synthesis with IP-specific insights."""
    ip_name = state.get("ip_name", "Unknown")
    signals = state.get("signals", {})
    analyses = state.get("analyses", [])

    parts = cause_desc.split("—")
    status = parts[0].strip()
    recommendation = parts[1].strip() if len(parts) > 1 else "종합 전략 수립"

    # Build richer narrative using actual data
    yt = signals.get("youtube_views", 0)
    rd = signals.get("reddit_subscribers", 0)
    fa = signals.get("fan_art_yoy_pct", 0)
    yt_str = f"{yt / 1_000_000:.0f}M" if yt >= 1_000_000 else f"{yt:,}"
    rd_str = f"{rd / 1000:.0f}K" if rd >= 1000 else f"{rd:,}"

    top_analyst = max(analyses, key=lambda a: a.score) if analyses else None
    top_insight = f" {top_analyst.key_finding}." if top_analyst else ""

    narrative = (
        f"{ip_name}은(는) YouTube {yt_str} views, Reddit {rd_str} subscribers, "
        f"팬아트 {fa:+.0f}% YoY 성장에도 불구하고 {status} 상태입니다.{top_insight} "
        f"{recommendation}이 권장됩니다."
    )

    # Genre-aware segment
    ip_info = state.get("ip_info", {})
    genres = ip_info.get("genre", [])
    genre_str = genres[0] if genres else "action"
    segment = f"{genre_str.title()} RPG 코어 유저 (25-40세, Achiever/Explorer 혼합형)"

    return SynthesisResult(
        undervaluation_cause=cause,
        action_type=action,
        value_narrative=narrative,
        target_gamer_segment=segment,
    )


def _build_llm_synthesis(
    state: GeodeState,
    cause: CauseLiteral,
    action: ActionLiteral,
) -> SynthesisResult:
    """Generate LLM-based synthesis narrative."""
    evaluations = state.get("evaluations", {})
    analyses = state.get("analyses", [])
    signals = state.get("signals", {})
    psm = state.get("psm_result")

    analyst_summary = "\n".join(
        f"- {a.analyst_type}: {a.score:.1f}/5 — {a.key_finding}" for a in analyses
    )
    eval_summary = "\n".join(
        f"- {k}: {v.composite_score:.0f}/100 ({v.rationale[:80]}...)"
        for k, v in evaluations.items()
    )
    sig_summary = "\n".join(
        f"- {k}: {v}" for k, v in signals.items() if not k.startswith("_")
    )

    qj = evaluations.get("quality_judge")
    cm = evaluations.get("community_momentum")

    user = SYNTHESIZER_USER.format(
        ip_name=state["ip_name"],
        cause=cause,
        action_type=action,
        tier=state.get("tier", "?"),
        final_score=state.get("final_score", 0),
        att_pct=psm.att_pct if psm else 0,
        z_value=psm.z_value if psm else 0,
        gamma=psm.rosenbaum_gamma if psm else 0,
        quality_score=qj.composite_score if qj else 0,
        momentum_score=cm.composite_score if cm else 0,
        recovery_score=state.get("subscores", {}).get("recovery_potential", 0),
        analyst_summary=analyst_summary,
        evaluator_summary=eval_summary,
        signals_summary=sig_summary,
    )

    data = call_llm_json(SYNTHESIZER_SYSTEM, user)
    return SynthesisResult(
        undervaluation_cause=cause,
        action_type=action,
        value_narrative=data.get("value_narrative", ""),
        target_gamer_segment=data.get("target_gamer_segment", ""),
    )


def synthesizer_node(state: GeodeState) -> dict:
    """Layer 5: Classify cause + generate narrative via LLM."""
    evaluations = state.get("evaluations", {})
    monolake = state.get("monolake", {})

    d_score, e_score, f_score = _extract_def_scores(evaluations)
    release_timing_issue = _detect_timing_issue(monolake)

    cause, cause_desc = _classify_cause(d_score, e_score, f_score, release_timing_issue)
    action = CAUSE_TO_ACTION[cause]

    if state.get("verbose"):
        console.print(
            f"    [muted]Cause: {cause} → Action: {action}"
            f" ({ACTION_DESCRIPTIONS[action]})[/muted]"
        )

    if state.get("dry_run"):
        synthesis = _build_dry_run_synthesis(state, cause, action, cause_desc)
    else:
        synthesis = _build_llm_synthesis(state, cause, action)

    return {"synthesis": synthesis}
