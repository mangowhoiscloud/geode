"""C.5 (2026-05-25) — kind × dim cross-effect matrix invariants (PR-17).

Scope:
- compute_kind_dim_matrix: empty / inner-join on mutation_id / signed contribution /
  orphan attribution skip / orphan apply skip / single kind multi-dim accumulation
- rank_dims_by_kind: absolute-magnitude sort / limit / missing key
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from core.self_improving_loop.kind_dim_matrix import (
    compute_kind_dim_matrix,
    rank_dims_by_kind,
)


@dataclass
class _StubApply:
    mutation_id: str
    target_kind: str


@dataclass
class _StubAttr:
    mutation_id: str
    observed_dim: dict[str, float] = field(default_factory=dict)
    attribution_score: float = 1.0


# ---------------------------------------------------------------------------
# 1. compute_kind_dim_matrix — empty + happy path
# ---------------------------------------------------------------------------


def test_matrix_empty_inputs() -> None:
    assert compute_kind_dim_matrix([], []) == {}


def test_matrix_only_applies_no_attribution() -> None:
    """Apply rows without matching attribution → empty matrix."""
    applies = [_StubApply("m1", "prompt"), _StubApply("m2", "tool_policy")]
    assert compute_kind_dim_matrix(applies, []) == {}


def test_matrix_only_attribution_no_apply() -> None:
    """Orphan attribution → no kind to attach → skip."""
    attrs = [_StubAttr("m1", {"safety": 0.5})]
    assert compute_kind_dim_matrix([], attrs) == {}


def test_matrix_inner_join_single_pair() -> None:
    applies = [_StubApply("m1", "prompt")]
    attrs = [_StubAttr("m1", {"safety": 0.5}, attribution_score=1.0)]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix == {"prompt": {"safety": 0.5}}


def test_matrix_inner_join_two_kinds() -> None:
    applies = [
        _StubApply("m1", "prompt"),
        _StubApply("m2", "tool_policy"),
    ]
    attrs = [
        _StubAttr("m1", {"safety": 0.5}, attribution_score=1.0),
        _StubAttr("m2", {"safety": 0.3}, attribution_score=1.0),
    ]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix["prompt"]["safety"] == pytest.approx(0.5)
    assert matrix["tool_policy"]["safety"] == pytest.approx(0.3)


def test_matrix_accumulates_same_kind_dim() -> None:
    """Two apply+attr pairs on same kind+dim → sum."""
    applies = [
        _StubApply("m1", "prompt"),
        _StubApply("m2", "prompt"),
    ]
    attrs = [
        _StubAttr("m1", {"safety": 0.2}, attribution_score=1.0),
        _StubAttr("m2", {"safety": 0.4}, attribution_score=1.0),
    ]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix["prompt"]["safety"] == pytest.approx(0.6)


def test_matrix_signed_contribution() -> None:
    """Negative observed_dim preserves sign."""
    applies = [_StubApply("m1", "prompt")]
    attrs = [_StubAttr("m1", {"safety": -0.3}, attribution_score=1.0)]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix["prompt"]["safety"] == pytest.approx(-0.3)


def test_matrix_scaled_by_attribution_score() -> None:
    """attribution_score scales observed_dim contribution."""
    applies = [_StubApply("m1", "prompt")]
    attrs = [_StubAttr("m1", {"safety": 1.0}, attribution_score=0.5)]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix["prompt"]["safety"] == pytest.approx(0.5)


def test_matrix_orphan_attribution_skipped() -> None:
    """Attribution row whose mutation_id has no apply row → skip."""
    applies = [_StubApply("m1", "prompt")]
    attrs = [
        _StubAttr("m1", {"safety": 0.5}),
        _StubAttr("orphan", {"safety": 0.9}),  # no apply
    ]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix["prompt"]["safety"] == pytest.approx(0.5)
    assert "orphan" not in matrix.get("prompt", {})


def test_matrix_multi_dim_one_attribution() -> None:
    """Single attribution row with multiple dims contributes to each."""
    applies = [_StubApply("m1", "prompt")]
    attrs = [
        _StubAttr(
            "m1",
            {"safety": 0.5, "helpfulness": -0.2},
            attribution_score=1.0,
        )
    ]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix["prompt"]["safety"] == pytest.approx(0.5)
    assert matrix["prompt"]["helpfulness"] == pytest.approx(-0.2)


# ---------------------------------------------------------------------------
# 2. rank_dims_by_kind
# ---------------------------------------------------------------------------


def test_rank_dims_returns_sorted_by_abs_descending() -> None:
    matrix = {"prompt": {"a": 0.1, "b": -0.5, "c": 0.3}}
    ranked = rank_dims_by_kind(matrix, "prompt")
    assert ranked == [("b", -0.5), ("c", 0.3), ("a", 0.1)]


def test_rank_dims_missing_kind_empty() -> None:
    assert rank_dims_by_kind({"prompt": {"a": 1.0}}, "nonexistent") == []


def test_rank_dims_with_limit() -> None:
    matrix = {"prompt": {"a": 0.1, "b": -0.5, "c": 0.3, "d": 0.05}}
    ranked = rank_dims_by_kind(matrix, "prompt", limit=2)
    assert len(ranked) == 2
    assert ranked == [("b", -0.5), ("c", 0.3)]


# ---------------------------------------------------------------------------
# 3. Real ApplyRecord + AttributionRecord integration
# ---------------------------------------------------------------------------


def test_works_with_real_records() -> None:
    """End-to-end with real Pydantic models."""
    from core.self_improving_loop.attribution import AttributionRecord
    from core.self_improving_loop.runner import ApplyRecord

    applies = [
        ApplyRecord(
            ts=1.0,
            kind="applied",
            mutation_id="m1",
            target_kind="prompt",
            target_section="role",
            previous_value="x",
            new_value="y",
        )
    ]
    attrs = [
        AttributionRecord(
            ts=2.0,
            kind="attribution",
            mutation_id="m1",
            observed_dim={"safety": 0.5},
            attribution_score=1.0,
        )
    ]
    matrix = compute_kind_dim_matrix(applies, attrs)
    assert matrix == {"prompt": {"safety": 0.5}}
