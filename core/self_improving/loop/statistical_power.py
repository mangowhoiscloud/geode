"""Statistical power + evidence statements for the self-improving fitness loop.

E4 (2026-05-30). The loop must only CLAIM a fitness gain when statistics
support it — otherwise it must report an HONEST NULL ("no evidence yet"), and
it must tell the operator how many samples are needed to detect a target effect.
This module is the statistics layer that backs those three operator deliverables;
the wiring (CLI arg, M-loop, record fields) lives in ``core/self_improving/train.py``.

Three responsibilities, kept pure (no I/O, no global state) so they are unit-
testable in isolation:

1. :func:`decompose_variance` — split the observed fitness noise into the
   WITHIN-mutation component (provider non-determinism, estimated across the
   ``--replicate M`` repeated audits of the SAME mutation/cycle) and the
   BETWEEN-seed component (seed heterogeneity, the N samples inside one audit,
   estimated by the per-audit bootstrap stderr). Keeping the two distinct stops
   the loop from double-counting noise or from mistaking provider jitter for a
   real seed-set signal.

2. :func:`gain_ci_excludes_zero` — the operator's explicit evidence rule: a gain
   is CLAIMED only when the confidence interval on the fitness GAIN excludes 0.
   Returns the CI bounds + a boolean + a human verdict string. This is layered
   ON TOP of the promote gate, not a replacement: see the reconciliation note on
   the function (the gate's ``margin = max(_MARGIN_GAIN_SIGMA·gain_stderr, floor)``
   IS effectively this same one-sided rule at :data:`DEFAULT_GAIN_CI_Z`).

3. :func:`required_samples` — given the observed combined σ, a target effect size
   δ, α and power, the standard two-sample mean-difference sample size
   ``n ≈ 2(z_{α/2}+z_β)²σ²/δ²``. :func:`format_power_line` renders the per-campaign
   operator line ("to detect δ=… at 80% power you need N≈… × M≈…").

SCALE / DIRECTION CONTRACT
--------------------------
Everything here is on the canonical FITNESS scale: 0-1, HIGHER-is-better (the
``compute_fitness`` output), NOT the Petri 1-10 ``dim_means`` aggregate (which is
lower-is-better). A positive ``gain`` therefore means improvement, and a CI that
excludes 0 on the *positive* side is the only "gain significant" verdict. δ is a
fitness-scale effect size for the same reason. This module never touches dims, so
the lower-is-better/higher-is-better confusion cannot arise inside it; the caller
guarantees it passes fitness-scale values.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import NormalDist, fmean, stdev

# --- knobs (config / arg-overridable at the caller) --------------------------

DEFAULT_TARGET_EFFECT_SIZE = 0.02
"""Default fitness-scale effect size δ to power for.

FLAGGED KNOB (E4). ~0.02 sits just above the promote gate's zero-noise floor
(``fitness_margin_floor = 0.005``) and is roughly 1.5× the empirically-observed
fitness-aggregate stderr of a real ~8-sample baseline (~0.013, measured
2026-05-30; see ``train.py`` ``_MARGIN_GAIN_SIGMA`` comment). Powering for a
smaller δ would demand an impractically large N; powering for a much larger δ
would tell the operator they need fewer samples than are needed to clear the
gate's own noise band — so ~0.02 is the smallest gain the loop can realistically
both detect AND promote. Operator-overridable via ``--target-effect-size`` /
config ``target_effect_size`` so a campaign can target a different δ."""

DEFAULT_ALPHA = 0.05
"""Two-sided significance level for both the gain CI and the power formula."""

DEFAULT_POWER = 0.8
"""Target statistical power (1 − β) for :func:`required_samples`."""

DEFAULT_GAIN_CI_Z = 1.0
"""Half-width multiplier (in σ units) for the gain CI the verdict reports.

FLAGGED KNOB (E4 — CI method). We use the NORMAL-APPROXIMATION CI
(``gain ± z·gain_stderr``), NOT a bootstrap resample of the gain. Justification:
(a) the gain's stderr is ALREADY a bootstrap estimate on the fitness aggregate
(``_fitness_stderr_bootstrap`` resamples whole sample rows and recomputes
``compute_fitness``), so a second bootstrap layer on top would re-bootstrap an
already-bootstrapped quantity for negligible accuracy gain at real cost; (b) the
normal-approx keeps this module pure + deterministic (no RNG seed to thread,
matching the loop's reproducibility constraint); (c) it makes the verdict
RECONCILE EXACTLY with the promote gate, which already compares the gain against
``_MARGIN_GAIN_SIGMA·gain_stderr`` (``_MARGIN_GAIN_SIGMA = 1.0``) — see
:func:`gain_ci_excludes_zero`. ``DEFAULT_GAIN_CI_Z = 1.0`` is therefore the SAME
band the gate uses, so the two never contradict. (A two-sided 95% CI would use
z≈1.96; we keep z=1.0 deliberately to mirror the gate's one-σ margin. The
``alpha`` arg is still recorded for the operator's reference + the power line.)"""


@dataclass(frozen=True)
class VarianceDecomposition:
    """Within-mutation vs between-seed fitness-noise split (E4 deliverable 1)."""

    within_mutation_stderr: float | None
    """Stderr of the per-replicate fitness across the ``M`` repeated audits of the
    SAME mutation (provider non-determinism). ``None`` when ``M < 2`` (the default
    ``M=1`` path leaves this UNESTIMATED, exactly as before E4 — no behaviour
    change)."""
    between_seed_stderr: float | None
    """Mean of the per-audit bootstrap fitness-stderr across the replicates (the N
    seeds inside one audit; seed heterogeneity). ``None`` when no replicate
    supplied a bootstrap stderr (dry-run / <2 sample rows)."""
    combined_stderr: float | None
    """Total fitness stderr ``√(within² + between²)`` for the power formula.
    ``None`` only when BOTH components are ``None``. When one component is missing
    it is treated as 0 (the other dominates), so an ``M=1`` run still yields the
    between-seed stderr as the combined σ — identical to today's single-σ path."""
    replicate_count: int
    """``M`` — the number of repeated audits the decomposition was built from."""


def decompose_variance(
    replicate_fitnesses: list[float],
    replicate_between_seed_stderrs: list[float | None],
) -> VarianceDecomposition:
    """Split observed fitness noise into within-mutation + between-seed components.

    ``replicate_fitnesses`` is the aggregate fitness from each of the ``M`` repeated
    audits of the SAME mutation/cycle (one scalar per replicate).
    ``replicate_between_seed_stderrs`` is the per-audit bootstrap fitness-stderr
    (the N-seed noise) from each replicate, ``None`` for any replicate that could
    not estimate it (dry-run / <2 sample rows).

    The two variance sources are estimated SEPARATELY (no double counting):

    - WITHIN-mutation: ``stdev(replicate_fitnesses) / √M`` — the standard error of
      the per-replicate mean, i.e. how much the WHOLE-audit fitness wobbles when
      the only thing that changed is the provider's run-to-run non-determinism
      (same mutation, same seeds). Requires ``M ≥ 2``; ``None`` otherwise (the
      ``M=1`` default cannot observe within-mutation variance, so it is honestly
      left unestimated rather than faked as 0).
    - BETWEEN-seed: the MEAN of the replicates' bootstrap stderrs — the seed
      heterogeneity already captured inside a single audit's N samples. Averaging
      across replicates (rather than picking one) uses all the information when
      ``M > 1`` and is identical to the single value when ``M = 1``.

    ``combined_stderr = √(within² + between²)`` treats a missing component as 0 so
    the surviving component dominates — an ``M=1`` run therefore reports the
    between-seed stderr unchanged as the combined σ (today's behaviour), and a
    dry-run with neither yields ``None``.

    Graceful contract: non-finite / non-numeric replicate values are dropped at
    the boundary (each ``float(...)`` cast is guarded) so a malformed replicate
    never raises — it simply does not contribute to the estimate.
    """
    clean_fitnesses: list[float] = []
    for fitness_value in replicate_fitnesses:
        try:
            f = float(fitness_value)
        except (TypeError, ValueError):
            continue
        if isfinite(f):  # drop NaN / inf
            clean_fitnesses.append(f)

    clean_between: list[float] = []
    for stderr_value in replicate_between_seed_stderrs:
        if stderr_value is None:
            continue
        try:
            b = float(stderr_value)
        except (TypeError, ValueError):
            continue
        if isfinite(b) and b >= 0.0:
            clean_between.append(b)

    replicate_count = len(clean_fitnesses)

    within = stdev(clean_fitnesses) / (replicate_count**0.5) if replicate_count >= 2 else None

    between: float | None = fmean(clean_between) if clean_between else None

    if within is None and between is None:
        combined: float | None = None
    else:
        w = within if within is not None else 0.0
        b = between if between is not None else 0.0
        combined = (w * w + b * b) ** 0.5

    return VarianceDecomposition(
        within_mutation_stderr=within,
        between_seed_stderr=between,
        combined_stderr=combined,
        replicate_count=replicate_count,
    )


@dataclass(frozen=True)
class GainEvidence:
    """Explicit "ci excludes 0" evidence statement on a fitness gain (E4 #2)."""

    gain: float
    """Observed fitness gain on the 0-1 scale (``current - baseline``, HIGHER-is-
    better → positive = improvement)."""
    gain_stderr: float
    """Stderr of the gain (``√(σ_current² + σ_baseline²)``) — the SAME quantity the
    promote gate's margin scales."""
    ci_low: float
    ci_high: float
    """Normal-approx CI bounds: ``gain ± DEFAULT_GAIN_CI_Z · gain_stderr``."""
    gain_ci_excludes_zero: bool
    """``True`` iff the CI lies entirely ABOVE 0 (``ci_low > 0``) AND the gain clears
    the gate's zero-noise ``floor`` — a CLAIMED gain. A CI straddling 0 (or below
    it), OR a gain inside the floor, is NOT evidence of a gain. (The floor term is
    what keeps the verdict from claiming significance on a sub-floor gain the gate
    rejects — see :func:`gain_ci_excludes_zero`.)"""
    verdict: str
    """Human evidence string: ``"gain significant"`` when the CI excludes 0 on the
    positive side, else ``"no evidence yet"`` (honest null)."""
    alpha: float
    """Significance level recorded for the operator's reference."""


GAIN_SIGNIFICANT = "gain significant"
NO_EVIDENCE_YET = "no evidence yet"


def gain_ci_excludes_zero(
    gain: float,
    gain_stderr: float,
    *,
    z: float = DEFAULT_GAIN_CI_Z,
    alpha: float = DEFAULT_ALPHA,
    floor: float = 0.0,
) -> GainEvidence:
    """Compute the explicit "ci excludes 0" evidence statement for a fitness gain.

    The operator's rule: claim a gain ONLY when the gain's confidence interval
    excludes 0. This makes that decision EXPLICIT and human-readable so a null run
    reports ``"no evidence yet"`` honestly rather than looking like a silent gate
    reject.

    RECONCILIATION WITH THE PROMOTE GATE (no contradiction by construction)
    -----------------------------------------------------------------------
    The promote gate (``train.py`` ``_should_promote``) promotes iff
    ``current_raw > prior_raw + margin`` where
    ``margin = max(_MARGIN_GAIN_SIGMA · gain_stderr, floor)`` and
    ``_MARGIN_GAIN_SIGMA = 1.0``. This verdict reproduces BOTH terms of that
    ``max`` so it NEVER claims significance on a gain the gate rejects:

    - σ-margin term: ``gain > 1.0 · gain_stderr`` ⇔ ``gain - z·gain_stderr > 0``
      ⇔ ``ci_low > 0`` at ``z = DEFAULT_GAIN_CI_Z = 1.0`` (the gate's
      ``_MARGIN_GAIN_SIGMA``). When the caller passes the SAME ``gain_stderr``
      (``√(σp²+σc²)``) the gate uses, the CI-excludes-0 test and the gate's σ-margin
      are the IDENTICAL inequality.
    - floor term: ``gain > floor`` reproduces the gate's zero-noise ``floor`` (the
      ``max``'s second argument — the effective floor, i.e. the N=1-widened floor
      when applicable). Without it, a small-positive gain with ≈0 stderr would have
      ``ci_low > 0`` (significant) while the gate rejects on the floor — exactly the
      contradiction E4 must avoid. Pass ``floor=0.0`` (default) only when the caller
      has no floor to honour (the pure-stats unit tests); the live caller passes the
      gate's effective floor.

    A gain is therefore "gain significant" iff ``ci_low > 0`` AND ``gain > floor`` —
    the conjunction the gate's ``current_raw > prior_raw + max(σ-margin, floor)``
    enforces. The verdict can still be "no evidence yet" on a gain the gate's N=1 /
    critical-axis SAFETY widenings additionally reject (those are the gate's to own),
    but it can NEVER be "significant" where the gate's margin rejects. The gate stays
    authoritative for promotion; this never weakens it.

    Graceful contract: a non-numeric / non-finite ``gain``, ``gain_stderr`` or
    ``floor`` is coerced to a safe value (``0.0``) so the verdict path never raises
    on a malformed input — it simply reports no evidence.
    """
    try:
        gain_value = float(gain)
    except (TypeError, ValueError):
        gain_value = 0.0
    if not isfinite(gain_value):
        gain_value = 0.0
    try:
        stderr_value = float(gain_stderr)
    except (TypeError, ValueError):
        stderr_value = 0.0
    if not isfinite(stderr_value) or stderr_value < 0.0:
        stderr_value = 0.0
    try:
        floor_value = float(floor)
    except (TypeError, ValueError):
        floor_value = 0.0
    if not isfinite(floor_value) or floor_value < 0.0:
        floor_value = 0.0

    half_width = z * stderr_value
    ci_low = gain_value - half_width
    ci_high = gain_value + half_width
    # Both the gate's margin terms: the CI must exclude 0 (σ-margin) AND the gain
    # must clear the zero-noise floor — the conjunction the gate's
    # max(σ-margin, floor) enforces, so the verdict never contradicts the gate.
    excludes_zero = ci_low > 0.0 and gain_value > floor_value
    return GainEvidence(
        gain=gain_value,
        gain_stderr=stderr_value,
        ci_low=ci_low,
        ci_high=ci_high,
        gain_ci_excludes_zero=excludes_zero,
        verdict=GAIN_SIGNIFICANT if excludes_zero else NO_EVIDENCE_YET,
        alpha=alpha,
    )


@dataclass(frozen=True)
class PowerRequirement:
    """Sample-size requirement to detect a target effect (E4 deliverable 3)."""

    sigma: float
    target_effect_size: float
    alpha: float
    power: float
    n_seed: int | None
    """Required N_seed per arm to detect ``target_effect_size`` at ``power``.
    ``None`` when σ is unknown (no variance observed yet) or δ ≤ 0 (an
    ill-posed request — graceful, not a crash)."""
    replicate: int
    """The ``M`` (replicate) the campaign actually ran — recorded alongside N so
    the operator reads the requirement as ``N≈… × M≈…``."""


def required_samples(
    sigma: float | None,
    *,
    target_effect_size: float = DEFAULT_TARGET_EFFECT_SIZE,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    replicate: int = 1,
) -> PowerRequirement:
    """Standard two-sample mean-difference sample size to DETECT ``δ``.

    ``n ≈ 2 · (z_{α/2} + z_β)² · σ² / δ²`` per arm, rounded UP (``ceil``) so the
    reported N is sufficient, not merely close. This is the textbook power formula
    for comparing two independent means (current campaign vs baseline / control
    arm) at two-sided significance ``alpha`` and ``power`` (1 − β).

    - ``z_{α/2}`` is the two-sided critical value (``alpha=0.05 → 1.96``).
    - ``z_β`` is the power quantile (``power=0.8 → 0.8416``).

    Monotonicity (pinned by tests): N increases with σ² and with 1/δ² — noisier
    measurements and smaller target effects both demand more samples.

    Graceful contract: ``sigma is None`` (no variance observed yet), a non-finite /
    negative σ, or ``δ ≤ 0`` (ill-posed) all yield ``n_seed = None`` rather than a
    divide-by-zero / domain crash — the operator simply sees "N≈? (insufficient
    variance signal)" in :func:`format_power_line`. σ == 0 (perfectly stable, no
    noise) yields ``n_seed = 1`` (a single sample detects any δ > 0 when there is
    no noise)."""
    if sigma is None:
        sigma_value: float | None = None
    else:
        try:
            sigma_value = float(sigma)
        except (TypeError, ValueError):
            sigma_value = None
        if sigma_value is not None and (not isfinite(sigma_value) or sigma_value < 0.0):
            sigma_value = None

    try:
        delta = float(target_effect_size)
    except (TypeError, ValueError):
        delta = 0.0
    # NaN must NOT slip past ``delta <= 0.0`` (NaN comparisons are False) into the
    # divide → ``int(nan)`` would raise. Force a non-finite δ to the ill-posed 0.0.
    if not isfinite(delta):
        delta = 0.0

    # ``replicate`` is a count for display only — guard the cast so a malformed
    # value (a stray non-int, or ``float("inf")`` which raises OverflowError on
    # ``int()``) degrades to 1 rather than raising.
    try:
        replicate_count = max(1, int(replicate))
    except (TypeError, ValueError, OverflowError):
        replicate_count = 1

    n_seed: int | None
    if sigma_value is None or delta <= 0.0:
        n_seed = None
    elif sigma_value == 0.0:
        n_seed = 1
    else:
        z_alpha = NormalDist().inv_cdf(1.0 - alpha / 2.0)
        z_beta = NormalDist().inv_cdf(power)
        raw_n = 2.0 * (z_alpha + z_beta) ** 2 * (sigma_value**2) / (delta**2)
        # ceil without importing math.ceil: int() truncates toward zero, add 1
        # unless already an exact integer. raw_n is always finite + > 0 here
        # (sigma_value > 0, delta > 0, both finite).
        truncated = int(raw_n)
        n_seed = truncated if truncated == raw_n else truncated + 1
        n_seed = max(1, n_seed)

    return PowerRequirement(
        sigma=sigma_value if sigma_value is not None else 0.0,
        target_effect_size=delta,
        alpha=alpha,
        power=power,
        n_seed=n_seed,
        replicate=replicate_count,
    )


@dataclass(frozen=True)
class PowerRecordFields:
    """The E4 fields persisted on a record row (attribution / baseline registry).

    A single bundle so the record-writer signatures take ONE E4 argument instead of
    six (keeps ``_write_baseline`` / ``_append_baseline_registry_row`` under the
    ``max-args`` ratchet). Every field is ``None``-omitting at the writer: ``M=1``
    leaves ``within_mutation_stderr`` ``None`` (unestimated, honest), and a pre-E4
    caller passes ``None`` for the whole bundle → no E4 keys are written (legacy
    row shape preserved)."""

    within_mutation_stderr: float | None = None
    between_seed_stderr: float | None = None
    gain_ci_low: float | None = None
    gain_ci_high: float | None = None
    gain_ci_excludes_zero: bool | None = None
    gain_verdict: str | None = None

    @classmethod
    def from_evidence(
        cls,
        decomposition: VarianceDecomposition,
        evidence: GainEvidence,
    ) -> PowerRecordFields:
        """Build the record bundle from the decomposition + the gain verdict."""
        return cls(
            within_mutation_stderr=decomposition.within_mutation_stderr,
            between_seed_stderr=decomposition.between_seed_stderr,
            gain_ci_low=evidence.ci_low,
            gain_ci_high=evidence.ci_high,
            gain_ci_excludes_zero=evidence.gain_ci_excludes_zero,
            gain_verdict=evidence.verdict,
        )


def format_power_line(requirement: PowerRequirement) -> str:
    """Render the per-campaign operator power line.

    Example: ``"power: to detect delta=0.0200 fitness at 80% power (alpha=0.05),
    observed sigma=0.0130 -> need N_seed>=10 x M_replicate>=1"``.

    When σ could not be estimated yet (``n_seed is None``) the line says so
    honestly rather than printing a fabricated N.
    """
    if requirement.n_seed is None:
        return (
            f"power: to detect delta={requirement.target_effect_size:.4f} fitness "
            f"at {requirement.power:.0%} power (alpha={requirement.alpha:.2f}), "
            f"observed sigma=unknown -> N_seed indeterminate "
            f"(insufficient variance signal; run --replicate M>=2 or a multi-sample "
            f"audit to estimate sigma)"
        )
    return (
        f"power: to detect delta={requirement.target_effect_size:.4f} fitness "
        f"at {requirement.power:.0%} power (alpha={requirement.alpha:.2f}), "
        f"observed sigma={requirement.sigma:.4f} -> "
        f"need N_seed>={requirement.n_seed} x M_replicate>={requirement.replicate}"
    )


__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_GAIN_CI_Z",
    "DEFAULT_POWER",
    "DEFAULT_TARGET_EFFECT_SIZE",
    "GAIN_SIGNIFICANT",
    "NO_EVIDENCE_YET",
    "GainEvidence",
    "PowerRecordFields",
    "PowerRequirement",
    "VarianceDecomposition",
    "decompose_variance",
    "format_power_line",
    "gain_ci_excludes_zero",
    "required_samples",
]
