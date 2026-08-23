"""Scheduling wiring — TriggerManager + SchedulerService + auto-trigger.

Extracted from the former ``core/wiring/automation.py``. PR-DEAD-PIPELINE
(2026-06-10) deleted the L4.5 automation chain that used to be built here
(CUSUMDetector / ModelRegistry / ExpertPanel / CorrelationAnalyzer /
OutcomeTracker / SnapshotManager / FeedbackLoop): every entry point into
that chain was a pipeline event with no remaining emitter, so the seven
components were constructed on every boot and never did any work. What
remains is the live scheduler stack.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from core.hooks import HookEvent, HookSystem
from core.scheduler.triggers import TriggerManager

log = logging.getLogger(__name__)


def build_scheduling(
    *,
    hooks: HookSystem,
    feature_registrar: Callable[[TriggerManager, HookSystem], None] | None = None,
    on_job_fired: Callable[[str, str, bool, str], None] | None = None,
) -> dict[str, Any]:
    """Build the scheduler stack and wire its hook handlers.

    Returns a dict of component name -> instance for the runtime constructor.
    """
    from core.config import settings

    # Trigger manager (auto-start scheduler for cron-based triggers)
    trigger_manager = TriggerManager(
        scheduler_interval_s=settings.trigger_scheduler_interval_s,
        hooks=hooks,
    )
    scheduler_service: Any | None = None
    try:
        trigger_manager.start_scheduler()

        # Advanced scheduler service (3-type: AT/EVERY/CRON + active hours)
        from core.scheduler import create_scheduler

        scheduler_service = create_scheduler(
            trigger_manager=trigger_manager,
            hooks=hooks,
            on_job_fired=on_job_fired,
            enable_jitter=settings.scheduler_jitter_enabled,
            max_jitter_ms=settings.scheduler_max_jitter_ms,
        )
        scheduler_service.load()

        # Predefined automations are package-specific templates.
        # They require a wired callback to be useful. Without callback/action,
        # they fire as empty jobs consuming resources.
        # Registration is skipped — users can enable predefined templates
        # via /schedule enable <template_id> when an external package provides
        # the callback wiring.

        # PR-MEMORY-LIFECYCLE (2026-07-03) — first-party read-only engineering
        # report jobs (callback path: pure-python collectors, budget_usd=0.0,
        # no tool loop). Registered DISABLED by default; operators opt in via
        # /schedule enable <job_id> or run once via /schedule run <job_id>.
        try:
            from core.scheduler.engineering_reports import register_engineering_report_jobs

            register_engineering_report_jobs(scheduler_service)
        except Exception:
            log.exception("engineering report job wiring failed; scheduler continues without them")

        if settings.scheduler_auto_start:
            scheduler_service.start(
                interval_s=settings.scheduler_interval_s,
            )

        if feature_registrar is not None:
            try:
                feature_registrar(trigger_manager, hooks)
            except Exception:
                log.exception("feature scheduler wiring failed; scheduler continues without it")

        _register_trigger_logger(hooks)

        return {
            "trigger_manager": trigger_manager,
            "scheduler_service": scheduler_service,
        }
    except BaseException:
        if scheduler_service is not None:
            with contextlib.suppress(Exception):
                scheduler_service.stop()
        with contextlib.suppress(Exception):
            trigger_manager.stop_scheduler()
        raise


def _register_trigger_logger(hooks: HookSystem) -> None:
    """Log TRIGGER_FIRED events (the scheduler's observable heartbeat)."""

    def _trigger_logger(event: HookEvent, data: dict[str, Any]) -> None:
        log.info("Trigger fired: %s", data.get("trigger_id", ""))

    hooks.register(
        HookEvent.TRIGGER_FIRED,
        _trigger_logger,
        name="trigger_logger",
        priority=90,
    )
