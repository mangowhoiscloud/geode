"""Advanced Scheduler — 3-type scheduling + active hours.

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

Architecture-v6 SS4.5: Automation Layer -- Advanced Scheduler (P4).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.paths import PROJECT_SCHEDULER_FILE, PROJECT_SCHEDULER_LOG_DIR
from core.scheduler.triggers import CronParser, TriggerManager

if TYPE_CHECKING:
    from core.hooks import HookSystem

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

OnJobFired = Callable[[str, str, bool, str], None]
"""Callback: (job_id, action, isolated, agent_id) -> None."""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


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
    metadata: dict[str, Any] = field(default_factory=dict)
    # State tracking
    created_at_ms: float = 0.0
    next_run_at_ms: float | None = None
    last_run_at_ms: float | None = None
    last_status: str = ""  # "ok" | "error" | "skipped" | "stuck"
    last_duration_ms: float = 0.0
    running_since_ms: float | None = None  # Set when executing, cleared on completion


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _job_to_dict(job: ScheduledJob) -> dict[str, Any]:
    """Serialize a ScheduledJob to a JSON-safe dict (excludes callback)."""
    return {
        "job_id": job.job_id,
        "name": job.name,
        "schedule": {
            "kind": job.schedule.kind.value,
            "at_ms": job.schedule.at_ms,
            "every_ms": job.schedule.every_ms,
            "anchor_ms": job.schedule.anchor_ms,
            "cron_expr": job.schedule.cron_expr,
            "timezone": job.schedule.timezone,
        },
        "enabled": job.enabled,
        "delete_after_run": job.delete_after_run,
        "durable": job.durable,
        "permanent": job.permanent,
        "agent_id": job.agent_id,
        "action": job.action,
        "isolated": job.isolated,
        "active_hours": (asdict(job.active_hours) if job.active_hours is not None else None),
        "metadata": job.metadata,
        "created_at_ms": job.created_at_ms,
        "next_run_at_ms": job.next_run_at_ms,
        "last_run_at_ms": job.last_run_at_ms,
        "last_status": job.last_status,
        "last_duration_ms": job.last_duration_ms,
        "running_since_ms": job.running_since_ms,
    }


def _job_from_dict(data: dict[str, Any]) -> ScheduledJob:
    """Deserialize a dict into a ScheduledJob (callback will be None)."""
    sched_data = data["schedule"]
    schedule = Schedule(
        kind=ScheduleKind(sched_data["kind"]),
        at_ms=sched_data.get("at_ms", 0.0),
        every_ms=sched_data.get("every_ms", 0.0),
        anchor_ms=sched_data.get("anchor_ms", 0.0),
        cron_expr=sched_data.get("cron_expr", ""),
        timezone=sched_data.get("timezone", ""),
    )
    ah_data = data.get("active_hours")
    active_hours = ActiveHours(**ah_data) if ah_data is not None else None

    return ScheduledJob(
        job_id=data["job_id"],
        name=data["name"],
        schedule=schedule,
        enabled=data.get("enabled", True),
        delete_after_run=data.get("delete_after_run", False),
        durable=data.get("durable", True),
        permanent=data.get("permanent", False),
        agent_id=data.get("agent_id", ""),
        callback=None,  # Callbacks are not serialised
        action=data.get("action", ""),
        isolated=data.get("isolated", True),
        active_hours=active_hours,
        metadata=data.get("metadata", {}),
        created_at_ms=data.get("created_at_ms", 0.0),
        next_run_at_ms=data.get("next_run_at_ms"),
        last_run_at_ms=data.get("last_run_at_ms"),
        last_status=data.get("last_status", ""),
        last_duration_ms=data.get("last_duration_ms", 0.0),
        running_since_ms=data.get("running_since_ms"),
    )


# ---------------------------------------------------------------------------
# Per-job JSONL run log
# ---------------------------------------------------------------------------


class JobRunLog:
    """Per-job JSONL run log with auto-pruning.

    Each job gets its own ``{job_id}.jsonl`` file under *log_dir*.
    """

    MAX_LINES: int = 2000
    MAX_BYTES: int = 2 * 1024 * 1024  # 2 MB

    def __init__(self, log_dir: Path | None = None) -> None:
        self._log_dir = log_dir if log_dir is not None else DEFAULT_LOG_DIR
        self._lock = threading.Lock()

    def _path(self, job_id: str) -> Path:
        safe = job_id.replace(":", "_").replace("/", "_")
        return self._log_dir / f"{safe}.jsonl"

    def append(self, job_id: str, entry: dict[str, Any]) -> None:
        """Append a run entry for *job_id*."""
        path = self._path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get_runs(self, job_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent *limit* entries (newest first)."""
        path = self._path(job_id)
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        entries: list[dict[str, Any]] = []
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                log.warning("Skipping malformed run log line: %s", raw[:80])
            if len(entries) >= limit:
                break
        return entries

    def prune(self, job_id: str) -> int:
        """Prune log file if it exceeds size/line limits.

        Returns the number of lines removed.
        """
        with self._lock:
            path = self._path(job_id)
            if not path.exists():
                return 0
            file_size = path.stat().st_size
            if file_size <= self.MAX_BYTES:
                return 0
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            original = len(lines)
            if original <= self.MAX_LINES:
                return 0
            kept = lines[-self.MAX_LINES :]
            removed = original - len(kept)
            # Atomic write: tmp + rename
            tmp_path = path.with_suffix(".jsonl.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(str(tmp_path), str(path))
            log.info(
                "Pruned job run log %s: %d -> %d lines (%d removed)",
                job_id,
                original,
                len(kept),
                removed,
            )
            return removed


# ---------------------------------------------------------------------------
# O_EXCL Lock — PID liveness probe (claude-code pattern)
# ---------------------------------------------------------------------------


class SchedulerLock:
    """Cross-platform file-based lock using O_EXCL atomic creation.

    Lock file contains ``{"pid": N, "acquired_at": T, "session_id": S}``
    for liveness probing and idempotent re-acquire on session restart.
    """

    STALE_TIMEOUT_S: float = 5.0

    def __init__(self, lock_path: Path, session_id: str = "") -> None:
        self._lock_path = lock_path
        self._session_id = session_id or f"pid-{os.getpid()}"
        self._acquired = False

    def _lock_content(self) -> str:
        return json.dumps(
            {
                "pid": os.getpid(),
                "acquired_at": time.time(),
                "session_id": self._session_id,
            }
        )

    def acquire(self, timeout_s: float = 10.0) -> bool:
        """Try to acquire the lock, probing for stale owners."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                try:
                    os.write(fd, self._lock_content().encode())
                finally:
                    os.close(fd)
                self._acquired = True
                return True
            except FileExistsError:
                # Lock file exists — check if owner is alive or same session
                reclaim_result = self._try_reclaim()
                if reclaim_result == "idempotent":
                    # Same session re-acquired — lock file updated in place
                    self._acquired = True
                    return True
                if reclaim_result == "reclaimed":
                    continue  # Stale lock removed, retry O_EXCL
                time.sleep(0.2)
        return False

    def release(self) -> None:
        """Release the lock by removing the lock file."""
        if self._acquired:
            with contextlib.suppress(OSError):
                self._lock_path.unlink(missing_ok=True)
            self._acquired = False

    def _try_reclaim(self) -> str:
        """Check if the current lock owner is dead and reclaim if so.

        Returns:
            "idempotent" — same session re-acquired (lock file updated in place)
            "reclaimed"  — stale lock removed (caller should retry O_EXCL)
            ""           — lock is held by another live session
        """
        try:
            with open(self._lock_path, encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("pid", -1)
            acquired_at = data.get("acquired_at", 0.0)
            owner_session = data.get("session_id", "")
            age = time.time() - acquired_at

            # Idempotent: same session, new PID (restart/resume)
            if owner_session and owner_session == self._session_id:
                try:
                    self._lock_path.write_text(self._lock_content())
                    return "idempotent"
                except OSError:
                    return ""

            if not _is_pid_alive(pid) or age > 600:
                # Owner dead or lock very old — reclaim
                try:
                    self._lock_path.unlink()
                    return "reclaimed"
                except FileNotFoundError:
                    return "reclaimed"
                except OSError:
                    return ""
        except (json.JSONDecodeError, OSError):
            # Corrupt lock file — remove and retry
            try:
                self._lock_path.unlink()
                return "reclaimed"
            except OSError:
                return ""
        return ""

    def __enter__(self) -> SchedulerLock:
        if not self.acquire():
            raise TimeoutError(f"Could not acquire scheduler lock: {self._lock_path}")
        return self

    def __exit__(self, *_args: Any) -> None:
        self.release()


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


# ---------------------------------------------------------------------------
# Jitter — deterministic per-job hash (claude-code pattern)
# ---------------------------------------------------------------------------


def _compute_jitter_frac(job_id: str) -> float:
    """Compute a deterministic jitter fraction [0, 1) from job_id.

    Uses SHA-256 to produce a stable, uniformly distributed value.
    Same job_id always produces the same jitter across restarts.
    """
    h = hashlib.sha256(job_id.encode()).digest()
    # Use first 4 bytes as uint32 → normalize to [0, 1)
    val = int.from_bytes(h[:4], "big")
    return val / (2**32)


def _jittered_next_run(
    next_ms: float,
    interval_ms: float,
    job_id: str,
    *,
    max_jitter_ms: float = DEFAULT_MAX_JITTER_MS,
    jitter_fraction: float = DEFAULT_JITTER_FRACTION,
) -> float:
    """Apply deterministic forward jitter to a recurring job's next-run time.

    Jitter = min(frac * interval * jitter_fraction, max_jitter_ms).
    This spreads jobs with the same cron across a window instead of all
    firing at :00.
    """
    frac = _compute_jitter_frac(job_id)
    jitter = min(frac * interval_ms * jitter_fraction, max_jitter_ms)
    return next_ms + jitter


# ---------------------------------------------------------------------------
# Active-hours helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(s: str) -> int:
    """Parse "HH:MM" -> total minutes since midnight."""
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM format: '{s}'")
    return int(parts[0]) * 60 + int(parts[1])


def _now_minutes(timezone: str) -> int:
    """Current local time as minutes since midnight.

    When *timezone* is empty or not available, falls back to local time.
    Uses ``datetime`` if *zoneinfo* is available for tz-aware resolution.
    """
    if timezone:
        try:
            import datetime
            import zoneinfo

            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.datetime.now(tz=tz)
            return now.hour * 60 + now.minute
        except Exception:
            log.debug("Timezone '%s' unavailable, falling back to local", timezone)
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def _cron_tuple_for_tz(timezone: str) -> tuple[int, int, int, int, int]:
    """Get a cron-compatible tuple, optionally in a specific timezone.

    Returns weekday in standard cron convention: 0=Sun, 1=Mon, ..., 6=Sat.
    Python's ``datetime.weekday()`` uses 0=Mon, so we convert:
    ``(weekday() + 1) % 7``.
    """
    if timezone:
        try:
            import datetime
            import zoneinfo

            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.datetime.now(tz=tz)
            cron_wday = (now.weekday() + 1) % 7  # Python 0=Mon -> cron 0=Sun
            return (now.minute, now.hour, now.day, now.month, cron_wday)
        except Exception:  # noqa: S110 — fallback to CronParser.current_tuple() below
            pass
    return CronParser.current_tuple()


# ---------------------------------------------------------------------------
# Scheduler Service
# ---------------------------------------------------------------------------


class SchedulerService:
    """Advanced scheduler with 3-type scheduling + active hours.

    Extends (via composition) the existing :class:`TriggerManager` from
    ``core.scheduler.triggers``.  The scheduler manages its own job store
    (atomic JSON) and per-job JSONL run logs.
    """

    MAX_JOBS: int = 50  # Maximum number of scheduled jobs (claude-code pattern)

    def __init__(
        self,
        trigger_manager: TriggerManager | None = None,
        hooks: HookSystem | None = None,
        store_path: Path | None = None,
        log_dir: Path | None = None,
        on_job_fired: OnJobFired | None = None,
        *,
        session_id: str = "",
        enable_jitter: bool = True,
        max_jitter_ms: float = DEFAULT_MAX_JITTER_MS,
        # Backward-compat: accept action_queue and wrap as callback
        action_queue: Any = None,
    ) -> None:
        self._trigger_manager = trigger_manager
        self._hooks = hooks
        self._store_path = store_path if store_path is not None else DEFAULT_STORE_PATH
        self._store_path_explicit = store_path is not None
        self._session_id = session_id or f"pid-{os.getpid()}"
        self._run_log = JobRunLog(log_dir=log_dir)
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Callback protocol (replaces action_queue)
        _fired_cb: OnJobFired | None = None
        if on_job_fired is not None:
            _fired_cb = on_job_fired
        elif action_queue is not None:
            # Backward-compat: wrap queue.put as callback (ignore agent_id)
            def _queue_adapter(jid: str, act: str, iso: bool, _aid: str = "") -> None:
                action_queue.put((jid, act, iso))

            _fired_cb = _queue_adapter
        self._on_job_fired: OnJobFired | None = _fired_cb

        # Jitter settings
        self._enable_jitter = enable_jitter
        self._max_jitter_ms = max_jitter_ms

        # mtime-based file watch for external changes
        self._last_store_mtime: float = 0.0

        # CRON dedup: prevent same cron job from firing twice in same minute
        self._last_fired_minute: dict[str, int] = {}

    # -- CRUD ---------------------------------------------------------------

    def add_job(self, job: ScheduledJob) -> None:
        """Add a new scheduled job.

        Raises ValueError if:
        - job_id already exists
        - job has no action AND no callback (would be a no-op zombie)
        - a job with the same schedule expression and action already exists (dedup)
        """
        if not job.action and job.callback is None:
            raise ValueError(
                "Job must have an action or callback. "
                "Empty-action jobs fire as no-ops and waste resources."
            )
        with self._lock:
            if len(self._jobs) >= self.MAX_JOBS:
                raise ValueError(
                    f"Too many scheduled jobs (max {self.MAX_JOBS}). Remove one first."
                )
            if job.job_id in self._jobs:
                raise ValueError(f"Job '{job.job_id}' already exists")
            # Dedup: reject if an enabled job with same schedule+action exists
            if job.enabled:
                for existing in self._jobs.values():
                    if (
                        existing.enabled
                        and existing.schedule.kind == job.schedule.kind
                        and existing.schedule.every_ms == job.schedule.every_ms
                        and existing.schedule.cron_expr == job.schedule.cron_expr
                        and existing.action == job.action
                    ):
                        raise ValueError(
                            f"Duplicate schedule: existing job '{existing.job_id}' "
                            f"has same schedule and action"
                        )
            if job.created_at_ms == 0.0:
                job.created_at_ms = time.time() * 1000
            job.next_run_at_ms = self.compute_next_run(job)
            self._jobs[job.job_id] = job
        log.info("Added job '%s' (%s)", job.job_id, job.schedule.kind.value)

    def remove_job(self, job_id: str) -> bool:
        """Remove a job. Returns True if found and removed."""
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def update_job(self, job_id: str, **updates: Any) -> bool:
        """Update fields on an existing job. Returns True if found."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            for key, value in updates.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            # Recompute next_run if schedule-related fields changed
            schedule_keys = {"schedule", "enabled"}
            if schedule_keys & set(updates):
                job.next_run_at_ms = self.compute_next_run(job)
            return True

    def get_job(self, job_id: str) -> ScheduledJob | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, include_disabled: bool = False) -> list[ScheduledJob]:
        """List jobs, optionally including disabled ones."""
        jobs = list(self._jobs.values())
        if not include_disabled:
            jobs = [j for j in jobs if j.enabled]
        return jobs

    # -- Scheduling ---------------------------------------------------------

    def compute_next_run(
        self,
        job: ScheduledJob,
        now_ms: float | None = None,
    ) -> float | None:
        """Compute the next run timestamp (ms) for a job.

        For AT:   returns ``at_ms`` if still in the future, else None (no jitter).
        For EVERY: uses anchor-based alignment to prevent drift on restart.
        For CRON:  returns the next minute boundary (checked by tick loop).

        Recurring jobs (EVERY/CRON) get deterministic jitter applied when
        ``enable_jitter`` is True, spreading fire times to prevent
        thundering herd.
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        kind = job.schedule.kind

        if kind == ScheduleKind.AT:
            # AT jobs fire at exact time — no jitter
            return job.schedule.at_ms if job.schedule.at_ms > now else None
        elif kind == ScheduleKind.EVERY:
            interval = job.schedule.every_ms
            if interval <= 0:
                return None
            anchor = job.schedule.anchor_ms
            if anchor <= 0:
                anchor = job.created_at_ms if job.created_at_ms > 0 else now
            # Compute next aligned tick >= now
            elapsed = now - anchor
            if elapsed < 0:
                # Anchor is in the future -- first run at anchor
                base = anchor
            else:
                periods = int(elapsed / interval)
                base = anchor + (periods + 1) * interval
            # Apply jitter
            if self._enable_jitter:
                return _jittered_next_run(
                    base,
                    interval,
                    job.job_id,
                    max_jitter_ms=self._max_jitter_ms,
                )
            return base
        else:
            # CRON: evaluated every tick; return next minute boundary.
            remainder = now % 60_000
            base = now + (60_000 - remainder) if remainder > 0 else now + 60_000
            if self._enable_jitter:
                # Jitter based on 60s interval for CRON
                return _jittered_next_run(
                    base,
                    60_000,
                    job.job_id,
                    max_jitter_ms=self._max_jitter_ms,
                )
            return base

    def _is_cron_due(self, job: ScheduledJob, now_ms: float) -> bool:
        """Check whether a CRON job matches the current minute.

        Includes dedup guard: prevents the same job from firing twice in
        the same minute (important at 1s check interval).
        """
        # Dedup: compute current minute timestamp
        current_minute = int(now_ms / 60_000)
        last_minute = self._last_fired_minute.get(job.job_id, -1)
        if current_minute == last_minute:
            return False

        tz = job.schedule.timezone
        dt_tuple = _cron_tuple_for_tz(tz)
        try:
            matches = CronParser.matches(job.schedule.cron_expr, dt_tuple)
        except ValueError as exc:
            log.warning("Invalid cron for job '%s': %s", job.job_id, exc)
            return False

        if matches:
            self._last_fired_minute[job.job_id] = current_minute
        return matches

    # -- Active Hours -------------------------------------------------------

    def is_within_active_hours(
        self,
        active_hours: ActiveHours,
        now_ms: float | None = None,
    ) -> bool:
        """Check whether the current time is within the active-hours window.

        - Unset (empty start/end): always active (returns True).
        - Normal range (e.g. 09:00--22:00): active when start <= now < end.
        - Midnight wrap (e.g. 22:00--06:00): active outside the gap.
        """
        if not active_hours.start or not active_hours.end:
            return True

        start_min = _parse_hhmm(active_hours.start)
        end_min = _parse_hhmm(active_hours.end)

        # Allow injecting a specific time for testing
        if now_ms is not None:
            # Derive minutes-since-midnight from epoch ms
            tz = active_hours.timezone
            if tz:
                try:
                    import datetime
                    import zoneinfo

                    tzinfo = zoneinfo.ZoneInfo(tz)
                    dt = datetime.datetime.fromtimestamp(now_ms / 1000, tz=tzinfo)
                    current_min = dt.hour * 60 + dt.minute
                except Exception:
                    t = time.localtime(now_ms / 1000)
                    current_min = t.tm_hour * 60 + t.tm_min
            else:
                t = time.localtime(now_ms / 1000)
                current_min = t.tm_hour * 60 + t.tm_min
        else:
            current_min = _now_minutes(active_hours.timezone)

        if start_min <= end_min:
            # Normal range: e.g. 09:00 -- 22:00
            return start_min <= current_min < end_min
        # Midnight wrap: e.g. 22:00 -- 06:00
        return current_min >= start_min or current_min < end_min

    # -- Execution ----------------------------------------------------------

    def run_now(self, job_id: str) -> dict[str, Any]:
        """Force immediate execution of a job, bypassing schedule & active hours."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job '{job_id}' not found")
        return self._execute_job(job)

    def check_due_jobs(self, now_ms: float | None = None) -> list[dict[str, Any]]:
        """Check all jobs and execute those that are due.

        Returns a list of execution result dicts.
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        results: list[dict[str, Any]] = []
        to_delete: list[str] = []

        with self._lock:
            snapshot = list(self._jobs.values())

        for job in snapshot:
            if not job.enabled:
                continue

            kind = job.schedule.kind

            # Age-out: recurring, non-permanent, older than RECURRING_MAX_AGE_MS
            if (
                kind in (ScheduleKind.EVERY, ScheduleKind.CRON)
                and not job.permanent
                and job.created_at_ms > 0
                and (now - job.created_at_ms) > RECURRING_MAX_AGE_MS
            ):
                result = self._execute_job(job, now_ms=now)
                result["aged_out"] = True
                to_delete.append(job.job_id)
                results.append(result)
                log.info(
                    "Job '%s' aged out (%.0f days)",
                    job.job_id,
                    (now - job.created_at_ms) / 86_400_000,
                )
                continue

            due = False

            if kind in (ScheduleKind.AT, ScheduleKind.EVERY):
                due = job.next_run_at_ms is not None and now >= job.next_run_at_ms
            elif kind == ScheduleKind.CRON:
                due = self._is_cron_due(job, now)

            if not due:
                continue

            # Active hours gate
            if job.active_hours and not self.is_within_active_hours(
                job.active_hours,
                now,
            ):
                result = self._skip_job(job, now, reason="outside_active_hours")
                results.append(result)
                continue

            result = self._execute_job(job, now_ms=now)
            results.append(result)

            # Post-execution handling for AT jobs
            if kind == ScheduleKind.AT:
                if result.get("status") == "ok" and job.delete_after_run:
                    to_delete.append(job.job_id)
                else:
                    # Disable AT job after execution (even if errored)
                    job.enabled = False
                    job.next_run_at_ms = None

        # Clean up delete-after-run jobs
        with self._lock:
            for jid in to_delete:
                self._jobs.pop(jid, None)

        return results

    def _execute_job(
        self,
        job: ScheduledJob,
        now_ms: float | None = None,
    ) -> dict[str, Any]:
        """Execute a single job and record the result."""
        now = now_ms if now_ms is not None else time.time() * 1000
        start = time.time() * 1000
        status = "ok"
        error = ""

        job.running_since_ms = start

        try:
            if job.callback is not None:
                job.callback({"job_id": job.job_id, "name": job.name, **job.metadata})
            elif job.action and self._on_job_fired is not None:
                self._on_job_fired(job.job_id, job.action, job.isolated, job.agent_id)
                log.debug(
                    "Job '%s' fired action (isolated=%s, agent=%s): %s",
                    job.job_id,
                    job.isolated,
                    job.agent_id or "main",
                    job.action[:60],
                )
        except Exception as exc:
            status = "error"
            error = str(exc)
            log.warning("Job '%s' failed: %s", job.job_id, exc)

        duration = time.time() * 1000 - start
        job.running_since_ms = None

        # Update job state
        job.last_run_at_ms = now
        job.last_status = status
        job.last_duration_ms = duration
        job.next_run_at_ms = self.compute_next_run(job, now)

        entry: dict[str, Any] = {
            "job_id": job.job_id,
            "status": status,
            "error": error,
            "duration_ms": duration,
            "executed_at_ms": now,
        }
        self._run_log.append(job.job_id, entry)

        # Fire hook
        if self._hooks:
            from core.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.TRIGGER_FIRED,
                {"job_id": job.job_id, "status": status, "source": "scheduler"},
            )

        return entry

    def _skip_job(
        self,
        job: ScheduledJob,
        now_ms: float,
        reason: str,
    ) -> dict[str, Any]:
        """Record a skipped execution."""
        job.last_status = "skipped"
        entry: dict[str, Any] = {
            "job_id": job.job_id,
            "status": "skipped",
            "reason": reason,
            "executed_at_ms": now_ms,
        }
        self._run_log.append(job.job_id, entry)
        return entry

    # -- Persistence --------------------------------------------------------

    def save(self) -> None:
        """Atomically persist the durable job store to disk (tmp + rename).

        Uses O_EXCL lock file with PID liveness probe for cross-process
        coordination. Non-durable (session-only) jobs are excluded.
        """
        path = Path(self._store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Filter: only persist durable jobs
        data = {jid: _job_to_dict(j) for jid, j in self._jobs.items() if j.durable}
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        lock = SchedulerLock(path.parent / "scheduled_tasks.lock", session_id=self._session_id)
        with lock:
            tmp_path = path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(str(tmp_path), str(path))
        # Update mtime tracking
        with contextlib.suppress(OSError):
            self._last_store_mtime = os.path.getmtime(path)
        log.debug("Scheduler state saved to %s (%d durable jobs)", path, len(data))

    def load(self) -> None:
        """Load job store from disk.

        Reads atomically (os.replace guarantees consistent writes).
        Preserves in-memory non-durable jobs across reloads.
        Falls back to legacy global store if project-local doesn't exist.
        """
        path = Path(self._store_path)

        # Backward-compat: fall back to legacy global store
        # Only when using default store path (not explicitly provided)
        if not path.exists() and not self._store_path_explicit and _LEGACY_STORE_PATH.exists():
            log.info(
                "Migrating from legacy store %s -> %s",
                _LEGACY_STORE_PATH,
                path,
            )
            path = _LEGACY_STORE_PATH

        if not path.exists():
            log.debug("No scheduler store at %s", path)
            return

        try:
            with open(path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to read scheduler store %s: %s", path, exc)
            return

        # Preserve non-durable (session-only) jobs
        session_jobs = {jid: j for jid, j in self._jobs.items() if not j.durable}

        loaded = 0
        zombies = 0
        for _jid, jdata in data.items():
            try:
                job = _job_from_dict(jdata)
                # Skip zombie jobs (no action, no callback) — auto-cleanup
                if not job.action and job.callback is None:
                    zombies += 1
                    continue
                self._jobs[job.job_id] = job
                loaded += 1
            except Exception as exc:
                log.warning("Skipping malformed job entry: %s", exc)

        # Re-add session-only jobs
        self._jobs.update(session_jobs)

        if zombies:
            log.warning("Skipped %d zombie jobs (empty action) on load", zombies)

        # Track file mtime for change detection
        with contextlib.suppress(OSError):
            self._last_store_mtime = os.path.getmtime(path)

        log.info("Loaded %d jobs from %s", loaded, path)

    # -- Background runner --------------------------------------------------

    def start(self, interval_s: float = 1.0) -> None:
        """Start the background scheduler loop (default: 1s check interval)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval_s,),
            daemon=True,
            name="advanced-scheduler",
        )
        self._thread.start()
        log.info("SchedulerService started (interval=%.1fs)", interval_s)

    def stop(self) -> None:
        """Stop the background scheduler loop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("SchedulerService stopped")

    @property
    def is_running(self) -> bool:
        """Whether the background loop is active."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def job_count(self) -> int:
        """Number of registered jobs."""
        return len(self._jobs)

    # -- Stuck job detection ---------------------------------------------------

    STUCK_TIMEOUT_MS: float = 600_000.0  # 10 minutes

    def detect_stuck_jobs(self, now_ms: float | None = None) -> list[str]:
        """Detect and mark jobs that have been running longer than STUCK_TIMEOUT_MS.

        Returns a list of stuck job IDs.
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        stuck: list[str] = []
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.running_since_ms is not None
                    and (now - job.running_since_ms) > self.STUCK_TIMEOUT_MS
                ):
                    elapsed_s = (now - job.running_since_ms) / 1000
                    log.warning(
                        "Stuck job detected: '%s' running for %.0fs (threshold %.0fs)",
                        job.job_id,
                        elapsed_s,
                        self.STUCK_TIMEOUT_MS / 1000,
                    )
                    job.last_status = "stuck"
                    job.running_since_ms = None
                    stuck.append(job.job_id)
        if stuck and self._hooks:
            from core.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.TRIGGER_FIRED,
                {"stuck_jobs": stuck, "source": "scheduler_stuck_detection"},
            )
        return stuck

    def _reload_if_changed(self) -> bool:
        """Reload job store if the file was modified externally.

        Uses mtime comparison instead of file watchers (no external dependency).
        Returns True if a reload occurred.
        """
        path = Path(self._store_path)
        if not path.exists():
            return False
        try:
            current_mtime = os.path.getmtime(path)
        except OSError:
            return False
        if current_mtime != self._last_store_mtime:
            log.debug(
                "Store file changed (mtime %.0f -> %.0f), reloading",
                self._last_store_mtime,
                current_mtime,
            )
            self.load()
            return True
        return False

    # -- Missed task recovery -----------------------------------------------

    def find_missed_tasks(
        self,
        now_ms: float | None = None,
        grace_ms: float = MISSED_TASK_GRACE_MS,
    ) -> list[ScheduledJob]:
        """Find one-shot/interval jobs that missed their execution window.

        AT jobs:   missed if ``at_ms < now < at_ms + grace_ms`` and never ran.
        EVERY jobs: missed if ``next_run_at_ms`` is more than 2 intervals past.
        CRON jobs: skipped (they naturally fire on the next matching minute).
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        missed: list[ScheduledJob] = []

        with self._lock:
            for job in self._jobs.values():
                if not job.enabled:
                    continue

                kind = job.schedule.kind

                if kind == ScheduleKind.AT:
                    at = job.schedule.at_ms
                    if job.last_run_at_ms is None and at < now and (now - at) <= grace_ms:
                        missed.append(job)

                elif kind == ScheduleKind.EVERY:
                    nxt = job.next_run_at_ms
                    interval = job.schedule.every_ms
                    if nxt is not None and interval > 0 and (now - nxt) > 2 * interval:
                        missed.append(job)

        return missed

    def recover_missed_tasks(
        self,
        now_ms: float | None = None,
    ) -> list[dict[str, Any]]:
        """Execute missed tasks and return their results."""
        missed = self.find_missed_tasks(now_ms=now_ms)
        if not missed:
            return []

        now = now_ms if now_ms is not None else time.time() * 1000
        results: list[dict[str, Any]] = []
        for job in missed:
            log.info("Recovering missed job '%s' (%s)", job.job_id, job.schedule.kind.value)
            result = self._execute_job(job, now_ms=now)
            result["recovered"] = True
            results.append(result)

        return results

    def _loop(self, interval_s: float) -> None:
        """Background tick loop (default 1s for responsive scheduling)."""
        while not self._stop_event.is_set():
            try:
                self._reload_if_changed()
                self.check_due_jobs()
                self.detect_stuck_jobs()
            except Exception as exc:
                log.warning("Scheduler tick error: %s", exc)
            self._stop_event.wait(interval_s)


# ---------------------------------------------------------------------------
# Factory function — claude-code-style library instantiation
# ---------------------------------------------------------------------------


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
