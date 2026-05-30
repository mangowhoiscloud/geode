"""Causal attribution for applied mutations.

PR-5 C-4 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

Pre-PR-5 ``mutations.jsonl`` recorded *what* was changed (target
section, new value, rationale) but not *what happened next* — only
the binary ``audit_failed → rollback`` signal was tracked. That made
it impossible to answer "which dim moved how much because of this
mutation?".

This module adds the second half of the ledger: after the next audit
the caller invokes :func:`compute_attribution` with the
``baseline_before`` and ``baseline_after`` snapshots; it computes:

  * ``observed_dim``  per-dim signed delta (``after - before``)
  * ``ci95``          per-dim 95% confidence interval half-width using
                      ``sqrt(stderr_before**2 + stderr_after**2) * 1.96``
                      (paired baseline CI from Karpathy's autoresearch
                      §5 ratchet pattern)
  * ``significant``   per-dim ``abs(delta) > ci95``
  * ``attribution_score``  scalar: sum over expected dims of
                           ``sign(expected) * observed`` clipped to
                           ``[-1, 1]``. Positive = mutation moved the
                           expected dims in the expected direction.

The result is appended to the same ``mutations.jsonl`` as a separate
row with ``kind="attribution"`` and the same ``mutation_id`` as the
``kind="applied"`` row written at apply time. Aggregation by
``mutation_id`` lets PR-6 (policy mutation) compute long-term rates
without changing the file format.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from core.self_improving_loop.signal_polarity import to_signed_improvement

if TYPE_CHECKING:
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH


class AttributionRecord(BaseModel):
    """Pydantic schema for ``mutations.jsonl`` attribution row (W4, 2026-05-25).

    Schema 정의는 ``compute_attribution()`` payload 와 1:1 매치.
    ``extra="allow"`` 로 legacy row 호환 + PR-E confidence_stability /
    PR-SIL-5THEME C4 fitness ledger / W3 audit_run_id 모두 optional.
    """

    model_config = ConfigDict(extra="allow")

    ts: float
    kind: str = Field(default="attribution", pattern=r"^attribution$")
    mutation_id: str
    observed_dim: dict[str, float] = Field(default_factory=dict)
    signed_improvement: dict[str, float] = Field(default_factory=dict)
    """PR-SIL-MULTIOBJ A4 (2026-05-29) — ``observed_dim`` polarity-
    normalised so ``+`` always means *improvement* and ``-`` *regression*,
    regardless of the metric's native direction (Petri dims are
    lower-is-better, so their sign is flipped here). Display/record only;
    fitness math is unchanged. Legacy rows omit the field → ``{}``."""
    ci95: dict[str, float] = Field(default_factory=dict)
    significant: dict[str, bool] = Field(default_factory=dict)
    attribution_score: float = 0.0
    missing_baseline: bool = True
    confidence_trajectory: list[float] = Field(default_factory=list)
    confidence_stability: float | None = None
    fitness_before: float | None = None
    fitness_after: float | None = None
    fitness_delta: float | None = None
    """``fitness_before`` / ``fitness_after`` / ``fitness_delta`` are on the
    canonical FITNESS scale: 0-1, HIGHER-is-better (the ``compute_fitness``
    output, NOT the 1-10 lower-is-better Petri ``dim_means`` aggregate).
    ``fitness_delta = fitness_after - fitness_before`` so a positive delta is
    an improvement on the same scale both sides share.

    PR-MARGIN-FITNESS-SCALE E1 (2026-05-30) reconciled the scale: before it,
    the autoresearch caller wrote ``mean(baseline_means)`` (1-10 dim mean) as
    ``fitness_before`` while ``fitness_after`` was already 0-1, so the delta
    mixed two incompatible scales. Pre-fix on-disk rows still carry that mixed
    scale — they are NOT rewritten (git-tracked ledger); a one-shot backfill
    is a documented follow-up. New rows are uniformly 0-1."""
    held_out_fitness: float | None = None
    held_out_bench_id: str | None = None
    """E2 (2026-05-30) — per-cycle fixed-ruler evidence. ``held_out_fitness`` is
    the SAME canonical 0-1 ``compute_fitness`` (HIGHER-is-better) measured on the
    VERSION-FROZEN held-out bench, NOT the co-evolving ``seed_select`` pool that
    produced ``fitness_after``. A curve built from this field across attribution
    rows (ordered by ``ts``) is therefore comparable ACROSS generations — the
    cross-generation evidence the moving-ruler ``fitness_after`` cannot give.
    ``held_out_bench_id`` is the bench's content-address (``pool-<hash>``), so a
    silent edit to the "frozen" set surfaces as an id change. Recorded on EVERY
    cycle when a held-out bench is configured (operator cadence); both fields are
    omitted together when no bench was scored, so legacy / no-bench rows validate
    as ``None`` via these defaults."""
    promote_policy: str | None = None
    promote_policy_seed: int | None = None
    """E3 (2026-05-30) — control-arm tag on the per-cycle held-out record so the
    three arms' fixed-ruler curves are distinguishable + comparable. ``promote_policy``
    is ``"gate"`` (selection arm), ``"random"`` (random-accept control), or
    ``"never"`` (no-mutation floor). ``promote_policy_seed`` is the explicit RNG
    seed RECORDED for the ``random`` arm (the per-cycle draw is
    ``Random(seed + cycle_index)``), so the random campaign is reproducible from
    the ledger; it is recorded for every arm (``0`` for gate / never) so the row
    is uniform. Legacy rows omit both → ``None`` via these defaults; a curve
    consumer filters the JSONL stream on ``promote_policy`` to split the arms."""
    audit_run_id: str | None = None
    source: str | None = None
    """PR-AR-L6 (2026-05-26) — distinguishes mutator-driven cycle rows
    (``"mutator"``) from operator manual ``--promote`` rows
    (``"manual"``). Legacy rows omit the field → ``None`` (downstream
    consumers can treat as ``"mutator"`` for backward compat).

    The field is a row-level *tag*; downstream consumers (operator
    analytics) can opt to filter the JSONL stream on it before
    aggregation — the source-aware filtering itself is a downstream
    caller concern, not implemented in this module."""


log = logging.getLogger(__name__)

# 95% confidence interval z-score for paired-baseline CI.
_Z95 = 1.96


def _dim_delta(before_means: dict[str, float], after_means: dict[str, float]) -> dict[str, float]:
    """Per-dim signed delta. Dims missing from either snapshot are
    skipped (silently — the seed-gen pipeline can drop dims between
    audits and the attribution must remain a robust read)."""
    out: dict[str, float] = {}
    for dim, after in after_means.items():
        before = before_means.get(dim)
        if before is None:
            continue
        out[dim] = float(after) - float(before)
    return out


def _ci95(
    before_stderr: dict[str, float],
    after_stderr: dict[str, float],
    keys: list[str],
) -> dict[str, float]:
    """Per-dim 95% CI half-width using the paired-baseline formula.

    ``ci95[d] = 1.96 * sqrt(stderr_before[d]**2 + stderr_after[d]**2)``

    Missing stderr is treated as zero (most conservative). The keys
    are passed explicitly so the function returns one entry per dim
    in the delta dict, not the union of stderr dicts.
    """
    out: dict[str, float] = {}
    for dim in keys:
        sb = float(before_stderr.get(dim, 0.0))
        sa = float(after_stderr.get(dim, 0.0))
        out[dim] = _Z95 * math.sqrt(sb * sb + sa * sa)
    return out


def _attribution_score(expected_dim: dict[str, float], observed_dim: dict[str, float]) -> float:
    """Aggregate attribution score across the operator's expected dims.

    For each dim the mutation committed to moving (``expected_dim``):
      contribution = sign(expected) * observed
    Sum and clip to ``[-1, 1]`` so the score stays comparable across
    mutations regardless of how many dims they committed to. A
    mutation with no ``expected_dim`` entries returns ``0.0`` (no
    signal in either direction).
    """
    if not expected_dim:
        return 0.0
    total = 0.0
    for dim, expected in expected_dim.items():
        observed = observed_dim.get(dim, 0.0)
        if expected > 0:
            total += observed
        elif expected < 0:
            total -= observed
        # expected == 0 contributes nothing
    return max(-1.0, min(1.0, total))


def _confidence_stability(trajectory: list[Any]) -> float | None:
    """PR-E (2026-05-21) — derive a 0..1 stability score from the
    confidence values the reflection node emitted across the
    mutation's active rounds.

    Formula: ``1.0 - clamp(sample_stddev, 0.0, 1.0)``. High stability
    (score ≈ 1.0) means confidence stayed steady — the mutation is
    consistent with itself. Low stability (score ≈ 0.0) means
    confidence wildly oscillated, which usually flags an unstable
    policy change even if the dim deltas look favourable.

    Returns ``None`` for trajectories shorter than 2 samples (no
    variance signal yet). Non-numeric / bool / out-of-range entries
    are silently dropped — PR-3 reflection's bool-exclusion guard
    has the same intent for the source data.
    """
    cleaned: list[float] = []
    for value in trajectory:
        if isinstance(value, bool):  # bool is int subclass — exclude
            continue
        if not isinstance(value, int | float):
            continue
        f = float(value)
        if 0.0 <= f <= 1.0:
            cleaned.append(f)
    if len(cleaned) < 2:
        return None
    mean = sum(cleaned) / len(cleaned)
    variance = sum((x - mean) ** 2 for x in cleaned) / (len(cleaned) - 1)
    stddev = math.sqrt(variance)
    return max(0.0, 1.0 - min(1.0, stddev))


def confidence_trajectory_from_episodes(episodes: list[Any]) -> list[float]:
    """Pull the per-round ``confidence`` values from a list of PR-4
    :class:`core.memory.episodic.Episode` rows (or any duck-typed
    objects that carry a ``cognitive_state`` dict). Missing /
    non-numeric values are skipped silently so a partial trajectory
    is still useful.

    Returns the trajectory in input order — PR-4 ``recent()`` returns
    newest-first, so callers that want chronological order should
    reverse first. The order doesn't matter for variance, but a
    future Wasserstein / drift metric would care.
    """
    out: list[float] = []
    for ep in episodes:
        snapshot = getattr(ep, "cognitive_state", None)
        if not isinstance(snapshot, dict):
            continue
        raw = snapshot.get("confidence")
        if isinstance(raw, bool):  # exclude bool (int subclass)
            continue
        if isinstance(raw, int | float):
            f = float(raw)
            if 0.0 <= f <= 1.0:
                out.append(f)
    return out


def compute_attribution(
    *,
    mutation_id: str,
    expected_dim: dict[str, float],
    baseline_before: BaselineSnapshot | None,
    baseline_after: BaselineSnapshot | None,
    confidence_trajectory: list[float] | None = None,
    fitness_before: float | None = None,
    fitness_after: float | None = None,
    audit_run_id: str = "",
    source: str = "mutator",
    held_out_fitness: float | None = None,
    held_out_bench_id: str | None = None,
    promote_policy: str | None = None,
    promote_policy_seed: int | None = None,
) -> dict[str, Any]:
    """Compute the attribution payload for one applied mutation.

    Either snapshot may be ``None`` (autoresearch can drop the
    baseline mid-loop, or the very first audit has no "before"). In
    that case the payload is still complete-shape but
    ``observed_dim`` / ``ci95`` / ``significant`` are empty and
    ``attribution_score`` is ``0.0``. The caller can still write the
    row to record the *absence* of signal.

    PR-E (2026-05-21) — added ``confidence_trajectory`` (optional
    list of floats sampled from the reflection node's
    ``cognitive_state.confidence`` across the mutation's active
    rounds, typically pulled via :func:`confidence_trajectory_from_episodes`).
    When supplied with >= 2 samples the payload gains a
    ``confidence_stability`` term ∈ [0,1] (1.0 = rock-steady,
    0.0 = wild oscillation). ``attribution_score`` stays unchanged
    so downstream policy-mutation aggregators (PR-6) can weight
    dim-deltas vs belief-stability independently.
    """
    trajectory = list(confidence_trajectory or [])
    stability = _confidence_stability(trajectory) if trajectory else None
    payload: dict[str, Any] = {
        "ts": time.time(),
        "kind": "attribution",
        "mutation_id": mutation_id,
        "observed_dim": {},
        "signed_improvement": {},
        "ci95": {},
        "significant": {},
        "attribution_score": 0.0,
        "missing_baseline": baseline_before is None or baseline_after is None,
        "confidence_trajectory": trajectory,
        "confidence_stability": stability,
    }
    # W3 (2026-05-25 attribution wiring) — cross-ref to the Petri eval
    # archive measured for this mutation. Empty string when the caller
    # didn't propagate the audit_run_id (e.g. legacy callsite); column
    # omitted so legacy readers stay graceful.
    if audit_run_id:
        payload["audit_run_id"] = audit_run_id
    # PR-AR-L6 (2026-05-26) — source distinguishes mutator-driven cycle
    # rows ("mutator") from operator manual --promote rows ("manual").
    # Downstream consumers (operator analytics; a future source-aware
    # attribution variant) filter the JSONL stream on this tag.
    # Default "mutator" matches every pre-existing caller —
    # legacy on-disk rows that omit the field validate as ``None`` via
    # the schema default.
    payload["source"] = source
    # PR-SIL-5THEME C4 (2026-05-23) — E1 mutation cost ledger 의 fitness Δ.
    # ``baseline_before.fitness`` / ``baseline_after.fitness`` 는 dataclass 에
    # 없으므로 caller 가 명시 fitness_before / fitness_after 전달. 둘 다
    # 명시되면 fitness_delta = after - before 계산해서 payload 에 동봉.
    # 부재 시 키 자체 미출현 (legacy reader 무영향).
    #
    # SCALE CONTRACT (PR-MARGIN-FITNESS-SCALE E1, 2026-05-30) — both
    # ``fitness_before`` and ``fitness_after`` are on the canonical 0-1
    # ``compute_fitness`` scale (HIGHER-is-better), so ``after - before`` is a
    # meaningful same-scale delta. The autoresearch caller guarantees this by
    # computing ``fitness_before`` through the same ``compute_fitness`` that
    # produced ``fitness_after``. (This module is scale-agnostic — it just
    # subtracts — so the guarantee lives at the caller; the docstring records
    # it so a future caller does not regress to a mixed scale.)
    if fitness_before is not None and fitness_after is not None:
        payload["fitness_before"] = round(float(fitness_before), 6)
        payload["fitness_after"] = round(float(fitness_after), 6)
        payload["fitness_delta"] = round(float(fitness_after) - float(fitness_before), 6)
    # E2 (2026-05-30) — per-cycle fixed-ruler evidence. ``held_out_fitness`` is
    # the SAME 0-1 ``compute_fitness`` measured on the VERSION-FROZEN held-out
    # bench (NOT the co-evolving ``seed_select`` pool that produced
    # ``fitness_after``), so a fitness-vs-generation curve built from this field
    # across attribution rows is comparable ACROSS generations — the only curve
    # that counts as evidence of real improvement. Recorded on EVERY cycle when a
    # held-out bench is configured (operator cadence decision); both fields are
    # OMITTED together when no bench was scored (``None``) so legacy / no-bench
    # rows keep their exact shape (this module is otherwise scale-agnostic — the
    # 0-1 guarantee lives at the autoresearch caller). ``held_out_bench_id`` is
    # the ruler's content-address, so a silent edit to the "frozen" set surfaces
    # as an id change in the curve.
    if held_out_fitness is not None and held_out_bench_id is not None:
        payload["held_out_fitness"] = round(float(held_out_fitness), 6)
        payload["held_out_bench_id"] = str(held_out_bench_id)
    # E3 (2026-05-30) — control-arm tag so the per-cycle held-out curve can be
    # split into the gate / random / never arms (the matched 3-arm comparison).
    # Recorded together when both are supplied (``promote_policy_seed`` is ``0``
    # for the gate / never arms; the RECORDED seed makes the random arm
    # reproducible from the ledger). ``None`` → fields omitted (legacy shape).
    if promote_policy is not None:
        payload["promote_policy"] = str(promote_policy)
        payload["promote_policy_seed"] = int(
            promote_policy_seed if promote_policy_seed is not None else 0
        )
    if baseline_before is None or baseline_after is None:
        return payload

    observed = _dim_delta(baseline_before.dim_means, baseline_after.dim_means)
    ci = _ci95(baseline_before.dim_stderr, baseline_after.dim_stderr, list(observed.keys()))
    significant = {dim: abs(observed[dim]) > ci.get(dim, 0.0) for dim in observed}
    score = _attribution_score(expected_dim, observed)

    payload["observed_dim"] = observed
    # PR-SIL-MULTIOBJ A4 — canonical "+ = improvement" view of observed_dim.
    payload["signed_improvement"] = {
        dim: round(to_signed_improvement(dim, delta), 6) for dim, delta in observed.items()
    }
    payload["ci95"] = ci
    payload["significant"] = significant
    payload["attribution_score"] = score
    return payload


def append_attribution_log(
    payload: dict[str, Any],
    *,
    log_path: Path | None = None,
) -> Path:
    """Append one attribution row to ``mutations.jsonl``.

    Returns the path so the caller can ``git add`` it (the file is
    git-tracked — same constraint as the apply rows).
    """
    target = log_path if log_path is not None else MUTATION_AUDIT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    # W4 (2026-05-25) — Pydantic schema validation. drift fail-fast.
    validated = AttributionRecord.model_validate(payload).model_dump(exclude_none=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(validated, ensure_ascii=False, sort_keys=True))
        fh.write("\n")
    return target


def write_attribution(
    *,
    mutation_id: str,
    expected_dim: dict[str, float],
    baseline_before: BaselineSnapshot | None,
    baseline_after: BaselineSnapshot | None,
    confidence_trajectory: list[float] | None = None,
    log_path: Path | None = None,
    fitness_before: float | None = None,
    fitness_after: float | None = None,
    audit_run_id: str = "",
    source: str = "mutator",
    held_out_fitness: float | None = None,
    held_out_bench_id: str | None = None,
    promote_policy: str | None = None,
    promote_policy_seed: int | None = None,
) -> dict[str, Any]:
    """Compute + append attribution in one call.

    Returns the written payload so callers can inspect /
    log / forward it. Convenience wrapper for the common case where
    the loop runner has both baseline snapshots in hand right after
    an audit completes.

    PR-E (2026-05-21) — accepts the optional
    ``confidence_trajectory`` and forwards it to
    :func:`compute_attribution`.

    PR-SIL-5THEME C4 (2026-05-23) — ``fitness_before`` / ``fitness_after``
    optional forward to ``compute_attribution`` — caller (autoresearch
    run loop / scheduler) 가 둘 다 in-scope 일 때 (e.g. previous
    audit's promoted fitness + current audit's fitness) 전달.
    """
    payload = compute_attribution(
        mutation_id=mutation_id,
        expected_dim=expected_dim,
        baseline_before=baseline_before,
        baseline_after=baseline_after,
        confidence_trajectory=confidence_trajectory,
        fitness_before=fitness_before,
        fitness_after=fitness_after,
        audit_run_id=audit_run_id,
        source=source,
        held_out_fitness=held_out_fitness,
        held_out_bench_id=held_out_bench_id,
        promote_policy=promote_policy,
        promote_policy_seed=promote_policy_seed,
    )
    append_attribution_log(payload, log_path=log_path)
    return payload


__all__ = [
    "AttributionRecord",
    "append_attribution_log",
    "compute_attribution",
    "confidence_trajectory_from_episodes",
    "write_attribution",
]
