"""A.3 (2026-05-25) — MAP-Elites niche grid invariants (PR-24)."""

from __future__ import annotations

import pytest
from core.self_improving_loop.map_elites import (
    MapElitesGrid,
    compute_cell_index,
    compute_grid_coverage,
    insert_many,
)

# ---------------------------------------------------------------------------
# 1. compute_cell_index — discretization
# ---------------------------------------------------------------------------


def test_cell_index_lo_bound_maps_to_zero() -> None:
    assert compute_cell_index(0.0, (0.0, 1.0), 10) == 0


def test_cell_index_hi_bound_maps_to_max() -> None:
    """value at upper bound → resolution - 1 (last cell)."""
    assert compute_cell_index(1.0, (0.0, 1.0), 10) == 9


def test_cell_index_midpoint() -> None:
    assert compute_cell_index(0.5, (0.0, 1.0), 10) == 5


def test_cell_index_clamp_below_lo() -> None:
    assert compute_cell_index(-1.0, (0.0, 1.0), 10) == 0


def test_cell_index_clamp_above_hi() -> None:
    assert compute_cell_index(99.0, (0.0, 1.0), 10) == 9


def test_cell_index_resolution_1_returns_zero() -> None:
    """resolution=1 → 모든 value 가 cell 0."""
    assert compute_cell_index(0.3, (0.0, 1.0), 1) == 0
    assert compute_cell_index(0.9, (0.0, 1.0), 1) == 0


def test_cell_index_invalid_resolution_raises() -> None:
    with pytest.raises(ValueError, match=r"resolution must be >= 1"):
        compute_cell_index(0.5, (0.0, 1.0), 0)


def test_cell_index_invalid_bounds_raises() -> None:
    with pytest.raises(ValueError, match=r"bounds must be"):
        compute_cell_index(0.5, (1.0, 1.0), 10)
    with pytest.raises(ValueError, match=r"bounds must be"):
        compute_cell_index(0.5, (2.0, 1.0), 10)


# ---------------------------------------------------------------------------
# 2. MapElitesGrid — insert / replace / get
# ---------------------------------------------------------------------------


def _grid_2d() -> MapElitesGrid:
    return MapElitesGrid(
        behavior_bounds=((0.0, 1.0), (0.0, 1.0)),
        resolution=(10, 10),
    )


def test_grid_starts_empty() -> None:
    grid = _grid_2d()
    assert len(grid) == 0


def test_grid_insert_into_empty_cell() -> None:
    grid = _grid_2d()
    assert grid.insert((0.5, 0.5), fitness=0.7, payload="m1") is True
    assert len(grid) == 1


def test_grid_insert_higher_replaces() -> None:
    """Same cell, higher fitness → replace."""
    grid = _grid_2d()
    grid.insert((0.5, 0.5), 0.5, "m1")
    assert grid.insert((0.55, 0.55), 0.9, "m2") is True  # same cell
    cell_entry = grid.get((0.5, 0.5))
    assert cell_entry == (0.9, "m2")


def test_grid_insert_lower_rejected() -> None:
    """Same cell, lower fitness → reject."""
    grid = _grid_2d()
    grid.insert((0.5, 0.5), 0.9, "m1")
    assert grid.insert((0.55, 0.55), 0.3, "m2") is False
    cell_entry = grid.get((0.5, 0.5))
    assert cell_entry == (0.9, "m1")


def test_grid_insert_equal_fitness_rejected() -> None:
    """Tie → existing wins (strict >)."""
    grid = _grid_2d()
    grid.insert((0.5, 0.5), 0.5, "m1")
    assert grid.insert((0.55, 0.55), 0.5, "m2") is False


def test_grid_different_cells_coexist() -> None:
    """Different cells = independent occupancy."""
    grid = _grid_2d()
    grid.insert((0.1, 0.1), 0.3, "m1")
    grid.insert((0.9, 0.9), 0.3, "m2")
    assert len(grid) == 2


def test_grid_get_empty_cell_returns_none() -> None:
    grid = _grid_2d()
    assert grid.get((0.5, 0.5)) is None


# ---------------------------------------------------------------------------
# 3. all_payloads / coverage / insert_many
# ---------------------------------------------------------------------------


def test_grid_all_payloads_returns_each() -> None:
    grid = _grid_2d()
    grid.insert((0.1, 0.1), 0.5, "m1")
    grid.insert((0.9, 0.9), 0.6, "m2")
    payloads = grid.all_payloads()
    assert set(payloads) == {"m1", "m2"}


def test_grid_coverage_empty_is_zero() -> None:
    grid = _grid_2d()
    assert compute_grid_coverage(grid) == 0.0


def test_grid_coverage_full_is_one() -> None:
    """All 10×10=100 cells occupied → coverage 1.0."""
    grid = MapElitesGrid(
        behavior_bounds=((0.0, 1.0), (0.0, 1.0)),
        resolution=(2, 2),  # 4 cells (manageable for test)
    )
    grid.insert((0.0, 0.0), 0.5, "a")
    grid.insert((0.0, 1.0), 0.5, "b")
    grid.insert((1.0, 0.0), 0.5, "c")
    grid.insert((1.0, 1.0), 0.5, "d")
    assert compute_grid_coverage(grid) == pytest.approx(1.0)


def test_grid_coverage_partial() -> None:
    """1 cell out of 100 → 0.01."""
    grid = _grid_2d()
    grid.insert((0.5, 0.5), 0.5, "m1")
    assert compute_grid_coverage(grid) == pytest.approx(0.01)


def test_insert_many_batches() -> None:
    grid = _grid_2d()
    entries = [
        ((0.1, 0.1), 0.5, "a"),
        ((0.5, 0.5), 0.7, "b"),
        ((0.9, 0.9), 0.3, "c"),
    ]
    count = insert_many(grid, entries)
    assert count == 3
    assert len(grid) == 3


def test_insert_many_respects_winner_takes_all() -> None:
    """Two entries in same cell — only the higher-fitness one inserts."""
    grid = _grid_2d()
    entries = [
        ((0.5, 0.5), 0.3, "loser"),
        ((0.55, 0.55), 0.9, "winner"),
    ]
    count = insert_many(grid, entries)
    assert count == 2  # both attempt, both succeed (2nd replaces 1st)
    assert len(grid) == 1
    cell = grid.get((0.5, 0.5))
    assert cell == (0.9, "winner")


# ---------------------------------------------------------------------------
# 4. Use case — niche diversity across attempts
# ---------------------------------------------------------------------------


def test_niche_diversity_preserved() -> None:
    """다양한 behavior 의 mutations 가 same fitness 라도 niche 별로 보존."""
    grid = _grid_2d()
    # 3 mutations with same fitness but different behaviors
    grid.insert((0.1, 0.1), 0.6, "safety-focused")
    grid.insert((0.5, 0.9), 0.6, "helpfulness-focused")
    grid.insert((0.9, 0.5), 0.6, "tool-focused")
    assert len(grid) == 3
    # All preserved — QD invariant: niche diversity not collapsed
