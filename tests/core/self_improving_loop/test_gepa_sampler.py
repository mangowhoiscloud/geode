"""A.4 (2026-05-25) — GEPA Pareto sampler invariants (PR-25)."""

from __future__ import annotations

import random

import pytest
from core.self_improving_loop.gepa_sampler import (
    compute_sparsity_weights,
    sample_sparse,
)

# ---------------------------------------------------------------------------
# 1. compute_sparsity_weights
# ---------------------------------------------------------------------------


def test_sparsity_empty_input() -> None:
    assert compute_sparsity_weights([]) == []


def test_sparsity_single_entry_weight_is_one() -> None:
    """1 entry → no neighbors → uniform fallback 1.0."""
    weights = compute_sparsity_weights([{"a": 0.5}])
    assert weights == [1.0]


def test_sparsity_two_entries_equal_weight() -> None:
    """2 entries — each has 1 neighbor (the other). Both same distance."""
    weights = compute_sparsity_weights([{"a": 0.1, "b": 0.1}, {"a": 0.9, "b": 0.9}])
    assert len(weights) == 2
    # Same mutual distance → same weight
    assert weights[0] == pytest.approx(weights[1])


def test_sparsity_isolated_entry_higher_weight() -> None:
    """Cluster of 3 close points + 1 isolated → isolated has higher weight."""
    vectors = [
        {"a": 0.1, "b": 0.1},  # cluster
        {"a": 0.12, "b": 0.11},  # cluster
        {"a": 0.11, "b": 0.13},  # cluster
        {"a": 0.9, "b": 0.9},  # isolated
    ]
    weights = compute_sparsity_weights(vectors, k=2)
    # The isolated entry (idx 3) should be the heaviest
    assert weights[3] > weights[0]
    assert weights[3] > weights[1]
    assert weights[3] > weights[2]


def test_sparsity_k_clamped_to_n_minus_1() -> None:
    """k > n-1 → 자동 clamp, no IndexError."""
    weights = compute_sparsity_weights([{"a": 0.1}, {"a": 0.5}], k=10)
    assert len(weights) == 2


def test_sparsity_all_identical_vectors_nonzero_weights() -> None:
    """All-identical fitness vectors → 0 distance + epsilon prevents
    zero-probability collapse."""
    weights = compute_sparsity_weights([{"a": 0.5}, {"a": 0.5}, {"a": 0.5}])
    assert all(w > 0 for w in weights), "epsilon prevents all-zero collapse"


# ---------------------------------------------------------------------------
# 2. sample_sparse — basic shape
# ---------------------------------------------------------------------------


def test_sample_sparse_empty_returns_empty() -> None:
    assert sample_sparse([], [], 3) == []


def test_sample_sparse_n_zero_returns_empty() -> None:
    entries = ["a", "b"]
    vectors = [{"x": 0.1}, {"x": 0.5}]
    assert sample_sparse(entries, vectors, 0) == []


def test_sample_sparse_n_larger_than_pool() -> None:
    """n > len(entries) → capped at len(entries)."""
    entries = ["a", "b"]
    vectors = [{"x": 0.1}, {"x": 0.5}]
    result = sample_sparse(entries, vectors, n=10, rng=random.Random(42))
    assert len(result) == 2


def test_sample_sparse_without_replacement() -> None:
    """Sampling without replacement — no duplicates."""
    entries = list("abcdef")
    vectors = [{"x": i / 6} for i in range(6)]
    rng = random.Random(42)
    result = sample_sparse(entries, vectors, n=4, rng=rng)
    assert len(result) == 4
    assert len(set(result)) == 4  # all distinct


def test_sample_sparse_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match=r"length mismatch"):
        sample_sparse(["a", "b"], [{"x": 0.1}], 2)


# ---------------------------------------------------------------------------
# 3. sample_sparse — density-aware behavior
# ---------------------------------------------------------------------------


def test_sample_sparse_isolated_entry_preferred() -> None:
    """3 close cluster + 1 isolated. Sample n=1 → isolated more likely.

    Run multiple trials and confirm isolated wins majority. Not a strict
    invariant per single trial, but probabilistic.
    """
    entries = ["c1", "c2", "c3", "isolated"]
    vectors = [
        {"a": 0.1, "b": 0.1},
        {"a": 0.12, "b": 0.11},
        {"a": 0.11, "b": 0.13},
        {"a": 0.9, "b": 0.9},
    ]
    isolated_count = 0
    trials = 100
    for trial in range(trials):
        rng = random.Random(trial)
        result = sample_sparse(entries, vectors, n=1, rng=rng, k_neighbors=2)
        if result == ["isolated"]:
            isolated_count += 1
    # Isolated should win clearly more often than uniform (25%) — expect
    # > 50% with the sparsity weighting.
    assert isolated_count > 50, (
        f"isolated picked {isolated_count}/{trials} times — sparsity weight not biasing as expected"
    )


def test_sample_sparse_deterministic_with_seeded_rng() -> None:
    """Same seed → same sampled order."""
    entries = list("abcdef")
    vectors = [{"x": i / 6} for i in range(6)]
    result_a = sample_sparse(entries, vectors, n=3, rng=random.Random(42))
    result_b = sample_sparse(entries, vectors, n=3, rng=random.Random(42))
    assert result_a == result_b


# ---------------------------------------------------------------------------
# 4. All-identical vectors → uniform fallback (degenerate case)
# ---------------------------------------------------------------------------


def test_sample_sparse_all_identical_vectors_works() -> None:
    """Degenerate case — all fitness identical. Sampling still completes."""
    entries = ["a", "b", "c"]
    vectors = [{"x": 0.5}] * 3
    rng = random.Random(0)
    result = sample_sparse(entries, vectors, n=2, rng=rng)
    assert len(result) == 2
    assert set(result).issubset({"a", "b", "c"})
