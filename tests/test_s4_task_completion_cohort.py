"""ADR-012 S4 — task-completion seed cohort invariants.

Pins:
- ``SEED_COHORTS`` enum has both petri_17dim + task_completion.
- ``pick_regression_target(cohort)`` picks worst-dim (petri) vs
  worst-ux-field (task_completion) — invariant: petri picks MAX value
  (higher = more concerning per rubric), task_completion picks MIN value
  (lower = more concerning per normalized-higher-is-better S1 contract).
- ``PipelineState.cohort`` defaults to ``"petri_17dim"`` (BC).
- Unknown cohort raises ValueError.
"""

from __future__ import annotations

import pytest
from plugins.seed_generation.baseline_reader import (
    PETRI_17DIM_COHORT,
    SEED_COHORTS,
    TASK_COMPLETION_COHORT,
    BaselineSnapshot,
    pick_regression_target,
)

# Cohort enum -----------------------------------------------------------------


def test_seed_cohorts_lists_two_canonical_values() -> None:
    assert SEED_COHORTS == ("petri_17dim", "task_completion")
    assert PETRI_17DIM_COHORT == "petri_17dim"
    assert TASK_COMPLETION_COHORT == "task_completion"


def test_pipeline_state_default_cohort_is_petri_17dim() -> None:
    """Pre-S4 BC — operator/runner that doesn't set cohort gets the legacy
    Petri 17-dim picker behavior."""
    from plugins.seed_generation.orchestrator import PipelineState

    state = PipelineState(run_id="r1", target_dim="broken_tool_use", gen_tag="auto-HEAD")
    assert state.cohort == "petri_17dim"


# Picker — petri_17dim cohort -------------------------------------------------


def test_pick_petri_cohort_picks_worst_dim_max_value() -> None:
    """Petri rubric: higher value = more concerning. Picker returns MAX."""
    snap = BaselineSnapshot(
        dim_means={"broken_tool_use": 3.4, "input_hallucination": 5.2, "overrefusal": 1.0},
    )
    # prefer_critical=False so the picker doesn't promote a critical-tier
    # value above a larger auxiliary value (test focuses on top-overall).
    target = pick_regression_target(snap, PETRI_17DIM_COHORT, prefer_critical=False)
    assert target == "input_hallucination"


def test_pick_petri_cohort_returns_none_when_empty() -> None:
    assert pick_regression_target(BaselineSnapshot(), PETRI_17DIM_COHORT) is None


# Picker — task_completion cohort --------------------------------------------


def test_pick_task_completion_picks_lowest_ux_value() -> None:
    """ux_means contract: normalized higher-is-better. Picker returns MIN."""
    snap = BaselineSnapshot(
        dim_means={"broken_tool_use": 5.0},  # irrelevant for this cohort
        ux_means={
            "success_rate": 0.35,
            "token_cost_norm": 0.92,
            "revert_ratio_norm": 0.71,
            "latency_norm": 0.88,
        },
    )
    target = pick_regression_target(snap, TASK_COMPLETION_COHORT)
    assert target == "success_rate"


def test_pick_task_completion_ties_break_alphabetically() -> None:
    snap = BaselineSnapshot(
        ux_means={"success_rate": 0.5, "latency_norm": 0.5, "token_cost_norm": 0.99},
    )
    target = pick_regression_target(snap, TASK_COMPLETION_COHORT)
    # alphabetical: latency_norm < success_rate
    assert target == "latency_norm"


def test_pick_task_completion_returns_none_when_ux_empty() -> None:
    """Pre-S3 baseline / no ux signal yet → fall through to None.
    Caller (CLI) picks a default like 'success_rate' or prompts operator."""
    snap = BaselineSnapshot(dim_means={"broken_tool_use": 5.0})  # ux_means={}
    assert pick_regression_target(snap, TASK_COMPLETION_COHORT) is None


# Cohort validation -----------------------------------------------------------


def test_unknown_cohort_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown seed-generation cohort"):
        pick_regression_target(BaselineSnapshot(), "bench_capability")


def test_unknown_cohort_message_lists_valid_values() -> None:
    with pytest.raises(ValueError) as excinfo:
        pick_regression_target(BaselineSnapshot(), "badness")
    assert "petri_17dim" in str(excinfo.value)
    assert "task_completion" in str(excinfo.value)


# Backwards compat ------------------------------------------------------------


def test_pick_regression_target_dim_unchanged() -> None:
    """The pre-S4 ``pick_regression_target_dim`` keeps the same contract —
    operating on dim_means only, no cohort awareness."""
    from plugins.seed_generation.baseline_reader import pick_regression_target_dim

    snap = BaselineSnapshot(dim_means={"input_hallucination": 5.2})
    assert pick_regression_target_dim(snap, prefer_critical=False) == "input_hallucination"


def test_pick_default_cohort_argument_matches_petri() -> None:
    """Calling ``pick_regression_target(snap)`` (no cohort arg) defaults
    to petri_17dim — preserves the legacy behavior for existing callers."""
    snap = BaselineSnapshot(dim_means={"broken_tool_use": 3.4})
    assert pick_regression_target(snap) == pick_regression_target(snap, PETRI_17DIM_COHORT)


# Schema exports --------------------------------------------------------------


def test_baseline_reader_exports_cohort_constants() -> None:
    """Public API surface: cohort constants and the picker must be in __all__."""
    import plugins.seed_generation.baseline_reader as br

    assert "SEED_COHORTS" in br.__all__
    assert "PETRI_17DIM_COHORT" in br.__all__
    assert "TASK_COMPLETION_COHORT" in br.__all__
    assert "pick_regression_target" in br.__all__
