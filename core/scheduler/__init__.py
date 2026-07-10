"""Advanced Scheduler — 3-type scheduling + active hours.

Originally a single 1208-LOC module (``core/scheduler/scheduler.py`` — pre-split monolith); split
into one module per concern while preserving every public symbol previously
imported by the 11 external consumer files.

Sub-modules:
- :mod:`models`         — `ScheduleKind`, `Schedule`, `ActiveHours`,
                          `ScheduledJob`, `OnJobFired`, constants
- :mod:`serialization`  — `_job_to_dict`, `_job_from_dict`
- :mod:`core.observability.run_log` — `JobRunLog` (bounded per-job JSONL)
- :mod:`lock`           — `SchedulerLock`, `_is_pid_alive` (O_EXCL pattern)
- :mod:`jitter`         — `_compute_jitter_frac`, `_jittered_next_run`
- :mod:`timezone`       — `_parse_hhmm`, `_now_minutes`, `_cron_tuple_for_tz`
- :mod:`service`        — `SchedulerService` (the central engine)
- :mod:`factory`        — `create_scheduler`

Architecture-v6 SS4.5: Automation Layer -- Advanced Scheduler (P4).
Inspired by OpenClaw's Cron Service + Claude Code's distributed scheduler.
Supports:
- AT: one-shot absolute timestamp jobs
- EVERY: fixed-interval with anchor-based drift prevention
- CRON: standard cron expressions (via existing CronParser)
- Active Hours: timezone-aware quiet-hours window with midnight wrap-around
- Per-job JSONL run log with auto-pruning
- Atomic JSON store (tmp + rename pattern)
- O_EXCL lock file + PID liveness probe (claude-code pattern)
- Deterministic per-job jitter (thundering herd prevention)
- Session-only tasks (durable flag)
- Missed task recovery
- mtime-based file watch reload (1s check interval)
"""

from __future__ import annotations

from core.observability.run_log import JobRunLog
from core.scheduler.factory import create_scheduler
from core.scheduler.jitter import _compute_jitter_frac, _jittered_next_run
from core.scheduler.lock import SchedulerLock, _is_pid_alive
from core.scheduler.models import (
    DEFAULT_JITTER_FRACTION,
    DEFAULT_LOG_DIR,
    DEFAULT_MAX_JITTER_MS,
    DEFAULT_STORE_PATH,
    MISSED_TASK_GRACE_MS,
    RECURRING_MAX_AGE_MS,
    ActiveHours,
    OnJobFired,
    Schedule,
    ScheduledJob,
    ScheduleKind,
)
from core.scheduler.serialization import _job_from_dict, _job_to_dict
from core.scheduler.service import SchedulerService
from core.scheduler.timezone import _cron_tuple_for_tz, _now_minutes, _parse_hhmm

__all__ = [
    "DEFAULT_JITTER_FRACTION",
    "DEFAULT_LOG_DIR",
    "DEFAULT_MAX_JITTER_MS",
    "DEFAULT_STORE_PATH",
    "MISSED_TASK_GRACE_MS",
    "RECURRING_MAX_AGE_MS",
    "ActiveHours",
    "JobRunLog",
    "OnJobFired",
    "Schedule",
    "ScheduleKind",
    "ScheduledJob",
    "SchedulerLock",
    "SchedulerService",
    "_compute_jitter_frac",
    "_cron_tuple_for_tz",
    "_is_pid_alive",
    "_jittered_next_run",
    "_job_from_dict",
    "_job_to_dict",
    "_now_minutes",
    "_parse_hhmm",
    "create_scheduler",
]
