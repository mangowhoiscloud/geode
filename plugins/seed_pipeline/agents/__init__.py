"""Seed-pipeline agent role implementations.

7 role (paper 6 + GEODE Pilot):
- generator     (S2, ✓)
- critic        (S3, ✓) — Reflection
- proximity     (S4, ✓) — 3-track dedup (embedding + lexical + role)
- pilot         (S5, ✓) — GEODE addition (scientist-in-the-loop 자리)
- ranker        (S6, ✓) — Elo tournament + 3-judge panel
- evolver       (S7, ✓) — Reflection-driven section rewrite
- meta_reviewer (S8)
"""

from __future__ import annotations

from plugins.seed_pipeline.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
)
from plugins.seed_pipeline.agents.critic import Critic
from plugins.seed_pipeline.agents.evolver import Evolver
from plugins.seed_pipeline.agents.generator import Generator
from plugins.seed_pipeline.agents.pilot import Pilot
from plugins.seed_pipeline.agents.proximity import Proximity
from plugins.seed_pipeline.agents.ranker import Ranker

__all__ = [
    "BaseSeedAgent",
    "Critic",
    "Evolver",
    "Generator",
    "Pilot",
    "Proximity",
    "Ranker",
    "SeedAgentResult",
    "parse_structured_output",
]
