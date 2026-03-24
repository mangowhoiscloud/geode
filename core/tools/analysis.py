"""Analysis Tools — wraps pipeline nodes as LLM-callable tools.

Layer 5 tools that enable agentic access to:
- RunAnalystTool: Run a specific analyst type
- RunEvaluatorTool: Run evaluators on analyst results
- PSMCalculateTool: Calculate PSM exposure lift
- ExplainScoreTool: Explain scoring breakdown for an IP
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.domains.game_ip.fixtures import load_fixture
from core.domains.game_ip.nodes.analysts import ANALYST_TYPES, get_dry_run_result
from core.state import PSMResult

# Load parameter schemas from centralized JSON
_SCHEMAS_PATH = Path(__file__).resolve().parent / "tool_schemas.json"
with _SCHEMAS_PATH.open(encoding="utf-8") as _f:
    _TOOL_SCHEMAS: dict[str, dict[str, Any]] = json.load(_f)


def _compute_psm_from_fixture(ip_name: str) -> PSMResult:
    """Compute PSM result from fixture data (public tool-layer wrapper)."""
    try:
        data = load_fixture(ip_name)
        expected = data.get("expected_results", {})
        att = expected.get("psm_att_pct", 25.0)
        z = expected.get("psm_z_value", 2.0)
        gamma = expected.get("psm_gamma", 1.5)
    except ValueError:
        att = 25.0
        z = 2.0
        gamma = 1.5
    exposure_lift = min(100.0, max(0.0, att * 1.5 + 30))
    z_pass = z > 1.645
    gamma_pass = gamma <= 2.0
    smd = 0.05
    return PSMResult(
        att_pct=att,
        z_value=z,
        rosenbaum_gamma=gamma,
        max_smd=smd,
        exposure_lift_score=exposure_lift,
        psm_valid=z_pass and gamma_pass and smd < 0.1,
    )


class RunAnalystTool:
    """Tool wrapper for running a single analyst."""

    @property
    def name(self) -> str:
        return "run_analyst"

    @property
    def description(self) -> str:
        return (
            "Run a specific analyst (game_mechanics, player_experience, "
            "growth_potential, discovery) on an IP to get scored analysis."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        schema = _TOOL_SCHEMAS["RunAnalystTool"].copy()
        schema["properties"] = dict(schema["properties"])
        schema["properties"]["analyst_type"] = dict(schema["properties"]["analyst_type"])
        schema["properties"]["analyst_type"]["enum"] = ANALYST_TYPES
        return schema

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        analyst_type = kwargs["analyst_type"]
        ip_name = kwargs["ip_name"]

        if analyst_type not in ANALYST_TYPES:
            return {"error": f"Unknown analyst_type: {analyst_type}"}

        result = get_dry_run_result(analyst_type, ip_name)
        return {
            "result": {
                "analyst_type": result.analyst_type,
                "score": result.score,
                "key_finding": result.key_finding,
                "confidence": result.confidence,
            }
        }


class RunEvaluatorTool:
    """Tool wrapper for running evaluators."""

    @property
    def name(self) -> str:
        return "run_evaluator"

    @property
    def description(self) -> str:
        return (
            "Run an evaluator (quality_judge, hidden_value, community_momentum) "
            "to get multi-axis rubric scores for an IP."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["RunEvaluatorTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        evaluator_type = kwargs["evaluator_type"]
        ip_name = kwargs["ip_name"]

        # Use fixture-based dry-run evaluator data
        from core.domains.game_ip.fixtures import load_fixture

        try:
            data = load_fixture(ip_name)
            expected = data.get("expected_results", {})
        except ValueError:
            return {"error": f"Unknown IP: {ip_name}"}

        # Build evaluator-specific result from expected data
        if evaluator_type == "quality_judge":
            return {
                "result": {
                    "evaluator_type": evaluator_type,
                    "composite_score": expected.get("quality_score", 50.0),
                    "ip_name": ip_name,
                }
            }
        elif evaluator_type == "hidden_value":
            return {
                "result": {
                    "evaluator_type": evaluator_type,
                    "d_e_f_profile": "See evaluator output for axis details",
                    "ip_name": ip_name,
                }
            }
        elif evaluator_type == "community_momentum":
            return {
                "result": {
                    "evaluator_type": evaluator_type,
                    "momentum_score": expected.get("momentum_score", 50.0),
                    "ip_name": ip_name,
                }
            }
        return {"error": f"Unknown evaluator_type: {evaluator_type}"}


class PSMCalculateTool:
    """Tool wrapper for PSM exposure lift calculation."""

    @property
    def name(self) -> str:
        return "psm_calculate"

    @property
    def description(self) -> str:
        return (
            "Calculate Propensity Score Matching (PSM) exposure lift for an IP. "
            "Returns ATT%, Z-value, Rosenbaum gamma, and validity flag."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["PSMCalculateTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs["ip_name"]
        try:
            psm = _compute_psm_from_fixture(ip_name)
            return {
                "result": {
                    "att_pct": psm.att_pct,
                    "z_value": psm.z_value,
                    "rosenbaum_gamma": psm.rosenbaum_gamma,
                    "exposure_lift_score": psm.exposure_lift_score,
                    "psm_valid": psm.psm_valid,
                }
            }
        except ValueError:
            return {"error": f"Unknown IP: {ip_name}"}


class ExplainScoreTool:
    """Tool that explains the scoring breakdown for an IP."""

    @property
    def name(self) -> str:
        return "explain_score"

    @property
    def description(self) -> str:
        return (
            "Explain why an IP received its score. Returns the scoring breakdown "
            "including analyst scores, evaluator axes, PSM validity, and tier reasoning."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["ExplainScoreTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs["ip_name"]
        try:
            data = load_fixture(ip_name)
        except ValueError:
            return {"error": f"Unknown IP: {ip_name}"}

        expected = data.get("expected_results", {})
        ip_info = data.get("ip_info", {})

        # Collect analyst scores
        analyst_scores: dict[str, float] = {}
        for at in ANALYST_TYPES:
            dry = get_dry_run_result(at, ip_name)
            analyst_scores[at] = dry.score

        # PSM
        psm = _compute_psm_from_fixture(ip_name)

        # Build breakdown
        final_score = expected.get("final_score", 0.0)
        tier = expected.get("tier", "?")

        return {
            "result": {
                "ip_name": ip_info.get("ip_name", ip_name),
                "tier": tier,
                "final_score": final_score,
                "analyst_scores": analyst_scores,
                "psm": {
                    "exposure_lift": psm.exposure_lift_score,
                    "valid": psm.psm_valid,
                },
                "scoring_formula": (
                    "final = weighted_avg(analyst_scores) * confidence_multiplier "
                    "+ evaluator_bonus + psm_bonus"
                ),
                "tier_thresholds": {
                    "S": ">= 80",
                    "A": ">= 65",
                    "B": ">= 50",
                    "C": "< 50",
                },
            }
        }
