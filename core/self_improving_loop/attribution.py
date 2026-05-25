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
    ci95: dict[str, float] = Field(default_factory=dict)
    significant: dict[str, bool] = Field(default_factory=dict)
    attribution_score: float = 0.0
    missing_baseline: bool = True
    confidence_trajectory: list[float] = Field(default_factory=list)
    confidence_stability: float | None = None
    fitness_before: float | None = None
    fitness_after: float | None = None
    fitness_delta: float | None = None
    audit_run_id: str | None = None
    group_id: str | None = None
    """P1-revised (2026-05-25 baseline RL grounding) — group sampling 의
    cross-ref key. 같은 cycle 의 N sibling mutation 의 attribution row 가
    모두 같은 group_id 를 가져 group statistic (mean / std / advantage) 재구성
    가능. group_size=1 (legacy) 일 때 None."""
    group_advantage: float | None = None
    """P1-revised — advantage normalization 의 z-score. ``(fitness_i - μ) /
    (σ + ε)`` over group. group_id 부재 (legacy) 일 때 None."""


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
    group_id: str = "",
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
    # P1-revised (2026-05-25 baseline RL grounding) — group sampling
    # cross-ref key. Empty string when caller is single-mutation
    # (legacy group_size=1) — column omitted, legacy readers graceful.
    if group_id:
        payload["group_id"] = group_id
    # PR-SIL-5THEME C4 (2026-05-23) — E1 mutation cost ledger 의 fitness Δ.
    # ``baseline_before.fitness`` / ``baseline_after.fitness`` 는 dataclass 에
    # 없으므로 caller 가 명시 fitness_before / fitness_after 전달. 둘 다
    # 명시되면 fitness_delta = after - before 계산해서 payload 에 동봉.
    # 부재 시 키 자체 미출현 (legacy reader 무영향).
    if fitness_before is not None and fitness_after is not None:
        payload["fitness_before"] = round(float(fitness_before), 6)
        payload["fitness_after"] = round(float(fitness_after), 6)
        payload["fitness_delta"] = round(float(fitness_after) - float(fitness_before), 6)
    if baseline_before is None or baseline_after is None:
        return payload

    observed = _dim_delta(baseline_before.dim_means, baseline_after.dim_means)
    ci = _ci95(baseline_before.dim_stderr, baseline_after.dim_stderr, list(observed.keys()))
    significant = {dim: abs(observed[dim]) > ci.get(dim, 0.0) for dim in observed}
    score = _attribution_score(expected_dim, observed)

    payload["observed_dim"] = observed
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
    group_id: str = "",
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
        group_id=group_id,
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
