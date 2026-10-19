"""SchedulerService — the central scheduling engine.

Combines the data models, run log, lock, jitter, and timezone helpers from
sibling modules into a single long-running service that ticks once per
second and fires due jobs.

Durable state follows one rule: every store mutation takes the cross-process
``SchedulerLock``, reloads the store, applies the operation to that fresh
state, and persists before releasing. A run is claimed the same way and
carries a ``run_id`` fence, so a second instance or a late completion of an
older run cannot fire the same occurrence twice or settle a newer run. The
lock is never held while a callback or dispatched session executes.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.memory.atomic_write import atomic_write_text
from core.memory.collaboration import current_process_owner, process_owner_alive
from core.observability.run_log import JobRunLog
from core.scheduler.jitter import _jittered_next_run
from core.scheduler.lock import SchedulerLock
from core.scheduler.models import (
    _LEGACY_STORE_PATH,
    DEFAULT_LOG_DIR,
    DEFAULT_MAX_JITTER_MS,
    DEFAULT_STORE_PATH,
    MISSED_TASK_GRACE_MS,
    RECURRING_MAX_AGE_MS,
    ActiveHours,
    OnJobFired,
    ScheduledJob,
    ScheduleKind,
)
from core.scheduler.serialization import _job_from_dict, _job_to_dict
from core.scheduler.timezone import _cron_tuple_for_tz, _now_minutes, _parse_hhmm
from core.scheduler.triggers import CronParser, TriggerManager

if TYPE_CHECKING:
    from core.hooks import HookSystem

log = logging.getLogger(__name__)

_LOCK_FILENAME = "scheduled_tasks.lock"

# Run IDs claimed by this process and not yet settled. With the persisted
# owner identity this is the observed-termination authority for same-process
# runs; it is process-wide because several service instances may share a store.
_ACTIVE_RUNS: set[str] = set()
_ACTIVE_RUNS_LOCK = threading.Lock()


def _accepts_args(callback: Callable[..., Any], count: int) -> bool:
    try:
        inspect.signature(callback).bind(*([None] * count))
    except TypeError:
        return False
    except ValueError:  # no introspectable signature (builtin): assume current form
        return True
    return True


class SchedulerStoreError(RuntimeError):
    """The durable job store is unreadable; it is left unchanged."""


class SchedulerService:
    """Advanced scheduler with 3-type scheduling + active hours.

    Owns the :class:`TriggerManager` passed at composition (exposed as
    :attr:`trigger_manager` for manual trigger dispatch). The scheduler
    manages its own job store (atomic JSON) and per-job JSONL run logs.
    """

    MAX_JOBS: int = 50  # Maximum number of scheduled jobs (claude-code pattern)

    def __init__(
        self,
        trigger_manager: TriggerManager | None = None,
        hooks: HookSystem | None = None,
        store_path: Path | None = None,
        log_dir: Path | None = None,
        on_job_fired: Callable[..., None] | None = None,
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
        self._run_log = JobRunLog(log_dir=log_dir if log_dir is not None else DEFAULT_LOG_DIR)
        self._jobs: dict[str, ScheduledJob] = {}
        # Re-entrant: store transactions call the CRUD methods below.
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Durable CRUD made outside a transaction, applied onto the freshly
        # reloaded store at the next save so stale copies never overwrite it.
        self._pending: dict[str, tuple[str, dict[str, Any]]] = {}
        self._txn_depth = 0

        # Callback protocol (replaces action_queue)
        self._on_job_fired: OnJobFired | None = None
        self._dispatch_reports_outcome = False
        if on_job_fired is not None:
            self.set_on_job_fired(on_job_fired)
        elif action_queue is not None:
            # Backward-compat: wrap queue.put as callback. A bare queue cannot
            # report the session outcome, so its runs settle at dispatch.
            def _queue_adapter(jid: str, act: str, iso: bool, _aid: str, _rid: str) -> None:
                action_queue.put((jid, act, iso))

            self._on_job_fired = _queue_adapter

        # Jitter settings
        self._enable_jitter = enable_jitter
        self._max_jitter_ms = max_jitter_ms

        # mtime-based file watch for external changes
        self._last_store_mtime: float = 0.0

        # CRON dedup: prevent same cron job from firing twice in same minute
        self._last_fired_minute: dict[str, int] = {}

    @property
    def trigger_manager(self) -> TriggerManager | None:
        """The composed trigger owner used for manual trigger dispatch."""
        return self._trigger_manager

    def set_on_job_fired(self, callback: Callable[..., None] | None) -> None:
        """Replace the action-dispatch callback for this scheduler.

        A five-argument ``(job_id, action, isolated, agent_id, run_id)``
        callback owns the run until it calls :meth:`record_run_outcome`. A
        legacy four-argument callback cannot report an outcome, so its runs
        settle immediately as ``dispatched`` (outcome unknown, never ``ok``).
        """
        self._dispatch_reports_outcome = False
        if callback is None or _accepts_args(callback, 5):
            self._on_job_fired = callback
            self._dispatch_reports_outcome = callback is not None
            return
        legacy = callback

        def _legacy_adapter(jid: str, act: str, iso: bool, aid: str, _rid: str) -> None:
            legacy(jid, act, iso, aid)

        self._on_job_fired = _legacy_adapter

    # -- CRUD (in-memory; durable changes persist at the next save) -------

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
            if job.durable:
                self._pending[job.job_id] = ("add", {})
        log.info("Added job '%s' (%s)", job.job_id, job.schedule.kind.value)

    def remove_job(self, job_id: str) -> bool:
        """Remove a job. Returns True if found and removed."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return False
            if job.durable:
                if self._pending.get(job_id, ("", {}))[0] == "add":
                    del self._pending[job_id]
                else:
                    self._pending[job_id] = ("delete", {})
            return True

    def update_job(self, job_id: str, **updates: Any) -> bool:
        """Update fields on an existing job. Returns True if found."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            self._apply_updates(job, updates)
            if job.durable:
                op, previous = self._pending.get(job_id, ("update", {}))
                if op != "add":
                    self._pending[job_id] = ("update", {**previous, **updates})
            return True

    def _apply_updates(self, job: ScheduledJob, updates: dict[str, Any]) -> None:
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        # Recompute next_run if schedule-related fields changed
        if {"schedule", "enabled"} & set(updates):
            job.next_run_at_ms = self.compute_next_run(job)

    def get_job(self, job_id: str) -> ScheduledJob | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, include_disabled: bool = False) -> list[ScheduledJob]:
        """List jobs, optionally including disabled ones."""
        with self._lock:
            jobs = list(self._jobs.values())
        if not include_disabled:
            jobs = [j for j in jobs if j.enabled]
        return jobs

    # -- Durable commands (lock -> reload -> operate -> persist) -----------

    def create_job(self, job: ScheduledJob) -> None:
        """Add and persist a job against the current store (ValueError if invalid)."""
        with self._store_transaction():
            self.add_job(job)

    def delete_job(self, job_id: str) -> bool:
        """Remove and persist; False when the current store has no such job."""
        with self._store_transaction():
            return self.remove_job(job_id)

    def set_job_enabled(self, job_id: str, enabled: bool) -> bool:
        """Enable/disable and persist; False when the current store has no such job."""
        with self._store_transaction():
            return self.update_job(job_id, enabled=enabled)

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
        """Force one manual run, bypassing schedule & active hours.

        A manual run never consumes the job's next scheduled occurrence.
        Returns a ``skipped`` entry while another run of the job is active.
        """
        now = time.time() * 1000
        job = self._claim(job_id, now, mode="manual")
        if job is None:
            return self._already_running(job_id, now)
        return self._execute_job(job, now_ms=now)

    def check_due_jobs(self, now_ms: float | None = None) -> list[dict[str, Any]]:
        """Check all jobs and execute those that are due.

        Returns a list of execution result dicts.
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        results: list[dict[str, Any]] = []

        with self._lock:
            snapshot = list(self._jobs.values())

        for job in snapshot:
            if not job.enabled:
                continue
            # A durable callback job loaded where its callback is not registered
            # has nothing to run here; it stays stored for the process that has it.
            if job.callback is None and not job.action:
                continue

            # A composition root may attach the action callback immediately
            # after constructing an already-running scheduler. Keep due jobs
            # pending until that dispatch path exists instead of recording a
            # false success and deleting one-shot work.
            if job.callback is None and job.action and self._on_job_fired is None:
                continue

            kind = job.schedule.kind

            # Age-out: recurring, non-permanent, older than RECURRING_MAX_AGE_MS
            if self._aged_out(job, now):
                claimed = self._claim(job.job_id, now, mode="aged_out")
                if claimed is None:
                    continue
                result = self._execute_job(claimed, now_ms=now)
                result["aged_out"] = True
                self._delete_durable(job.job_id)
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

            claimed = self._claim(job.job_id, now, mode="due")
            if claimed is None:
                continue
            results.append(self._execute_job(claimed, now_ms=now))

        return results

    @staticmethod
    def _aged_out(job: ScheduledJob, now: float) -> bool:
        return (
            job.schedule.kind in (ScheduleKind.EVERY, ScheduleKind.CRON)
            and not job.permanent
            and job.created_at_ms > 0
            and (now - job.created_at_ms) > RECURRING_MAX_AGE_MS
        )

    def _missed(self, job: ScheduledJob, now: float, grace_ms: float) -> bool:
        if job.schedule.kind == ScheduleKind.AT:
            at = job.schedule.at_ms
            never_ran = job.last_run_at_ms is None and job.last_scheduled_at_ms is None
            return never_ran and at < now and (now - at) <= grace_ms
        if job.schedule.kind == ScheduleKind.EVERY:
            nxt = job.next_run_at_ms
            interval = job.schedule.every_ms
            return nxt is not None and interval > 0 and (now - nxt) > 2 * interval
        return False

    def _eligible(self, job: ScheduledJob, now: float, mode: str) -> bool:
        """Re-check on freshly loaded state that this run is still authorized.

        Another instance may have paused, rescheduled, re-timed, or already
        claimed the job since the caller's stale snapshot decided to run it.
        """
        if mode == "manual":
            return True
        if not job.enabled or (job.callback is None and not job.action):
            return False
        if job.active_hours and not self.is_within_active_hours(job.active_hours, now):
            return False
        if mode == "aged_out":
            return self._aged_out(job, now)
        if mode == "missed":
            return self._missed(job, now, MISSED_TASK_GRACE_MS)
        if job.schedule.kind == ScheduleKind.CRON:
            last = job.last_scheduled_at_ms
            if last is not None and int(last / 60_000) == int(now / 60_000):
                return False
            try:
                return CronParser.matches(
                    job.schedule.cron_expr, _cron_tuple_for_tz(job.schedule.timezone)
                )
            except ValueError:
                return False
        return job.next_run_at_ms is not None and now >= job.next_run_at_ms

    def _run_alive(self, job: ScheduledJob) -> bool:
        """Whether the claimed run's owner has not been observed to terminate.

        Same process: the run is alive until it settles here. Another process:
        alive while that exact process (PID + birth time) exists. A legacy row
        with no owner is unknown, which never counts as terminated.
        """
        if job.running_since_ms is None:
            return False
        if job.run_owner == current_process_owner():
            with _ACTIVE_RUNS_LOCK:
                return job.run_id in _ACTIVE_RUNS
        if not job.run_owner:
            return True
        return process_owner_alive(job.run_owner)

    def _claim(self, job_id: str, now: float, *, mode: str) -> ScheduledJob | None:
        """Atomically mark one run of ``job_id`` as started.

        ``mode`` is ``due``, ``missed``, ``aged_out`` (scheduled occurrences)
        or ``manual``. Returns the claimed job, or None when it is gone,
        another run's owner is still alive, or the occurrence is no longer
        authorized on the current store. Raises KeyError for a manual run of
        an unknown job. A previous run whose owner is observed gone is
        recorded as ``interrupted`` before the new claim.
        """
        scheduled = mode != "manual"
        registered = ""
        interrupted: dict[str, Any] | None = None
        claimed: ScheduledJob | None = None
        try:
            with self._persisted_transaction():
                job = self._jobs.get(job_id)
                if job is None:
                    if not scheduled:
                        raise KeyError(f"Job '{job_id}' not found")
                elif not self._run_alive(job):
                    if job.running_since_ms is not None:
                        interrupted = {
                            "job_id": job_id,
                            "run_id": job.run_id,
                            "status": "interrupted",
                            "error": "run owner exited before reporting an outcome",
                            "executed_at_ms": now,
                        }
                        job.running_since_ms, job.run_id = None, ""
                        job.run_owner, job.run_kind, job.last_status = "", "", "interrupted"
                    if self._eligible(job, now, mode):
                        job.running_since_ms = now
                        job.run_id = uuid.uuid4().hex
                        job.run_owner = current_process_owner()
                        job.run_kind = "scheduled" if scheduled else "manual"
                        job.last_run_at_ms = now
                        if scheduled:
                            job.last_scheduled_at_ms = now
                            # AT runs once; recurring kinds advance past this occurrence.
                            at_once = job.schedule.kind == ScheduleKind.AT
                            job.next_run_at_ms = (
                                None if at_once else self.compute_next_run(job, now)
                            )
                        # Registered while the store lock is held, so no
                        # same-process instance sees the claim on disk without
                        # its owner record; withdrawn below if the write fails.
                        registered = job.run_id
                        with _ACTIVE_RUNS_LOCK:
                            _ACTIVE_RUNS.add(registered)
                        claimed = job
        except BaseException:
            if registered:
                with _ACTIVE_RUNS_LOCK:
                    _ACTIVE_RUNS.discard(registered)
            raise
        # Only reached once the transaction (if any) was written.
        if interrupted is not None:
            self._run_log.append(job_id, interrupted)
        return claimed

    def _already_running(self, job_id: str, now: float) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "status": "skipped",
            "reason": "already_running",
            "error": f"Job '{job_id}' already has an active run",
            "executed_at_ms": now,
        }

    def _execute_job(
        self,
        job: ScheduledJob,
        now_ms: float | None = None,
    ) -> dict[str, Any]:
        """Execute one claimed run and record it.

        A callback finishes synchronously and is settled here. An action is
        handed to the dispatch callback; when that callback reports outcomes
        the run stays ``dispatched`` until :meth:`record_run_outcome`.
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        if not job.run_id:  # unclaimed direct call: claim in memory only
            job.run_id = uuid.uuid4().hex
            job.run_owner = current_process_owner()
            job.run_kind = "manual"
            job.running_since_ms = now
            job.last_run_at_ms = now
            with _ACTIVE_RUNS_LOCK:
                _ACTIVE_RUNS.add(job.run_id)
        run_id = job.run_id
        start = time.time() * 1000
        status = "ok"
        error = ""

        try:
            if job.callback is not None:
                job.callback({"job_id": job.job_id, "name": job.name, **job.metadata})
            elif job.action and self._on_job_fired is not None:
                self._on_job_fired(job.job_id, job.action, job.isolated, job.agent_id, run_id)
                status = "dispatched"
                log.debug(
                    "Job '%s' dispatched action (isolated=%s, agent=%s): %s",
                    job.job_id,
                    job.isolated,
                    job.agent_id or "main",
                    job.action[:60],
                )
            else:
                status = "error"
                error = "no callback or dispatch path for this job"
        except Exception as exc:
            status = "error"
            error = str(exc)
            log.warning("Job '%s' failed: %s", job.job_id, exc)

        duration = time.time() * 1000 - start
        entry: dict[str, Any] = {
            "job_id": job.job_id,
            "run_id": run_id,
            "status": status,
            "error": error,
            "duration_ms": duration,
            "executed_at_ms": now,
        }
        if status == "dispatched" and self._dispatch_reports_outcome:
            job.last_status = status
            self._run_log.append(job.job_id, entry)
        else:
            # Terminal here; a failure to persist it propagates and the claim stays.
            self._settle(job.job_id, run_id, status, error=error, duration_ms=duration)

        # Fire hook
        if self._hooks:
            from core.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.TRIGGER_FIRED,
                {"job_id": job.job_id, "status": status, "source": "scheduler"},
            )

        return entry

    def record_run_outcome(
        self,
        job_id: str,
        run_id: str,
        status: str,
        *,
        error: str = "",
        duration_ms: float | None = None,
    ) -> bool:
        """Settle a dispatched run. Returns False when ``run_id`` is not current.

        A stale outcome (a newer run was claimed, or the job was deleted)
        leaves the current state untouched. A store failure propagates: the
        run then stays claimed rather than being reported as settled.
        """
        return self._settle(job_id, run_id, status, error=error, duration_ms=duration_ms)

    def _settle(
        self,
        job_id: str,
        run_id: str,
        status: str,
        *,
        error: str = "",
        duration_ms: float | None = None,
    ) -> bool:
        now = time.time() * 1000
        with self._persisted_transaction():
            job = self._jobs.get(job_id)
            if job is None or not run_id or job.run_id != run_id:
                log.info("Ignoring stale outcome for job '%s' run %s", job_id, run_id[:8])
                current = False
            else:
                current = True
                manual = job.run_kind == "manual"
                job.running_since_ms = None
                job.run_id = ""
                job.run_owner = ""
                job.run_kind = ""
                job.last_status = status
                if duration_ms is not None:
                    job.last_duration_ms = duration_ms
                if job.schedule.kind == ScheduleKind.AT and not manual:
                    if status == "ok" and job.delete_after_run:
                        self.remove_job(job_id)
                    else:
                        # Disable AT job after execution (even if errored)
                        self.update_job(job_id, enabled=False)
                        job.next_run_at_ms = None
        # Persisted (or no longer ours): the in-process liveness record ends.
        with _ACTIVE_RUNS_LOCK:
            _ACTIVE_RUNS.discard(run_id)
        if not current:
            return False
        entry: dict[str, Any] = {
            "job_id": job_id,
            "run_id": run_id,
            "status": status,
            "error": error,
            "executed_at_ms": now,
        }
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        self._run_log.append(job_id, entry)
        return True

    def _delete_durable(self, job_id: str) -> None:
        with self._persisted_transaction():
            self.remove_job(job_id)

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

    def _lock_path(self) -> Path:
        return Path(self._store_path).parent / _LOCK_FILENAME

    def _read_path(self) -> Path:
        path = Path(self._store_path)
        # Backward-compat: fall back to legacy global store
        # Only when using default store path (not explicitly provided)
        if not path.exists() and not self._store_path_explicit and _LEGACY_STORE_PATH.exists():
            return _LEGACY_STORE_PATH
        return path

    @contextlib.contextmanager
    def _store_transaction(self) -> Iterator[None]:
        """Lock the store, reload it, let the caller operate, then persist.

        Nested transactions on the same thread join the outer one. Nothing is
        written when the body raises.
        """
        with self._lock:
            if self._txn_depth:
                self._txn_depth += 1
                try:
                    yield
                finally:
                    self._txn_depth -= 1
                return
            with SchedulerLock(self._lock_path()):
                self._load_locked(strict=True)
                self._txn_depth = 1
                try:
                    yield
                finally:
                    self._txn_depth = 0
                self._write_locked()

    @contextlib.contextmanager
    def _persisted_transaction(self) -> Iterator[None]:
        """Store transaction when a store exists; in-memory only otherwise.

        Run claims and settles on a never-persisted scheduler (no store file)
        have no other instance to coordinate with, so they do not create one.
        """
        with self._lock:
            # Only the project store: a run must never trigger legacy migration.
            if self._txn_depth or Path(self._store_path).exists():
                with self._store_transaction():
                    yield
            else:
                yield

    def save(self) -> None:
        """Persist pending durable changes onto the current store.

        Reloads under the cross-process lock first, so another instance's
        additions, deletions, pauses and run claims are preserved; this
        instance's own adds/updates/deletes are then applied and written
        atomically (tmp + rename). Non-durable (session-only) jobs are
        excluded.
        """
        with self._store_transaction():
            pass

    def _write_locked(self) -> None:
        path = Path(self._store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {jid: _job_to_dict(j) for jid, j in self._jobs.items() if j.durable}
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        self._pending.clear()
        with contextlib.suppress(OSError):
            self._last_store_mtime = os.path.getmtime(path)
        log.debug("Scheduler state saved to %s (%d durable jobs)", path, len(data))

    def load(self) -> None:
        """Load job store from disk.

        Reads atomically (os.replace guarantees consistent writes).
        Preserves in-memory non-durable jobs and pending local changes.
        Falls back to legacy global store if project-local doesn't exist.
        An unreadable store is reported and leaves memory unchanged.
        """
        with self._lock:
            self._load_locked(strict=False)

    def _load_locked(self, *, strict: bool) -> None:
        path = self._read_path()
        if path != Path(self._store_path):
            log.info("Migrating from legacy store %s -> %s", path, self._store_path)
        data: dict[str, Any] = {}
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("store root is not an object")
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                if strict:
                    raise SchedulerStoreError(
                        f"Scheduler store {path} is unreadable; it was left unchanged"
                    ) from exc
                log.warning("Failed to read scheduler store %s: %s", path, exc)
                return
        else:
            log.debug("No scheduler store at %s", path)

        previous = self._jobs
        merged: dict[str, ScheduledJob] = {}
        loaded = 0
        zombies = 0
        for _jid, jdata in data.items():
            try:
                job = _job_from_dict(jdata)
            except Exception as exc:
                if strict:
                    # Rewriting would silently delete the row; refuse instead.
                    raise SchedulerStoreError(
                        f"Scheduler store {path} has a malformed job entry; it was left unchanged"
                    ) from exc
                log.warning("Skipping malformed job entry: %s", exc)
                continue
            old = previous.get(job.job_id)
            if old is not None and old.callback is not None:
                job.callback = old.callback
            # A callback job persists without its callable. Keep the row (and the
            # operator's flags) for the process that registers the callback; it
            # is never run here (check_due_jobs skips it).
            if not job.action and job.callback is None:
                zombies += 1
            merged[job.job_id] = job
            loaded += 1

        # Re-apply this instance's pending durable changes onto the fresh state.
        for jid, (op, updates) in list(self._pending.items()):
            if op == "delete":
                merged.pop(jid, None)
            elif op == "add":
                if jid in merged:
                    log.warning("Job '%s' was added by another scheduler; keeping it", jid)
                    del self._pending[jid]
                elif jid in previous:
                    merged[jid] = previous[jid]
            elif jid in merged:
                self._apply_updates(merged[jid], updates)
            else:
                # Deleted elsewhere: an update must not resurrect it.
                del self._pending[jid]

        # Preserve non-durable (session-only) jobs
        merged.update({jid: j for jid, j in previous.items() if not j.durable})
        self._jobs = merged

        if zombies:
            log.debug("Loaded %d callback jobs without a registered callback", zombies)

        # Track file mtime for change detection
        with contextlib.suppress(OSError):
            self._last_store_mtime = os.path.getmtime(path)

        log.debug("Loaded %d jobs from %s", loaded, path)

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
        """Report runs active longer than STUCK_TIMEOUT_MS.

        Elapsed time alone never releases a claim: the original run may still
        be executing. A run whose owner is observed gone is settled as
        ``interrupted``; a still-owned (or unknown legacy) run is only marked
        ``stuck`` for display and keeps blocking a second execution.

        Returns a list of stuck job IDs.
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        with self._lock:
            candidates = [
                job
                for job in self._jobs.values()
                if job.running_since_ms is not None
                and (now - job.running_since_ms) > self.STUCK_TIMEOUT_MS
            ]
        stuck: list[str] = []
        for job in candidates:
            log.warning(
                "Stuck job detected: '%s' running for %.0fs (threshold %.0fs)",
                job.job_id,
                (now - (job.running_since_ms or now)) / 1000,
                self.STUCK_TIMEOUT_MS / 1000,
            )
            if job.run_id and not self._run_alive(job):
                self._settle(
                    job.job_id,
                    job.run_id,
                    "interrupted",
                    error="run owner exited before reporting an outcome",
                )
            else:
                job.last_status = "stuck"
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

        AT jobs:   missed if ``at_ms < now < at_ms + grace_ms`` and it never ran
                   (at-most-once: any earlier run, manual or scheduled, counts).
        EVERY jobs: missed if ``next_run_at_ms`` is more than 2 intervals past.
        CRON jobs: skipped (they naturally fire on the next matching minute).
        """
        now = now_ms if now_ms is not None else time.time() * 1000
        missed: list[ScheduledJob] = []

        with self._lock:
            missed.extend(
                job
                for job in self._jobs.values()
                if job.enabled and self._missed(job, now, grace_ms)
            )
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
            claimed = self._claim(job.job_id, now, mode="missed")
            if claimed is None:
                continue
            result = self._execute_job(claimed, now_ms=now)
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


# Re-export DEFAULT_LOG_DIR for service consumers that need the constant
__all__ = ["DEFAULT_LOG_DIR", "SchedulerService", "SchedulerStoreError"]
