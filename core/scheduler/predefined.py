"""Pre-defined Automation Templates — scheduled pipeline configurations.

Provides 10 reusable automation templates for common GEODE operations:
discovery scans, pending analysis workers, calibration drift checks,
data quality scans, anomaly detection, outcome tracking, report generation,
S-tier reports, discovery summaries, and failed evaluation summaries.

Architecture-v6 §4.5 / §12.4: Automation Layer — Pre-defined Automations.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.scheduler.triggers import TriggerConfig, TriggerType


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
    AutomationTemplate(
        id="pending_analysis_worker",
        name="Pending Analysis Worker",
        description=(
            "Process pending IP analysis queue every 30 minutes. "
            "Picks up IPs awaiting evaluation and runs them through "
            "the full pipeline with verification."
        ),
        schedule="*/30 * * * *",  # Every 30 minutes
        pipeline_config=PipelineConfig(
            mode="full_pipeline",
            batch_size=10,
            dry_run=False,
            skip_verification=False,
            extra={
                "source": "pending_queue",
                "priority": "fifo",
                "max_concurrent": 3,
            },
        ),
        tags=["worker", "queue", "scheduled"],
    ),
    AutomationTemplate(
        id="data_quality_scan",
        name="Data Quality Scan",
        description=(
            "Daily data quality validation at 05:00 UTC. Checks signal "
            "completeness, schema conformance, and stale data across all "
            "active IP records in the pipeline."
        ),
        schedule="0 5 * * *",  # Daily 05:00 UTC
        pipeline_config=PipelineConfig(
            mode="evaluation",
            batch_size=1,
            dry_run=False,
            skip_verification=True,
            extra={
                "checks": [
                    "signal_completeness",
                    "schema_conformance",
                    "stale_data",
                    "duplicate_detection",
                ],
                "staleness_threshold_days": 30,
                "min_signal_coverage": 0.6,
            },
        ),
        tags=["quality", "data", "daily"],
    ),
    AutomationTemplate(
        id="anomaly_detector",
        name="Anomaly Detector",
        description=(
            "Event-triggered anomaly detection on pipeline completion. "
            "Analyzes scoring distributions for statistical outliers "
            "and flags IPs with anomalous evaluation patterns."
        ),
        schedule="event:pipeline_complete",
        pipeline_config=PipelineConfig(
            mode="evaluation",
            batch_size=1,
            dry_run=False,
            skip_verification=True,
            extra={
                "detection_methods": ["zscore", "iqr", "isolation_forest"],
                "zscore_threshold": 3.0,
                "iqr_multiplier": 1.5,
                "notify_on_anomaly": True,
            },
        ),
        tags=["anomaly", "detection", "event-driven"],
    ),
    AutomationTemplate(
        id="weekly_s_tier_report",
        name="Weekly S-Tier Report",
        description=(
            "Weekly report of S-tier IP discoveries every Friday at 10:00 UTC. "
            "Aggregates top-scoring IPs from the week and generates an "
            "executive briefing with investment recommendations."
        ),
        schedule="0 10 * * 5",  # Friday 10:00 UTC
        pipeline_config=PipelineConfig(
            mode="scoring",
            batch_size=1,
            dry_run=False,
            skip_verification=False,
            extra={
                "tier_filter": ["S", "A"],
                "report_format": "markdown",
                "include_sections": [
                    "executive_summary",
                    "top_discoveries",
                    "score_breakdown",
                    "investment_signals",
                ],
                "lookback_days": 7,
            },
        ),
        tags=["report", "s-tier", "weekly"],
    ),
    AutomationTemplate(
        id="weekly_discovery_summary",
        name="Weekly Discovery Summary",
        description=(
            "Monday morning summary of all IP discoveries from the past week. "
            "Provides pipeline throughput metrics, tier distribution, "
            "and highlights notable findings. Runs after weekly_discovery_scan."
        ),
        schedule="0 10 * * 1",  # Monday 10:00 UTC (after discovery scan at 09:00)
        pipeline_config=PipelineConfig(
            mode="scoring",
            batch_size=1,
            dry_run=False,
            skip_verification=False,
            extra={
                "report_type": "weekly_summary",
                "include_metrics": [
                    "throughput",
                    "tier_distribution",
                    "avg_confidence",
                    "notable_findings",
                ],
                "lookback_days": 7,
            },
        ),
        tags=["summary", "discovery", "weekly"],
    ),
    AutomationTemplate(
        id="failed_evaluation_summary",
        name="Failed Evaluation Summary",
        description=(
            "Daily summary of failed evaluations at 08:00 UTC. "
            "Aggregates pipeline failures, guardrail rejections, and "
            "verification failures for debugging and process improvement."
        ),
        schedule="0 8 * * *",  # Daily 08:00 UTC
        pipeline_config=PipelineConfig(
            mode="evaluation",
            batch_size=1,
            dry_run=False,
            skip_verification=True,
            extra={
                "failure_categories": [
                    "pipeline_error",
                    "guardrail_rejection",
                    "verification_failure",
                    "timeout",
                ],
                "include_stack_traces": False,
                "lookback_hours": 24,
            },
        ),
        tags=["failures", "debugging", "daily"],
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
        raise KeyError(f"Automation '{automation_id}' not found. Available: {available}")
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
