"""Pre-defined Automation Templates — scheduled pipeline configurations.

Provides reusable automation templates for common GEODE operations:
weekly discovery scans, calibration drift checks, outcome tracking,
and auto-report generation.

Architecture-v6 SS4.5: Automation Layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from geode.automation.triggers import TriggerConfig, TriggerType


class PipelineConfig(BaseModel):
    """Configuration for a pipeline execution within an automation."""

    mode: str = "full_pipeline"
    batch_size: int = 1
    dry_run: bool = False
    skip_verification: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class AutomationTemplate(BaseModel):
    """A pre-defined automation template.

    Defines a named, schedulable pipeline configuration that
    can be triggered on a cron schedule or by events.
    """

    id: str
    name: str
    description: str
    schedule: str  # cron expression or "event:<event_type>"
    pipeline_config: PipelineConfig
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pre-defined automation templates
# ---------------------------------------------------------------------------

PREDEFINED_AUTOMATIONS: list[AutomationTemplate] = [
    AutomationTemplate(
        id="weekly_discovery_scan",
        name="Weekly Discovery Scan",
        description=(
            "Batch scan of top 50 candidate IPs every Monday at 09:00 UTC. "
            "Runs full pipeline with verification for new IP discovery."
        ),
        schedule="0 9 * * 1",  # Monday 09:00 UTC
        pipeline_config=PipelineConfig(
            mode="full_pipeline",
            batch_size=50,
            dry_run=False,
            skip_verification=False,
            extra={
                "source": "monolake_top_candidates",
                "min_signal_threshold": 0.3,
            },
        ),
        tags=["discovery", "batch", "weekly"],
    ),
    AutomationTemplate(
        id="calibration_drift_scan",
        name="Calibration Drift Scan",
        description=(
            "Daily CUSUM drift detection at 06:00 UTC. Monitors Spearman rho, "
            "human-LLM alpha, precision@10, and tier accuracy for distributional shifts."
        ),
        schedule="0 6 * * *",  # Daily 06:00 UTC
        pipeline_config=PipelineConfig(
            mode="evaluation",
            batch_size=1,
            dry_run=False,
            skip_verification=True,
            extra={
                "metrics": [
                    "spearman_rho",
                    "human_llm_alpha",
                    "precision_at_10",
                    "tier_accuracy",
                ],
                "cusum_warning_threshold": 2.5,
                "cusum_critical_threshold": 4.0,
                "psi_warning_threshold": 0.25,
            },
        ),
        tags=["calibration", "drift", "daily"],
    ),
    AutomationTemplate(
        id="outcome_tracker",
        name="Outcome Tracker",
        description=(
            "Monthly outcome tracking on the 1st at 00:00 UTC. "
            "Compares pipeline predictions against actual T+30 and T+90 day outcomes "
            "to measure prediction accuracy and calibrate scoring models."
        ),
        schedule="0 0 1 * *",  # 1st of month, 00:00 UTC
        pipeline_config=PipelineConfig(
            mode="scoring",
            batch_size=1,
            dry_run=False,
            skip_verification=False,
            extra={
                "tracking_windows": [30, 90],
                "metrics_to_compare": [
                    "predicted_tier",
                    "actual_tier",
                    "predicted_score",
                    "actual_revenue",
                ],
                "correlation_method": "spearman",
            },
        ),
        tags=["outcome", "tracking", "monthly"],
    ),
    AutomationTemplate(
        id="auto_generate_report",
        name="Auto-Generate Report",
        description=(
            "Event-triggered report generation on pipeline completion. "
            "Produces a structured analysis report with executive summary, "
            "scores, and recommendations for each completed IP evaluation."
        ),
        schedule="event:pipeline_complete",
        pipeline_config=PipelineConfig(
            mode="full_pipeline",
            batch_size=1,
            dry_run=False,
            skip_verification=False,
            extra={
                "report_format": "markdown",
                "include_sections": [
                    "executive_summary",
                    "scores",
                    "verification",
                    "recommendations",
                ],
                "notify_on_complete": True,
                "notification_channel": "slack",
            },
        ),
        tags=["report", "event-driven"],
    ),
]

# Lookup index for O(1) access
_AUTOMATION_INDEX: dict[str, AutomationTemplate] = {a.id: a for a in PREDEFINED_AUTOMATIONS}


def get_automation(automation_id: str) -> AutomationTemplate:
    """Get a pre-defined automation template by ID.

    Raises:
        KeyError: If automation ID not found.
    """
    template = _AUTOMATION_INDEX.get(automation_id)
    if template is None:
        available = list(_AUTOMATION_INDEX.keys())
        raise KeyError(
            f"Automation '{automation_id}' not found. Available: {available}"
        )
    return template


def list_automations(*, enabled_only: bool = False) -> list[AutomationTemplate]:
    """List all pre-defined automation templates.

    Args:
        enabled_only: If True, return only enabled templates.
    """
    if enabled_only:
        return [a for a in PREDEFINED_AUTOMATIONS if a.enabled]
    return list(PREDEFINED_AUTOMATIONS)


def create_trigger_from_template(template: AutomationTemplate) -> TriggerConfig:
    """Convert a predefined template to a TriggerConfig for the TriggerManager.

    Maps the template's schedule to the appropriate trigger type:
    - ``event:<name>`` schedules become EVENT triggers.
    - Cron expressions become SCHEDULED triggers.
    """
    if template.schedule.startswith("event:"):
        trigger_type = TriggerType.EVENT
        event_name = template.schedule.removeprefix("event:")
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
        event_name=event_name,
        enabled=template.enabled,
        metadata={
            "description": template.description,
            "pipeline_config": template.pipeline_config.model_dump(),
            "tags": template.tags,
        },
    )
