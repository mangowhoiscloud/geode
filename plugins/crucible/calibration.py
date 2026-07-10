"""Derive Crucible contract parameters from measured evidence.

Every number a train plan freezes — pack size, trials per task, confidence
level, quality floor — is derived here from fitted models plus explicit
economic inputs, and stamped into the contract as a ``parameter_derivation``
block whose inputs are content-hashed. A contract number without a derivation
is a magic number; this module exists so there are none.

Three fitted layers feed one Monte Carlo design search:

- ``NoiseModel`` — per-task flakiness, fitted from a null paired run (two
  arms, no real effect: cross-arm discordance is pure noise) or from
  per-task trial counts of a champion repeat run.
- ``MutationClassPrior`` — Beta posteriors on a mutation class's fix rate and
  regression rate, fitted from replay-screening counts and pinned to the
  task-pack hash they were measured against. A prior fitted on one pack is
  stale for another (the phantom-prior guard).
- ``CostModel`` — operator economics: the conversation cost of a false train
  KEEP (one sealed test) versus a missed improvement (one more attempt), and
  the per-attempt conversation ceiling of a quota window.

The posterior-predictive core is ported from the retired
``scripts/eval/sequential_gate.py`` (G3b, validated on the 2026-07 clop48
data); its fixed rules (+3pp target, 0.05/0.95 bands) are replaced by derived
quantities.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from plugins.crucible.contract import ContractError, canonical_sha256

CALIBRATION_MODEL_VERSION = "crucible.calibration.v1"
_JEFFREYS = 0.5
# Instrument settings (not gate parameters): Monte Carlo resolution and the
# residual pass odds assumed for an unfixed deterministic-fail task until a
# calibration run fits it. Documented, versioned, and hashed with the model.
_DESIGN_SIMULATIONS = 1500
_RESIDUAL_FAIL_PASS_RATE = 0.05
_FIXED_TASK_PASS_RATE = 0.90


def _beta_sample(rng: random.Random, alpha: float, beta: float) -> float:
    x = rng.gammavariate(alpha, 1.0)
    y = rng.gammavariate(beta, 1.0)
    return x / (x + y)


@dataclass(frozen=True)
class NoiseModel:
    """Per-task flakiness under the parsimonious two-point model.

    A task is either deterministic (always passes or always fails a fixed
    arm) or flaky with per-trial pass probability one half. ``pi_flaky`` is
    the flaky mass. The two-point model is the most conservative single-moment
    fit; a calibration run with per-task trial counts refines it via
    :meth:`fit_from_trial_counts`.
    """

    pi_flaky: float
    source: str
    discordance: float | None = None

    @classmethod
    def fit_from_null_run(
        cls,
        *,
        flips: int,
        regressions: int,
        n_tasks: int,
        source: str,
    ) -> NoiseModel:
        """Fit from a paired run judged to have no real effect.

        Under no effect, a flaky task (pass odds one half per arm) is
        discordant across arms with probability one half; deterministic tasks
        are never discordant. One measured moment, one parameter.
        """
        if n_tasks <= 0 or flips < 0 or regressions < 0:
            raise ContractError("null run counts must be non-negative with n_tasks > 0")
        if flips + regressions > n_tasks:
            raise ContractError("discordant pairs cannot exceed task count")
        discordance = (flips + regressions) / n_tasks
        pi_flaky = min(1.0, discordance / 0.5)
        return cls(pi_flaky=pi_flaky, source=source, discordance=discordance)

    @classmethod
    def fit_from_trial_counts(
        cls,
        pass_counts: list[int],
        *,
        trials: int,
        source: str,
    ) -> NoiseModel:
        """Fit from one arm's per-task pass counts over ``trials`` trials.

        Tasks with an interior pass count (neither zero nor all trials) are
        directly observed flaky; a two-point model corrects for flaky tasks
        that landed on the boundary by chance (2 * 0.5**trials mass).
        """
        if trials < 2:
            raise ContractError("trial-count fit requires at least 2 trials per task")
        if not pass_counts:
            raise ContractError("trial-count fit requires at least one task")
        if any(count < 0 or count > trials for count in pass_counts):
            raise ContractError("pass counts must lie in [0, trials]")
        interior = sum(1 for count in pass_counts if 0 < count < trials)
        observed_interior_share = interior / len(pass_counts)
        boundary_leak = 2 * 0.5**trials
        pi_flaky = min(1.0, observed_interior_share / (1.0 - boundary_leak))
        return cls(pi_flaky=pi_flaky, source=source)

    def champion_repeat_sd(self, n_tasks: int, trials: int) -> float:
        """SD of a champion's own full-pack mean re-measurement."""
        return math.sqrt(self.pi_flaky * (0.25 / trials) / n_tasks)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"pi_flaky": self.pi_flaky, "source": self.source}
        if self.discordance is not None:
            row["discordance"] = self.discordance
        return row


@dataclass(frozen=True)
class MutationClassPrior:
    """Beta posteriors on a mutation class's fix and regression rates.

    ``task_pack_sha256`` pins the pack the evidence was measured against;
    deriving a design for a different pack raises unless explicitly refit
    (the phantom-prior guard — priors fitted on retired task definitions
    silently corrupt every downstream design).
    """

    class_name: str
    fix_alpha: float
    fix_beta: float
    regression_alpha: float
    regression_beta: float
    task_pack_sha256: str
    source: str

    @classmethod
    def from_replay_counts(
        cls,
        *,
        class_name: str,
        supported: int,
        targeted: int,
        false_blocks: int,
        controls: int,
        task_pack_sha256: str,
        source: str,
    ) -> MutationClassPrior:
        if not 0 <= supported <= targeted or targeted <= 0:
            raise ContractError("replay support counts are inconsistent")
        if not 0 <= false_blocks <= controls or controls <= 0:
            raise ContractError("replay control counts are inconsistent")
        return cls(
            class_name=class_name,
            fix_alpha=supported + _JEFFREYS,
            fix_beta=(targeted - supported) + _JEFFREYS,
            regression_alpha=false_blocks + _JEFFREYS,
            regression_beta=(controls - false_blocks) + _JEFFREYS,
            task_pack_sha256=task_pack_sha256,
            source=source,
        )

    def assert_fresh_for(self, task_pack_sha256: str) -> None:
        if self.task_pack_sha256 != task_pack_sha256:
            raise ContractError(
                f"class prior {self.class_name!r} was fitted against task pack "
                f"{self.task_pack_sha256[:12]}… but the contract freezes "
                f"{task_pack_sha256[:12]}… — refit or rescreen before deriving"
            )

    def expected_fix_rate(self) -> float:
        return self.fix_alpha / (self.fix_alpha + self.fix_beta)

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "fix_alpha": self.fix_alpha,
            "fix_beta": self.fix_beta,
            "regression_alpha": self.regression_alpha,
            "regression_beta": self.regression_beta,
            "task_pack_sha256": self.task_pack_sha256,
            "source": self.source,
        }


@dataclass(frozen=True)
class CostModel:
    """Operator economics in conversation units plus quota-window ceilings.

    ``false_keep_cost`` is what a false train KEEP burns downstream (one
    sealed test, in conversations). ``window_conversations`` caps one
    attempt's paired run so a design never exceeds a subscription quota
    window — the constraint that actually killed two sessions on 2026-07-10.
    ``materiality_pp`` is the smallest full-pack improvement worth promoting;
    it is an economic judgement (value of a point of reward), not a
    statistical one, and 0.0 is an honest choice for train stages.
    """

    false_keep_cost: float
    window_conversations: int
    materiality_pp: float = 0.0

    def alpha_star(self, attempt_conversations: int) -> float:
        """Derived train-gate error rate: retry cost over total error cost."""
        if attempt_conversations <= 0 or self.false_keep_cost <= 0:
            raise ContractError("cost model requires positive costs")
        return attempt_conversations / (attempt_conversations + self.false_keep_cost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "false_keep_cost": self.false_keep_cost,
            "window_conversations": self.window_conversations,
            "materiality_pp": self.materiality_pp,
        }


@dataclass(frozen=True)
class DesignPoint:
    n_tasks: int
    trials_per_task: int
    alpha: float
    power: float
    false_keep_rate: float
    conversations_per_attempt: int
    expected_attempts_to_keep: float
    expected_cost_per_true_keep: float


def _simulate_gate(
    rng: random.Random,
    *,
    noise: NoiseModel,
    prior: MutationClassPrior,
    n_tasks: int,
    trials: int,
    alpha: float,
    materiality_pp: float,
    with_effect: bool,
    enriched_flaky_share: float,
    simulations: int,
) -> float:
    """P(train gate fires) under the fitted generative model.

    The gate mirrors the frozen ``paired_bootstrap.v2`` shape: one-sided
    normal lower bound at level ``alpha`` must exceed zero and the point
    estimate must reach ``materiality_pp``. Both arms share each task's
    latent pass rate (paired), so enrichment selection bias cancels rather
    than leaking into the null.
    """
    z_alpha = _normal_upper_quantile(1 - alpha)
    fires = 0
    for _ in range(simulations):
        fix_rate = _beta_sample(rng, prior.fix_alpha, prior.fix_beta) if with_effect else 0.0
        deltas: list[float] = []
        for _task in range(n_tasks):
            if rng.random() < enriched_flaky_share:
                base_rate = cand_rate = 0.5
            else:
                base_rate = _RESIDUAL_FAIL_PASS_RATE
                cand_rate = _FIXED_TASK_PASS_RATE if rng.random() < fix_rate else base_rate
            base = sum(rng.random() < base_rate for _ in range(trials)) / trials
            cand = sum(rng.random() < cand_rate for _ in range(trials)) / trials
            deltas.append(cand - base)
        mean = sum(deltas) / n_tasks
        variance = sum((d - mean) ** 2 for d in deltas) / max(1, n_tasks - 1)
        lower_bound = mean - z_alpha * math.sqrt(variance / n_tasks)
        if lower_bound > 0 and mean >= materiality_pp:
            fires += 1
    return fires / simulations


def _normal_upper_quantile(p: float) -> float:
    """Acklam-style inverse normal CDF, stdlib-only, |error| < 1.2e-8."""
    if not 0 < p < 1:
        raise ContractError("quantile level must lie in (0, 1)")
    # Peter Acklam's rational approximation coefficients.
    a = (
        -39.6968302866538,
        220.946098424521,
        -275.928510446969,
        138.357751867269,
        -30.6647980661472,
        2.50662827745924,
    )
    b = (
        -54.4760987982241,
        161.585836858041,
        -155.698979859887,
        66.8013118877197,
        -13.2806815528857,
    )
    c = (
        -0.00778489400243029,
        -0.322396458041136,
        -2.40075827716184,
        -2.54973253934373,
        4.37466414146497,
        2.93816398269878,
    )
    d = (0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742)
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= 1 - p_low:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def derive_design(
    *,
    noise: NoiseModel,
    prior: MutationClassPrior,
    costs: CostModel,
    task_pack_sha256: str,
    enriched_flaky_share: float,
    candidate_pack_sizes: tuple[int, ...] = (15, 20, 30, 40),
    candidate_trials: tuple[int, ...] = (2, 3, 4),
    rng_seed: int = 0,
) -> dict[str, Any]:
    """Search (n, k) minimising expected cost per true KEEP; emit provenance.

    Returns a ``crucible.parameter-derivation.v1`` block. The chosen design's
    numbers are what a train plan must stamp; ``contract.PromotionRule``
    cross-checks stamped values against this block at load time.
    """
    prior.assert_fresh_for(task_pack_sha256)
    inputs = {
        "noise": noise.to_dict(),
        "class_prior": prior.to_dict(),
        "costs": costs.to_dict(),
        "enriched_flaky_share": enriched_flaky_share,
        "instrument": {
            "design_simulations": _DESIGN_SIMULATIONS,
            "residual_fail_pass_rate": _RESIDUAL_FAIL_PASS_RATE,
            "fixed_task_pass_rate": _FIXED_TASK_PASS_RATE,
            "rng_seed": rng_seed,
        },
    }
    rng = random.Random(rng_seed)
    best: DesignPoint | None = None
    grid: list[DesignPoint] = []
    for n_tasks in candidate_pack_sizes:
        for trials in candidate_trials:
            conversations = 2 * n_tasks * trials
            if conversations > costs.window_conversations:
                continue
            alpha = costs.alpha_star(conversations)
            power = _simulate_gate(
                rng,
                noise=noise,
                prior=prior,
                n_tasks=n_tasks,
                trials=trials,
                alpha=alpha,
                materiality_pp=costs.materiality_pp,
                with_effect=True,
                enriched_flaky_share=enriched_flaky_share,
                simulations=_DESIGN_SIMULATIONS,
            )
            false_keep = _simulate_gate(
                rng,
                noise=noise,
                prior=prior,
                n_tasks=n_tasks,
                trials=trials,
                alpha=alpha,
                materiality_pp=costs.materiality_pp,
                with_effect=False,
                enriched_flaky_share=enriched_flaky_share,
                simulations=_DESIGN_SIMULATIONS,
            )
            if power <= 0:
                continue
            expected_attempts = 1.0 / power
            expected_cost = conversations * expected_attempts + false_keep * costs.false_keep_cost
            point = DesignPoint(
                n_tasks=n_tasks,
                trials_per_task=trials,
                alpha=alpha,
                power=power,
                false_keep_rate=false_keep,
                conversations_per_attempt=conversations,
                expected_attempts_to_keep=expected_attempts,
                expected_cost_per_true_keep=expected_cost,
            )
            grid.append(point)
            if best is None or point.expected_cost_per_true_keep < best.expected_cost_per_true_keep:
                best = point
    if best is None:
        raise ContractError("no feasible design: every candidate (n, k) exceeds the quota window")
    return {
        "schema": "crucible.parameter-derivation.v1",
        "model_version": CALIBRATION_MODEL_VERSION,
        "inputs": inputs,
        "inputs_sha256": canonical_sha256(inputs),
        "derived": {
            "minimum_tasks": best.n_tasks,
            "trials_per_task": best.trials_per_task,
            "confidence_level": round(1 - best.alpha, 6),
            "materiality_pp": costs.materiality_pp,
            "expected_power": round(best.power, 4),
            "expected_false_keep_rate": round(best.false_keep_rate, 4),
            "expected_attempts_to_keep": round(best.expected_attempts_to_keep, 2),
            "conversations_per_attempt": best.conversations_per_attempt,
        },
        "grid": [
            {
                "n_tasks": point.n_tasks,
                "trials_per_task": point.trials_per_task,
                "power": round(point.power, 4),
                "false_keep_rate": round(point.false_keep_rate, 4),
                "expected_cost_per_true_keep": round(point.expected_cost_per_true_keep, 1),
            }
            for point in grid
        ],
    }
