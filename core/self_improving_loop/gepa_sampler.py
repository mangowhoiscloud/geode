"""A.4 (2026-05-25) — GEPA Pareto sampler (PR-25).

Plan ``docs/plans/2026-05-25-p2-pareto-archive-dynamic-reward-weighting.md``
§C8. PR-15 ``pareto_archive.PareteArchive.sample`` 의 uniform-random
sampling 을 **density-aware** sparsity-weighted 로 개선.

**Why density-aware**:

- Uniform sampling 은 archive 의 dense region (많은 entry 가 비슷한
  fitness vector 공유) 에 편향. Pareto front 의 sparse region (rare
  trade-off) 은 over-explored 부족.
- Sparsity weight ∝ inverse local density — sparse niche 의 entry 가
  sample 될 확률 ↑. Quality-Diversity 의 핵심 (Mouret & Clune 2015).

**Frontier reference**: GEPA (Genetic Evolutionary Pareto Archive,
arXiv 2406.xxxxx) — Pareto sampler 의 reflection-text 친화 (sampled
entry 의 mutation rationale 을 next mutator 의 priors 로 forward).

본 module = **pure helper**:

- :func:`compute_sparsity_weights(fitness_vectors, k)` — k-NN 평균거리
  기반 sparsity score. sparse = high weight.
- :func:`sample_sparse(entries, k_neighbors, n, rng)` — sparsity 가중
  random sample.

caller (apply_group_proposals 의 archive sample 분기) wiring 후속 PR.
"""

from __future__ import annotations

import math
import random


def _euclidean_distance(a: dict[str, float], b: dict[str, float]) -> float:
    """Per-dim squared diff sum의 sqrt. Missing dim → treated as 0
    on the missing side (conservative — caller can normalize beforehand)."""
    dims = set(a.keys()) | set(b.keys())
    if not dims:
        return 0.0
    squared = 0.0
    for d in dims:
        av = float(a.get(d, 0.0))
        bv = float(b.get(d, 0.0))
        diff = av - bv
        squared += diff * diff
    return math.sqrt(squared)


def compute_sparsity_weights(
    fitness_vectors: list[dict[str, float]],
    k: int = 3,
) -> list[float]:
    """Return per-entry sparsity weight (higher = more sparse / under-
    represented in fitness space).

    Algorithm — for each entry, compute the mean Euclidean distance to
    its ``k`` nearest neighbors. Larger mean distance = sparser region =
    higher weight. Returns raw distances (not normalized); caller may
    normalize to a probability distribution.

    Edge cases:
    - ``len(fitness_vectors) <= 1`` → all weights 1.0 (no neighbors)
    - ``k`` clamped to ``len(fitness_vectors) - 1``
    - empty input → empty list
    """
    n = len(fitness_vectors)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    effective_k = min(k, n - 1)
    weights: list[float] = []
    for i, vec_i in enumerate(fitness_vectors):
        distances: list[float] = []
        for j, vec_j in enumerate(fitness_vectors):
            if i == j:
                continue
            distances.append(_euclidean_distance(vec_i, vec_j))
        distances.sort()
        nearest = distances[:effective_k]
        mean_dist = sum(nearest) / len(nearest) if nearest else 0.0
        # Sparsity weight = mean k-NN distance; sparse regions yield larger
        # values. We add small epsilon so all-identical vectors don't
        # collapse to zero probability.
        weights.append(mean_dist + 1e-9)
    return weights


def sample_sparse[T](
    entries: list[T],
    fitness_vectors: list[dict[str, float]],
    n: int,
    *,
    k_neighbors: int = 3,
    rng: random.Random | None = None,
) -> list[T]:
    """Sample ``n`` entries with probability ∝ sparsity weight.

    ``entries`` and ``fitness_vectors`` must be parallel (same length,
    same indexing). Sampling is **without replacement** — at most
    ``len(entries)`` returned. Empty input → empty list.

    Returns the sampled entries in random order.
    """
    if len(entries) != len(fitness_vectors):
        raise ValueError(
            f"entries / fitness_vectors length mismatch: {len(entries)} vs {len(fitness_vectors)}"
        )
    if not entries or n <= 0:
        return []
    rng = rng or random.Random()
    weights = compute_sparsity_weights(fitness_vectors, k=k_neighbors)
    # rng.choices with replacement; then dedupe — caller wants without-
    # replacement. For without-replacement, repeated weighted sampling
    # without replacement requires removing the sampled index.
    pool: list[tuple[T, float]] = list(zip(entries, weights, strict=True))
    sampled: list[T] = []
    target = min(n, len(pool))
    while pool and len(sampled) < target:
        items, ws = zip(*pool, strict=True)
        total = sum(ws)
        if total <= 0:
            # All-zero weights — fall back to uniform
            choice_idx = rng.randrange(len(items))
        else:
            choice_idx = rng.choices(range(len(items)), weights=ws, k=1)[0]
        sampled.append(items[choice_idx])
        pool.pop(choice_idx)
    return sampled


__all__ = [
    "compute_sparsity_weights",
    "sample_sparse",
]
