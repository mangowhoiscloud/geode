"""P4 (2026-05-25) — Swarm-level baseline scaffolding (Kimi K2.6 영감).

Plan: ``docs/plans/2026-05-25-p4-parl-swarm-scaffolding.md``.

Frontier source:
- Kimi K2.6 (Moonshot 2026-04-20) — PARL (Parallel-Agent RL), 100→300
  sub-agent + 1500→4000 coordinated step. credit assignment 식은 미공개.

GEODE 적용 — Kimi K2.6 의 *post-trained* decomposition policy 는 mutator
frozen 와 충돌. **inference-time 변형**:
- M sub-agent 가 각자 mutation chain (다른 agent_contract policy slice)
- swarm-level fitness aggregation (mean / max config)
- multi-level grouping: swarm_id (level 2) + group_id (level 1)

본 모듈 = **selection-only scaffolding** (P1-revised, P2 와 같은 정합):
- training-time policy update 없음 (mutator API frozen)
- post-trained PARL 의 정확한 식 미공개로, 본 MVP 는 aggregation +
  multi-level grouping helper 만. 실제 propose_swarm + apply_swarm
  wiring 은 P4.1 후속.
"""

from __future__ import annotations

import logging
import statistics
from typing import Literal

log = logging.getLogger(__name__)

SwarmAggregation = Literal["mean", "median", "max"]
"""Swarm-level fitness aggregation strategy. plan §3 D1.

- ``mean``: M sub-agent 의 fitness 평균. PARL 의 swarm-mean 패턴 (Kimi
  K2.6 추정).
- ``median``: outlier-resilient. 단일 sub-agent failure 시 swarm 안정.
- ``max``: best-of-M. exploration 강조.
"""


def aggregate_swarm_fitness(
    fitness_values: list[float],
    *,
    method: SwarmAggregation = "mean",
) -> float:
    """M sub-agent 의 fitness scalar → 1 swarm-level fitness.

    Plan §5 D3 — apply_swarm_proposals 의 fitness aggregation step.
    aggregation strategy 는 config knob (``AutoresearchConfig.swarm_aggregation``).

    Empty list → 0.0 (graceful fallback, swarm 폐기 시그널).
    """
    if not fitness_values:
        return 0.0
    if method == "mean":
        return sum(fitness_values) / len(fitness_values)
    if method == "median":
        return statistics.median(fitness_values)
    if method == "max":
        return max(fitness_values)
    raise ValueError(f"unknown swarm_aggregation method: {method!r}")


def decompose_sub_agent_contribution(
    swarm_fitness: float,
    sub_agent_fitness_values: list[float],
    *,
    method: SwarmAggregation = "mean",
) -> list[float]:
    """Sub-agent 별 swarm fitness 기여도 (per-agent contribution).

    Plan §3 sub-agent contribution decomposition. PARL 의 credit assignment
    식이 미공개라 본 MVP 는 단순 deviation:

    - ``mean``: contribution_i = fitness_i - swarm_mean
    - ``median``: contribution_i = fitness_i - swarm_median
    - ``max``: contribution_i = 1.0 if argmax else 0.0

    Returns list parallel to ``sub_agent_fitness_values`` — same indexing.
    """
    if not sub_agent_fitness_values:
        return []
    if method == "max":
        max_val = max(sub_agent_fitness_values)
        return [1.0 if v == max_val else 0.0 for v in sub_agent_fitness_values]
    return [v - swarm_fitness for v in sub_agent_fitness_values]


__all__ = [
    "SwarmAggregation",
    "aggregate_swarm_fitness",
    "decompose_sub_agent_contribution",
]
