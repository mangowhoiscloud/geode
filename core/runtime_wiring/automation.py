"""Automation wiring — L4.5 9 components + hook wiring.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from core.automation.correlation import CorrelationAnalyzer
from core.automation.drift import CUSUMDetector
from core.automation.expert_panel import ExpertPanel
from core.automation.feedback_loop import FeedbackLoop
from core.automation.model_registry import ModelRegistry
from core.automation.outcome_tracking import OutcomeTracker
from core.automation.snapshot import SnapshotManager
from core.automation.triggers import TriggerManager, TriggerType
from core.config import settings
from core.hooks import HookEvent, HookSystem
from core.memory.project import ProjectMemory

log = logging.getLogger(__name__)


def build_automation(
    *,
    hooks: HookSystem,
    session_key: str,
    ip_name: str,
    project_memory: ProjectMemory | None = None,
) -> dict[str, Any]:
    """Build L4.5 automation components and wire hook event handlers.

    Returns a dict of component name -> instance for passing to the constructor.
    """
    # Drift detector (CUSUM)
    drift_detector = CUSUMDetector()

    # Model registry (file-based)
    if settings.model_registry_dir:
        reg_dir: Path | None = Path(settings.model_registry_dir)
    else:
        from core.paths import resolve_models_dir

        reg_dir = resolve_models_dir()
    model_registry = ModelRegistry(storage_dir=reg_dir, hooks=hooks)

    # Expert panel
    expert_panel = ExpertPanel()

    # Correlation analyzer
    correlation_analyzer = CorrelationAnalyzer()

    # Outcome tracker
    outcome_tracker = OutcomeTracker(hooks=hooks)

    # Snapshot manager (with auto-GC)
    if settings.snapshot_dir:
        snapshot_dir: Path | None = Path(settings.snapshot_dir)
    else:
        from core.paths import resolve_snapshots_dir

        snapshot_dir = resolve_snapshots_dir()
    snapshot_manager = SnapshotManager(
        storage_dir=snapshot_dir,
        max_recent=settings.snapshot_max_recent,
        hooks=hooks,
        auto_gc_threshold=settings.snapshot_gc_threshold,
    )

    # Trigger manager (auto-start scheduler for cron-based triggers)
    trigger_manager = TriggerManager(
        scheduler_interval_s=settings.trigger_scheduler_interval_s,
        hooks=hooks,
    )
    trigger_manager.start_scheduler()

    # Advanced scheduler service (3-type: AT/EVERY/CRON + active hours)
    from core.automation.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

    scheduler_service = SchedulerService(
        trigger_manager=trigger_manager,
        hooks=hooks,
    )
    scheduler_service.load()

    from core.automation.predefined import PREDEFINED_AUTOMATIONS

    for tmpl in PREDEFINED_AUTOMATIONS:
        if tmpl.enabled and not tmpl.schedule.startswith("event:"):
            job = ScheduledJob(
                job_id=f"predefined:{tmpl.id}",
                name=tmpl.name,
                schedule=Schedule(
                    kind=ScheduleKind.CRON,
                    cron_expr=tmpl.schedule,
                ),
                enabled=tmpl.enabled,
                metadata={
                    "source": "predefined",
                    "template_id": tmpl.id,
                },
            )
            with contextlib.suppress(ValueError):
                scheduler_service.add_job(job)

    if settings.scheduler_auto_start:
        scheduler_service.start(
            interval_s=settings.scheduler_interval_s,
        )

    # Feedback loop (wires all L4.5 components + hooks)
    feedback_loop = FeedbackLoop(
        model_registry=model_registry,
        expert_panel=expert_panel,
        correlation_analyzer=correlation_analyzer,
        drift_detector=drift_detector,
        hooks=hooks,
    )

    wire_automation_hooks(
        hooks,
        snapshot_manager=snapshot_manager,
        trigger_manager=trigger_manager,
        session_key=session_key,
        ip_name=ip_name,
        project_memory=project_memory,
    )

    return {
        "drift_detector": drift_detector,
        "model_registry": model_registry,
        "expert_panel": expert_panel,
        "correlation_analyzer": correlation_analyzer,
        "outcome_tracker": outcome_tracker,
        "snapshot_manager": snapshot_manager,
        "trigger_manager": trigger_manager,
        "scheduler_service": scheduler_service,
        "feedback_loop": feedback_loop,
    }


# ---------------------------------------------------------------------------
# Logger hook registration table (table-driven instead of 5 copy-paste blocks)
# ---------------------------------------------------------------------------

_LOGGER_HOOKS: list[tuple[HookEvent, str, str]] = [
    (HookEvent.DRIFT_DETECTED, "drift_logger", "Drift detected: %s"),
    (HookEvent.SNAPSHOT_CAPTURED, "snapshot_logger", "Snapshot captured: %s"),
    (HookEvent.TRIGGER_FIRED, "trigger_logger", "Trigger fired: %s"),
    (HookEvent.OUTCOME_COLLECTED, "outcome_logger", "Outcome collected: cycle=%s"),
    (HookEvent.MODEL_PROMOTED, "model_promotion_logger", "Model promoted: %s"),
]

_LOGGER_DATA_KEYS: dict[str, list[str]] = {
    "drift_logger": [],  # logs full data dict
    "snapshot_logger": ["snapshot_id"],
    "trigger_logger": ["trigger_id"],
    "outcome_logger": ["cycle_id"],
    "model_promotion_logger": ["version_id", "stage"],
}


def wire_automation_hooks(
    hooks: HookSystem,
    *,
    snapshot_manager: Any,
    trigger_manager: Any,
    session_key: str,
    ip_name: str,
    project_memory: Any,
) -> None:
    """Wire L4.5 automation event handlers to the hook system."""

    # Table-driven logger hooks
    for hook_event, handler_name, msg_template in _LOGGER_HOOKS:
        keys = _LOGGER_DATA_KEYS[handler_name]

        def _make_logger(tmpl: str, ks: list[str]) -> Any:
            def _handler(event: HookEvent, data: dict[str, Any]) -> None:
                if not ks:
                    log.info(tmpl, data)
                elif len(ks) == 1:
                    log.info(tmpl, data.get(ks[0], ""))
                else:
                    log.info(tmpl, *(data.get(k, "") for k in ks))

            return _handler

        hooks.register(
            hook_event,
            _make_logger(msg_template, keys),
            name=handler_name,
            priority=90,
        )

    # Reactive chain: drift -> auto-snapshot for debugging
    def _on_drift_snapshot(event: HookEvent, data: dict[str, Any]) -> None:
        if snapshot_manager:
            snapshot_manager.capture(
                session_key,
                pipeline_state={"trigger": "drift_detected", "alerts": data},
                context={"ip_name": ip_name},
            )

    hooks.register(
        HookEvent.DRIFT_DETECTED,
        _on_drift_snapshot,
        name="drift_auto_snapshot",
        priority=80,
    )

    # Wire TriggerManager -> pipeline integration
    trigger_manager.register_pipeline_trigger(
        trigger_id="drift-reanalysis",
        ip_name=ip_name,
        trigger_type=TriggerType.EVENT,
    )
    drift_trigger_handler = trigger_manager.make_event_handler("drift-reanalysis")
    hooks.register(
        HookEvent.DRIFT_DETECTED,
        drift_trigger_handler,
        name="drift_pipeline_trigger",
        priority=70,
    )

    # Reactive chain: pipeline end -> auto-snapshot for reproducibility
    def _on_pipeline_end_snapshot(event: HookEvent, data: dict[str, Any]) -> None:
        if snapshot_manager:
            snapshot_manager.capture(
                session_key,
                pipeline_state=data,
                context={"ip_name": ip_name},
            )

    hooks.register(
        HookEvent.PIPELINE_END,
        _on_pipeline_end_snapshot,
        name="pipeline_end_snapshot",
        priority=80,
    )

    # Memory write-back: pipeline end -> add_insight to MEMORY.md (P0 auto-learning)
    def _on_pipeline_end_memory(event: HookEvent, data: dict[str, Any]) -> None:
        if project_memory is None:
            return
        if data.get("dry_run", False):
            return  # dry_run은 기록하지 않음
        ip = data.get("ip_name") or "unknown"
        tier = data.get("tier") or "?"
        score = data.get("final_score") or 0.0
        cause = data.get("synthesis_cause", "")
        action = data.get("synthesis_action", "")
        insight = f"[{ip}] tier={tier}, score={score:.2f}"
        if cause:
            insight += f", cause={cause}"
        if action:
            insight += f", action={action}"
        if not project_memory.add_insight(insight):
            log.warning("Failed to write insight for IP=%s", ip)

    hooks.register(
        HookEvent.PIPELINE_END,
        _on_pipeline_end_memory,
        name="memory_write_back",
        priority=85,
    )
