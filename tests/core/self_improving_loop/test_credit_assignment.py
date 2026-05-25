"""C.4 (2026-05-25) — credit_assignment invariants (PR-16).

Scope:
- compute_credit_assignment: group_advantage None / empty expected_dim /
  zero-magnitude expected_dim → empty dict (graceful)
- happy path: magnitude-weighted partition sum = group_advantage
- single dim → all credit goes there
- aggregate_credit_history: empty / cumulative / skip rows without advantage
- expected_dim sign convention — credit is unsigned, caller multiplies by
  sign(expected_dim[d]) if directional intent needed
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from core.self_improving_loop.credit_assignment import (
    aggregate_credit_history,
    compute_credit_assignment,
)

# ---------------------------------------------------------------------------
# Test fixtures — minimal Mutation/ApplyRecord stand-ins
# ---------------------------------------------------------------------------


@dataclass
class _StubMutation:
    expected_dim: dict[str, float] = field(default_factory=dict)


@dataclass
class _StubApplyRecord:
    expected_dim: dict[str, float] = field(default_factory=dict)
    group_advantage: float | None = None


# ---------------------------------------------------------------------------
# 1. compute_credit_assignment — graceful empty paths
# ---------------------------------------------------------------------------


def test_compute_returns_empty_when_advantage_none() -> None:
    mutation = _StubMutation(expected_dim={"safety": 0.3})
    assert compute_credit_assignment(mutation, None) == {}


def test_compute_returns_empty_when_expected_dim_empty() -> None:
    mutation = _StubMutation(expected_dim={})
    assert compute_credit_assignment(mutation, 0.5) == {}


def test_compute_returns_empty_when_expected_magnitudes_all_zero() -> None:
    mutation = _StubMutation(expected_dim={"safety": 0.0, "helpfulness": 0.0})
    assert compute_credit_assignment(mutation, 0.5) == {}


# ---------------------------------------------------------------------------
# 2. compute_credit_assignment — magnitude-weighted partition
# ---------------------------------------------------------------------------


def test_compute_single_dim_full_credit() -> None:
    mutation = _StubMutation(expected_dim={"safety": 0.3})
    result = compute_credit_assignment(mutation, 0.5)
    assert result == {"safety": 0.5}


def test_compute_two_equal_magnitude_splits_evenly() -> None:
    mutation = _StubMutation(expected_dim={"safety": 0.3, "helpfulness": -0.3})
    result = compute_credit_assignment(mutation, 1.0)
    assert result["safety"] == pytest.approx(0.5)
    assert result["helpfulness"] == pytest.approx(0.5)


def test_compute_unequal_magnitude_weighted() -> None:
    """|0.3| + |0.1| = 0.4; safety gets 0.75 share, helpfulness 0.25."""
    mutation = _StubMutation(expected_dim={"safety": 0.3, "helpfulness": -0.1})
    result = compute_credit_assignment(mutation, 1.0)
    assert result["safety"] == pytest.approx(0.75)
    assert result["helpfulness"] == pytest.approx(0.25)


def test_compute_sum_equals_advantage() -> None:
    """Magnitude partition invariant: sum(credit) == group_advantage."""
    mutation = _StubMutation(expected_dim={"a": 0.4, "b": 0.6, "c": -0.2})
    result = compute_credit_assignment(mutation, 0.8)
    assert sum(result.values()) == pytest.approx(0.8)


def test_compute_negative_advantage_propagates() -> None:
    """Negative group_advantage → all credit negative (intent-direction is
    encoded in expected_dim sign, not credit sign)."""
    mutation = _StubMutation(expected_dim={"safety": 0.3, "helpfulness": -0.3})
    result = compute_credit_assignment(mutation, -1.0)
    assert result["safety"] == pytest.approx(-0.5)
    assert result["helpfulness"] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# 3. aggregate_credit_history — accumulation
# ---------------------------------------------------------------------------


def test_aggregate_empty_records() -> None:
    assert aggregate_credit_history([]) == {}


def test_aggregate_skips_records_without_advantage() -> None:
    """records with group_advantage=None (legacy single-mutation) skipped."""
    records = [
        _StubApplyRecord(expected_dim={"safety": 0.3}, group_advantage=None),
        _StubApplyRecord(expected_dim={}, group_advantage=0.5),
    ]
    assert aggregate_credit_history(records) == {}


def test_aggregate_single_record() -> None:
    records = [_StubApplyRecord(expected_dim={"safety": 0.3}, group_advantage=0.5)]
    result = aggregate_credit_history(records)
    assert result == {"safety": 0.5}


def test_aggregate_accumulates_across_records() -> None:
    records = [
        _StubApplyRecord(expected_dim={"safety": 0.3}, group_advantage=0.5),
        _StubApplyRecord(expected_dim={"safety": 0.4}, group_advantage=0.2),
        _StubApplyRecord(expected_dim={"helpfulness": 0.1}, group_advantage=0.3),
    ]
    result = aggregate_credit_history(records)
    assert result["safety"] == pytest.approx(0.7)
    assert result["helpfulness"] == pytest.approx(0.3)


def test_aggregate_handles_negative_advantage() -> None:
    """Negative advantage subtracts from cumulative."""
    records = [
        _StubApplyRecord(expected_dim={"safety": 0.3}, group_advantage=0.5),
        _StubApplyRecord(expected_dim={"safety": 0.3}, group_advantage=-0.2),
    ]
    result = aggregate_credit_history(records)
    assert result["safety"] == pytest.approx(0.3)


def test_aggregate_multi_dim_per_record() -> None:
    """Single record with multiple dims contributes to each."""
    records = [
        _StubApplyRecord(
            expected_dim={"safety": 0.5, "helpfulness": -0.5},
            group_advantage=1.0,
        )
    ]
    result = aggregate_credit_history(records)
    assert result["safety"] == pytest.approx(0.5)
    assert result["helpfulness"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 4. Real ApplyRecord integration
# ---------------------------------------------------------------------------


def test_works_with_real_apply_record() -> None:
    """ApplyRecord (real Pydantic) → aggregate_credit_history 호출 가능."""
    from core.self_improving_loop.runner import ApplyRecord

    records = [
        ApplyRecord(
            ts=1.0,
            kind="applied",
            mutation_id="m1",
            target_kind="prompt",
            target_section="role",
            previous_value="x",
            new_value="y",
            expected_dim={"safety": 0.5},
            group_advantage=0.6,
        )
    ]
    result = aggregate_credit_history(records)
    assert result == {"safety": 0.6}
