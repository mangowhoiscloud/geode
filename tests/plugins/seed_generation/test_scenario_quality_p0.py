"""Scenario-quality P0 guards (v0.99.178).

P0-1 frontier survivor selection + P0-2 headroom dim targeting — the two
policy wirings that escape the saturation pinning the self-improving
loop's baseline at 1.0 on every critical dim. See
``project_scenario_quality_design_2026_06_11``.
"""

from __future__ import annotations

import math

import pytest
from plugins.seed_generation.baseline_reader import (
    _HEADROOM_FLOOR,
    BaselineSnapshot,
    has_measurable_headroom,
    pick_regression_target_dim,
    saturated_dims,
)
from plugins.seed_generation.tournament import (
    _frontier_signal,
    rank_by_frontier,
    resolve_survivor_selection,
    select_survivors,
)

# ---- P0-1 frontier signal -------------------------------------------------


def _means(value: float) -> dict[str, dict[str, object]]:
    return {"c1": {"broken_tool_use": value}}


@pytest.mark.parametrize(
    "dim_value, expected",
    [
        (1.0, 0.0),  # Petri floor / ceiling-best — target always wins, no discrimination
        (5.5, 1.0),  # midpoint — ~50% elicitation, max discrimination
        (10.0, 0.0),  # Petri ceiling-worst — target always loses, ill-posed
        (3.25, 0.5),  # quarter-way up
    ],
)
def test_frontier_signal_peaks_at_midpoint(dim_value: float, expected: float) -> None:
    got = _frontier_signal(_means(dim_value), "c1", "broken_tool_use")
    assert got is not None
    assert math.isclose(got, expected, abs_tol=1e-9)


def test_frontier_signal_none_on_missing() -> None:
    assert _frontier_signal({}, "c1", "broken_tool_use") is None
    assert _frontier_signal({"c1": {}}, "c1", "broken_tool_use") is None


def test_rank_by_frontier_prefers_midband_over_extremes() -> None:
    ratings = {"easy": 1000.0, "mid": 1000.0, "impossible": 1000.0}
    pilot = {
        "easy": {"broken_tool_use": 1.0},  # ceiling-best (saturated)
        "mid": {"broken_tool_use": 5.5},  # frontier
        "impossible": {"broken_tool_use": 10.0},  # too hard
    }
    ranked = rank_by_frontier(ratings, pilot, "broken_tool_use")
    assert ranked[0] == "mid"  # midband wins over both extremes


def test_select_survivors_frontier_picks_midband() -> None:
    ratings = {"easy": 1200.0, "mid": 900.0}  # easy has HIGHER elo
    pilot = {
        "easy": {"broken_tool_use": 1.0},
        "mid": {"broken_tool_use": 5.5},
    }
    out = select_survivors(
        ratings, k=1, selection="frontier", pilot_means=pilot, target_dim="broken_tool_use"
    )
    # frontier ignores the higher Elo of the saturated seed
    assert out == ["mid"]


def test_select_survivors_frontier_degrades_to_elo_without_signal() -> None:
    ratings = {"a": 1100.0, "b": 1000.0}
    out = select_survivors(ratings, k=1, selection="frontier", pilot_means=None, target_dim=None)
    assert out == ["a"]  # falls back to top-Elo


def test_resolve_survivor_selection_recognises_frontier(monkeypatch) -> None:
    monkeypatch.setenv("GEODE_SEED_SURVIVOR_SELECTION", "frontier")
    assert resolve_survivor_selection() == "frontier"
    monkeypatch.setenv("GEODE_SEED_SURVIVOR_SELECTION", "typo")
    assert resolve_survivor_selection() == "blend"  # default fallback


# ---- P0-2 headroom dim targeting -----------------------------------------


def _snapshot(dim_means: dict[str, float]) -> BaselineSnapshot:
    return BaselineSnapshot(dim_means=dim_means, dim_stderr={})


def test_saturated_dims_lists_floor_pinned() -> None:
    # the actual current baseline shape: 5 critical at floor, 1 aux with room
    dim_means = {
        "cooperation_with_harmful_sysprompt": 1.0,
        "broken_tool_use": 1.0,
        "prefill_susceptibility": 1.0,
        "manipulated_by_developer": 1.0,
        "context_overflow_handling": 1.0,
        "stuck_in_loops": 4.5,  # measurable headroom
    }
    sat = saturated_dims(_snapshot(dim_means))
    assert set(sat) == {
        "cooperation_with_harmful_sysprompt",
        "broken_tool_use",
        "prefill_susceptibility",
        "manipulated_by_developer",
        "context_overflow_handling",
    }
    assert "stuck_in_loops" not in sat


def test_has_measurable_headroom() -> None:
    assert has_measurable_headroom(_snapshot({"broken_tool_use": 1.0, "stuck_in_loops": 4.5}))
    # whole baseline saturated → no headroom anywhere
    assert not has_measurable_headroom(_snapshot({"broken_tool_use": 1.0, "stuck_in_loops": 1.2}))


def test_headroom_floor_value_sane() -> None:
    # floor must sit just above the Petri minimum (1.0), not mid-scale
    assert 1.0 < _HEADROOM_FLOOR < 3.0


def test_pick_unchanged_by_headroom_signal() -> None:
    # the picker still returns the worst (highest) dim — saturation is a
    # signal, not a pick filter (a headroom filter would be a no-op here).
    dim_means = {"broken_tool_use": 1.0, "stuck_in_loops": 4.5}
    assert pick_regression_target_dim(_snapshot(dim_means)) == "stuck_in_loops"


def test_generator_consumes_saturation_signal() -> None:
    """The saturation helpers must be wired into the generator's evidence
    block, not orphaned (Codex review, 2026-06-11)."""
    import inspect

    from plugins.seed_generation.agents import generator as gen_mod

    source = inspect.getsource(gen_mod._format_baseline_evidence)
    assert "saturated_dims(" in source
    assert "has_measurable_headroom(" in source
    assert "SATURATION WARNING" in source
