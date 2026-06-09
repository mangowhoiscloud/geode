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

import logging
from typing import Any

from core.hooks import HookEvent, HookSystem
from core.scheduler.triggers import TriggerManager

log = logging.getLogger(__name__)


def build_scheduling(*, hooks: HookSystem) -> dict[str, Any]:
    """Build the scheduler stack and wire its hook handlers.

    Returns a dict of component name -> instance for the runtime constructor.
    """
    from core.config import settings

    # Trigger manager (auto-start scheduler for cron-based triggers)
    trigger_manager = TriggerManager(
        scheduler_interval_s=settings.trigger_scheduler_interval_s,
        hooks=hooks,
    )
    trigger_manager.start_scheduler()

    # Advanced scheduler service (3-type: AT/EVERY/CRON + active hours)
    from core.scheduler import create_scheduler

    scheduler_service = create_scheduler(
        trigger_manager=trigger_manager,
        hooks=hooks,
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

    if settings.scheduler_auto_start:
        scheduler_service.start(
            interval_s=settings.scheduler_interval_s,
        )

    # OL-A1 (2026-05-22) — self-improving-loop auto-trigger. Opt-in:
    # only fires when [self_improving_loop.scheduler] enabled=true in
    # ~/.geode/config.toml. Default off → register_auto_trigger no-ops.
    try:
        from core.config.self_improving_loop import load_self_improving_loop_config
        from core.self_improving.loop.auto_trigger import register_auto_trigger

        sil_cfg = load_self_improving_loop_config()
        register_auto_trigger(
            trigger_manager,
            enabled=sil_cfg.scheduler.enabled,
            cron=sil_cfg.scheduler.cron,
            min_interval_minutes=sil_cfg.scheduler.min_interval_minutes,
            # PR-MAX-GEN (2026-05-26) — production wiring for the
            # generation cap. ``0`` (config default) preserves legacy
            # unbounded behaviour. Operators set a non-zero cap in
            # ~/.geode/config.toml under [self_improving_loop.scheduler]
            # max_generation = N.
            max_generation=sil_cfg.scheduler.max_generation,
            hooks=hooks,
        )
    except Exception:
        log.exception("auto_trigger wiring failed; scheduler continues without it")

    _register_trigger_logger(hooks)

    return {
        "trigger_manager": trigger_manager,
        "scheduler_service": scheduler_service,
    }


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
