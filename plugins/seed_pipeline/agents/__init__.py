"""Seed-pipeline agent role implementations.

7 role (paper 6 + GEODE Pilot):
- generator     (S2, ✓)
- critic        (S3, ✓) — Reflection
- proximity     (S4)
- pilot         (S5)   — GEODE addition (scientist-in-the-loop 자리)
- ranker        (S6)   — Elo tournament + 3-judge panel
- evolver       (S7)
- meta_reviewer (S8)
"""

from __future__ import annotations

from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_pipeline.agents.critic import Critic
from plugins.seed_pipeline.agents.generator import Generator

__all__ = ["BaseSeedAgent", "Critic", "Generator", "SeedAgentResult"]
