"""Layer 3: Evaluators — 3 parallel evaluators using 14-axis rubric.

Supports Send API pattern for parallel execution (like analysts).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from core.infrastructure.ports.domain_port import get_domain_or_none
from core.infrastructure.ports.llm_port import get_llm_json, get_llm_parsed
from core.infrastructure.ports.tool_port import get_tool_executor
from core.llm.client import call_llm_with_tools
from core.llm.prompts import (
    EVALUATOR_AXES,
    EVALUATOR_SYSTEM,
    EVALUATOR_USER,
    PROSPECT_EVALUATOR_AXES,
)
from core.state import AnalysisResult, EvaluatorResult, GeodeState

log = logging.getLogger(__name__)

EVALUATOR_TYPES: list[str] = list(EVALUATOR_AXES.keys())
PROSPECT_EVALUATOR_TYPES: list[str] = list(PROSPECT_EVALUATOR_AXES.keys())


def _get_evaluator_types() -> list[str]:
    """Get evaluator types from domain adapter if available, else static."""
    domain = get_domain_or_none()
    if domain is not None:
        return domain.get_evaluator_types()
    return list(EVALUATOR_AXES.keys())


def _get_evaluator_axes_config() -> dict[str, dict[str, Any]]:
    """Get evaluator axes config from domain adapter if available, else static."""
    domain = get_domain_or_none()
    if domain is not None:
        return domain.get_evaluator_axes()
    return EVALUATOR_AXES


# ---------------------------------------------------------------------------
# Typed axes models — enforce required keys in structured output JSON schema
# ---------------------------------------------------------------------------


class QualityJudgeAxes(BaseModel):
    """8-axis rubric for quality_judge evaluator."""

    a_score: float = Field(ge=1, le=5)
    b_score: float = Field(ge=1, le=5)
    c_score: float = Field(ge=1, le=5)
    b1_score: float = Field(ge=1, le=5)
    c1_score: float = Field(ge=1, le=5)
    c2_score: float = Field(ge=1, le=5)
    m_score: float = Field(ge=1, le=5)
    n_score: float = Field(ge=1, le=5)


class HiddenValueAxes(BaseModel):
    """3-axis rubric for hidden_value evaluator."""

    d_score: float = Field(ge=1, le=5)
    e_score: float = Field(ge=1, le=5)
    f_score: float = Field(ge=1, le=5)


class CommunityMomentumAxes(BaseModel):
    """3-axis rubric for community_momentum evaluator."""

    j_score: float = Field(ge=1, le=5)
    k_score: float = Field(ge=1, le=5)
    l_score: float = Field(ge=1, le=5)


class ProspectJudgeAxes(BaseModel):
    """9-axis rubric for prospect_judge evaluator (non-gamified IP)."""

    g_score: float = Field(ge=1, le=5)
    h_score: float = Field(ge=1, le=5)
    i_score: float = Field(ge=1, le=5)
    o_score: float = Field(ge=1, le=5)
    p_score: float = Field(ge=1, le=5)
    q_score: float = Field(ge=1, le=5)
    r_score: float = Field(ge=1, le=5)
    s_score: float = Field(ge=1, le=5)
    t_score: float = Field(ge=1, le=5)


class _QualityJudgeOutput(BaseModel):
    evaluator_type: str
    axes: QualityJudgeAxes
    composite_score: float = Field(ge=0, le=100)
    rationale: str


class _HiddenValueOutput(BaseModel):
    evaluator_type: str
    axes: HiddenValueAxes
    composite_score: float = Field(ge=0, le=100)
    rationale: str


class _CommunityMomentumOutput(BaseModel):
    evaluator_type: str
    axes: CommunityMomentumAxes
    composite_score: float = Field(ge=0, le=100)
    rationale: str


class _ProspectJudgeOutput(BaseModel):
    evaluator_type: str
    axes: ProspectJudgeAxes
    composite_score: float = Field(ge=0, le=100)
    rationale: str


_EVALUATOR_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "quality_judge": _QualityJudgeOutput,
    "hidden_value": _HiddenValueOutput,
    "community_momentum": _CommunityMomentumOutput,
    "prospect_judge": _ProspectJudgeOutput,
}


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _get_axes_config(evaluator_type: str) -> dict[str, Any]:
    """Get axes config from standard or prospect evaluator axes."""
    if evaluator_type in EVALUATOR_AXES:
        return EVALUATOR_AXES[evaluator_type]
    if evaluator_type in PROSPECT_EVALUATOR_AXES:
        return PROSPECT_EVALUATOR_AXES[evaluator_type]
    raise KeyError(f"Unknown evaluator_type: {evaluator_type}")


def _format_axes_schema(evaluator_type: str) -> str:
    config = _get_axes_config(evaluator_type)
    axes: dict[str, str] = config["axes"]
    parts = [f'"{k}": <float 1-5 — {v}>' for k, v in axes.items()]
    return ", ".join(parts)


def _format_rubric_anchors(evaluator_type: str) -> str:
    """Format per-level rubric anchors for the evaluator prompt."""
    config = _get_axes_config(evaluator_type)
    rubric: dict[str, dict[str, str]] = config.get("rubric", {})
    if not rubric:
        return ""
    axes_desc: dict[str, str] = config["axes"]
    lines = ["## Rubric Anchors (1=Poor, 2=Below Avg, 3=Good, 4=Above Avg, 5=Outstanding)"]
    for key, anchors in rubric.items():
        desc = axes_desc.get(key, key)
        parts = [f"{lvl}={anchors[lvl]}" for lvl in ("1", "2", "3", "4", "5") if lvl in anchors]
        lines.append(f"- {key} ({desc}): {', '.join(parts)}")
    formula = config.get("composite_formula", "")
    if formula:
        lines.append(f"\nComposite formula: {formula}")
    return "\n".join(lines)


def _build_evaluator_prompt(evaluator_type: str, state: GeodeState) -> tuple[str, str]:
    ip = state["ip_info"]
    analyses = state.get("analyses", [])
    signals = state.get("signals", {})

    ip_summary = (
        f"{ip['ip_name']} ({ip['media_type']}, {ip['release_year']}, {ip['studio']})\n"
        f"Genre: {', '.join(ip['genre']) if isinstance(ip['genre'], list) else ip['genre']}\n"
        f"{ip['synopsis']}"
    )

    analyst_lines = []
    for a in analyses:
        if isinstance(a, AnalysisResult):
            analyst_lines.append(f"- {a.analyst_type}: {a.score:.1f}/5 — {a.key_finding}")
    analyst_findings = "\n".join(analyst_lines) or "No analyst data available."

    sig_lines = [f"- {k}: {v}" for k, v in signals.items() if not k.startswith("_")]
    signals_summary = "\n".join(sig_lines) or "No signal data."

    # Note: evaluator system prompt includes rubric anchors as part of base template
    base_system = (
        EVALUATOR_SYSTEM.format(
            evaluator_type=evaluator_type,
            axes_schema=_format_axes_schema(evaluator_type),
        )
        + "\n\n"
        + _format_rubric_anchors(evaluator_type)
    )
    base_user = EVALUATOR_USER.format(
        ip_name=ip["ip_name"],
        ip_summary=ip_summary,
        analyst_findings=analyst_findings,
        signals_summary=signals_summary,
        evaluator_type=evaluator_type,
        rubric_anchors=_format_rubric_anchors(evaluator_type),
    )

    # ADR-007: PromptAssembler injection
    assembler: Any = state.get("_prompt_assembler")
    if assembler is not None:
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=dict(state),
            node="evaluator",
            role_type=evaluator_type,
        )
        return result.system, result.user

    # Fallback: no assembler
    return base_system, base_user


def _run_evaluator(evaluator_type: str, state: GeodeState) -> EvaluatorResult:
    if state.get("dry_run"):
        return _dry_run_result(evaluator_type, state.get("ip_name", ""))

    system, user = _build_evaluator_prompt(evaluator_type, state)
    if state.get("verbose"):
        log.debug("Running %s evaluator...", evaluator_type)

    # Tool-augmented path: evaluator can query memory/steam/reddit data
    tool_defs: Any = state.get("_tool_definitions", [])
    tool_executor = get_tool_executor()
    if tool_defs and tool_executor is not None:
        try:
            enhanced_system = (
                system + "\n\n## Available Tools\n"
                "You have access to tools for querying past evaluations (memory_search, "
                "memory_get), Steam data (steam_info), and community sentiment "
                "(reddit_sentiment). Use them to ground your evaluation."
            )
            result = call_llm_with_tools(
                enhanced_system,
                user,
                tools=tool_defs,
                tool_executor=tool_executor,
                temperature=0.3,
                max_tool_rounds=2,
            )
            if result.text:
                data = json.loads(result.text)
                eval_result = EvaluatorResult(**data)
                if eval_result.evaluator_type != evaluator_type:
                    eval_result = eval_result.model_copy(update={"evaluator_type": evaluator_type})
                return eval_result
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            log.warning(
                "Evaluator %s tool-augmented path failed: %s — falling back",
                evaluator_type,
                exc,
            )

    # Use Anthropic Structured Output with evaluator-specific typed model.
    # Typed axes models enforce required keys in the JSON schema, preventing
    # the LLM from returning axes: {} (which generic dict[str, float] allows).
    output_model = _EVALUATOR_OUTPUT_MODELS.get(evaluator_type)
    if output_model is None:
        log.warning(
            "No typed output model for evaluator %s, using generic EvaluatorResult",
            evaluator_type,
        )
        output_model = EvaluatorResult

    try:
        typed_result: Any = get_llm_parsed()(system, user, output_model=output_model)
        # Convert typed result back to EvaluatorResult for state compatibility
        if isinstance(typed_result, EvaluatorResult):
            result = typed_result
        else:
            axes_dict = typed_result.axes.model_dump()
            result = EvaluatorResult(
                evaluator_type=evaluator_type,
                axes=axes_dict,
                composite_score=typed_result.composite_score,
                rationale=typed_result.rationale,
            )
        # Ensure evaluator_type matches (LLM may hallucinate a different type)
        if result.evaluator_type != evaluator_type:
            result = result.model_copy(update={"evaluator_type": evaluator_type})
        return result
    except Exception as exc:
        log.warning(
            "Evaluator %s structured output failed: %s — falling back to legacy JSON parse",
            evaluator_type,
            exc,
        )

    # Fallback: legacy JSON parse (for non-Anthropic providers or SDK issues)
    try:
        data = get_llm_json()(system, user)
        return EvaluatorResult(**data)
    except (ValidationError, ValueError) as ve:
        log.warning("Evaluator %s legacy fallback also failed: %s", evaluator_type, ve)
        # Fallback neutral (3.0) — matches analyst fallback convention.
        # Using 1.0 (min) would unfairly penalise; 3.0 = "unknown/neutral".
        _FALLBACK_NEUTRAL = 3.0
        default_axes: dict[str, dict[str, float]] = {
            "quality_judge": {
                "a_score": _FALLBACK_NEUTRAL,
                "b_score": _FALLBACK_NEUTRAL,
                "c_score": _FALLBACK_NEUTRAL,
                "b1_score": _FALLBACK_NEUTRAL,
                "c1_score": _FALLBACK_NEUTRAL,
                "c2_score": _FALLBACK_NEUTRAL,
                "m_score": _FALLBACK_NEUTRAL,
                "n_score": _FALLBACK_NEUTRAL,
            },
            "hidden_value": {
                "d_score": _FALLBACK_NEUTRAL,
                "e_score": _FALLBACK_NEUTRAL,
                "f_score": _FALLBACK_NEUTRAL,
            },
            "community_momentum": {
                "j_score": _FALLBACK_NEUTRAL,
                "k_score": _FALLBACK_NEUTRAL,
                "l_score": _FALLBACK_NEUTRAL,
            },
        }
        _default_hidden = {
            "d_score": _FALLBACK_NEUTRAL,
            "e_score": _FALLBACK_NEUTRAL,
            "f_score": _FALLBACK_NEUTRAL,
        }
        return EvaluatorResult(
            evaluator_type=evaluator_type,
            axes=default_axes.get(evaluator_type, _default_hidden),
            composite_score=0.0,
            rationale="LLM response failed validation (degraded)",
            is_degraded=True,
        )


def _dry_run_result(evaluator_type: str, ip_name: str = "") -> EvaluatorResult:
    """Return IP-specific mock results for dry-run mode."""
    key = ip_name.lower().strip()

    # Cowboy Bebop (B2 concept card: D5/E2/F4 → undermarketed)
    cowboy_bebop = {
        "quality_judge": EvaluatorResult(
            evaluator_type="quality_judge",
            axes={
                "a_score": 4.2,
                "b_score": 4.0,
                "c_score": 4.3,
                "b1_score": 3.9,
                "c1_score": 4.1,
                "c2_score": 4.0,
                "m_score": 3.8,
                "n_score": 4.2,
            },
            composite_score=76.56,  # (32.5-8)/32*100
            rationale=(
                "Strong IP-game adaptation potential with rich narrative "
                "hooks and engaging world design."
            ),
        ),
        "hidden_value": EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 5.0, "e_score": 2.0, "f_score": 4.0},
            composite_score=50.0,  # (2.0+4.0-2)/8*100
            rationale=(
                "Extreme acquisition gap (D=5) with no active marketing. "
                "Low monetization gap (E=2) since no game exists to "
                "monetize. High expansion potential (F=4)."
            ),
        ),
        "community_momentum": EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 4.3, "k_score": 4.1, "l_score": 3.9},
            composite_score=77.50,  # (4.3+4.1+3.9-3)/12*100
            rationale=(
                "Active organic community with strong growth signals "
                "despite no game presence. Fan art +42% YoY indicates "
                "accelerating momentum."
            ),
        ),
    }

    # Berserk (D4/E4.5/F4.5 → conversion_failure; IP power far exceeds game quality)
    berserk = {
        "quality_judge": EvaluatorResult(
            evaluator_type="quality_judge",
            axes={
                "a_score": 4.5,
                "b_score": 4.2,
                "c_score": 4.4,
                "b1_score": 3.8,
                "c1_score": 3.8,
                "c2_score": 3.6,
                "m_score": 3.8,
                "n_score": 4.0,
            },
            composite_score=75.31,  # (32.1-8)/32*100
            rationale=(
                "Berserk's dark fantasy world is ideally suited for Souls-like "
                "adaptation. Previous game was poor execution, not IP weakness. "
                "Elden Ring proves massive demand for this genre."
            ),
        ),
        "hidden_value": EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 4.0, "e_score": 4.5, "f_score": 4.5},
            composite_score=87.50,  # (4.5+4.5-2)/8*100
            rationale=(
                "Massive fandom-to-game conversion gap. Both marketing and "
                "monetization severely underperformed. High expansion potential "
                "across platforms with Souls-like genre demand."
            ),
        ),
        "community_momentum": EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 4.8, "k_score": 4.6, "l_score": 4.5},
            composite_score=90.83,  # (4.8+4.6+4.5-3)/12*100
            rationale=(
                "Exceptionally strong community momentum. Reddit 520K, "
                "YouTube 25M, fan art +65% YoY. Souls-like genre demand "
                "is high."
            ),
        ),
    }

    # Ghost in the Shell (D2/E2/F2 → discovery_failure)
    ghost_in_shell = {
        "quality_judge": EvaluatorResult(
            evaluator_type="quality_judge",
            axes={
                "a_score": 3.8,
                "b_score": 3.5,
                "c_score": 3.6,
                "b1_score": 3.3,
                "c1_score": 3.4,
                "c2_score": 3.2,
                "m_score": 3.4,
                "n_score": 3.5,
            },
            composite_score=61.56,  # (27.7-8)/32*100
            rationale=(
                "Good IP-game fit for stealth/cyberpunk but prior games "
                "were average. Needs AAA-quality execution."
            ),
        ),
        "hidden_value": EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 2.0, "e_score": 2.0, "f_score": 2.0},
            composite_score=25.0,  # (2.0+2.0-2)/8*100
            rationale=(
                "No single undervaluation axis is dominant. Complex, "
                "multi-factor discovery failure."
            ),
        ),
        "community_momentum": EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 3.5, "k_score": 3.3, "l_score": 3.0},
            composite_score=56.67,  # (3.5+3.3+3.0-3)/12*100
            rationale=(
                "Moderate community presence. Stable but not growing rapidly. Needs catalyst event."
            ),
        ),
    }

    # Prospect evaluator dry-run results (9-axis)
    # Sum=34.5 → (34.5-9)/36*100 = 70.83
    cowboy_bebop_prospect = {
        "prospect_judge": EvaluatorResult(
            evaluator_type="prospect_judge",
            axes={
                "g_score": 4.5,
                "h_score": 3.8,
                "i_score": 4.2,
                "o_score": 4.0,
                "p_score": 3.5,
                "q_score": 3.0,
                "r_score": 4.5,
                "s_score": 3.5,
                "t_score": 3.5,
            },
            composite_score=70.83,
            rationale=(
                "Strong world-building and narrative arc with moderate transmedia track record."
            ),
        ),
    }
    # Sum=36.0 → (36.0-9)/36*100 = 75.00
    berserk_prospect = {
        "prospect_judge": EvaluatorResult(
            evaluator_type="prospect_judge",
            axes={
                "g_score": 5.0,
                "h_score": 4.0,
                "i_score": 4.5,
                "o_score": 4.5,
                "p_score": 4.0,
                "q_score": 3.5,
                "r_score": 4.0,
                "s_score": 3.5,
                "t_score": 3.0,
            },
            composite_score=75.00,
            rationale=(
                "Exceptional world-building and visual identity; licensing complexity is a concern."
            ),
        ),
    }
    # Sum=30.0 → (30.0-9)/36*100 = 58.33
    ghost_prospect = {
        "prospect_judge": EvaluatorResult(
            evaluator_type="prospect_judge",
            axes={
                "g_score": 4.0,
                "h_score": 3.0,
                "i_score": 3.5,
                "o_score": 3.5,
                "p_score": 3.0,
                "q_score": 3.5,
                "r_score": 3.0,
                "s_score": 3.5,
                "t_score": 3.0,
            },
            composite_score=58.33,
            rationale=(
                "Decent IP potential but competitive landscape is crowded post-Cyberpunk 2077."
            ),
        ),
    }

    ip_mocks = {
        "cowboy bebop": {**cowboy_bebop, **cowboy_bebop_prospect},
        "berserk": {**berserk, **berserk_prospect},
        "ghost in the shell": {**ghost_in_shell, **ghost_prospect},
    }

    mock = ip_mocks.get(key, {**cowboy_bebop, **cowboy_bebop_prospect})
    return mock[evaluator_type]


# ---------------------------------------------------------------------------
# Send API pattern for parallel evaluators (mirrors analysts.py)
# ---------------------------------------------------------------------------


def evaluator_node(state: GeodeState) -> dict[str, Any]:
    """Run a single evaluator. Called via Send API for parallel execution."""
    try:
        evaluator_type = state.get("_evaluator_type", "quality_judge")
        result = _run_evaluator(evaluator_type, state)
        return {"evaluations": {evaluator_type: result}}
    except Exception as exc:
        log.error("Node evaluator (%s) failed: %s", state.get("_evaluator_type", "?"), exc)
        return {"evaluations": {}, "errors": [f"evaluator: {exc}"]}


def make_evaluator_sends(state: GeodeState) -> list[Any]:
    """Create Send objects for evaluators.

    Uses standard 3 evaluators for gamified IPs, or prospect_judge for prospect IPs.
    """
    from langgraph.types import Send

    mode = state.get("pipeline_mode", "full_pipeline")
    etypes = PROSPECT_EVALUATOR_TYPES if mode == "prospect" else _get_evaluator_types()

    sends = []
    for etype in etypes:
        send_state = {
            "ip_name": state.get("ip_name", ""),
            "ip_info": state.get("ip_info", {}),
            "monolake": state.get("monolake", {}),
            "signals": state.get("signals", {}),
            "analyses": state.get("analyses", []),
            "dry_run": state.get("dry_run", False),
            "verbose": state.get("verbose", False),
            "pipeline_mode": mode,
            "_evaluator_type": etype,
            "evaluations": {},
            "errors": [],
            # ADR-007: bootstrap + memory key propagation
            "_prompt_overrides": state.get("_prompt_overrides", {}),
            "_extra_instructions": state.get("_extra_instructions", []),
            "memory_context": state.get("memory_context"),
            # Phase 2: tool definitions propagation for tool-augmented evaluators
            "_tool_definitions": state.get("_tool_definitions", []),
        }
        sends.append(Send("evaluator", send_state))
    return sends
