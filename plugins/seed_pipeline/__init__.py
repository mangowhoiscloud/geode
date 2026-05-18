"""Seed-pipeline plugin — co-scientist (arXiv:2502.18864) port.

co-scientist 의 7-role generate/debate/evolve loop 를 GEODE 의 sub-agent
인프라 위에 port. Petri × autoresearch 의 frozen seed pool quality + size
확장 (`plugins/petri_audit/seeds_safe10/` → `plugins/petri_audit/seeds_gen<N>/`).

본 plugin 은 ``plugins.petri_audit`` 에 sibling 의존:
- credential resolution: ``plugins.petri_audit.credential_source``
- adapter binding: ``plugins.petri_audit.adapters``
- inner-loop pilot: ``plugins.petri_audit.runner``

진입점:
- Typer CLI: ``geode audit-seeds <sub>`` (S11)
- Slash: ``/audit-seeds <sub>`` (S11)

SOT:
- ADR-001: ``docs/architecture/seed-pipeline-decision.md``
- ADR-003: ``docs/architecture/seed-pipeline-ui-decision.md``
- Plan: ``docs/plans/2026-05-18-seed-pipeline-sprint-plan.md``
"""

from __future__ import annotations

from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_pipeline.manifest import (
    JudgePanelSpec,
    SeedPipelineManifest,
    SeedRoleSpec,
    VoterSpec,
    load_manifest,
)
from plugins.seed_pipeline.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
)

__all__ = [
    "BaseSeedAgent",
    "JudgePanelSpec",
    "Pipeline",
    "PipelineRegistry",
    "PipelineState",
    "SeedAgentResult",
    "SeedPipelineManifest",
    "SeedRoleSpec",
    "VoterSpec",
    "load_manifest",
]
