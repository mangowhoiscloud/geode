"""C.5 (2026-05-25) — kind × dim cross-effect matrix (PR-17).

Memory ``project_autoresearch_fragmentation_audit.md`` 신호 4 — 한 cycle 에
multi-kind mutation 가능성 + kind 간 interference confound. dim 단위
attribution 으로는 (kind × dim) interaction 추적 불가.

본 module = **5 kind × 24 dim matrix observability**:

- :func:`compute_kind_dim_matrix(apply_records, attribution_records)` —
  ApplyRecord 의 ``target_kind`` 와 AttributionRecord 의 ``observed_dim`` 을
  ``mutation_id`` 로 inner-join 해서 2D dict (``{kind: {dim: cumulative_score}}``)
  produce.
- :func:`rank_dims_by_kind(matrix, kind)` — 한 kind 가 가장 영향 준 dim 들
  내림차순.

PR-12 ``read_recent_applies`` + PR-12 ``read_recent_attributions`` 결과를
caller 가 inject — module 자체는 pure (I/O X). caller (CLI / dashboard) 가
2D matrix 를 시각화.

Frontier reference: Quality-Diversity 의 behavior-niche grid + DGM 의
archive lineage causal trace.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.self_improving.loop.mutate.runner import ApplyRecord
    from core.self_improving.loop.observe.attribution import AttributionRecord


def compute_kind_dim_matrix(
    apply_records: Iterable[ApplyRecord],
    attribution_records: Iterable[AttributionRecord],
) -> dict[str, dict[str, float]]:
    """Build a ``{target_kind: {dim_name: cumulative_attribution_score}}`` matrix.

    Inner-join apply 와 attribution rows on ``mutation_id``. Each
    (kind, dim) cell accumulates ``observed_dim[dim]`` from every
    matched attribution row, scaled by ``attribution_score`` of that
    row. The result lets operators answer "which kind of mutation has
    moved which dim the most over history" — F4 fragmentation signal
    resolver.

    Apply rows whose ``mutation_id`` doesn't appear in any attribution
    row are skipped (no signal). Attribution rows without a matching
    apply row are skipped (orphan). Both iterables are consumed once.
    """
    apply_kind_by_id: dict[str, str] = {}
    for ar in apply_records:
        mid = getattr(ar, "mutation_id", "")
        kind = getattr(ar, "target_kind", "")
        if mid and kind:
            apply_kind_by_id[mid] = kind

    matrix: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for attr in attribution_records:
        mid = getattr(attr, "mutation_id", "")
        if not mid or mid not in apply_kind_by_id:
            continue
        kind = apply_kind_by_id[mid]
        observed = getattr(attr, "observed_dim", None) or {}
        score = float(getattr(attr, "attribution_score", 0.0))
        for dim, value in observed.items():
            # signed contribution — direction is preserved
            matrix[kind][dim] += score * float(value)

    return {kind: dict(dims) for kind, dims in matrix.items()}


def rank_dims_by_kind(
    matrix: dict[str, dict[str, float]],
    kind: str,
    *,
    limit: int | None = None,
) -> list[tuple[str, float]]:
    """Return ``[(dim, score), ...]`` sorted by absolute score descending
    for the given kind. Empty list when kind absent."""
    dims = matrix.get(kind, {})
    if not dims:
        return []
    ranked = sorted(dims.items(), key=lambda kv: abs(kv[1]), reverse=True)
    if limit is not None:
        return ranked[:limit]
    return ranked


__all__ = [
    "compute_kind_dim_matrix",
    "rank_dims_by_kind",
]
