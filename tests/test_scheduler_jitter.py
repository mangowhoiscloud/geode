"""Tests for deterministic per-job jitter (thundering herd prevention)."""

from __future__ import annotations

from pathlib import Path

from core.scheduler.scheduler import (
    Schedule,
    ScheduledJob,
    ScheduleKind,
    SchedulerService,
    _compute_jitter_frac,
    _jittered_next_run,
)


class TestJitterFraction:
    """Deterministic hash-based jitter fraction."""

    def test_deterministic(self) -> None:
        """Same job_id always produces same jitter fraction."""
        frac1 = _compute_jitter_frac("test-job-123")
        frac2 = _compute_jitter_frac("test-job-123")
        assert frac1 == frac2

    def test_range(self) -> None:
        """Jitter fraction should be in [0, 1)."""
        for i in range(100):
            frac = _compute_jitter_frac(f"job-{i}")
            assert 0.0 <= frac < 1.0

    def test_distribution(self) -> None:
        """100 random job IDs should produce a spread (not all same value)."""
        fracs = {_compute_jitter_frac(f"job-{i}") for i in range(100)}
        # At least 50 distinct values from 100 IDs
        assert len(fracs) >= 50

    def test_different_ids_different_fracs(self) -> None:
        """Different job IDs should generally produce different fractions."""
        frac_a = _compute_jitter_frac("job-alpha")
        frac_b = _compute_jitter_frac("job-beta")
        assert frac_a != frac_b


class TestJitteredNextRun:
    """Forward jitter applied to recurring jobs."""

    def test_jitter_adds_delay(self) -> None:
        """Jittered next run should be >= base next run."""
        base = 1_000_000.0
        interval = 60_000.0
        result = _jittered_next_run(base, interval, "test-job")
        assert result >= base

    def test_jitter_bounded(self) -> None:
        """Jitter should not exceed max_jitter_ms."""
        base = 1_000_000.0
        interval = 600_000.0  # 10 min
        max_jitter = 5_000.0  # 5 sec cap
        result = _jittered_next_run(
            base,
            interval,
            "test-job",
            max_jitter_ms=max_jitter,
        )
        assert result <= base + max_jitter

    def test_jitter_respects_fraction(self) -> None:
        """Jitter should use fraction * interval * jitter_fraction."""
        base = 1_000_000.0
        interval = 60_000.0
        result = _jittered_next_run(
            base,
            interval,
            "test-job",
            jitter_fraction=0.1,
            max_jitter_ms=900_000.0,
        )
        # Max possible jitter: 1.0 * 60_000 * 0.1 = 6_000
        assert result <= base + 6_000

    def test_zero_interval(self) -> None:
        """Zero interval should produce zero jitter."""
        base = 1_000_000.0
        result = _jittered_next_run(base, 0.0, "test-job")
        assert result == base


class TestSchedulerServiceJitter:
    """Integration tests for jitter in SchedulerService."""

    def test_jitter_enabled(self, tmp_path: Path) -> None:
        """With jitter enabled, EVERY jobs should have shifted next_run."""
        svc = SchedulerService(
            store_path=tmp_path / "jobs.json",
            enable_jitter=True,
        )
        anchor = 1_000_000.0
        now = anchor + 150_000
        job = ScheduledJob(
            job_id="jitter-test",
            name="test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000, anchor_ms=anchor),
            action="test",
        )
        result = svc.compute_next_run(job, now_ms=now)
        base = anchor + 3 * 60_000  # Without jitter
        assert result is not None
        assert result >= base  # Jitter is forward (positive)

    def test_jitter_disabled(self, tmp_path: Path) -> None:
        """With jitter disabled, next_run should be exact."""
        svc = SchedulerService(
            store_path=tmp_path / "jobs.json",
            enable_jitter=False,
        )
        anchor = 1_000_000.0
        now = anchor + 150_000
        job = ScheduledJob(
            job_id="jitter-off",
            name="test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000, anchor_ms=anchor),
            action="test",
        )
        result = svc.compute_next_run(job, now_ms=now)
        assert result == anchor + 3 * 60_000

    def test_at_no_jitter(self, tmp_path: Path) -> None:
        """AT jobs should never be jittered."""
        svc = SchedulerService(
            store_path=tmp_path / "jobs.json",
            enable_jitter=True,
        )
        at_time = 2_000_000.0
        job = ScheduledJob(
            job_id="at-test",
            name="test",
            schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_time),
            action="test",
        )
        result = svc.compute_next_run(job, now_ms=1_500_000.0)
        assert result == at_time  # Exact, no jitter

    def test_cron_jitter(self, tmp_path: Path) -> None:
        """CRON jobs should get jitter when enabled."""
        svc = SchedulerService(
            store_path=tmp_path / "jobs.json",
            enable_jitter=True,
        )
        job = ScheduledJob(
            job_id="cron-jitter",
            name="test",
            schedule=Schedule(kind=ScheduleKind.CRON, cron_expr="* * * * *"),
            action="test",
        )
        now = 1_000_000.0
        result = svc.compute_next_run(job, now_ms=now)
        base_no_jitter = now + (60_000 - now % 60_000)
        assert result is not None
        assert result >= base_no_jitter
