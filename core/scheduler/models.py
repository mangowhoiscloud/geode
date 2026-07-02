"""Data models, type aliases, and module-level constants for the scheduler.

Architecture-v6 SS4.5: Automation Layer -- Advanced Scheduler (P4).
Inspired by OpenClaw's Cron Service + Claude Code's distributed scheduler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.paths import PROJECT_SCHEDULER_FILE, PROJECT_SCHEDULER_LOG_DIR

OnJobFired = Callable[[str, str, bool, str], None]
"""Callback: (job_id, action, isolated, agent_id) -> None."""

DEFAULT_STORE_PATH = PROJECT_SCHEDULER_FILE
DEFAULT_LOG_DIR = PROJECT_SCHEDULER_LOG_DIR

# Backward-compat: old global store path for migration detection
_LEGACY_STORE_PATH = Path.home() / ".geode" / "scheduler" / "jobs.json"

# Missed task recovery: 1 hour grace window
MISSED_TASK_GRACE_MS: float = 3_600_000.0

# Jitter defaults
DEFAULT_MAX_JITTER_MS: float = 900_000.0  # 15 minutes cap
DEFAULT_JITTER_FRACTION: float = 0.1  # 10% of interval

# Recurring age-out: 30 days (claude-code pattern)
RECURRING_MAX_AGE_MS: float = 30 * 24 * 60 * 60 * 1000.0


class ScheduleKind(Enum):
    """Supported schedule types."""

    AT = "at"  # One-shot absolute timestamp
    EVERY = "every"  # Fixed interval with anchor
    CRON = "cron"  # Cron expression


@dataclass
class Schedule:
    """Schedule configuration for a job."""

    kind: ScheduleKind
    at_ms: float = 0.0  # For AT: Unix timestamp in ms
    every_ms: float = 0.0  # For EVERY: interval in ms
    anchor_ms: float = 0.0  # For EVERY: anchor time for drift prevention
    cron_expr: str = ""  # For CRON: cron expression
    timezone: str = ""  # For CRON/active hours: IANA timezone


@dataclass
class ActiveHours:
    """Quiet-hours window configuration.

    When set, jobs only run within the specified time window.
    Supports midnight wrap-around (e.g., start="22:00", end="06:00").
    """

    start: str = ""  # "HH:MM" format
    end: str = ""  # "HH:MM" format
    timezone: str = ""  # IANA timezone or "" for local


@dataclass
class ScheduledJob:
    """A job managed by the SchedulerService."""

    job_id: str
    name: str
    schedule: Schedule
    enabled: bool = True
    delete_after_run: bool = False  # For AT type: auto-delete after success
    durable: bool = True  # False = session-only (not persisted to disk)
    permanent: bool = False  # Exempt from recurring age-out
    agent_id: str = ""  # Sub-agent owner (empty = main session)
    callback: Any = None  # Callable[[dict], None]
    action: str = ""  # Prompt text to enqueue when fired (no callback)
    isolated: bool = True  # Run in isolated session (agentTurn) vs main session (systemEvent)
    active_hours: ActiveHours | None = None
    # Per-job spend ceiling in USD. 0.0 = the job must not spend anything
    # (pure-python collectors, no LLM calls). Informational for callback
    # jobs (they never enter an LLM loop); prompt-action jobs surface it to
    # the session cost guard via metadata propagation.
    budget_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    # State tracking
    created_at_ms: float = 0.0
    next_run_at_ms: float | None = None
    last_run_at_ms: float | None = None
    last_status: str = ""  # "ok" | "error" | "skipped" | "stuck"
    last_duration_ms: float = 0.0
    running_since_ms: float | None = None  # Set when executing, cleared on completion
