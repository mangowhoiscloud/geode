"""Advanced Scheduler — 3-type scheduling + active hours.

Inspired by OpenClaw's Cron Service. Supports:
- AT: one-shot absolute timestamp jobs
- EVERY: fixed-interval with anchor-based drift prevention
- CRON: standard cron expressions (via existing CronParser)
- Active Hours: timezone-aware quiet-hours window with midnight wrap-around
- Per-job JSONL run log with auto-pruning
- Atomic JSON store (tmp + rename pattern)

Architecture-v6 SS4.5: Automation Layer -- Advanced Scheduler (P4).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.automation.triggers import CronParser, TriggerManager

if TYPE_CHECKING:
    from core.hooks import HookSystem

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STORE_PATH = Path.home() / ".geode" / "scheduler" / "jobs.json"
DEFAULT_LOG_DIR = Path.home() / ".geode" / "scheduler" / "logs"


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
    callback: Any = None  # Callable[[dict], None]
    action: str = ""  # Prompt text to enqueue when fired (no callback)
    isolated: bool = True  # Run in isolated session (agentTurn) vs main session (systemEvent)
    active_hours: ActiveHours | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # State tracking
    created_at_ms: float = 0.0
    next_run_at_ms: float | None = None
    last_run_at_ms: float | None = None
    last_status: str = ""  # "ok" | "error" | "skipped"
    last_duration_ms: float = 0.0


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
        "action": job.action,
        "isolated": job.isolated,
        "active_hours": (asdict(job.active_hours) if job.active_hours is not None else None),
        "metadata": job.metadata,
        "created_at_ms": job.created_at_ms,
        "next_run_at_ms": job.next_run_at_ms,
        "last_run_at_ms": job.last_run_at_ms,
        "last_status": job.last_status,
        "last_duration_ms": job.last_duration_ms,
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
    ``core.automation.triggers``.  The scheduler manages its own job store
    (atomic JSON) and per-job JSONL run logs.
    """

    def __init__(
        self,
        trigger_manager: TriggerManager | None = None,
        hooks: HookSystem | None = None,
        store_path: Path | None = None,
        log_dir: Path | None = None,
        action_queue: queue.Queue[tuple[str, str, bool]] | None = None,
    ) -> None:
        self._trigger_manager = trigger_manager
        self._hooks = hooks
        self._store_path = store_path if store_path is not None else DEFAULT_STORE_PATH
        self._run_log = JobRunLog(log_dir=log_dir)
        self._jobs: dict[str, ScheduledJob] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._action_queue = action_queue

    # -- CRUD ---------------------------------------------------------------

    def add_job(self, job: ScheduledJob) -> None:
        """Add a new scheduled job.

        Raises ValueError if job_id already exists or a job with the same
        schedule expression and action already exists (dedup).
        """
        with self._lock:
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

        For AT:   returns ``at_ms`` if still in the future, else None.
        For EVERY: uses anchor-based alignment to prevent drift on restart.
        For CRON:  returns the next minute boundary (checked by tick loop).
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        kind = job.schedule.kind

        if kind == ScheduleKind.AT:
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
                return anchor
            periods = int(elapsed / interval)
            return anchor + (periods + 1) * interval
        else:
            # CRON: evaluated every tick; return next minute boundary.
            remainder = now % 60_000
            return now + (60_000 - remainder) if remainder > 0 else now + 60_000

    def _is_cron_due(self, job: ScheduledJob, now_ms: float) -> bool:
        """Check whether a CRON job matches the current minute."""
        tz = job.schedule.timezone
        dt_tuple = _cron_tuple_for_tz(tz)
        try:
            return CronParser.matches(job.schedule.cron_expr, dt_tuple)
        except ValueError as exc:
            log.warning("Invalid cron for job '%s': %s", job.job_id, exc)
            return False

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

            due = False
            kind = job.schedule.kind

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

        try:
            if job.callback is not None:
                job.callback({"job_id": job.job_id, "name": job.name, **job.metadata})
            elif job.action and self._action_queue is not None:
                self._action_queue.put((job.job_id, job.action, job.isolated))
                log.debug(
                    "Job '%s' enqueued action (isolated=%s): %s",
                    job.job_id,
                    job.isolated,
                    job.action[:60],
                )
        except Exception as exc:
            status = "error"
            error = str(exc)
            log.warning("Job '%s' failed: %s", job.job_id, exc)

        duration = time.time() * 1000 - start

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
        """Atomically persist the job store to disk (tmp + rename)."""
        path = Path(self._store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {jid: _job_to_dict(j) for jid, j in self._jobs.items()}
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_path = path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(str(tmp_path), str(path))
        log.debug("Scheduler state saved to %s (%d jobs)", path, len(data))

    def load(self) -> None:
        """Load job store from disk."""
        path = Path(self._store_path)
        if not path.exists():
            log.debug("No scheduler store at %s", path)
            return
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        loaded = 0
        for _jid, jdata in data.items():
            try:
                job = _job_from_dict(jdata)
                self._jobs[job.job_id] = job
                loaded += 1
            except Exception as exc:
                log.warning("Skipping malformed job entry: %s", exc)
        log.info("Loaded %d jobs from %s", loaded, path)

    # -- Background runner --------------------------------------------------

    def start(self, interval_s: float = 60.0) -> None:
        """Start the background scheduler loop."""
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
        log.info("SchedulerService started (interval=%.0fs)", interval_s)

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

    def _loop(self, interval_s: float) -> None:
        """Background tick loop."""
        while not self._stop_event.is_set():
            try:
                self.check_due_jobs()
            except Exception as exc:
                log.warning("Scheduler tick error: %s", exc)
            self._stop_event.wait(interval_s)
