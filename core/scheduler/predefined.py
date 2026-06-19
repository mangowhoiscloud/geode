"""Pre-defined automation template registry.

GEODE core no longer ships package-specific automation templates. External
packages may register their own templates through scheduler wiring.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineConfig(BaseModel):
    """Configuration for a pipeline execution within an automation."""

    mode: str = "pipeline"
    batch_size: int = 1
    dry_run: bool = False
    skip_verification: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class AutomationTemplate(BaseModel):
    """A schedulable automation template."""

    id: str
    name: str
    description: str
    schedule: str
    pipeline_config: PipelineConfig
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


PREDEFINED_AUTOMATIONS: list[AutomationTemplate] = []
