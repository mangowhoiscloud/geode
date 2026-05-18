"""Seed-pipeline plugin — co-scientist (arXiv:2502.18864) port.

Ports the co-scientist 7-role generate/debate/evolve loop onto GEODE's
sub-agent infrastructure. Goal: expand the Petri × autoresearch seed
pool in both quality and size (legacy flat pool → hierarchical tree,
post-PR-0).  # slop:keep

This plugin has sibling-level dependencies on ``plugins.petri_audit``:
- credential resolution: ``plugins.petri_audit.credential_source``
- adapter binding: ``plugins.petri_audit.adapters``
- inner-loop pilot: ``plugins.petri_audit.runner``

Entry points:
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
