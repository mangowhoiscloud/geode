"""A.3 (2026-05-25) — MAP-Elites niche grid helper (PR-24).

Plan ``docs/plans/2026-05-25-p2-pareto-archive-dynamic-reward-weighting.md``
§C6 — Quality-Diversity 패턴 (Mouret & Clune 2015, AlphaEvolve 2025-05).

**Concept**: behavior-characterization dim 2 개 를 grid 의 (x, y) 로 사용,
각 cell 에 fitness 가장 높은 한 entry 만 보존. 결과 — 다양한 behavior
niche 의 elite 들이 archive 에 보존되어 exploration vs exploitation 균형.

vs Pareto archive (PR-15):
- Pareto: dominance 기준 prune (전체 ordering)
- MAP-Elites: behavior niche 기준 (local ordering per cell)
- 둘은 보완 — 함께 사용 가능 (Pareto + niche 둘 다 anchor)

본 module = **pure selection-only helper**:

- :func:`compute_cell_index(value, bounds, resolution)` — float → grid cell idx
- :class:`MapElitesGrid` — sparse dict-based 2D grid + insert/sample
- :func:`compute_grid_coverage(grid)` — occupied cells / total cells ratio

caller (archive 의 niche-aware sampling) wiring 후속 PR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def compute_cell_index(
    value: float,
    bounds: tuple[float, float],
    resolution: int,
) -> int:
    """Discretize ``value`` into a grid cell index ``[0, resolution)``.

    ``bounds = (lo, hi)``. value clamp to [lo, hi]. value at ``hi`` maps to
    ``resolution - 1``. ``resolution`` must be >= 1.

    Raises ValueError on bad inputs (resolution <= 0, bounds[0] >= bounds[1]).
    """
    if resolution < 1:
        raise ValueError(f"resolution must be >= 1, got {resolution}")
    lo, hi = bounds
    if lo >= hi:
        raise ValueError(f"bounds must be (lo < hi), got ({lo}, {hi})")
    clamped = max(lo, min(hi, value))
    # Map [lo, hi] to [0, resolution) linearly. value=hi must hit
    # resolution-1 (not resolution); use floor with epsilon-clip.
    frac = (clamped - lo) / (hi - lo)
    idx = math.floor(frac * resolution)
    return min(idx, resolution - 1)


@dataclass(frozen=True)
class _CellKey:
    """2D cell coordinate — frozen so it's hashable for dict key."""

    x: int
    y: int


@dataclass
class MapElitesGrid:
    """Sparse 2D niche grid — only occupied cells stored.

    Each cell maps to a single ``(fitness, payload)`` tuple. Insert
    replaces the cell's entry only when the new fitness is strictly
    higher (winner-takes-all per cell).

    ``payload`` is opaque to the grid — caller supplies anything
    (e.g. mutation_id, full ArchiveEntry, ...).
    """

    behavior_bounds: tuple[tuple[float, float], tuple[float, float]]
    """((x_lo, x_hi), (y_lo, y_hi)) — bounds for the 2 behavior dims."""

    resolution: tuple[int, int] = (10, 10)
    """(x_resolution, y_resolution) — cells per dim. default 10×10 = 100."""

    cells: dict[_CellKey, tuple[float, object]] = field(default_factory=dict)
    """{cell_key: (fitness, payload)} — only occupied cells."""

    def _cell(self, behavior: tuple[float, float]) -> _CellKey:
        bx, by = behavior
        (x_lo, x_hi), (y_lo, y_hi) = self.behavior_bounds
        rx, ry = self.resolution
        x_idx = compute_cell_index(bx, (x_lo, x_hi), rx)
        y_idx = compute_cell_index(by, (y_lo, y_hi), ry)
        return _CellKey(x_idx, y_idx)

    def insert(
        self,
        behavior: tuple[float, float],
        fitness: float,
        payload: object,
    ) -> bool:
        """Insert ``payload`` at the cell for ``behavior`` if ``fitness``
        strictly exceeds the existing occupant. Returns True if inserted."""
        cell = self._cell(behavior)
        existing = self.cells.get(cell)
        if existing is not None and existing[0] >= fitness:
            return False
        self.cells[cell] = (float(fitness), payload)
        return True

    def get(self, behavior: tuple[float, float]) -> tuple[float, object] | None:
        """Return ``(fitness, payload)`` at the cell for ``behavior``, or None."""
        return self.cells.get(self._cell(behavior))

    def all_payloads(self) -> list[object]:
        """Return every occupied cell's payload (order unspecified)."""
        return [payload for _fitness, payload in self.cells.values()]

    def __len__(self) -> int:
        return len(self.cells)


def compute_grid_coverage(grid: MapElitesGrid) -> float:
    """Ratio of occupied cells to total cells in the grid.

    Result in ``[0.0, 1.0]``. 0.0 = empty, 1.0 = every cell occupied
    (saturated niche space).
    """
    rx, ry = grid.resolution
    total = rx * ry
    if total <= 0:
        return 0.0
    return len(grid) / total


def insert_many(
    grid: MapElitesGrid,
    entries: Iterable[tuple[tuple[float, float], float, object]],
) -> int:
    """Batch-insert ``(behavior, fitness, payload)`` triples. Returns the
    count of successful inserts (entries that won their cell)."""
    inserted = 0
    for behavior, fitness, payload in entries:
        if grid.insert(behavior, fitness, payload):
            inserted += 1
    return inserted


__all__ = [
    "MapElitesGrid",
    "compute_cell_index",
    "compute_grid_coverage",
    "insert_many",
]
