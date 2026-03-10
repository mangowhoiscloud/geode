"""Tests for Advanced Scheduler — 3-type scheduling + active hours (P4)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.automation.scheduler import (
    ActiveHours,
    JobRunLog,
    Schedule,
    ScheduledJob,
    ScheduleKind,
    SchedulerService,
    _job_from_dict,
    _job_to_dict,
    _parse_hhmm,
)
from core.automation.triggers import TriggerManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_store(tmp_path: Path) -> Path:
    return tmp_path / "jobs.json"


@pytest.fixture()
def tmp_log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture()
def svc(tmp_store: Path, tmp_log_dir: Path) -> SchedulerService:
    return SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)


def _now_ms() -> float:
    return time.time() * 1000


def _make_job(
    job_id: str = "j1",
    kind: ScheduleKind = ScheduleKind.EVERY,
    *,
    every_ms: float = 60_000,
    anchor_ms: float = 0.0,
    at_ms: float = 0.0,
    cron_expr: str = "",
    callback: Any = None,
    enabled: bool = True,
    delete_after_run: bool = False,
    active_hours: ActiveHours | None = None,
    name: str = "test-job",
) -> ScheduledJob:
    return ScheduledJob(
        job_id=job_id,
        name=name,
        schedule=Schedule(
            kind=kind,
            every_ms=every_ms,
            anchor_ms=anchor_ms,
            at_ms=at_ms,
            cron_expr=cron_expr,
        ),
        enabled=enabled,
        delete_after_run=delete_after_run,
        callback=callback,
        active_hours=active_hours,
    )


# ===========================================================================
# ScheduleKind enum
# ===========================================================================


class TestScheduleKind:
    def test_all_kinds(self) -> None:
        assert len(ScheduleKind) == 3
        assert ScheduleKind.AT.value == "at"
        assert ScheduleKind.EVERY.value == "every"
        assert ScheduleKind.CRON.value == "cron"


# ===========================================================================
# _parse_hhmm helper
# ===========================================================================


class TestParseHHMM:
    def test_normal(self) -> None:
        assert _parse_hhmm("09:00") == 540
        assert _parse_hhmm("22:30") == 1350

    def test_midnight(self) -> None:
        assert _parse_hhmm("00:00") == 0

    def test_end_of_day(self) -> None:
        assert _parse_hhmm("23:59") == 1439

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid HH:MM"):
            _parse_hhmm("9am")


# ===========================================================================
# Compute next run
# ===========================================================================


class TestComputeNextRun:
    def test_at_future(self, svc: SchedulerService) -> None:
        now = _now_ms()
        job = _make_job(kind=ScheduleKind.AT, at_ms=now + 5000)
        result = svc.compute_next_run(job, now_ms=now)
        assert result == now + 5000

    def test_at_past_returns_none(self, svc: SchedulerService) -> None:
        now = _now_ms()
        job = _make_job(kind=ScheduleKind.AT, at_ms=now - 1000)
        result = svc.compute_next_run(job, now_ms=now)
        assert result is None

    def test_every_basic_interval(self, svc: SchedulerService) -> None:
        anchor = 1_000_000.0
        now = anchor + 150_000  # 2.5 intervals past anchor (interval = 60_000)
        job = _make_job(
            kind=ScheduleKind.EVERY,
            every_ms=60_000,
            anchor_ms=anchor,
        )
        result = svc.compute_next_run(job, now_ms=now)
        # Should be anchor + 3 * 60_000 = 1_180_000
        assert result == anchor + 3 * 60_000

    def test_every_anchor_drift_prevention(self, svc: SchedulerService) -> None:
        """Restarting at different offsets should converge to the same grid."""
        anchor = 1_000_000.0
        interval = 60_000.0

        # Restart at two different offsets within the same interval
        now_a = anchor + 125_000
        now_b = anchor + 145_000

        job_a = _make_job(kind=ScheduleKind.EVERY, every_ms=interval, anchor_ms=anchor)
        job_b = _make_job(kind=ScheduleKind.EVERY, every_ms=interval, anchor_ms=anchor)

        next_a = svc.compute_next_run(job_a, now_ms=now_a)
        next_b = svc.compute_next_run(job_b, now_ms=now_b)

        # Both should land on the same aligned tick
        assert next_a == next_b == anchor + 3 * interval

    def test_every_anchor_in_future(self, svc: SchedulerService) -> None:
        anchor = _now_ms() + 100_000
        job = _make_job(kind=ScheduleKind.EVERY, every_ms=60_000, anchor_ms=anchor)
        result = svc.compute_next_run(job, now_ms=_now_ms())
        assert result == anchor

    def test_every_zero_interval_returns_none(self, svc: SchedulerService) -> None:
        job = _make_job(kind=ScheduleKind.EVERY, every_ms=0)
        assert svc.compute_next_run(job) is None

    def test_every_no_anchor_uses_created_at(self, svc: SchedulerService) -> None:
        now = 500_000.0
        job = _make_job(kind=ScheduleKind.EVERY, every_ms=10_000, anchor_ms=0)
        job.created_at_ms = 490_000.0
        result = svc.compute_next_run(job, now_ms=now)
        # anchor fallback = created_at_ms = 490_000
        # elapsed = 10_000, periods = 1, next = 490_000 + 2*10_000 = 510_000
        assert result == 510_000.0

    def test_cron_returns_next_minute_boundary(self, svc: SchedulerService) -> None:
        now = 120_500.0  # Mid-second within a minute
        job = _make_job(kind=ScheduleKind.CRON, cron_expr="* * * * *")
        result = svc.compute_next_run(job, now_ms=now)
        assert result is not None
        # Should be rounded up to next full minute
        assert result % 60_000 == 0
        assert result > now


# ===========================================================================
# Active Hours
# ===========================================================================


class TestActiveHours:
    def test_unset_always_active(self, svc: SchedulerService) -> None:
        ah = ActiveHours()
        assert svc.is_within_active_hours(ah) is True

    def test_normal_range_inside(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="09:00", end="22:00")
        # 12:00 UTC -> epoch for 12:00 on 2025-01-01
        noon_ms = _epoch_ms_for_local_hm(12, 0)
        assert svc.is_within_active_hours(ah, now_ms=noon_ms) is True

    def test_normal_range_outside(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="09:00", end="17:00")
        late_ms = _epoch_ms_for_local_hm(23, 0)
        assert svc.is_within_active_hours(ah, now_ms=late_ms) is False

    def test_midnight_wrap_active_late(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="22:00", end="06:00")
        late_ms = _epoch_ms_for_local_hm(23, 30)
        assert svc.is_within_active_hours(ah, now_ms=late_ms) is True

    def test_midnight_wrap_active_early(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="22:00", end="06:00")
        early_ms = _epoch_ms_for_local_hm(3, 0)
        assert svc.is_within_active_hours(ah, now_ms=early_ms) is True

    def test_midnight_wrap_inactive_midday(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="22:00", end="06:00")
        mid_ms = _epoch_ms_for_local_hm(12, 0)
        assert svc.is_within_active_hours(ah, now_ms=mid_ms) is False

    def test_boundary_start_inclusive(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="09:00", end="17:00")
        start_ms = _epoch_ms_for_local_hm(9, 0)
        assert svc.is_within_active_hours(ah, now_ms=start_ms) is True

    def test_boundary_end_exclusive(self, svc: SchedulerService) -> None:
        ah = ActiveHours(start="09:00", end="17:00")
        end_ms = _epoch_ms_for_local_hm(17, 0)
        assert svc.is_within_active_hours(ah, now_ms=end_ms) is False


def _epoch_ms_for_local_hm(hour: int, minute: int) -> float:
    """Build epoch ms for today at a specific local HH:MM."""
    import datetime

    dt = datetime.datetime.now().replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    return dt.timestamp() * 1000


# ===========================================================================
# Job CRUD
# ===========================================================================


class TestJobCRUD:
    def test_add_and_get(self, svc: SchedulerService) -> None:
        job = _make_job()
        svc.add_job(job)
        fetched = svc.get_job("j1")
        assert fetched is not None
        assert fetched.name == "test-job"

    def test_add_duplicate_raises(self, svc: SchedulerService) -> None:
        svc.add_job(_make_job())
        with pytest.raises(ValueError, match="already exists"):
            svc.add_job(_make_job())

    def test_add_sets_created_at(self, svc: SchedulerService) -> None:
        job = _make_job()
        svc.add_job(job)
        assert job.created_at_ms > 0

    def test_add_computes_next_run(self, svc: SchedulerService) -> None:
        job = _make_job()
        svc.add_job(job)
        assert job.next_run_at_ms is not None

    def test_remove_existing(self, svc: SchedulerService) -> None:
        svc.add_job(_make_job())
        assert svc.remove_job("j1") is True
        assert svc.get_job("j1") is None

    def test_remove_missing(self, svc: SchedulerService) -> None:
        assert svc.remove_job("nonexistent") is False

    def test_update_fields(self, svc: SchedulerService) -> None:
        svc.add_job(_make_job())
        assert svc.update_job("j1", name="updated") is True
        assert svc.get_job("j1") is not None
        assert svc.get_job("j1").name == "updated"  # type: ignore[union-attr]

    def test_update_missing(self, svc: SchedulerService) -> None:
        assert svc.update_job("nope", name="x") is False

    def test_list_enabled_only(self, svc: SchedulerService) -> None:
        svc.add_job(_make_job(job_id="a", enabled=True))
        svc.add_job(_make_job(job_id="b", enabled=False))
        assert len(svc.list_jobs(include_disabled=False)) == 1

    def test_list_include_disabled(self, svc: SchedulerService) -> None:
        svc.add_job(_make_job(job_id="a", enabled=True))
        svc.add_job(_make_job(job_id="b", enabled=False))
        assert len(svc.list_jobs(include_disabled=True)) == 2

    def test_get_missing_returns_none(self, svc: SchedulerService) -> None:
        assert svc.get_job("nope") is None


# ===========================================================================
# run_now
# ===========================================================================


class TestRunNow:
    def test_run_now_success(self, svc: SchedulerService) -> None:
        calls: list[dict[str, Any]] = []
        svc.add_job(_make_job(callback=lambda d: calls.append(d)))
        result = svc.run_now("j1")
        assert result["status"] == "ok"
        assert len(calls) == 1
        assert calls[0]["job_id"] == "j1"

    def test_run_now_error(self, svc: SchedulerService) -> None:
        def _fail(_: Any) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        svc.add_job(_make_job(callback=_fail))
        result = svc.run_now("j1")
        assert result["status"] == "error"
        assert "boom" in result["error"]

    def test_run_now_missing_raises(self, svc: SchedulerService) -> None:
        with pytest.raises(KeyError, match="not found"):
            svc.run_now("nope")

    def test_run_now_updates_state(self, svc: SchedulerService) -> None:
        svc.add_job(_make_job(callback=lambda d: None))
        svc.run_now("j1")
        job = svc.get_job("j1")
        assert job is not None
        assert job.last_status == "ok"
        assert job.last_run_at_ms is not None
        assert job.last_duration_ms >= 0


# ===========================================================================
# check_due_jobs
# ===========================================================================


class TestCheckDueJobs:
    def test_every_job_fires_when_due(self, svc: SchedulerService) -> None:
        calls: list[dict[str, Any]] = []
        now = _now_ms()
        anchor = now - 5_000  # Anchor 5s ago
        job = _make_job(
            kind=ScheduleKind.EVERY,
            every_ms=10_000,
            anchor_ms=anchor,
            callback=lambda d: calls.append(d),
        )
        svc.add_job(job)
        # next_run should be anchor + 10_000 = now + 5_000
        # Advance 6s past now -> past the first tick
        results = svc.check_due_jobs(now_ms=now + 6_000)
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        assert len(calls) == 1

    def test_at_job_fires_once(self, svc: SchedulerService) -> None:
        calls: list[dict[str, Any]] = []
        at_time = _now_ms() + 1000
        job = _make_job(
            kind=ScheduleKind.AT,
            at_ms=at_time,
            callback=lambda d: calls.append(d),
        )
        svc.add_job(job)

        # First check: before due time -> no fire
        results = svc.check_due_jobs(now_ms=at_time - 500)
        assert len(results) == 0

        # Second check: after due time -> fires
        results = svc.check_due_jobs(now_ms=at_time + 500)
        assert len(results) == 1
        assert results[0]["status"] == "ok"

        # Third check: should be disabled now
        results = svc.check_due_jobs(now_ms=at_time + 1500)
        assert len(results) == 0

    def test_at_delete_after_run(self, svc: SchedulerService) -> None:
        at_time = _now_ms() + 1000
        job = _make_job(
            kind=ScheduleKind.AT,
            at_ms=at_time,
            delete_after_run=True,
            callback=lambda d: None,
        )
        svc.add_job(job)
        results = svc.check_due_jobs(now_ms=at_time + 500)
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        # Job should be gone
        assert svc.get_job("j1") is None

    def test_at_delete_after_run_only_on_success(self, svc: SchedulerService) -> None:
        at_time = _now_ms() + 1000

        def _fail(_: Any) -> None:
            msg = "fail"
            raise RuntimeError(msg)

        job = _make_job(
            kind=ScheduleKind.AT,
            at_ms=at_time,
            delete_after_run=True,
            callback=_fail,
        )
        svc.add_job(job)
        results = svc.check_due_jobs(now_ms=at_time + 500)
        assert len(results) == 1
        assert results[0]["status"] == "error"
        # Job still exists but disabled
        fetched = svc.get_job("j1")
        assert fetched is not None
        assert fetched.enabled is False

    def test_disabled_job_skipped(self, svc: SchedulerService) -> None:
        anchor = 1_000_000.0
        job = _make_job(
            kind=ScheduleKind.EVERY,
            every_ms=10_000,
            anchor_ms=anchor,
            enabled=False,
        )
        svc.add_job(job)
        results = svc.check_due_jobs(now_ms=anchor + 15_000)
        assert len(results) == 0

    def test_active_hours_blocks_execution(self, svc: SchedulerService) -> None:
        calls: list[dict[str, Any]] = []
        anchor = 1_000_000.0
        # 09:00--17:00 active hours
        ah = ActiveHours(start="09:00", end="17:00")
        job = _make_job(
            kind=ScheduleKind.EVERY,
            every_ms=10_000,
            anchor_ms=anchor,
            callback=lambda d: calls.append(d),
            active_hours=ah,
        )
        svc.add_job(job)

        # Execute at a time when localtime(now_ms/1000) is outside 09:00-17:00
        # Use 23:00 local
        outside_ms = _epoch_ms_for_local_hm(23, 0)
        # But we need the job to be "due" as well
        # Override next_run_at_ms to be in the past relative to outside_ms
        job.next_run_at_ms = outside_ms - 1000

        results = svc.check_due_jobs(now_ms=outside_ms)
        # Should be skipped
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "outside_active_hours"
        assert len(calls) == 0


# ===========================================================================
# Cron job due detection
# ===========================================================================


class TestCronDue:
    def test_cron_job_fires_on_match(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        svc = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        calls: list[dict[str, Any]] = []
        job = _make_job(
            kind=ScheduleKind.CRON,
            cron_expr="* * * * *",  # every minute
            callback=lambda d: calls.append(d),
        )
        svc.add_job(job)

        # Force _is_cron_due to return True by using "* * * * *"
        results = svc.check_due_jobs()
        assert len(results) == 1
        assert results[0]["status"] == "ok"


# ===========================================================================
# Atomic store persistence
# ===========================================================================


class TestPersistence:
    def test_save_load_roundtrip(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        svc1 = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc1.add_job(_make_job(job_id="a", name="alpha"))
        svc1.add_job(
            _make_job(
                job_id="b",
                name="beta",
                kind=ScheduleKind.AT,
                at_ms=_now_ms() + 10_000,
            ),
        )
        svc1.save()

        assert tmp_store.exists()

        svc2 = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc2.load()

        assert svc2.get_job("a") is not None
        assert svc2.get_job("a").name == "alpha"  # type: ignore[union-attr]
        assert svc2.get_job("b") is not None
        assert svc2.get_job("b").schedule.kind == ScheduleKind.AT  # type: ignore[union-attr]

    def test_save_atomic_no_tmp_left(self, tmp_store: Path, tmp_log_dir: Path) -> None:
        svc = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc.add_job(_make_job())
        svc.save()
        tmp_file = tmp_store.with_suffix(".json.tmp")
        assert not tmp_file.exists()
        assert tmp_store.exists()

    def test_load_empty_store(self, tmp_store: Path, tmp_log_dir: Path) -> None:
        svc = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc.load()  # Should not raise
        assert len(svc.list_jobs(include_disabled=True)) == 0

    def test_save_with_active_hours(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        svc1 = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        ah = ActiveHours(start="09:00", end="22:00", timezone="US/Eastern")
        svc1.add_job(_make_job(active_hours=ah))
        svc1.save()

        svc2 = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc2.load()
        job = svc2.get_job("j1")
        assert job is not None
        assert job.active_hours is not None
        assert job.active_hours.start == "09:00"
        assert job.active_hours.timezone == "US/Eastern"


# ===========================================================================
# Serialisation helpers
# ===========================================================================


class TestSerialization:
    def test_job_to_dict_and_back(self) -> None:
        ah = ActiveHours(start="10:00", end="18:00", timezone="UTC")
        job = _make_job(
            job_id="ser1",
            kind=ScheduleKind.EVERY,
            every_ms=30_000,
            anchor_ms=1_000_000,
            active_hours=ah,
        )
        job.created_at_ms = 999.0
        d = _job_to_dict(job)
        restored = _job_from_dict(d)
        assert restored.job_id == "ser1"
        assert restored.schedule.kind == ScheduleKind.EVERY
        assert restored.schedule.every_ms == 30_000
        assert restored.schedule.anchor_ms == 1_000_000
        assert restored.active_hours is not None
        assert restored.active_hours.start == "10:00"
        assert restored.created_at_ms == 999.0

    def test_job_to_dict_no_active_hours(self) -> None:
        job = _make_job()
        d = _job_to_dict(job)
        assert d["active_hours"] is None
        restored = _job_from_dict(d)
        assert restored.active_hours is None


# ===========================================================================
# Per-job JSONL run log
# ===========================================================================


class TestJobRunLog:
    def test_append_and_get(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        rl.append("j1", {"status": "ok", "ts": 1})
        rl.append("j1", {"status": "ok", "ts": 2})
        runs = rl.get_runs("j1")
        assert len(runs) == 2
        # Newest first
        assert runs[0]["ts"] == 2

    def test_get_empty(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        assert rl.get_runs("nope") == []

    def test_get_with_limit(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        for i in range(10):
            rl.append("j1", {"i": i})
        runs = rl.get_runs("j1", limit=3)
        assert len(runs) == 3
        assert runs[0]["i"] == 9

    def test_separate_files_per_job(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        rl.append("j1", {"x": 1})
        rl.append("j2", {"x": 2})
        assert (tmp_log_dir / "j1.jsonl").exists()
        assert (tmp_log_dir / "j2.jsonl").exists()
        assert rl.get_runs("j1")[0]["x"] == 1
        assert rl.get_runs("j2")[0]["x"] == 2

    def test_prune_noop_under_limit(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        rl.append("j1", {"x": 1})
        assert rl.prune("j1") == 0

    def test_prune_over_limit(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        rl.MAX_BYTES = 100  # Very small to trigger
        rl.MAX_LINES = 3
        for i in range(20):
            rl.append("j1", {"i": i, "padding": "x" * 50})
        removed = rl.prune("j1")
        assert removed > 0
        remaining = rl.get_runs("j1", limit=9999)
        assert len(remaining) == 3

    def test_prune_nonexistent(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        assert rl.prune("nope") == 0

    def test_prune_atomic(self, tmp_log_dir: Path) -> None:
        rl = JobRunLog(log_dir=tmp_log_dir)
        rl.MAX_BYTES = 100
        rl.MAX_LINES = 2
        for i in range(10):
            rl.append("j1", {"i": i, "padding": "x" * 50})
        rl.prune("j1")
        tmp_file = tmp_log_dir / "j1.jsonl.tmp"
        assert not tmp_file.exists()
        assert (tmp_log_dir / "j1.jsonl").exists()

    def test_execution_writes_run_log(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        svc = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc.add_job(_make_job(callback=lambda d: None))
        svc.run_now("j1")
        rl = JobRunLog(log_dir=tmp_log_dir)
        runs = rl.get_runs("j1")
        assert len(runs) == 1
        assert runs[0]["status"] == "ok"


# ===========================================================================
# Hook integration
# ===========================================================================


class TestHookIntegration:
    def test_fires_trigger_hook_on_execution(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        mock_hooks = MagicMock()
        svc = SchedulerService(
            store_path=tmp_store,
            log_dir=tmp_log_dir,
            hooks=mock_hooks,
        )
        svc.add_job(_make_job(callback=lambda d: None))
        svc.run_now("j1")

        mock_hooks.trigger.assert_called_once()
        call_args = mock_hooks.trigger.call_args
        from core.orchestration.hooks import HookEvent

        assert call_args[0][0] == HookEvent.TRIGGER_FIRED
        assert call_args[0][1]["job_id"] == "j1"
        assert call_args[0][1]["source"] == "scheduler"


# ===========================================================================
# Background runner
# ===========================================================================


class TestBackgroundRunner:
    def test_start_stop(self, svc: SchedulerService) -> None:
        svc.start(interval_s=0.05)
        assert svc.is_running is True
        svc.stop()
        assert svc.is_running is False

    def test_idempotent_start(self, svc: SchedulerService) -> None:
        svc.start(interval_s=0.05)
        svc.start(interval_s=0.05)  # Should not raise or create duplicate
        assert svc.is_running is True
        svc.stop()

    def test_background_executes_due_jobs(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        calls: list[dict[str, Any]] = []
        svc = SchedulerService(store_path=tmp_store, log_dir=tmp_log_dir)
        svc.add_job(
            _make_job(
                kind=ScheduleKind.CRON,
                cron_expr="* * * * *",  # every minute
                callback=lambda d: calls.append(d),
            ),
        )
        svc.start(interval_s=0.05)
        time.sleep(0.15)
        svc.stop()
        # Should have fired at least once
        assert len(calls) >= 1


# ===========================================================================
# TriggerManager composition
# ===========================================================================


class TestTriggerManagerComposition:
    def test_scheduler_with_trigger_manager(
        self,
        tmp_store: Path,
        tmp_log_dir: Path,
    ) -> None:
        """SchedulerService can be created alongside TriggerManager."""
        tm = TriggerManager()
        svc = SchedulerService(
            trigger_manager=tm,
            store_path=tmp_store,
            log_dir=tmp_log_dir,
        )
        svc.add_job(_make_job(callback=lambda d: None))
        result = svc.run_now("j1")
        assert result["status"] == "ok"
