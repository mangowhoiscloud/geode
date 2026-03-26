"""Outcome Tracking — schedule and monitor post-analysis outcome collection.

Tracks real-world outcomes (revenue, DAU, retention) at T+30/90/180 days
with job scheduling, retry logic, and SLA monitoring.

Architecture-v6 §4.5: Automation Layer — Outcome Tracking.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.hooks import HookSystem

log = logging.getLogger(__name__)


class TrackingPoint(Enum):
    """Outcome measurement timepoints."""

    T_PLUS_30 = "t_plus_30"
    T_PLUS_90 = "t_plus_90"
    T_PLUS_180 = "t_plus_180"


# SLA deadlines (days) — allows buffer beyond measurement point
TRACKING_SLA: dict[TrackingPoint, int] = {
    TrackingPoint.T_PLUS_30: 35,
    TrackingPoint.T_PLUS_90: 95,
    TrackingPoint.T_PLUS_180: 185,
}


@dataclass
class OutcomeData:
    """Collected outcome measurements."""

    ip_name: str
    tracking_point: TrackingPoint
    revenue_delta_pct: float = 0.0
    dau_delta_pct: float = 0.0
    retention_delta_pct: float = 0.0
    confounding_factors: list[str] = field(default_factory=list)
    collected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip_name": self.ip_name,
            "tracking_point": self.tracking_point.value,
            "revenue_delta_pct": self.revenue_delta_pct,
            "dau_delta_pct": self.dau_delta_pct,
            "retention_delta_pct": self.retention_delta_pct,
            "confounding_factors": self.confounding_factors,
            "collected_at": self.collected_at,
        }


class JobStatus(Enum):
    """Outcome job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class OutcomeJob:
    """A scheduled outcome collection job."""

    job_id: str
    ip_name: str
    tracking_point: TrackingPoint
    status: JobStatus = JobStatus.PENDING
    scheduled_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    retry_count: int = 0
    max_retries: int = 3
    last_error: str = ""
    next_eligible_at: float = 0.0
    result: OutcomeData | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "ip_name": self.ip_name,
            "tracking_point": self.tracking_point.value,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_error": self.last_error,
        }


class _TrackerStats:
    """Internal instrumentation."""

    __slots__ = ("jobs_completed", "jobs_failed", "jobs_in_backoff", "jobs_scheduled", "retries")

    def __init__(self) -> None:
        self.jobs_scheduled: int = 0
        self.jobs_completed: int = 0
        self.jobs_failed: int = 0
        self.retries: int = 0
        self.jobs_in_backoff: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "jobs_scheduled": self.jobs_scheduled,
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
            "retries": self.retries,
            "jobs_in_backoff": self.jobs_in_backoff,
        }


class OutcomeTracker:
    """Schedule and manage outcome collection jobs.

    Usage:
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        tracker.execute_job(job.job_id, outcome_data)
    """

    BASE_BACKOFF_S = 60.0  # 1 minute
    MAX_BACKOFF_S = 3600.0  # 1 hour

    def __init__(self, *, hooks: HookSystem | None = None) -> None:
        self._jobs: dict[str, OutcomeJob] = {}
        self._outcomes: dict[str, list[OutcomeData]] = {}  # ip_name → outcomes
        self._next_id = 0
        self._lock = threading.Lock()
        self._stats = _TrackerStats()
        self._hooks = hooks

    @property
    def stats(self) -> _TrackerStats:
        return self._stats

    def schedule(
        self,
        ip_name: str,
        tracking_point: TrackingPoint,
        *,
        max_retries: int = 3,
    ) -> OutcomeJob:
        """Schedule a new outcome collection job."""
        with self._lock:
            self._next_id += 1
            job_id = f"outcome-{self._next_id:04d}"
            job = OutcomeJob(
                job_id=job_id,
                ip_name=ip_name,
                tracking_point=tracking_point,
                max_retries=max_retries,
            )
            self._jobs[job_id] = job
            self._stats.jobs_scheduled += 1
        log.info("Scheduled outcome job %s: %s @ %s", job_id, ip_name, tracking_point.value)
        return job

    def execute_job(self, job_id: str, outcome: OutcomeData) -> OutcomeJob:
        """Execute a job with collected outcome data."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Job '{job_id}' not found")

            if job.next_eligible_at > 0 and time.time() < job.next_eligible_at:
                raise RuntimeError(
                    f"Job '{job_id}' is in backoff until "
                    f"{job.next_eligible_at:.0f} (now={time.time():.0f})"
                )

            job.status = JobStatus.RUNNING
            job.started_at = time.time()

            job.result = outcome
            job.status = JobStatus.SUCCESS
            job.completed_at = time.time()
            self._stats.jobs_completed += 1

            # Store outcome
            if job.ip_name not in self._outcomes:
                self._outcomes[job.ip_name] = []
            self._outcomes[job.ip_name].append(outcome)

        log.info("Job %s completed successfully", job_id)

        if self._hooks:
            from core.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.OUTCOME_COLLECTED,
                {
                    "job_id": job_id,
                    "ip_name": job.ip_name,
                    "tracking_point": job.tracking_point.value,
                },
            )

        return job

    def fail_job(self, job_id: str, error: str) -> OutcomeJob:
        """Mark a job as failed."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Job '{job_id}' not found")

            job.status = JobStatus.FAILED
            job.last_error = error
            job.completed_at = time.time()
            self._stats.jobs_failed += 1
        return job

    def retry_job(self, job_id: str) -> OutcomeJob:
        """Retry a failed job with exponential backoff.

        Returns the job with updated retry count. Raises ValueError if max retries exceeded.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Job '{job_id}' not found")

            if job.status != JobStatus.FAILED:
                raise ValueError(
                    f"Job '{job_id}' is not in FAILED state (current: {job.status.value})"
                )

            if job.retry_count >= job.max_retries:
                raise ValueError(f"Job '{job_id}' exceeded max retries ({job.max_retries})")

            job.retry_count += 1
            job.status = JobStatus.PENDING
            job.last_error = ""
            self._stats.retries += 1

            # Enforce backoff via next_eligible_at (with jitter to prevent thundering herd)
            base_backoff = min(
                self.BASE_BACKOFF_S * (2 ** (job.retry_count - 1)),
                self.MAX_BACKOFF_S,
            )
            jitter = random.uniform(0, 0.1 * base_backoff)  # Up to 10% jitter
            backoff = base_backoff + jitter
            job.next_eligible_at = time.time() + backoff
            self._stats.jobs_in_backoff = sum(
                1
                for j in self._jobs.values()
                if j.next_eligible_at > 0 and time.time() < j.next_eligible_at
            )
        log.info("Retrying job %s (attempt %d, backoff %.0fs)", job_id, job.retry_count, backoff)
        return job

    def get_backoff_seconds(self, job_id: str) -> float:
        """Calculate current exponential backoff for a job."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job '{job_id}' not found")
        backoff: float = min(
            self.BASE_BACKOFF_S * (2 ** max(job.retry_count - 1, 0)),
            self.MAX_BACKOFF_S,
        )
        return backoff

    def check_sla(self, job_id: str, analysis_time: float) -> bool:
        """Check if a job is within its SLA deadline.

        Emits DRIFT_DETECTED hook event when SLA is breached (operational drift).

        Args:
            job_id: The job to check.
            analysis_time: When the original analysis was performed (epoch).

        Returns:
            True if within SLA, False if breached.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job '{job_id}' not found")

        sla_days = TRACKING_SLA[job.tracking_point]
        deadline = analysis_time + (sla_days * 86400)
        within_sla = time.time() <= deadline

        if not within_sla and self._hooks:
            from core.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.DRIFT_DETECTED,
                {
                    "source": "sla_breach",
                    "job_id": job_id,
                    "ip_name": job.ip_name,
                    "tracking_point": job.tracking_point.value,
                    "sla_days": sla_days,
                },
            )

        return within_sla

    def get_job(self, job_id: str) -> OutcomeJob | None:
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        ip_name: str | None = None,
        status: JobStatus | None = None,
    ) -> list[OutcomeJob]:
        """List jobs, optionally filtered."""
        with self._lock:
            jobs = list(self._jobs.values())
        if ip_name:
            jobs = [j for j in jobs if j.ip_name == ip_name]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.scheduled_at)

    def schedule_tracking(
        self,
        ip_name: str,
        checkpoints: list[TrackingPoint] | None = None,
    ) -> list[OutcomeJob]:
        """Schedule outcome collection at standard checkpoints.

        Args:
            ip_name: IP to track.
            checkpoints: Tracking points to schedule. Defaults to all three
                (T+30, T+90, T+180).

        Returns:
            List of scheduled OutcomeJob objects.
        """
        if checkpoints is None:
            checkpoints = [
                TrackingPoint.T_PLUS_30,
                TrackingPoint.T_PLUS_90,
                TrackingPoint.T_PLUS_180,
            ]
        return [self.schedule(ip_name, tp) for tp in checkpoints]

    def get_outcomes(self, ip_name: str) -> list[OutcomeData]:
        """Get all collected outcomes for an IP."""
        return self._outcomes.get(ip_name, [])

    def outcomes_to_metrics(self, ip_name: str) -> dict[str, float]:
        """Transform collected outcomes into feedback metrics.

        Bridges OutcomeData (revenue/DAU/retention deltas) to metric values
        that can feed into the FeedbackLoop's analyze() phase.

        Returns:
            Dict of metric_name → metric_value suitable for drift detection
            or correlation analysis.
        """
        outcomes = self.get_outcomes(ip_name)
        if not outcomes:
            return {}

        # Use the most recent outcome at each tracking point
        latest: dict[str, OutcomeData] = {}
        for o in outcomes:
            tp = o.tracking_point.value
            if tp not in latest or o.collected_at > latest[tp].collected_at:
                latest[tp] = o

        metrics: dict[str, float] = {}
        for tp_key, o in latest.items():
            metrics[f"revenue_delta_{tp_key}"] = o.revenue_delta_pct
            metrics[f"dau_delta_{tp_key}"] = o.dau_delta_pct
            metrics[f"retention_delta_{tp_key}"] = o.retention_delta_pct

        # Aggregate: weighted average across available timepoints
        all_rev = [o.revenue_delta_pct for o in latest.values()]
        all_dau = [o.dau_delta_pct for o in latest.values()]
        all_ret = [o.retention_delta_pct for o in latest.values()]

        if all_rev:
            metrics["revenue_delta_avg"] = sum(all_rev) / len(all_rev)
        if all_dau:
            metrics["dau_delta_avg"] = sum(all_dau) / len(all_dau)
        if all_ret:
            metrics["retention_delta_avg"] = sum(all_ret) / len(all_ret)

        return metrics
