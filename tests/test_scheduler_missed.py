"""Tests for missed task recovery."""

from __future__ import annotations

import time
from pathlib import Path

from core.automation.scheduler import (
    MISSED_TASK_GRACE_MS,
    Schedule,
    ScheduledJob,
    ScheduleKind,
    SchedulerService,
)


def _make_svc(tmp_path: Path) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "jobs.json",
        log_dir=tmp_path / "logs",
        enable_jitter=False,
    )


class TestFindMissedTasks:
    """find_missed_tasks() detection logic."""

    def test_at_missed_within_grace(self, tmp_path: Path) -> None:
        """AT job within grace window should be detected as missed."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000
        at_time = now - 1_000  # 1 second ago

        job = ScheduledJob(
            job_id="at-missed",
            name="test",
            schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_time),
            action="test action",
        )
        svc.add_job(job)

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 1
        assert missed[0].job_id == "at-missed"

    def test_at_missed_outside_grace(self, tmp_path: Path) -> None:
        """AT job outside grace window should NOT be detected."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000
        at_time = now - MISSED_TASK_GRACE_MS - 1_000  # Beyond grace

        job = ScheduledJob(
            job_id="at-old",
            name="test",
            schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_time),
            action="test action",
        )
        svc.add_job(job)

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 0

    def test_at_already_ran_not_missed(self, tmp_path: Path) -> None:
        """AT job that already ran should NOT be detected as missed."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000
        at_time = now - 1_000

        job = ScheduledJob(
            job_id="at-ran",
            name="test",
            schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_time),
            action="test action",
            last_run_at_ms=at_time,  # Already ran
        )
        svc.add_job(job)

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 0

    def test_every_missed_multiple_intervals(self, tmp_path: Path) -> None:
        """EVERY job missed by 2+ intervals should be detected."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000
        interval = 60_000.0  # 1 min
        # next_run was 3 intervals ago
        next_run = now - 3 * interval

        job = ScheduledJob(
            job_id="every-missed",
            name="test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=interval),
            action="test action",
            next_run_at_ms=next_run,
        )
        # Bypass add_job (which recomputes next_run)
        svc._jobs[job.job_id] = job

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 1

    def test_every_within_interval_not_missed(self, tmp_path: Path) -> None:
        """EVERY job within 1 interval of next_run should NOT be missed."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000
        interval = 60_000.0
        next_run = now - interval * 0.5  # Only half an interval ago

        job = ScheduledJob(
            job_id="every-ok",
            name="test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=interval),
            action="test action",
            next_run_at_ms=next_run,
        )
        svc._jobs[job.job_id] = job

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 0

    def test_cron_never_missed(self, tmp_path: Path) -> None:
        """CRON jobs should never be reported as missed."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000

        job = ScheduledJob(
            job_id="cron-skip",
            name="test",
            schedule=Schedule(kind=ScheduleKind.CRON, cron_expr="0 9 * * *"),
            action="test action",
        )
        svc.add_job(job)

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 0

    def test_disabled_job_not_missed(self, tmp_path: Path) -> None:
        """Disabled jobs should never be detected as missed."""
        svc = _make_svc(tmp_path)
        now = time.time() * 1000
        at_time = now - 1_000

        job = ScheduledJob(
            job_id="disabled",
            name="test",
            schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_time),
            action="test",
            enabled=False,
        )
        svc.add_job(job)

        missed = svc.find_missed_tasks(now_ms=now)
        assert len(missed) == 0


class TestRecoverMissedTasks:
    """recover_missed_tasks() execution logic."""

    def test_recover_executes_and_marks(self, tmp_path: Path) -> None:
        """Recovered tasks should be executed with 'recovered' flag."""
        fired: list[tuple[str, str, bool]] = []
        svc = SchedulerService(
            store_path=tmp_path / "jobs.json",
            log_dir=tmp_path / "logs",
            on_job_fired=lambda jid, act, iso: fired.append((jid, act, iso)),
            enable_jitter=False,
        )
        now = time.time() * 1000
        at_time = now - 1_000

        job = ScheduledJob(
            job_id="recover-1",
            name="test",
            schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_time),
            action="recover me",
        )
        svc.add_job(job)

        results = svc.recover_missed_tasks(now_ms=now)
        assert len(results) == 1
        assert results[0]["recovered"] is True
        assert results[0]["status"] == "ok"
        assert len(fired) == 1
        assert fired[0] == ("recover-1", "recover me", True)

    def test_recover_empty_when_none_missed(self, tmp_path: Path) -> None:
        """No missed tasks should return empty list."""
        svc = _make_svc(tmp_path)
        results = svc.recover_missed_tasks()
        assert results == []


class TestDurableFlag:
    """Session-only (durable=False) task behavior."""

    def test_non_durable_excluded_from_save(self, tmp_path: Path) -> None:
        """Non-durable jobs should not be persisted to disk."""
        svc = _make_svc(tmp_path)

        # Add durable job
        svc.add_job(ScheduledJob(
            job_id="durable-1",
            name="persist",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="persist me",
            durable=True,
        ))

        # Add non-durable (session-only) job
        svc.add_job(ScheduledJob(
            job_id="session-1",
            name="ephemeral",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="session only",
            durable=False,
        ))

        assert svc.job_count == 2
        svc.save()

        # Load in new service — only durable job should appear
        svc2 = _make_svc(tmp_path)
        svc2.load()
        assert svc2.job_count == 1
        assert svc2.get_job("durable-1") is not None
        assert svc2.get_job("session-1") is None

    def test_non_durable_survives_reload(self, tmp_path: Path) -> None:
        """Non-durable jobs should survive load() (not overwritten)."""
        svc = _make_svc(tmp_path)

        # Add durable job and save
        svc.add_job(ScheduledJob(
            job_id="d1",
            name="d",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="d",
            durable=True,
        ))
        svc.save()

        # Add non-durable job after save
        svc.add_job(ScheduledJob(
            job_id="s1",
            name="s",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="s",
            durable=False,
        ))

        assert svc.job_count == 2

        # Reload — session-only should survive
        svc.load()
        assert svc.job_count == 2
        assert svc.get_job("s1") is not None


class TestMtimeReload:
    """mtime-based file watch for external changes."""

    def test_reload_on_external_change(self, tmp_path: Path) -> None:
        """Service should reload when store file is modified externally."""
        store = tmp_path / "jobs.json"
        svc = _make_svc(tmp_path)

        # Save initial state
        svc.add_job(ScheduledJob(
            job_id="init",
            name="initial",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="init",
        ))
        svc.save()

        # Externally modify the store (simulate another process)
        import json
        data = json.loads(store.read_text())
        data["ext-1"] = {
            "job_id": "ext-1",
            "name": "external",
            "schedule": {"kind": "every", "at_ms": 0, "every_ms": 60000, "anchor_ms": 0, "cron_expr": "", "timezone": ""},
            "enabled": True,
            "delete_after_run": False,
            "durable": True,
            "action": "external job",
            "isolated": True,
            "active_hours": None,
            "metadata": {},
            "created_at_ms": 0,
            "next_run_at_ms": None,
            "last_run_at_ms": None,
            "last_status": "",
            "last_duration_ms": 0,
            "running_since_ms": None,
        }
        # Write with slightly different mtime
        import time
        time.sleep(0.01)
        store.write_text(json.dumps(data, indent=2))

        # Should detect change and reload
        reloaded = svc._reload_if_changed()
        assert reloaded
        assert svc.get_job("ext-1") is not None

    def test_no_reload_when_unchanged(self, tmp_path: Path) -> None:
        """No reload when store file hasn't changed."""
        svc = _make_svc(tmp_path)
        svc.add_job(ScheduledJob(
            job_id="stable",
            name="stable",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="stable",
        ))
        svc.save()

        reloaded = svc._reload_if_changed()
        assert not reloaded
