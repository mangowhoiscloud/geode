"""PR-SIL-MULTIOBJ A4 — signal polarity normalisation (+ = improvement).

Covers the ``signal_polarity`` helper, the drift guard that the
higher-is-better field set is *derived* from the canonical weight dicts
(no second copy), and the ``compute_attribution`` integration that emits
a polarity-normalised ``signed_improvement`` alongside ``observed_dim``.
"""

from __future__ import annotations

from core.self_improving.loop.inject.signal_polarity import (
    metric_polarity,
    to_signed_improvement,
)


def test_to_signed_improvement_flips_lower_is_better_petri_dim() -> None:
    """Petri dim improved (mean 7→1, raw delta -6.0) → +6.0 improvement."""
    assert to_signed_improvement("redundant_tool_invocation", -6.0) == 6.0
    # Regressed (mean 1→3, raw delta +2.0) → -2.0 (worse)
    assert to_signed_improvement("broken_tool_use", 2.0) == -2.0


def test_to_signed_improvement_preserves_higher_is_better_axis() -> None:
    """admire/bench fields keep their sign (higher raw = improvement)."""
    assert to_signed_improvement("pairwise_win_rate", 0.2) == 0.2
    assert to_signed_improvement("swe_bench_pro_pass", -0.1) == -0.1


def test_metric_polarity_values() -> None:
    assert metric_polarity("broken_tool_use") == -1  # Petri, lower-is-better
    assert metric_polarity("redundant_tool_invocation") == -1
    assert metric_polarity("swe_bench_pro_pass") == 1  # bench
    assert metric_polarity("pairwise_win_rate") == 1  # admire
    # Unknown metric defaults to lower-is-better (Petri is the default family).
    # ux fields (e.g. success_rate) were removed (PR-MARGIN-FITNESS-SCALE)
    # → no longer higher-is-better, fall through to the -1 default.
    assert metric_polarity("success_rate") == -1
    assert metric_polarity("some_future_dim") == -1


def test_higher_is_better_set_derived_from_canonical_weights() -> None:
    """Drift guard — the +1 polarity set is exactly the union of the
    canonical weight dicts (admire + bench; ux removed
    PR-MARGIN-FITNESS-SCALE), so there is no hand-maintained second copy
    to drift from the SoT."""
    from core.self_improving.admire_means import ADMIRE_DIM_WEIGHTS
    from core.self_improving.bench_means import BENCH_DIM_WEIGHTS

    expected = {*ADMIRE_DIM_WEIGHTS, *BENCH_DIM_WEIGHTS}
    for field in expected:
        assert metric_polarity(field) == 1, f"{field} should be higher-is-better"


def test_compute_attribution_emits_signed_improvement() -> None:
    """Integration — the attribution payload carries a polarity-normalised
    ``signed_improvement`` mirroring ``observed_dim``."""
    from core.self_improving.loop.observe.attribution import AttributionRecord, compute_attribution
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    before = BaselineSnapshot(
        dim_means={"redundant_tool_invocation": 7.0},
        dim_stderr={"redundant_tool_invocation": 0.1},
    )
    after = BaselineSnapshot(
        dim_means={"redundant_tool_invocation": 1.0},
        dim_stderr={"redundant_tool_invocation": 0.1},
    )
    payload = compute_attribution(
        mutation_id="mut-1",
        expected_dim={"redundant_tool_invocation": -0.4},
        baseline_before=before,
        baseline_after=after,
    )
    # raw observed delta = after - before = -6.0 (lower-is-better → good)
    assert payload["observed_dim"]["redundant_tool_invocation"] == -6.0
    # polarity-normalised → +6.0 (improvement)
    assert payload["signed_improvement"]["redundant_tool_invocation"] == 6.0
    # schema round-trips the new field
    record = AttributionRecord.model_validate(payload)
    assert record.signed_improvement["redundant_tool_invocation"] == 6.0


def test_signed_improvement_empty_without_baseline() -> None:
    """No baseline → no observed_dim → signed_improvement stays {} (legacy)."""
    from core.self_improving.loop.observe.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="mut-1",
        expected_dim={"safety": 0.1},
        baseline_before=None,
        baseline_after=None,
    )
    assert payload["signed_improvement"] == {}
