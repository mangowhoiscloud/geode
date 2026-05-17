import time

import pytest
from core.automation.outcome_tracking import (
    JobStatus,
    OutcomeData,
    OutcomeTracker,
    TrackingPoint,
)


def test_outcome_data_serializes_subject_id() -> None:
    data = OutcomeData(
        subject_id="subject-1",
        tracking_point=TrackingPoint.T_PLUS_30,
        revenue_delta_pct=1.2,
        dau_delta_pct=2.3,
        retention_delta_pct=3.4,
        confounding_factors=["launch"],
    )

    assert data.to_dict()["subject_id"] == "subject-1"
    assert data.to_dict()["tracking_point"] == "t_plus_30"


def test_schedule_execute_and_metrics_latest_per_tracking_point() -> None:
    tracker = OutcomeTracker()
    job = tracker.schedule("subject-1", TrackingPoint.T_PLUS_30)
    older = OutcomeData(
        subject_id="subject-1",
        tracking_point=TrackingPoint.T_PLUS_30,
        revenue_delta_pct=1,
        dau_delta_pct=2,
        retention_delta_pct=3,
        collected_at=1,
    )
    newer = OutcomeData(
        subject_id="subject-1",
        tracking_point=TrackingPoint.T_PLUS_30,
        revenue_delta_pct=4,
        dau_delta_pct=5,
        retention_delta_pct=6,
        collected_at=2,
    )

    tracker.execute_job(job.job_id, older)
    second = tracker.schedule("subject-1", TrackingPoint.T_PLUS_30)
    tracker.execute_job(second.job_id, newer)

    assert tracker.get_job(job.job_id).status == JobStatus.SUCCESS
    assert tracker.list_jobs(subject_id="subject-1", status=JobStatus.SUCCESS)
    assert tracker.outcomes_to_metrics("subject-1")["revenue_delta_t_plus_30"] == 4
    assert tracker.outcomes_to_metrics("subject-1")["revenue_delta_avg"] == 4


def test_retry_sets_backoff_and_blocks_early_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = OutcomeTracker()
    job = tracker.schedule("subject-1", TrackingPoint.T_PLUS_90, max_retries=1)
    tracker.fail_job(job.job_id, "network")
    monkeypatch.setattr("core.automation.outcome_tracking.random.uniform", lambda _a, _b: 0.0)

    retry = tracker.retry_job(job.job_id)

    assert retry.status == JobStatus.PENDING
    assert retry.retry_count == 1
    assert tracker.get_backoff_seconds(job.job_id) == tracker.BASE_BACKOFF_S
    with pytest.raises(RuntimeError):
        tracker.execute_job(
            job.job_id,
            OutcomeData(subject_id="subject-1", tracking_point=TrackingPoint.T_PLUS_90),
        )


def test_schedule_tracking_and_sla() -> None:
    tracker = OutcomeTracker()
    jobs = tracker.schedule_tracking("subject-1")

    assert [job.tracking_point for job in jobs] == [
        TrackingPoint.T_PLUS_30,
        TrackingPoint.T_PLUS_90,
        TrackingPoint.T_PLUS_180,
    ]
    assert tracker.check_sla(jobs[0].job_id, time.time()) is True
    assert tracker.check_sla(jobs[0].job_id, 0) is False


def test_missing_job_errors() -> None:
    tracker = OutcomeTracker()

    with pytest.raises(KeyError):
        tracker.fail_job("missing", "error")
    with pytest.raises(KeyError):
        tracker.get_backoff_seconds("missing")
