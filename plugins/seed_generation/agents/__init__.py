"""Seed-pipeline agent role implementations.

7 role (paper 6 + GEODE Pilot):
- generator     (S2, ✓)
- critic        (S3, ✓) — Reflection
- proximity     (S4, ✓) — paper §3 LLM-clustering (CSP-8 revert)
- pilot         (S5, ✓) — GEODE addition (scientist-in-the-loop slot)
- ranker        (S6, ✓) — Elo tournament + 3-judge panel
- evolver       (S7, ✓) — Reflection-driven section rewrite
- meta_reviewer (S8, ✓) — coverage + next-gen prior + session summary
"""

from __future__ import annotations

from plugins.seed_generation.agents.base import (
    DEFAULT_AGENT_MODEL,
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
)
from plugins.seed_generation.agents.critic import Critic
from plugins.seed_generation.agents.evolver import Evolver
from plugins.seed_generation.agents.generator import Generator
from plugins.seed_generation.agents.meta_reviewer import MetaReviewer
from plugins.seed_generation.agents.pilot import Pilot
from plugins.seed_generation.agents.proximity import Proximity
from plugins.seed_generation.agents.ranker import Ranker

__all__ = [
    "DEFAULT_AGENT_MODEL",
    "BaseSeedAgent",
    "Critic",
    "Evolver",
    "Generator",
    "MetaReviewer",
    "Pilot",
    "Proximity",
    "Ranker",
    "SeedAgentResult",
    "parse_structured_output",
]
