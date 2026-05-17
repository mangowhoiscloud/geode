"""Seed-pipeline agent role implementations.

7 role (paper 6 + GEODE Pilot):
- generator   (S2)
- critic      (S3)   — Reflection
- proximity   (S4)
- pilot       (S5)   — GEODE addition (scientist-in-the-loop 자리)
- ranker      (S6)   — Elo tournament + 3-judge panel
- evolver     (S7)
- meta_reviewer (S8)

본 S1 PR 은 ``BaseSeedAgent`` 추상 클래스 + ``SeedAgentResult`` dataclass
만 도입. 각 role 의 concrete 구현은 후속 PR.
"""

from __future__ import annotations

from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult

__all__ = ["BaseSeedAgent", "SeedAgentResult"]
