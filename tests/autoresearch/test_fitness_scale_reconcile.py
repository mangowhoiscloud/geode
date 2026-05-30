"""PR-MARGIN-FITNESS-SCALE E1 (2026-05-30) — fitness_before/delta scale.

The self-improving loop recorded *two* numbers both called "fitness" on
incompatible scales:

- ``fitness_after`` = ``compute_fitness(...)`` — canonical FITNESS scale
  (0-1, HIGHER-is-better, e.g. baseline ≈ 0.79).
- ``fitness_before`` = ``mean(baseline_means)`` — the Petri ``dim_means``
  DIM-AGGREGATE (1-10, LOWER-is-better, e.g. ≈ 2.3). WRONG scale.

So ``fitness_delta = fitness_after - fitness_before`` subtracted a 1-10 dim
mean from a 0-1 fitness → nonsense (e.g. ≈ -1.7, deterministically negative).

E1 reconciles both sides to the single 0-1 ``compute_fitness`` scale via the
:func:`autoresearch.train._baseline_raw_fitness` helper (the shared SoT for
the attribution ledger's ``fitness_before`` and the few-shot/DPO pile's
``fitness_delta``). This file pins:

1. ``_baseline_raw_fitness`` returns the baseline's ``compute_fitness`` value
   (0-1), and is byte-for-byte equal to calling ``compute_fitness`` with the
   gate's ``prior_raw`` argument shape — NOT ``mean(baseline_means)``.
2. ``fitness_delta == fitness_after - fitness_before`` on the same 0-1 scale,
   so it is positive iff the current audit improved on the baseline.
3. The old bug is gone: ``fitness_before`` is NOT the dim-aggregate mean (and
   the two differ for any realistic dim_means).
4. No baseline → ``fitness_before`` is ``None`` (graceful, unchanged).
"""

from __future__ import annotations

from autoresearch.train import (
    ANCHOR_DIMS,
    AXIS_TIERS,
    _baseline_raw_fitness,
    compute_fitness,
)
from core.self_improving_loop.attribution import compute_attribution
from plugins.seed_generation.baseline_reader import BaselineSnapshot

# A complete dim_means over every AXIS_TIERS dim so the "missing dim = best
# case" fallback in compute_dim_scores does not silently inflate fitness and
# confuse the scale assertions. The baseline is mildly concerning (means ≈ 2-3
# on the 1-10 Petri scale); the current audit is uniformly *better* (lower
# means), so the FITNESS delta must come out positive.
_BASELINE_DIM_MEANS: dict[str, float] = dict.fromkeys(AXIS_TIERS, 2.0)
_CURRENT_DIM_MEANS: dict[str, float] = dict.fromkeys(AXIS_TIERS, 1.0)
_BASELINE_DIM_STDERR: dict[str, float] = dict.fromkeys(AXIS_TIERS, 0.1)
_CURRENT_DIM_STDERR: dict[str, float] = dict.fromkeys(AXIS_TIERS, 0.1)


def _prior_raw_reference(
    baseline_means: dict[str, float],
    baseline_stderr: dict[str, float],
) -> float:
    """Re-create the promote gate's ``prior_raw`` call shape verbatim.

    Mirrors ``_should_promote``'s ``prior_raw = compute_fitness(baseline_means,
    baseline_stderr, measurement_modality=..., anchor_means=<baseline anchor
    subset>, anchor_confidence_mode=..., admire_means=...)`` so the test pins
    that ``_baseline_raw_fitness`` produces the *same* baseline-side fitness the
    gate compares against (one scale, one function, both sides).
    """
    anchor_subset = {dim: baseline_means[dim] for dim in ANCHOR_DIMS if dim in baseline_means}
    return compute_fitness(
        baseline_means,
        baseline_stderr,
        measurement_modality=None,
        anchor_means=anchor_subset or None,
        anchor_confidence_mode=False,
        admire_means=None,
    )


def test_baseline_raw_fitness_is_0_1_compute_fitness_not_dim_mean() -> None:
    """``_baseline_raw_fitness`` returns the baseline's 0-1 ``compute_fitness``
    value — NOT the 1-10 ``mean(baseline_means)`` the buggy code wrote."""
    fitness_before = _baseline_raw_fitness(
        _BASELINE_DIM_MEANS,
        _BASELINE_DIM_STDERR,
        baseline_measurement_modality=None,
        baseline_admire_means=None,
        anchor_confidence_mode=False,
    )
    assert fitness_before is not None
    # On the canonical FITNESS scale (0-1, higher-is-better).
    assert 0.0 <= fitness_before <= 1.0
    # Byte-for-byte equal to the gate's prior_raw call shape.
    assert fitness_before == _prior_raw_reference(_BASELINE_DIM_MEANS, _BASELINE_DIM_STDERR)

    # The OLD bug: fitness_before used to be mean(baseline_means) = 2.0 (a 1-10
    # dim aggregate). Assert that exact wrong value is gone.
    dim_aggregate_mean = sum(_BASELINE_DIM_MEANS.values()) / len(_BASELINE_DIM_MEANS)
    assert dim_aggregate_mean == 2.0  # the old (wrong) number, for the record
    assert fitness_before != dim_aggregate_mean
    # And it is NOT on the 1-10 scale at all: dim mean 2.0 maps to a fitness
    # ≈ 0.8 (well below the old wrong value of 2.0), so they differ widely.
    assert abs(fitness_before - dim_aggregate_mean) > 0.5


def test_fitness_before_matches_compute_fitness_after_same_function() -> None:
    """``fitness_before`` and ``fitness_after`` are produced by the SAME
    ``compute_fitness`` function on the SAME 0-1 scale, so a direct comparison
    is meaningful."""
    fitness_before = _baseline_raw_fitness(
        _BASELINE_DIM_MEANS,
        _BASELINE_DIM_STDERR,
        baseline_measurement_modality=None,
        baseline_admire_means=None,
        anchor_confidence_mode=False,
    )
    # fitness_after is the current audit's compute_fitness (the train.py caller
    # passes the gated value; for the scale contract the relevant fact is that
    # both come from compute_fitness — use the raw current-side here).
    fitness_after = compute_fitness(_CURRENT_DIM_MEANS, _CURRENT_DIM_STDERR)
    assert fitness_before is not None
    assert 0.0 <= fitness_after <= 1.0
    # Current means (1.0) are lower-is-better-better than baseline (2.0) → the
    # FITNESS (higher-is-better) of the current side must exceed the baseline.
    assert fitness_after > fitness_before


def test_fitness_delta_is_after_minus_before_on_0_1_scale() -> None:
    """``compute_attribution`` computes ``fitness_delta = after - before`` and
    both sides are on the 0-1 scale, so the delta is the true fitness gain."""
    fitness_before = _baseline_raw_fitness(
        _BASELINE_DIM_MEANS,
        _BASELINE_DIM_STDERR,
        baseline_measurement_modality=None,
        baseline_admire_means=None,
        anchor_confidence_mode=False,
    )
    fitness_after = compute_fitness(_CURRENT_DIM_MEANS, _CURRENT_DIM_STDERR)
    assert fitness_before is not None
    payload = compute_attribution(
        mutation_id="e1-scale-check",
        expected_dim={},
        baseline_before=BaselineSnapshot(
            dim_means=dict(_BASELINE_DIM_MEANS),
            dim_stderr=dict(_BASELINE_DIM_STDERR),
        ),
        baseline_after=BaselineSnapshot(
            dim_means=dict(_CURRENT_DIM_MEANS),
            dim_stderr=dict(_CURRENT_DIM_STDERR),
        ),
        fitness_before=fitness_before,
        fitness_after=fitness_after,
    )
    expected_delta = round(fitness_after - fitness_before, 6)
    assert payload["fitness_before"] == round(fitness_before, 6)
    assert payload["fitness_after"] == round(fitness_after, 6)
    assert payload["fitness_delta"] == expected_delta
    # Improvement → strictly positive (and a sane 0-1-magnitude number, NOT the
    # old ≈ -1.7 mixed-scale artefact).
    assert payload["fitness_delta"] > 0.0
    assert -1.0 <= payload["fitness_delta"] <= 1.0


def test_fitness_delta_old_mixed_scale_artefact_is_gone() -> None:
    """Regression guard for the exact pre-E1 nonsense. The old code computed
    ``fitness_after - mean(baseline_means)`` — a 0-1 value minus a 1-10 value,
    which for an *improving* mutation came out deterministically negative.
    With the fix the delta is positive for the same improvement."""
    fitness_after = compute_fitness(_CURRENT_DIM_MEANS, _CURRENT_DIM_STDERR)
    old_mixed_scale_delta = fitness_after - (
        sum(_BASELINE_DIM_MEANS.values()) / len(_BASELINE_DIM_MEANS)
    )
    # The old artefact: a strongly negative number for an improving mutation.
    assert old_mixed_scale_delta < -0.5

    fitness_before = _baseline_raw_fitness(
        _BASELINE_DIM_MEANS,
        _BASELINE_DIM_STDERR,
        baseline_measurement_modality=None,
        baseline_admire_means=None,
        anchor_confidence_mode=False,
    )
    assert fitness_before is not None
    fixed_delta = fitness_after - fitness_before
    # The fixed delta is positive (real improvement) — opposite sign to the bug.
    assert fixed_delta > 0.0
    assert fixed_delta != old_mixed_scale_delta


def test_no_baseline_yields_none_fitness_before() -> None:
    """Graceful contract — no baseline (first audit / N=0) → ``None``, NOT a
    crash and NOT a fabricated zero."""
    assert (
        _baseline_raw_fitness(
            None,
            None,
            baseline_measurement_modality=None,
            baseline_admire_means=None,
            anchor_confidence_mode=False,
        )
        is None
    )
    assert (
        _baseline_raw_fitness(
            {},
            {},
            baseline_measurement_modality=None,
            baseline_admire_means=None,
            anchor_confidence_mode=False,
        )
        is None
    )
