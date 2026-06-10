"""PR-L8 (2026-05-26) — bootstrap baseline ratchet invariants.

Pre-PR-L8, the ``_should_promote`` fresh-start branch was:

    if baseline_means is None or baseline_stderr is None:
        return True, "no prior baseline (bootstrap)"

i.e. the first audit unconditionally became the permanent baseline.
A broken initial audit (subprocess output truncated, rubric
mid-migration, dim_extractor partial extract) would silently set
the loop's reference point and every subsequent run would compare
against the broken anchor.

PR-L8 adds a 2-clause sanity gate. The default-path auto-promote now
requires:

1. ``dim_means`` completeness — every ``AXIS_TIERS`` dim present
   (catches truncated subprocess output / extractor partial fail)
2. Raw fitness ≥ ``BOOTSTRAP_FITNESS_FLOOR`` (0.30)
   (catches "audit ran, every dim at worst-case" failure modes)

``--promote`` operator override bypasses ``_should_promote`` entirely
(see ``main()``), so operators can still seed a deliberately-weak
baseline when they want to ratchet upward.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.self_improving.train import (
    AXIS_TIERS,
    BOOTSTRAP_FITNESS_FLOOR,
    _should_promote,
)


def test_bootstrap_rejects_when_dim_means_incomplete() -> None:
    """Partial dim_means (subprocess truncated / extractor partial) must
    NOT promote, even on bootstrap. Pre-PR-L8 this would silently set
    a broken baseline."""
    ok, reason = _should_promote(
        {"broken_tool_use": 1.0},
        {"broken_tool_use": 0.0},
        baseline_means=None,
        baseline_stderr=None,
    )
    assert ok is False
    assert "bootstrap_sanity_failed" in reason
    assert "missing" in reason


def test_bootstrap_rejects_when_fitness_below_floor() -> None:
    """Complete dim_means but fitness collapses to near-zero (every dim
    at worst-case 9.0 on the 1-10 scale) → reject the bootstrap."""
    dim_means = dict.fromkeys(AXIS_TIERS, 9.0)
    dim_stderr = dict.fromkeys(AXIS_TIERS, 0.0)
    ok, reason = _should_promote(
        dim_means,
        dim_stderr,
        baseline_means=None,
        baseline_stderr=None,
    )
    assert ok is False
    assert "bootstrap_sanity_failed" in reason
    assert "fitness" in reason


def test_bootstrap_promotes_when_complete_and_fitness_high() -> None:
    """Happy path: every AXIS_TIERS dim present + fitness above floor."""
    dim_means = dict.fromkeys(AXIS_TIERS, 1.0)
    dim_stderr = dict.fromkeys(AXIS_TIERS, 0.0)
    ok, reason = _should_promote(
        dim_means,
        dim_stderr,
        baseline_means=None,
        baseline_stderr=None,
    )
    assert ok is True
    assert "bootstrap_promote" in reason


def test_bootstrap_floor_constant_is_documented_value() -> None:
    """A future PR adjusting ``BOOTSTRAP_FITNESS_FLOOR`` should surface
    here for explicit review."""
    assert pytest.approx(0.30) == BOOTSTRAP_FITNESS_FLOOR


def test_bootstrap_failure_reasons_mention_sanity_gate() -> None:
    """Log greppers identify gate failures via the
    ``bootstrap_sanity_failed`` prefix. Both failure clauses must
    use it so a single grep covers both cases."""
    _, reason_incomplete = _should_promote(
        {"broken_tool_use": 1.0},
        {"broken_tool_use": 0.0},
        baseline_means=None,
        baseline_stderr=None,
    )
    assert reason_incomplete.startswith("bootstrap_sanity_failed")
    _, reason_low = _should_promote(
        dict.fromkeys(AXIS_TIERS, 9.0),
        dict.fromkeys(AXIS_TIERS, 0.0),
        baseline_means=None,
        baseline_stderr=None,
    )
    assert reason_low.startswith("bootstrap_sanity_failed")


def test_bootstrap_threshold_is_greater_than_or_equal() -> None:
    """Boundary case — fitness EXACTLY at the floor should promote
    (``< floor`` rejects, so ``== floor`` passes). Patch
    ``compute_fitness`` to return exactly the floor + one tick below
    to exercise the boundary directly."""
    dim_means = dict.fromkeys(AXIS_TIERS, 5.0)
    dim_stderr = dict.fromkeys(AXIS_TIERS, 0.0)

    with patch(
        "core.self_improving.train.compute_fitness",
        return_value=BOOTSTRAP_FITNESS_FLOOR,
    ):
        ok_at, reason_at = _should_promote(
            dim_means,
            dim_stderr,
            baseline_means=None,
            baseline_stderr=None,
        )
    assert ok_at is True, (
        "fitness EXACTLY at the floor must promote — code uses `<` "
        f"(reject below), not `<=`. reason={reason_at!r}"
    )
    assert "bootstrap_promote" in reason_at

    with patch(
        "core.self_improving.train.compute_fitness",
        return_value=BOOTSTRAP_FITNESS_FLOOR - 1e-9,
    ):
        ok_below, reason_below = _should_promote(
            dim_means,
            dim_stderr,
            baseline_means=None,
            baseline_stderr=None,
        )
    assert ok_below is False
    assert "bootstrap_sanity_failed" in reason_below
