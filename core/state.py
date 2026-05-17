"""Generic GEODE workflow state types.

Specialized pipeline state models live outside GEODE core. Core keeps only the
small shared shape needed by generic orchestration, verification, and runtime
plumbing.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

_ITERATION_HISTORY_MAX = 10


def _add_and_trim_history(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append iteration history and keep only the latest entries."""
    merged = left + right
    return merged[-_ITERATION_HISTORY_MAX:]


def _merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two dicts for parallel graph reducers."""
    return {**a, **b}


class GuardrailResult(BaseModel):
    """Generic verification guardrail result."""

    g1_schema: bool = True
    g2_range: bool = True
    g3_grounding: bool = True
    g4_consistency: bool = True
    all_passed: bool = True
    details: list[str] = Field(default_factory=list)
    grounding_ratio: float = 0.0


class GeodeState(TypedDict, total=False):
    """Shared state fields owned by GEODE core.

    External packages may extend this TypedDict with task-specific model fields.
    """

    subject_id: str
    session_id: str
    output_language: str
    memory_context: dict[str, Any]
    inputs: dict[str, Any]
    signals: dict[str, Any]
    analyses: Annotated[list[dict[str, Any]], operator.add]
    evaluations: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    result: dict[str, Any]
    guardrails: GuardrailResult
    cross_llm: dict[str, Any]
    dry_run: bool
    verbose: bool
    skip_verification: bool
    errors: Annotated[list[str], operator.add]
    skip_nodes: list[str]
    skipped_nodes: Annotated[list[str], operator.add]
    enrichment_needed: bool
    iteration: int
    max_iterations: int
    iteration_history: Annotated[list[dict[str, Any]], _add_and_trim_history]
    run_id: str
