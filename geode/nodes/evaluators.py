"""Layer 3: Evaluators — 3 parallel evaluators using 14-axis rubric."""

from __future__ import annotations

from geode.llm.client import call_llm_json
from geode.llm.prompts import EVALUATOR_AXES, EVALUATOR_SYSTEM, EVALUATOR_USER
from geode.state import AnalysisResult, EvaluatorResult, GeodeState
from geode.ui.console import console

EVALUATOR_TYPES = ["quality_judge", "hidden_value", "community_momentum"]


def _format_axes_schema(evaluator_type: str) -> str:
    axes: dict[str, str] = EVALUATOR_AXES[evaluator_type]["axes"]  # type: ignore[assignment]
    parts = [f'"{k}": <float 1-5 — {v}>' for k, v in axes.items()]
    return ", ".join(parts)


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
    )
    user = EVALUATOR_USER.format(
        ip_name=ip["ip_name"],
        ip_summary=ip_summary,
        analyst_findings=analyst_findings,
        signals_summary=signals_summary,
        evaluator_type=evaluator_type,
    )
    return system, user


def _run_evaluator(evaluator_type: str, state: GeodeState) -> EvaluatorResult:
    if state.get("dry_run"):
        return _dry_run_result(evaluator_type, state.get("ip_name", ""))

    system, user = _build_evaluator_prompt(evaluator_type, state)
    if state.get("verbose"):
        console.print(f"    [muted]Running {evaluator_type} evaluator...[/muted]")
    data = call_llm_json(system, user)
    return EvaluatorResult(**data)


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
            composite_score=82.0,
            rationale=(
                "Strong IP-game adaptation potential with rich narrative "
                "hooks and engaging world design."
            ),
        ),
        "hidden_value": EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 5.0, "e_score": 2.0, "f_score": 4.0},
            composite_score=50.0,
            rationale=(
                "Extreme acquisition gap (D=5) with no active marketing. "
                "Low monetization gap (E=2) since no game exists to "
                "monetize. High expansion potential (F=4)."
            ),
        ),
        "community_momentum": EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 4.3, "k_score": 4.1, "l_score": 3.9},
            composite_score=78.0,
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
            composite_score=80.0,
            rationale=(
                "Berserk's dark fantasy world is ideally suited for Souls-like "
                "adaptation. Previous game was poor execution, not IP weakness. "
                "Elden Ring proves massive demand for this genre."
            ),
        ),
        "hidden_value": EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 4.0, "e_score": 4.5, "f_score": 4.5},
            composite_score=83.0,
            rationale=(
                "Massive fandom-to-game conversion gap. Both marketing and "
                "monetization severely underperformed. High expansion potential "
                "across platforms with Souls-like genre demand."
            ),
        ),
        "community_momentum": EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 4.8, "k_score": 4.6, "l_score": 4.5},
            composite_score=92.0,
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
            composite_score=72.0,
            rationale=(
                "Good IP-game fit for stealth/cyberpunk but prior games "
                "were average. Needs AAA-quality execution."
            ),
        ),
        "hidden_value": EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 2.0, "e_score": 2.0, "f_score": 2.0},
            composite_score=25.0,
            rationale=(
                "No single undervaluation axis is dominant. Complex, "
                "multi-factor discovery failure."
            ),
        ),
        "community_momentum": EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 3.5, "k_score": 3.3, "l_score": 3.0},
            composite_score=62.0,
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


def evaluators_node(state: GeodeState) -> dict:
    """Run all 3 evaluators (sequentially for simplicity, parallel in production)."""
    results: dict[str, EvaluatorResult] = {}
    for etype in EVALUATOR_TYPES:
        results[etype] = _run_evaluator(etype, state)
    return {"evaluations": results}
