"""ADR-012 M4.4.2 — rubric_excerpts reader + orchestrator wiring invariants.

Pins:
- ``load_baseline`` graceful on missing / malformed / non-dict input.
- ``find_worst_regressions`` returns dims where ``baseline_mean -
  current_mean > 0``, sorted desc, capped at ``top_k``; skips
  improving dims; tolerates partial / type-bad rows.
- ``format_rubric_block`` renders ``<rubric-warning>`` block; empty →
  empty string.
- ``DIM_RUBRIC`` covers the 17 fitness dims (5 critical + 12 auxiliary)
  defined in ``autoresearch.train.AXIS_TIERS``.
- Orchestrator: ``rubric_excerpts`` slot active + baseline has
  regressions → block prepended to system prompt.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def baseline_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect ``resolve_baseline_path`` to a tmp_path location."""
    target = tmp_path / "state" / "baseline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "core.self_improving_loop.rubric_excerpts.resolve_baseline_path",
        lambda: target,
    )
    yield target


# DIM_RUBRIC coverage --------------------------------------------------------


def test_dim_rubric_covers_all_fitness_dims() -> None:
    """Every dim in ``AXIS_TIERS`` (critical + auxiliary) needs a rubric line."""
    from autoresearch.train import AXIS_TIERS
    from core.self_improving_loop.rubric_excerpts import DIM_RUBRIC

    fitness_dims = {d for d, t in AXIS_TIERS.items() if t in ("critical", "auxiliary")}
    missing = fitness_dims - set(DIM_RUBRIC.keys())
    assert not missing, f"DIM_RUBRIC missing: {sorted(missing)}"


def test_dim_rubric_entries_are_non_empty_strings() -> None:
    from core.self_improving_loop.rubric_excerpts import DIM_RUBRIC

    for dim, line in DIM_RUBRIC.items():
        assert isinstance(line, str) and line.strip(), f"empty rubric for {dim}"


# load_baseline -------------------------------------------------------------


def test_load_baseline_missing_file_returns_none(baseline_path: Path) -> None:
    from core.self_improving_loop.rubric_excerpts import load_baseline

    assert load_baseline() is None  # file not written yet


def test_load_baseline_malformed_json_returns_none(baseline_path: Path) -> None:
    from core.self_improving_loop.rubric_excerpts import load_baseline

    baseline_path.write_text("not json at all", encoding="utf-8")
    assert load_baseline() is None


def test_load_baseline_non_dict_root_returns_none(baseline_path: Path) -> None:
    from core.self_improving_loop.rubric_excerpts import load_baseline

    baseline_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_baseline() is None


def test_load_baseline_valid_returns_dict(baseline_path: Path) -> None:
    from core.self_improving_loop.rubric_excerpts import load_baseline

    payload = {
        "dim_means": {"broken_tool_use": 0.7},
        "baseline_means": {"broken_tool_use": 0.85},
        "fitness": 0.6,
    }
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    out = load_baseline()
    assert out == payload


# find_worst_regressions ----------------------------------------------------


def test_find_returns_empty_for_top_k_zero() -> None:
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    baseline = {
        "dim_means": {"d1": 0.5},
        "baseline_means": {"d1": 0.9},
    }
    assert find_worst_regressions(baseline, top_k=0) == []


def test_find_skips_improving_dims() -> None:
    """Dims where current >= baseline are excluded — slot focuses on risks."""
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    baseline = {
        "dim_means": {"improved": 0.95, "regressed": 0.5},
        "baseline_means": {"improved": 0.7, "regressed": 0.85},
    }
    rows = find_worst_regressions(baseline, top_k=5)
    assert len(rows) == 1
    assert rows[0].dim == "regressed"


def test_find_sorts_by_regression_desc() -> None:
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    baseline = {
        "dim_means": {"a": 0.6, "b": 0.4, "c": 0.7},
        "baseline_means": {"a": 0.8, "b": 0.9, "c": 0.75},
    }
    rows = find_worst_regressions(baseline, top_k=5)
    # regression: a=0.2, b=0.5, c=0.05 → order b, a, c
    assert [r.dim for r in rows] == ["b", "a", "c"]


def test_find_top_k_caps() -> None:
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    baseline = {
        "dim_means": {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5},
        "baseline_means": {"a": 0.8, "b": 0.7, "c": 0.9, "d": 0.6},
    }
    rows = find_worst_regressions(baseline, top_k=2)
    assert len(rows) == 2


def test_find_tolerates_missing_means(baseline_path: Path) -> None:
    """Baseline without ``dim_means`` / ``baseline_means`` → empty list."""
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    assert find_worst_regressions({}, top_k=3) == []
    assert find_worst_regressions({"dim_means": {}}, top_k=3) == []
    assert find_worst_regressions({"baseline_means": {}}, top_k=3) == []


def test_find_skips_non_numeric_values() -> None:
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    baseline = {
        "dim_means": {"good": 0.5, "bad_type": "not a number"},
        "baseline_means": {"good": 0.9, "bad_type": 0.7},
    }
    rows = find_worst_regressions(baseline, top_k=5)
    assert [r.dim for r in rows] == ["good"]


def test_find_attaches_rubric_when_dim_in_table() -> None:
    """Known dims pick up DIM_RUBRIC entry; unknowns get empty string."""
    from core.self_improving_loop.rubric_excerpts import find_worst_regressions

    baseline = {
        "dim_means": {"broken_tool_use": 0.5, "made_up_dim": 0.5},
        "baseline_means": {"broken_tool_use": 0.9, "made_up_dim": 0.9},
    }
    rows = find_worst_regressions(baseline, top_k=5)
    by_dim = {r.dim: r.rubric for r in rows}
    assert "broken_tool_use" in by_dim
    assert by_dim["broken_tool_use"]  # non-empty
    assert "made_up_dim" in by_dim
    assert by_dim["made_up_dim"] == ""


# format_rubric_block --------------------------------------------------------


def test_format_empty_returns_empty_string() -> None:
    from core.self_improving_loop.rubric_excerpts import format_rubric_block

    assert format_rubric_block([]) == ""


def test_format_renders_rubric_block() -> None:
    from core.self_improving_loop.rubric_excerpts import (
        DimRegression,
        format_rubric_block,
    )

    rows = [
        DimRegression(
            dim="broken_tool_use",
            current_mean=0.5,
            baseline_mean=0.9,
            regression=0.4,
            rubric="Use tools with valid arguments.",
        ),
        DimRegression(
            dim="unknown_dim",
            current_mean=0.5,
            baseline_mean=0.9,
            regression=0.4,
            rubric="",
        ),
    ]
    block = format_rubric_block(rows)
    assert block.startswith("<rubric-warning>")
    assert block.endswith("</rubric-warning>")
    assert "[broken_tool_use] Use tools with valid arguments." in block
    assert "[unknown_dim] watch this dim" in block


# Orchestrator wiring -------------------------------------------------------


def test_orchestrator_prepends_rubric_block(
    baseline_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rubric_excerpts slot active + baseline has regression → block in system."""
    from core.self_improving_loop.in_context_slots import (
        SLOT_RUBRIC_EXCERPTS,
        InContextSlot,
    )
    from core.self_improving_loop.in_context_wiring import apply_in_context_slots

    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {"broken_tool_use": 0.5},
                "baseline_means": {"broken_tool_use": 0.9},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_RUBRIC_EXCERPTS: InContextSlot(
                name=SLOT_RUBRIC_EXCERPTS,
                max_entries=3,
                rank_by="regression_severity",
                injection_point="system_prompt",
            )
        },
    )
    _, new_sys = apply_in_context_slots([{"role": "user", "content": "task"}], system="ORIGINAL")
    assert "<rubric-warning>" in new_sys
    assert "[broken_tool_use]" in new_sys
    assert new_sys.endswith("ORIGINAL")


def test_orchestrator_no_op_when_baseline_missing(
    baseline_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rubric_excerpts slot active but baseline.json absent → system unchanged."""
    from core.self_improving_loop.in_context_slots import (
        SLOT_RUBRIC_EXCERPTS,
        InContextSlot,
    )
    from core.self_improving_loop.in_context_wiring import apply_in_context_slots

    # baseline_path fixture creates the parent dir but not the file
    monkeypatch.setattr(
        "core.self_improving_loop.in_context_slots._load_in_context_slots_override",
        lambda: {
            SLOT_RUBRIC_EXCERPTS: InContextSlot(
                name=SLOT_RUBRIC_EXCERPTS,
                max_entries=3,
                rank_by="regression_severity",
                injection_point="system_prompt",
            )
        },
    )
    _, new_sys = apply_in_context_slots([{"role": "user", "content": "task"}], system="SYS")
    assert new_sys == "SYS"
