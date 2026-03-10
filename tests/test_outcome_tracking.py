"""Tests for L4.5 Outcome Tracking."""

import time

import pytest
from core.automation.outcome_tracking import (
    TRACKING_SLA,
    JobStatus,
    OutcomeData,
    OutcomeTracker,
    TrackingPoint,
)


class TestTrackingPoint:
    def test_enum_values(self):
        assert TrackingPoint.T_PLUS_30.value == "t_plus_30"
        assert TrackingPoint.T_PLUS_90.value == "t_plus_90"
        assert TrackingPoint.T_PLUS_180.value == "t_plus_180"

    def test_sla_values(self):
        assert TRACKING_SLA[TrackingPoint.T_PLUS_30] == 35
        assert TRACKING_SLA[TrackingPoint.T_PLUS_90] == 95
        assert TRACKING_SLA[TrackingPoint.T_PLUS_180] == 185


class TestOutcomeData:
    def test_to_dict(self):
        od = OutcomeData(
            ip_name="Berserk",
            tracking_point=TrackingPoint.T_PLUS_30,
            revenue_delta_pct=15.0,
        )
        d = od.to_dict()
        assert d["ip_name"] == "Berserk"
        assert d["revenue_delta_pct"] == 15.0


class TestOutcomeTracker:
    def test_schedule(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        assert job.status == JobStatus.PENDING
        assert job.ip_name == "Berserk"
        assert tracker.stats.jobs_scheduled == 1

    def test_execute_job(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        outcome = OutcomeData(
            ip_name="Berserk",
            tracking_point=TrackingPoint.T_PLUS_30,
            revenue_delta_pct=20.0,
        )
        updated = tracker.execute_job(job.job_id, outcome)
        assert updated.status == JobStatus.SUCCESS
        assert tracker.stats.jobs_completed == 1

    def test_execute_not_found(self):
        tracker = OutcomeTracker()
        with pytest.raises(KeyError, match="not found"):
            tracker.execute_job(
                "nope",
                OutcomeData(
                    ip_name="X",
                    tracking_point=TrackingPoint.T_PLUS_30,
                ),
            )

    def test_fail_job(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        failed = tracker.fail_job(job.job_id, "timeout")
        assert failed.status == JobStatus.FAILED
        assert failed.last_error == "timeout"
        assert tracker.stats.jobs_failed == 1

    def test_retry_job(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        tracker.fail_job(job.job_id, "timeout")
        retried = tracker.retry_job(job.job_id)
        assert retried.status == JobStatus.PENDING
        assert retried.retry_count == 1
        assert tracker.stats.retries == 1

    def test_retry_not_failed_raises(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        with pytest.raises(ValueError, match="not in FAILED"):
            tracker.retry_job(job.job_id)

    def test_retry_max_exceeded(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30, max_retries=1)
        tracker.fail_job(job.job_id, "err")
        tracker.retry_job(job.job_id)
        tracker.fail_job(job.job_id, "err2")
        with pytest.raises(ValueError, match="exceeded max"):
            tracker.retry_job(job.job_id)

    def test_backoff_calculation(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        b0 = tracker.get_backoff_seconds(job.job_id)
        assert b0 == 60.0  # Base backoff

    def test_check_sla_within(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        assert tracker.check_sla(job.job_id, time.time()) is True

    def test_check_sla_breached(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        # Analysis was 100 days ago
        assert tracker.check_sla(job.job_id, time.time() - 100 * 86400) is False

    def test_list_jobs(self):
        tracker = OutcomeTracker()
        tracker.schedule("A", TrackingPoint.T_PLUS_30)
        tracker.schedule("B", TrackingPoint.T_PLUS_90)
        assert len(tracker.list_jobs()) == 2

    def test_list_jobs_filter_ip(self):
        tracker = OutcomeTracker()
        tracker.schedule("A", TrackingPoint.T_PLUS_30)
        tracker.schedule("B", TrackingPoint.T_PLUS_90)
        assert len(tracker.list_jobs(ip_name="A")) == 1

    def test_get_outcomes(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        outcome = OutcomeData(
            ip_name="Berserk",
            tracking_point=TrackingPoint.T_PLUS_30,
            dau_delta_pct=10.0,
        )
        tracker.execute_job(job.job_id, outcome)
        outcomes = tracker.get_outcomes("Berserk")
        assert len(outcomes) == 1
        assert outcomes[0].dau_delta_pct == 10.0

    def test_outcomes_to_metrics(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        outcome = OutcomeData(
            ip_name="Berserk",
            tracking_point=TrackingPoint.T_PLUS_30,
            revenue_delta_pct=15.0,
            dau_delta_pct=10.0,
            retention_delta_pct=5.0,
        )
        tracker.execute_job(job.job_id, outcome)
        metrics = tracker.outcomes_to_metrics("Berserk")
        assert metrics["revenue_delta_t_plus_30"] == 15.0
        assert metrics["dau_delta_t_plus_30"] == 10.0
        assert metrics["retention_delta_t_plus_30"] == 5.0
        assert metrics["revenue_delta_avg"] == 15.0

    def test_outcomes_to_metrics_empty(self):
        tracker = OutcomeTracker()
        assert tracker.outcomes_to_metrics("Nobody") == {}

    def test_outcomes_to_metrics_multiple_timepoints(self):
        tracker = OutcomeTracker()
        for tp in [TrackingPoint.T_PLUS_30, TrackingPoint.T_PLUS_90]:
            job = tracker.schedule("Berserk", tp)
            outcome = OutcomeData(
                ip_name="Berserk",
                tracking_point=tp,
                revenue_delta_pct=20.0 if tp == TrackingPoint.T_PLUS_30 else 10.0,
                dau_delta_pct=5.0,
                retention_delta_pct=3.0,
            )
            tracker.execute_job(job.job_id, outcome)
        metrics = tracker.outcomes_to_metrics("Berserk")
        assert metrics["revenue_delta_avg"] == 15.0  # (20+10)/2

    def test_backoff_enforced_on_retry(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        tracker.fail_job(job.job_id, "err")
        retried = tracker.retry_job(job.job_id)
        assert retried.next_eligible_at > time.time()

    def test_backoff_doubles_on_second_retry(self):
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        tracker.fail_job(job.job_id, "err1")
        r1 = tracker.retry_job(job.job_id)
        backoff1 = r1.next_eligible_at - time.time()
        tracker.fail_job(job.job_id, "err2")
        r2 = tracker.retry_job(job.job_id)
        backoff2 = r2.next_eligible_at - time.time()
        assert backoff2 > backoff1 * 1.5  # should roughly double

    def test_jitter_varies_across_retries(self):
        """Jitter should cause different backoff values for same retry count."""
        import random

        random.seed(None)  # Ensure randomness
        backoffs = []
        for _ in range(10):
            tracker = OutcomeTracker()
            job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
            tracker.fail_job(job.job_id, "err")
            retried = tracker.retry_job(job.job_id)
            backoffs.append(retried.next_eligible_at)
        # With jitter, not all backoffs should be identical
        unique = len(set(backoffs))
        assert unique > 1, "Jitter should produce varying backoff values"

    def test_jobs_in_backoff_stat(self):
        """jobs_in_backoff stat should track pending backoff jobs."""
        tracker = OutcomeTracker()
        job = tracker.schedule("Berserk", TrackingPoint.T_PLUS_30)
        tracker.fail_job(job.job_id, "err")
        tracker.retry_job(job.job_id)
        assert tracker.stats.jobs_in_backoff >= 1
