"""A.2 (2026-05-25) — Tchebycheff scalarization helper (PR-23).

Plan ``docs/plans/2026-05-25-p2-pareto-archive-dynamic-reward-weighting.md``
§C5 — linear scalarization (현재 fitness = w·r) 한계 회피.

**Why Tchebycheff vs linear** (Das & Dennis 1997):

- Linear scalarization (``f_total = sum(w_i * f_i)``) 의 fundamental
  한계 — concave Pareto front 영역은 어떤 weight 조합으로도 도달 불가.
- Tchebycheff (``f_total = max_i w_i * |f_i - z_i*|``) 은 concave 영역
  포함 모든 Pareto-optimal 점에 도달 가능.

**Formula** (higher-is-better convention 으로 변환):

    minimize: max_i w_i * |f_i - z_i*|
    equivalent (higher-is-better): minimize max_i w_i * (z_i* - f_i)
                                   when z_i* is ideal (max of f_i)

The scalar returned is **negative-magnitude** — higher is better
(callers compare directly with linear fitness; max(scalar) = closest
to ideal point z*).

본 module = **pure helper**:

- :func:`compute_tchebycheff` — (fitness_dim, weights, ideal_point) → scalar
- :func:`compute_ideal_point(archive_entries)` — per-dim max as z*

Caller (apply_group_proposals 의 pareto_mode 분기) wiring 은 후속 PR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def compute_tchebycheff(
    fitness_dim: dict[str, float],
    weights: dict[str, float],
    ideal_point: dict[str, float],
) -> float:
    """Tchebycheff scalarization of a multi-dim fitness vector.

    Formula (higher-is-better)::

        scalar = -max_d w_d * (ideal_point[d] - fitness_dim[d])

    Negation flips so caller can take ``max(scalar)`` to pick the
    closest-to-ideal candidate. Per-dim weights normalize fitness
    direction — set ``w_d = 1`` for uniform Tchebycheff, or
    ``w_d = 1/range_d`` for normalized.

    Edge cases:

    - dim missing from ``fitness_dim`` → contribution skipped
    - dim missing from ``weights`` → defaults to 1.0
    - dim missing from ``ideal_point`` → contribution skipped (no anchor)
    - all dims skipped (empty intersection) → returns 0.0

    Pure function — no I/O, no side effect.
    """
    contributions: list[float] = []
    for dim, f in fitness_dim.items():
        ideal = ideal_point.get(dim)
        if ideal is None:
            continue
        w = float(weights.get(dim, 1.0))
        # higher-is-better: ideal - f >= 0 when f <= ideal
        contributions.append(w * (float(ideal) - float(f)))
    if not contributions:
        return 0.0
    return -max(contributions)


def compute_ideal_point(
    fitness_vectors: Iterable[dict[str, float]],
) -> dict[str, float]:
    """Per-dim max across an iterable of fitness vectors = ideal point z*.

    Empty input → ``{}``. Each dim's ideal is the maximum observed
    value across all vectors (higher-is-better). Dims that appear only
    in some vectors are still included with their observed max.

    Useful for archive-driven Tchebycheff — caller computes z* from
    current Pareto archive before scalarizing candidates against it.
    """
    ideal: dict[str, float] = {}
    for vec in fitness_vectors:
        for dim, value in vec.items():
            current = ideal.get(dim)
            if current is None or float(value) > current:
                ideal[dim] = float(value)
    return ideal


__all__ = [
    "compute_ideal_point",
    "compute_tchebycheff",
]
