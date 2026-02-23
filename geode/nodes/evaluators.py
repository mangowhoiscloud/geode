"""Layer 3: Evaluators — 3 parallel evaluators using 14-axis rubric.

Supports Send API pattern for parallel execution (like analysts).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from geode.infrastructure.ports.llm_port import get_llm_json
from geode.llm.prompts import EVALUATOR_AXES, EVALUATOR_SYSTEM, EVALUATOR_USER
from geode.state import AnalysisResult, EvaluatorResult, GeodeState

log = logging.getLogger(__name__)

EVALUATOR_TYPES = ["quality_judge", "hidden_value", "community_momentum"]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _format_axes_schema(evaluator_type: str) -> str:
    axes: dict[str, str] = EVALUATOR_AXES[evaluator_type]["axes"]  # type: ignore[assignment]
    parts = [f'"{k}": <float 1-5 — {v}>' for k, v in axes.items()]
    return ", ".join(parts)


def _format_rubric_anchors(evaluator_type: str) -> str:
    """Format per-level rubric anchors for the evaluator prompt."""
    rubric: dict[str, dict[str, str]] = EVALUATOR_AXES[evaluator_type].get("rubric", {})  # type: ignore[assignment]
    if not rubric:
        return ""
    axes_desc: dict[str, str] = EVALUATOR_AXES[evaluator_type]["axes"]  # type: ignore[assignment]
    lines = ["## Rubric Anchors (1=Poor, 3=Good, 5=Outstanding)"]
    for key, anchors in rubric.items():
        desc = axes_desc.get(key, key)
        lines.append(f"- {key} ({desc}): 1={anchors['1']}, 3={anchors['3']}, 5={anchors['5']}")
    formula = EVALUATOR_AXES[evaluator_type].get("composite_formula", "")
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

    system = EVALUATOR_SYSTEM.format(
        evaluator_type=evaluator_type,
        axes_schema=_format_axes_schema(evaluator_type),
    ) + "\n\n" + _format_rubric_anchors(evaluator_type)
    user = EVALUATOR_USER.format(
        ip_name=ip["ip_name"],
        ip_summary=ip_summary,
        analyst_findings=analyst_findings,
        signals_summary=signals_summary,
        evaluator_type=evaluator_type,
        rubric_anchors=_format_rubric_anchors(evaluator_type),
    )
    return system, user


def _run_evaluator(evaluator_type: str, state: GeodeState) -> EvaluatorResult:
    if state.get("dry_run"):
        return _dry_run_result(evaluator_type, state.get("ip_name", ""))

    system, user = _build_evaluator_prompt(evaluator_type, state)
    if state.get("verbose"):
        log.debug("Running %s evaluator...", evaluator_type)
    data = get_llm_json()(system, user)
    try:
        return EvaluatorResult(**data)
    except ValidationError as ve:
        log.warning("Evaluator %s LLM response failed schema validation: %s", evaluator_type, ve)
        default_axes: dict[str, dict[str, float]] = {
            "quality_judge": {
                "a_score": 1.0, "b_score": 1.0, "c_score": 1.0, "b1_score": 1.0,
                "c1_score": 1.0, "c2_score": 1.0, "m_score": 1.0, "n_score": 1.0,
            },
            "hidden_value": {"d_score": 1.0, "e_score": 1.0, "f_score": 1.0},
            "community_momentum": {"j_score": 1.0, "k_score": 1.0, "l_score": 1.0},
        }
        return EvaluatorResult(
            evaluator_type=evaluator_type,
            axes=default_axes.get(evaluator_type, {"d_score": 1.0, "e_score": 1.0, "f_score": 1.0}),
            composite_score=0.0,
            rationale="LLM response failed validation (degraded)",
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
            composite_score=81.25,  # (4.2+4.0+4.3+3.9+4.1+4.0+3.8+4.2)/8*20
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
            composite_score=80.25,  # (4.5+4.2+4.4+3.8+3.8+3.6+3.8+4.0)/8*20
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
            composite_score=69.25,  # (3.8+3.5+3.6+3.3+3.4+3.2+3.4+3.5)/8*20
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

    ip_mocks = {
        "cowboy bebop": cowboy_bebop,
        "berserk": berserk,
        "ghost in the shell": ghost_in_shell,
    }

    mock = ip_mocks.get(key, cowboy_bebop)
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


def make_evaluator_sends(state: GeodeState) -> list:
    """Create Send objects for all 3 evaluators."""
    from langgraph.types import Send

    sends = []
    for etype in EVALUATOR_TYPES:
        send_state = {
            "ip_name": state.get("ip_name", ""),
            "ip_info": state.get("ip_info", {}),
            "monolake": state.get("monolake", {}),
            "signals": state.get("signals", {}),
            "analyses": state.get("analyses", []),
            "dry_run": state.get("dry_run", False),
            "verbose": state.get("verbose", False),
            "_evaluator_type": etype,
            "evaluations": {},
            "errors": [],
        }
        sends.append(Send("evaluator", send_state))
    return sends
