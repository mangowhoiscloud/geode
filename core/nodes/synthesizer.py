"""Layer 5: Synthesizer — Final narrative + cause classification.

Cause classification uses a Decision Tree (code-based, NOT LLM).
Narrative generation uses Claude Opus.

Decision Tree: architecture-v6 §13.9.2
CAUSE_TO_ACTION: architecture-v6 §13.9.3
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from core.infrastructure.ports.llm_port import get_llm_json, get_llm_parsed, get_llm_tool
from core.infrastructure.ports.tool_port import get_tool_executor
from core.llm.prompts import SYNTHESIZER_SYSTEM, SYNTHESIZER_TOOLS_SUFFIX, SYNTHESIZER_USER
from core.state import (
    ActionLiteral,
    CauseLiteral,
    EvaluatorResult,
    GeodeState,
    SynthesisResult,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load domain data from YAML (architecture-v6 §13.9.3)
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "cause_actions.yaml"

with _CONFIG_PATH.open(encoding="utf-8") as _f:
    _CONFIG_DATA: dict[str, Any] = yaml.safe_load(_f)

CAUSE_TO_ACTION: dict[CauseLiteral, ActionLiteral] = _CONFIG_DATA["cause_to_action"]
CAUSE_DESCRIPTIONS: dict[str, str] = _CONFIG_DATA["cause_descriptions"]
ACTION_DESCRIPTIONS: dict[str, str] = _CONFIG_DATA["action_descriptions"]


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


def _detect_timing_issue(monolake: dict[str, Any]) -> bool:
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


def _extract_def_scores(evaluations: dict[str, EvaluatorResult]) -> tuple[int, int, int]:
    """Extract D/E/F scores from evaluations, rounded to int per §13.9.2."""
    hv = evaluations.get("hidden_value")
    d = round(hv.axes.get("d_score", 3.0)) if hv else 3
    e = round(hv.axes.get("e_score", 3.0)) if hv else 3
    f = round(hv.axes.get("f_score", 3.0)) if hv else 3
    return d, e, f


# IP-specific narrative hooks for dry-run mode (F-3: differentiated narratives)
_IP_NARRATIVE_HOOKS: dict[str, dict[str, str]] = _CONFIG_DATA["ip_narrative_hooks"]


def _build_dry_run_synthesis(
    state: GeodeState,
    cause: CauseLiteral,
    action: ActionLiteral,
    cause_desc: str,
) -> SynthesisResult:
    """Build a dry-run synthesis with IP-specific insights."""
    ip_name = state.get("ip_name", "Unknown")
    ip_key = ip_name.lower().strip()
    signals = state.get("signals", {})

    parts = cause_desc.split("—")
    status = parts[0].strip()
    recommendation = parts[1].strip() if len(parts) > 1 else "종합 전략 수립"

    # Signal formatting
    yt = signals.get("youtube_views", 0)
    rd = signals.get("reddit_subscribers", 0)
    fa = signals.get("fan_art_yoy_pct", 0)
    yt_str = f"{yt / 1_000_000:.0f}M" if yt >= 1_000_000 else f"{yt:,}"
    rd_str = f"{rd / 1000:.0f}K" if rd >= 1000 else f"{rd:,}"

    # IP-specific hooks (F-2, F-3)
    hooks = _IP_NARRATIVE_HOOKS.get(ip_key, {})
    hook = hooks.get("hook", f"YouTube {yt_str}, Reddit {rd_str} 규모의 팬덤에도")
    insight = hooks.get("insight", f"팬아트 {fa:+.0f}% YoY 성장이 잠재력을 증명")

    narrative = (
        f"{ip_name}: {hook} {status} 상태로 분류됩니다. "
        f"{insight}. YouTube {yt_str} views, Reddit {rd_str}, 팬아트 {fa:+.0f}% YoY. "
        f"권장 액션: {recommendation}."
    )

    # IP-specific segment (F-2)
    segment = hooks.get("segment", "")
    if not segment:
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
    sig_summary = "\n".join(f"- {k}: {v}" for k, v in signals.items() if not k.startswith("_"))

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

    # ADR-007: PromptAssembler injection
    system = SYNTHESIZER_SYSTEM
    assembler: Any = state.get("_prompt_assembler")
    if assembler is not None:
        result = assembler.assemble(
            base_system=SYNTHESIZER_SYSTEM,
            base_user=user,
            state=dict(state),
            node="synthesizer",
            role_type="synthesis",
        )
        system = result.system
        user = result.user

    # Use Anthropic Structured Output (messages.parse) for guaranteed JSON
    try:
        result = get_llm_parsed()(system, user, output_model=SynthesisResult)
        # Ensure cause/action match (LLM may hallucinate different values)
        if result.undervaluation_cause != cause or result.action_type != action:
            result = result.model_copy(
                update={
                    "undervaluation_cause": cause,
                    "action_type": action,
                }
            )
        return result
    except Exception as exc:
        log.warning(
            "Synthesizer structured output failed: %s — falling back to legacy JSON parse",
            exc,
        )

    # Fallback: legacy JSON parse
    try:
        data = get_llm_json()(system, user)
        return SynthesisResult(
            undervaluation_cause=cause,
            action_type=action,
            value_narrative=data.get("value_narrative", ""),
            target_gamer_segment=data.get("target_gamer_segment", ""),
        )
    except (ValidationError, ValueError) as ve:
        log.warning("Synthesizer legacy fallback also failed: %s", ve)
        return SynthesisResult(
            undervaluation_cause=cause,
            action_type=action,
            value_narrative="Schema validation failed (degraded)",
            target_gamer_segment="Unknown (degraded)",
        )


def _build_tool_augmented_synthesis(
    state: GeodeState,
    cause: CauseLiteral,
    action: ActionLiteral,
    tool_fn: Any,
) -> SynthesisResult | None:
    """Generate synthesis using tool-augmented LLM (OpenClaw pattern).

    The LLM can call memory_search, signal_query, data_lookup tools
    during narrative generation. The tool loop runs inside the adapter.
    Returns None if tool-use path fails (caller falls back to standard).
    """
    tool_defs = state.get("_tool_definitions", [])
    if not tool_defs:
        return None

    evaluations = state.get("evaluations", {})
    analyses = state.get("analyses", [])

    analyst_summary = "\n".join(
        f"- {a.analyst_type}: {a.score:.1f}/5 — {a.key_finding}" for a in analyses
    )
    eval_summary = "\n".join(f"- {k}: {v.composite_score:.0f}/100" for k, v in evaluations.items())

    enhanced_system = SYNTHESIZER_SYSTEM + "\n\n" + SYNTHESIZER_TOOLS_SUFFIX

    user = SYNTHESIZER_USER.format(
        ip_name=state["ip_name"],
        cause=cause,
        action_type=action,
        tier=state.get("tier", "?"),
        final_score=state.get("final_score", 0),
        att_pct=0,
        z_value=0,
        gamma=0,
        quality_score=0,
        momentum_score=0,
        recovery_score=0,
        analyst_summary=analyst_summary,
        evaluator_summary=eval_summary,
        signals_summary="(available via tools)",
    )

    try:
        result = tool_fn(
            enhanced_system,
            user,
            tools=tool_defs,
            tool_executor=get_tool_executor(),
            max_tool_rounds=3,
        )
        if result.text:
            return SynthesisResult(
                undervaluation_cause=cause,
                action_type=action,
                value_narrative=result.text,
                target_gamer_segment="(tool-augmented)",
            )
    except Exception as exc:
        log.warning("Tool-augmented synthesis failed: %s — falling back to standard", exc)

    return None


def synthesizer_node(state: GeodeState) -> dict[str, Any]:
    """Layer 5: Classify cause + generate narrative via LLM.

    Execution paths (priority order):
      1. dry_run → fixture-based mock narrative
      2. tool-augmented → LLM with memory/signal tools (OpenClaw pattern)
      3. standard → LLM structured output / JSON parse
    """
    try:
        evaluations = state.get("evaluations", {})
        monolake = state.get("monolake", {})

        d_score, e_score, f_score = _extract_def_scores(evaluations)
        release_timing_issue = _detect_timing_issue(monolake)

        cause, cause_desc = _classify_cause(d_score, e_score, f_score, release_timing_issue)
        action = CAUSE_TO_ACTION[cause]

        if state.get("verbose"):
            log.debug("Cause: %s -> Action: %s (%s)", cause, action, ACTION_DESCRIPTIONS[action])

        if state.get("dry_run"):
            synthesis = _build_dry_run_synthesis(state, cause, action, cause_desc)
        else:
            # Try tool-augmented path first (graceful degradation to standard)
            synthesis = None
            try:
                tool_fn = get_llm_tool()
                synthesis = _build_tool_augmented_synthesis(state, cause, action, tool_fn)
            except RuntimeError:
                pass  # tool callable not injected — skip to standard path

            if synthesis is None:
                synthesis = _build_llm_synthesis(state, cause, action)

        return {"synthesis": synthesis}
    except Exception as exc:
        log.error("Node synthesizer failed: %s", exc)
        return {"errors": [f"synthesizer: {exc}"]}
