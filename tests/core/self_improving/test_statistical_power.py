"""E4 (2026-05-30) — statistical power: replicate variance decomposition, the
explicit "ci excludes 0" gain verdict, and the power-analysis sample-size formula.

Pins (matching the E4 deliverables + the operator's flagged knobs):

  1. M=1 default path is UNCHANGED — the replicate loop runs the audit exactly once
     (no cost / behaviour regression) and within-mutation variance is honestly left
     unestimated (``None``), not faked as 0.
  2. M>1 DECOMPOSES the noise — the within-mutation stderr (provider jitter across
     replicates) and the between-seed stderr (the N samples inside one audit) are
     reported SEPARATELY (no double-counting), with a synthetic check.
  3. The gain CI verdict — a clear gain excludes 0 ("gain significant"); a
     noise-level gain includes 0 ("no evidence yet"); and the verdict RECONCILES
     with the promote gate's σ-margin (no contradiction).
  4. The power formula is correct (a known σ/δ → a known N) and MONOTONIC (N grows
     with σ and with 1/δ²).
  5. Records carry the new fields BACKWARD-COMPATIBLY (M=1 / no-power-config → no
     new required key breaks readers).
"""

from __future__ import annotations

import pytest
from core.self_improving.loop import statistical_power as sp

# --- deliverable 1: variance decomposition (within vs between) ----------------


def test_m1_within_unestimated_combined_equals_between() -> None:
    """M=1 (default): a single replicate cannot observe within-mutation variance →
    within is honestly ``None`` (NOT 0), and combined == the between-seed stderr
    (today's single-σ path, unchanged)."""
    decomp = sp.decompose_variance(
        replicate_fitnesses=[0.62],
        replicate_between_seed_stderrs=[0.013],
    )
    assert decomp.replicate_count == 1
    assert decomp.within_mutation_stderr is None
    assert decomp.between_seed_stderr == pytest.approx(0.013)
    # combined treats the missing within as 0 → equals between exactly
    assert decomp.combined_stderr == pytest.approx(0.013)


def test_m1_dry_run_no_signal_combined_none() -> None:
    """M=1 with no bootstrap stderr (dry-run / <2 sample rows) → every component is
    ``None``: there is no variance signal at all (honest, not a fabricated 0)."""
    decomp = sp.decompose_variance(
        replicate_fitnesses=[0.5],
        replicate_between_seed_stderrs=[None],
    )
    assert decomp.within_mutation_stderr is None
    assert decomp.between_seed_stderr is None
    assert decomp.combined_stderr is None


def test_m_gt_1_decomposes_within_and_between_separately() -> None:
    """M>1 synthetic: the within-mutation stderr is the standard error of the
    per-replicate fitness spread, the between-seed stderr is the MEAN of the
    per-audit bootstrap stderrs, and they are reported as DISTINCT numbers (not
    conflated / double-counted)."""
    import statistics as _stats

    fitnesses = [0.60, 0.64, 0.62, 0.66]  # genuine replicate spread
    betweens = [0.010, 0.014, 0.012, 0.012]
    decomp = sp.decompose_variance(fitnesses, betweens)

    expected_within = _stats.stdev(fitnesses) / (len(fitnesses) ** 0.5)
    expected_between = _stats.fmean(betweens)
    assert decomp.within_mutation_stderr == pytest.approx(expected_within)
    assert decomp.between_seed_stderr == pytest.approx(expected_between)
    # the two are genuinely different sources — not the same number
    assert decomp.within_mutation_stderr != pytest.approx(decomp.between_seed_stderr)
    # combined is the orthogonal sum, NOT within+between (no double counting)
    assert decomp.combined_stderr == pytest.approx(
        (expected_within**2 + expected_between**2) ** 0.5
    )
    assert decomp.combined_stderr != pytest.approx(expected_within + expected_between)


def test_decompose_drops_nonfinite_replicates_gracefully() -> None:
    """Graceful contract: a NaN / inf / non-numeric replicate is dropped at the
    boundary (never raises) and simply does not contribute to the estimate."""
    decomp = sp.decompose_variance(
        replicate_fitnesses=[0.60, float("nan"), 0.64, "oops"],  # type: ignore[list-item]
        replicate_between_seed_stderrs=[0.01, None, float("inf"), 0.02],
    )
    # only the two clean fitnesses survive → within estimable from 2 points
    assert decomp.replicate_count == 2
    assert decomp.within_mutation_stderr is not None
    # only the two finite, non-negative betweens survive
    assert decomp.between_seed_stderr == pytest.approx(0.015)


# --- deliverable 2: "ci excludes 0" gain verdict ------------------------------


def test_clear_gain_excludes_zero_significant() -> None:
    """A gain much larger than its stderr → CI excludes 0 → 'gain significant'."""
    ev = sp.gain_ci_excludes_zero(gain=0.10, gain_stderr=0.01)
    assert ev.gain_ci_excludes_zero is True
    assert ev.verdict == sp.GAIN_SIGNIFICANT
    assert ev.ci_low > 0.0


def test_noise_level_gain_includes_zero_no_evidence() -> None:
    """A gain at / below the noise level → CI straddles 0 → honest 'no evidence
    yet' (NOT a false 'significant')."""
    ev = sp.gain_ci_excludes_zero(gain=0.005, gain_stderr=0.013)
    assert ev.gain_ci_excludes_zero is False
    assert ev.verdict == sp.NO_EVIDENCE_YET
    assert ev.ci_low <= 0.0


def test_negative_gain_never_significant() -> None:
    """A regression (negative gain) is never 'significant' on the positive side."""
    ev = sp.gain_ci_excludes_zero(gain=-0.05, gain_stderr=0.01)
    assert ev.gain_ci_excludes_zero is False
    assert ev.verdict == sp.NO_EVIDENCE_YET


def test_verdict_reconciles_with_promote_gate_margin() -> None:
    """The verdict must match the promote gate's σ-margin semantics: at
    DEFAULT_GAIN_CI_Z=1.0 the CI excludes 0 IFF ``gain > _MARGIN_GAIN_SIGMA *
    gain_stderr`` (the gate's binding condition, ignoring the zero-noise floor).
    No contradiction where the gate rejects but the verdict says 'significant'."""
    from core.self_improving.train import _MARGIN_GAIN_SIGMA

    assert sp.DEFAULT_GAIN_CI_Z == _MARGIN_GAIN_SIGMA == 1.0
    gain_stderr = 0.02
    # just below the gate margin → gate REJECTS → verdict must be no-evidence
    below = sp.gain_ci_excludes_zero(gain=gain_stderr * 0.99, gain_stderr=gain_stderr)
    assert below.gain_ci_excludes_zero is False
    # just above the gate margin → gate PROMOTES → verdict must be significant
    above = sp.gain_ci_excludes_zero(gain=gain_stderr * 1.01, gain_stderr=gain_stderr)
    assert above.gain_ci_excludes_zero is True


def test_gain_verdict_graceful_on_nan() -> None:
    """Graceful contract: a non-finite gain / stderr / floor never raises — it
    degrades to a no-evidence verdict."""
    ev = sp.gain_ci_excludes_zero(gain=float("nan"), gain_stderr=float("inf"))
    assert ev.gain_ci_excludes_zero is False
    assert ev.verdict == sp.NO_EVIDENCE_YET
    ev2 = sp.gain_ci_excludes_zero(gain=0.1, gain_stderr=0.0, floor=float("nan"))
    # a non-finite floor degrades to 0.0 → the σ-margin term still decides
    assert ev2.gain_ci_excludes_zero is True


def test_verdict_honours_gate_floor() -> None:
    """A small-positive gain BELOW the gate's zero-noise floor with ≈0 stderr must
    NOT be claimed significant — the gate rejects it on the floor, so the verdict
    must too (Codex MCP catch: the verdict previously ignored the floor and would
    falsely say 'significant')."""
    # gain 0.003 < floor 0.005, stderr 0 → ci_low = 0.003 > 0 BUT below floor
    ev = sp.gain_ci_excludes_zero(gain=0.003, gain_stderr=0.0, floor=0.005)
    assert ev.gain_ci_excludes_zero is False, "sub-floor gain must not be significant"
    assert ev.verdict == sp.NO_EVIDENCE_YET
    # a gain ABOVE the floor with ≈0 stderr IS significant (clears both terms)
    ev2 = sp.gain_ci_excludes_zero(gain=0.02, gain_stderr=0.0, floor=0.005)
    assert ev2.gain_ci_excludes_zero is True
    assert ev2.verdict == sp.GAIN_SIGNIFICANT


# --- deliverable 3: power-analysis formula ------------------------------------


def test_power_formula_known_sigma_delta_known_n() -> None:
    """A known (σ, δ) at α=0.05 / power=0.8 yields the textbook N.

    n = 2(z_{0.025}+z_{0.20})² σ²/δ² with z_{0.025}=1.95996, z_{0.20}=0.84162.
    For σ=0.013, δ=0.02: 2·(2.80158)²·(0.013²)/(0.02²) ≈ 6.63 → ceil → 7."""
    req = sp.required_samples(0.013, target_effect_size=0.02)
    assert req.n_seed == 7  # ceil(6.63)


def test_power_formula_monotonic_in_sigma() -> None:
    """N grows with σ (noisier measurement → more samples)."""
    n_small = sp.required_samples(0.01, target_effect_size=0.02).n_seed
    n_big = sp.required_samples(0.05, target_effect_size=0.02).n_seed
    assert n_small is not None and n_big is not None
    assert n_big > n_small


def test_power_formula_monotonic_in_inverse_delta_squared() -> None:
    """N grows with 1/δ² (smaller target effect → more samples). Halving δ should
    roughly quadruple N."""
    n_big_delta = sp.required_samples(0.02, target_effect_size=0.04).n_seed
    n_small_delta = sp.required_samples(0.02, target_effect_size=0.02).n_seed
    assert n_big_delta is not None and n_small_delta is not None
    assert n_small_delta > n_big_delta
    # quadratic relationship: δ/2 → ~4× N
    assert n_small_delta == pytest.approx(n_big_delta * 4, rel=0.25)


def test_power_formula_indeterminate_when_sigma_unknown() -> None:
    """Graceful: σ unknown (no variance observed yet) → N indeterminate, NOT a
    crash or a fabricated number."""
    req = sp.required_samples(None, target_effect_size=0.02)
    assert req.n_seed is None
    assert "indeterminate" in sp.format_power_line(req)


def test_power_formula_zero_sigma_needs_one_sample() -> None:
    """σ=0 (perfectly stable, no noise) → a single sample detects any δ>0."""
    req = sp.required_samples(0.0, target_effect_size=0.02)
    assert req.n_seed == 1


def test_power_formula_illposed_delta_graceful() -> None:
    """δ ≤ 0 is ill-posed (divide-by-zero) → indeterminate, not a crash."""
    req = sp.required_samples(0.013, target_effect_size=0.0)
    assert req.n_seed is None


def test_power_formula_nonfinite_delta_graceful() -> None:
    """δ = NaN must NOT slip past the ``δ <= 0`` guard into ``int(nan)`` (NaN
    comparisons are False) — it degrades to indeterminate, not a crash (Codex MCP
    catch)."""
    req = sp.required_samples(0.013, target_effect_size=float("nan"))
    assert req.n_seed is None
    req2 = sp.required_samples(0.013, target_effect_size=float("inf"))
    assert req2.n_seed is None


def test_power_formula_malformed_replicate_graceful() -> None:
    """A malformed ``replicate`` count degrades to 1, never raises (graceful cast).
    Includes ``float('inf')`` which raises OverflowError on ``int()`` (Codex MCP
    catch — the guard must catch OverflowError too)."""
    req = sp.required_samples(0.013, target_effect_size=0.02, replicate="oops")  # type: ignore[arg-type]
    assert req.replicate == 1
    assert req.n_seed == 7  # the rest of the formula is unaffected
    req_inf = sp.required_samples(0.013, target_effect_size=0.02, replicate=float("inf"))  # type: ignore[arg-type]
    assert req_inf.replicate == 1
    assert req_inf.n_seed == 7


def test_power_line_real_campaign_shape() -> None:
    """The per-campaign line for the real N≈8-10 / observed stderr≈0.013 case the
    operator launches 10 cycles under: it names δ, α, power, σ, and the required
    N_seed × M_replicate honestly."""
    req = sp.required_samples(0.013, target_effect_size=0.02, replicate=1)
    line = sp.format_power_line(req)
    assert "delta=0.0200" in line
    assert "alpha=0.05" in line
    assert "sigma=0.0130" in line
    assert "N_seed>=7" in line
    assert "M_replicate>=1" in line
