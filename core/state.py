"""GeodeState — LangGraph state definition.

Domain layer: pure data models with no infrastructure dependencies.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator

from core.verification.rights_risk import RightsRiskResult

# ---------------------------------------------------------------------------
# Type aliases for Literal types (used by synthesizer.py etc.)
# ---------------------------------------------------------------------------

CauseLiteral = Literal[
    "undermarketed",
    "conversion_failure",
    "monetization_misfit",
    "niche_gem",
    "timing_mismatch",
    "discovery_failure",
]

ActionLiteral = Literal[
    "marketing_boost",
    "monetization_pivot",
    "platform_expansion",
    "timing_optimization",
    "community_activation",
]


# ---------------------------------------------------------------------------
# Pydantic models for structured LLM output
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel):
    analyst_type: str
    score: float = Field(ge=1, le=5)
    key_finding: str
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=100, default=80.0)
    is_degraded: bool = False
    model_provider: str | None = Field(
        default=None,
        description="LLM provider that produced this result",
    )


class EvaluatorResult(BaseModel):
    evaluator_type: str
    axes: dict[str, float]  # e.g. {"a_score": 4.2, "b_score": 3.8, ...}
    composite_score: float = Field(ge=0, le=100)
    rationale: str
    is_degraded: bool = False

    @model_validator(mode="after")
    def validate_axes(self) -> EvaluatorResult:
        """Validate that axes keys match evaluator_type and values are in [1.0, 5.0]."""
        from core.llm.prompts.axes import get_valid_axes_map

        valid_map = get_valid_axes_map()
        expected_keys = valid_map.get(self.evaluator_type)
        if expected_keys is None:
            raise ValueError(
                f"Unknown evaluator_type: {self.evaluator_type}. "
                f"Valid types: {list(valid_map.keys())}"
            )

        actual_keys = set(self.axes.keys())
        if not actual_keys.issubset(expected_keys):
            invalid_keys = actual_keys - expected_keys
            raise ValueError(
                f"Invalid axis keys for {self.evaluator_type}: {invalid_keys}. "
                f"Expected subset of: {expected_keys}"
            )

        # Guard against empty axes — LLM may return {} which passes subset check
        if not self.is_degraded and len(actual_keys) == 0:
            raise ValueError(f"Empty axes for {self.evaluator_type}. Expected: {expected_keys}")

        for key, value in self.axes.items():
            if not (1.0 <= value <= 5.0):
                raise ValueError(f"Axis '{key}' value {value} out of range [1.0, 5.0]")

        return self


class PSMResult(BaseModel):
    att_pct: float  # e.g. +31.2
    z_value: float
    rosenbaum_gamma: float
    max_smd: float
    exposure_lift_score: float = Field(ge=0, le=100)
    psm_valid: bool


class SynthesisResult(BaseModel):
    undervaluation_cause: str  # Was CauseLiteral — now str for domain-flexible values
    action_type: str  # Was ActionLiteral — now str for domain-flexible values
    value_narrative: str
    target_gamer_segment: str


class GuardrailResult(BaseModel):
    g1_schema: bool = True
    g2_range: bool = True
    g3_grounding: bool = True
    g4_consistency: bool = True
    all_passed: bool = True
    details: list[str] = Field(default_factory=list)


class BiasBusterResult(BaseModel):
    confirmation_bias: bool = False
    recency_bias: bool = False
    anchoring_bias: bool = False
    position_bias: bool = False
    verbosity_bias: bool = False
    self_enhancement_bias: bool = False
    overall_pass: bool = True
    explanation: str = ""


class AxisCalibration(BaseModel):
    """Per-axis calibration result against Golden Set reference range."""

    axis: str
    actual: float
    ref_low: float
    ref_high: float
    in_range: bool
    deviation: float = Field(
        ge=0, description="Distance from nearest range boundary (0 if in range)"
    )


class EvaluatorCalibration(BaseModel):
    """Per-evaluator calibration result."""

    evaluator_type: str
    axes: list[AxisCalibration] = Field(default_factory=list)
    axes_in_range_pct: float = Field(
        ge=0, le=100, description="Percentage of axes within reference range"
    )
    mean_deviation: float = Field(ge=0, description="Mean deviation from range boundaries")


class CalibrationResult(BaseModel):
    """Ground Truth calibration result for a single IP.

    Compares pipeline output against expert-annotated Golden Set.
    Components: tier match (20%), cause match (20%), score range (20%), axes accuracy (40%).
    """

    ip_name: str
    tier_match: bool
    tier_actual: str
    tier_expected: str
    cause_match: bool
    cause_actual: str
    cause_expected: str
    final_score_in_range: bool
    final_score_actual: float
    final_score_range: list[float] = Field(min_length=2, max_length=2)
    evaluator_results: list[EvaluatorCalibration] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=100, default=0.0)
    passed: bool = False
    details: list[str] = Field(default_factory=list)


class CalibrationReport(BaseModel):
    """Aggregate calibration report across all Golden Set IPs."""

    results: list[CalibrationResult] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=100, default=0.0)
    passed: bool = False
    summary: str = ""


# ---------------------------------------------------------------------------
# LangGraph reducers
# ---------------------------------------------------------------------------


def _merge_dicts(a: dict, b: dict) -> dict:  # type: ignore[type-arg]
    """Merge two dicts (LangGraph reducer for parallel Send results)."""
    return {**a, **b}


def ensure_analysis_results(raw: list[Any]) -> list[AnalysisResult]:
    """Rehydrate analyses that may have been deserialized to dicts by LangGraph."""
    out: list[AnalysisResult] = []
    for item in raw:
        if isinstance(item, AnalysisResult):
            out.append(item)
        elif isinstance(item, dict):
            out.append(AnalysisResult(**item))
    return out


def ensure_evaluator_results(raw: dict[str, Any]) -> dict[str, EvaluatorResult]:
    """Rehydrate evaluations that may have been deserialized to dicts by LangGraph."""
    out: dict[str, EvaluatorResult] = {}
    for key, item in raw.items():
        if isinstance(item, EvaluatorResult):
            out[key] = item
        elif isinstance(item, dict):
            out[key] = EvaluatorResult(**item)
    return out


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------


class GeodeState(TypedDict, total=False):
    # Input
    ip_name: str
    pipeline_mode: str  # full_pipeline, cortex_only, evaluation, scoring
    ip_type: str  # "gamified" (default) or "prospect" (non-gamified IP)
    session_id: str  # Hierarchical session key for 3-tier memory

    # Layer 1: Data Loading (Router)
    ip_info: dict[str, Any]
    monolake: dict[str, Any]
    memory_context: dict[str, Any]  # 3-tier merged context from ContextAssembler

    # Layer 2: Signals
    signals: dict[str, Any]

    # Layer 3: Analysts (accumulated via Send)
    analyses: Annotated[list[AnalysisResult], operator.add]

    # Layer 3: Evaluators (merged via _merge_dicts for parallel Send results)
    evaluations: Annotated[dict[str, EvaluatorResult], _merge_dicts]

    # Layer 4: Scoring
    psm_result: PSMResult
    subscores: dict[str, float]  # exposure_lift, quality, recovery, growth, momentum, developer
    analyst_confidence: float
    final_score: float
    tier: str

    # Layer 5: Synthesis
    synthesis: SynthesisResult

    # Verification
    guardrails: GuardrailResult
    biasbuster: BiasBusterResult
    cross_llm: dict[str, Any]
    rights_risk: RightsRiskResult
    calibration: CalibrationResult

    # Meta
    dry_run: bool
    verbose: bool
    skip_verification: bool
    errors: Annotated[list[str], operator.add]

    # Feedback Loop (L3)
    iteration: int  # Current iteration count (starts at 1)
    max_iterations: int  # Maximum allowed iterations before force-proceeding
    iteration_history: Annotated[list[dict[str, Any]], operator.add]  # Per-iteration snapshots

    # Telemetry
    run_id: str  # Unique pipeline execution ID

    # Internal (Send API)
    _analyst_type: str
    _evaluator_type: str  # Which evaluator to run (for Send API)
