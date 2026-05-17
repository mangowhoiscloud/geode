"""Pre-defined automation template registry.

GEODE core no longer ships domain-specific automation templates. External
domain plugins may register their own templates through scheduler wiring.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.scheduler.triggers import TriggerConfig, TriggerType


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
_AUTOMATION_INDEX: dict[str, AutomationTemplate] = {}


def get_automation(automation_id: str) -> AutomationTemplate:
    """Get a pre-defined automation template by ID."""
    template = _AUTOMATION_INDEX.get(automation_id)
    if template is None:
        raise KeyError(f"Automation template not found: {automation_id}")
    return template


def list_automations(
    *,
    tag: str | None = None,
    enabled_only: bool = False,
) -> list[AutomationTemplate]:
    """List registered automation templates."""
    automations = PREDEFINED_AUTOMATIONS
    if tag:
        automations = [a for a in automations if tag in a.tags]
    if enabled_only:
        automations = [a for a in automations if a.enabled]
    return list(automations)


def to_trigger_config(template: AutomationTemplate) -> TriggerConfig:
    """Convert an AutomationTemplate to a TriggerConfig."""
    if template.schedule.startswith("event:"):
        trigger_type = TriggerType.EVENT
        event_name = template.schedule.split(":", 1)[1]
        cron_expr = ""
    else:
        trigger_type = TriggerType.SCHEDULED
        event_name = ""
        cron_expr = template.schedule

    return TriggerConfig(
        trigger_id=template.id,
        trigger_type=trigger_type,
        name=template.name,
        cron_expr=cron_expr,
        metadata={
            "automation_id": template.id,
            "event_name": event_name,
            "pipeline_config": template.pipeline_config.model_dump(),
        },
        enabled=template.enabled,
    )
