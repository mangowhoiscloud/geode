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

if TYPE_CHECKING:
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

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


def compute_attribution(
    *,
    mutation_id: str,
    expected_dim: dict[str, float],
    baseline_before: BaselineSnapshot | None,
    baseline_after: BaselineSnapshot | None,
) -> dict[str, Any]:
    """Compute the attribution payload for one applied mutation.

    Either snapshot may be ``None`` (autoresearch can drop the
    baseline mid-loop, or the very first audit has no "before"). In
    that case the payload is still complete-shape but
    ``observed_dim`` / ``ci95`` / ``significant`` are empty and
    ``attribution_score`` is ``0.0``. The caller can still write the
    row to record the *absence* of signal.
    """
    payload: dict[str, Any] = {
        "ts": time.time(),
        "kind": "attribution",
        "mutation_id": mutation_id,
        "observed_dim": {},
        "ci95": {},
        "significant": {},
        "attribution_score": 0.0,
        "missing_baseline": baseline_before is None or baseline_after is None,
    }
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
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        fh.write("\n")
    return target


def write_attribution(
    *,
    mutation_id: str,
    expected_dim: dict[str, float],
    baseline_before: BaselineSnapshot | None,
    baseline_after: BaselineSnapshot | None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Compute + append attribution in one call.

    Returns the written payload so callers can inspect /
    log / forward it. Convenience wrapper for the common case where
    the loop runner has both baseline snapshots in hand right after
    an audit completes.
    """
    payload = compute_attribution(
        mutation_id=mutation_id,
        expected_dim=expected_dim,
        baseline_before=baseline_before,
        baseline_after=baseline_after,
    )
    append_attribution_log(payload, log_path=log_path)
    return payload


__all__ = [
    "append_attribution_log",
    "compute_attribution",
    "write_attribution",
]
