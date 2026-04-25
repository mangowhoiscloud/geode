"""Automation wiring — L4.5 9 components + hook wiring.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

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
    from core.automation.scheduler import create_scheduler

    scheduler_service = create_scheduler(
        trigger_manager=trigger_manager,
        hooks=hooks,
        enable_jitter=settings.scheduler_jitter_enabled,
        max_jitter_ms=settings.scheduler_max_jitter_ms,
    )
    scheduler_service.load()

    # Predefined automations are domain-specific templates (game_ip).
    # They require a wired callback to be useful. Without callback/action,
    # they fire as empty jobs consuming resources.
    # Registration is skipped — users can enable predefined templates
    # via /schedule enable <template_id> when a domain plugin provides
    # the callback wiring.

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
        feedback_loop=feedback_loop,
        outcome_tracker=outcome_tracker,
        drift_detector=drift_detector,
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
    feedback_loop: Any = None,
    outcome_tracker: Any = None,
    drift_detector: Any = None,
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

    # Memory write-back removed: PIPELINE_END hook produced broken stub entries
    # (tier=?, score=0.00) because effective_state in synthesizer node didn't
    # reliably contain scoring results. Pipeline results are already recorded
    # in journal (runs.jsonl) via journal_hooks.

    # ── Feedback Loop Integration (activates L4.5 dead code) ──────────────

    # Handler #1: SCORING_COMPLETE → drift scan on subscores
    if drift_detector and feedback_loop:

        def _on_scoring_drift(event: HookEvent, data: dict[str, Any]) -> None:
            subscores = data.get("subscores") or data.get("scores", {})
            if not subscores:
                return
            try:
                alerts = drift_detector.scan_all(subscores)
                if alerts:
                    log.info(
                        "SCORING_COMPLETE: drift scan found %d alerts",
                        len(alerts),
                    )
                    hooks.trigger(
                        HookEvent.DRIFT_DETECTED,
                        {"alerts": alerts, "ip_name": ip_name, "source": "scoring"},
                    )
            except Exception:
                log.debug("Drift scan on SCORING_COMPLETE failed", exc_info=True)

        hooks.register(
            HookEvent.SCORING_COMPLETE,
            _on_scoring_drift,
            name="scoring_drift_scan",
            priority=60,
        )

    # Handler #2: PIPELINE_END → schedule outcome tracking at T+30/90/180
    if outcome_tracker:

        def _on_pipeline_end_outcomes(event: HookEvent, data: dict[str, Any]) -> None:
            target_ip = data.get("ip_name") or ip_name
            if not target_ip:
                return
            try:
                from core.automation.outcome_tracking import TrackingPoint

                for tp in TrackingPoint:
                    outcome_tracker.schedule(ip_name=target_ip, tracking_point=tp)
                log.info(
                    "PIPELINE_END: scheduled %d outcome checkpoints for %s",
                    len(TrackingPoint),
                    target_ip,
                )
            except Exception:
                log.debug("Outcome scheduling on PIPELINE_END failed", exc_info=True)

        hooks.register(
            HookEvent.PIPELINE_END,
            _on_pipeline_end_outcomes,
            name="pipeline_end_outcomes",
            priority=70,
        )

    # Handler #3: OUTCOME_COLLECTED → run feedback correlation cycle
    if feedback_loop:

        def _on_outcome_feedback(event: HookEvent, data: dict[str, Any]) -> None:
            try:
                auto_scores = data.get("auto_scores", [])
                human_scores = data.get("human_scores", [])
                cycle_id = data.get("cycle_id", "auto")
                if not auto_scores:
                    return
                result = feedback_loop.run_cycle(
                    auto_scores=auto_scores,
                    human_scores=human_scores,
                    cycle_id=cycle_id,
                )
                log.info(
                    "OUTCOME_COLLECTED: feedback cycle %s — success=%s",
                    result.cycle_id if hasattr(result, "cycle_id") else cycle_id,
                    result.success if hasattr(result, "success") else "unknown",
                )
            except Exception:
                log.debug("Feedback cycle on OUTCOME_COLLECTED failed", exc_info=True)

        hooks.register(
            HookEvent.OUTCOME_COLLECTED,
            _on_outcome_feedback,
            name="outcome_feedback_cycle",
            priority=60,
        )
