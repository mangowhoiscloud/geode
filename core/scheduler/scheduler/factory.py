"""SchedulerService factory — claude-code-style library instantiation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.scheduler.scheduler.models import DEFAULT_MAX_JITTER_MS, OnJobFired
from core.scheduler.scheduler.service import SchedulerService
from core.scheduler.triggers import TriggerManager

if TYPE_CHECKING:
    from core.hooks import HookSystem


def create_scheduler(
    *,
    store_path: Path | None = None,
    log_dir: Path | None = None,
    on_job_fired: OnJobFired | None = None,
    trigger_manager: TriggerManager | None = None,
    hooks: HookSystem | None = None,
    session_id: str = "",
    enable_jitter: bool = True,
    max_jitter_ms: float = DEFAULT_MAX_JITTER_MS,
) -> SchedulerService:
    """Create a SchedulerService with project-local defaults.

    This factory function makes the scheduler usable as a library component
    that any context (serve, REPL, SDK, daemon) can instantiate with
    appropriate configuration.
    """
    return SchedulerService(
        trigger_manager=trigger_manager,
        hooks=hooks,
        store_path=store_path,
        log_dir=log_dir,
        on_job_fired=on_job_fired,
        session_id=session_id,
        enable_jitter=enable_jitter,
        max_jitter_ms=max_jitter_ms,
    )
