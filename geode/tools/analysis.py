"""Analysis Tools — wraps pipeline nodes as LLM-callable tools.

Layer 5 tools that enable agentic access to:
- RunAnalystTool: Run a specific analyst type
- RunEvaluatorTool: Run evaluators on analyst results
- PSMCalculateTool: Calculate PSM exposure lift
"""

from __future__ import annotations

from typing import Any

from geode.fixtures import load_fixture
from geode.nodes.analysts import ANALYST_TYPES, get_dry_run_result
from geode.state import PSMResult


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
        return {
            "type": "object",
            "properties": {
                "analyst_type": {
                    "type": "string",
                    "enum": ANALYST_TYPES,
                    "description": "The analyst type to run.",
                },
                "ip_name": {
                    "type": "string",
                    "description": "IP name to analyze (e.g., 'Berserk').",
                },
            },
            "required": ["analyst_type", "ip_name"],
        }

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
        return {
            "type": "object",
            "properties": {
                "evaluator_type": {
                    "type": "string",
                    "enum": ["quality_judge", "hidden_value", "community_momentum"],
                    "description": "The evaluator type to run.",
                },
                "ip_name": {
                    "type": "string",
                    "description": "IP name to evaluate.",
                },
            },
            "required": ["evaluator_type", "ip_name"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        evaluator_type = kwargs["evaluator_type"]
        ip_name = kwargs["ip_name"]

        # Use fixture-based dry-run evaluator data
        from geode.fixtures import load_fixture

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
        return {
            "type": "object",
            "properties": {
                "ip_name": {
                    "type": "string",
                    "description": "IP name to calculate PSM for.",
                },
            },
            "required": ["ip_name"],
        }

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
