"""Integration tests for Scheduler + NLScheduleParser + cmd_schedule wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from core.automation.nl_scheduler import NLScheduleParser
from core.automation.predefined import PREDEFINED_AUTOMATIONS
from core.automation.scheduler import (
    Schedule,
    ScheduledJob,
    ScheduleKind,
    SchedulerService,
)
from core.cli.commands import cmd_schedule

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc(tmp_path: Path) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "jobs.json",
        log_dir=tmp_path / "logs",
        enable_jitter=False,
    )


@pytest.fixture()
def parser() -> NLScheduleParser:
    return NLScheduleParser()


# ---------------------------------------------------------------------------
# NLScheduleParser -> SchedulerService integration
# ---------------------------------------------------------------------------


class TestNLToSchedulerIntegration:
    """Test that NL-parsed jobs can be added to SchedulerService."""

    def test_nl_every_job_added(self, svc: SchedulerService, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.success
        assert result.job is not None
        result.job.action = "test action"
        svc.add_job(result.job)
        assert svc.get_job(result.job.job_id) is not None
        assert result.job.schedule.kind == ScheduleKind.EVERY
        assert result.job.schedule.every_ms == 300_000

    def test_nl_cron_job_added(self, svc: SchedulerService, parser: NLScheduleParser) -> None:
        result = parser.parse("daily at 9:00")
        assert result.success
        assert result.job is not None
        result.job.action = "test action"
        svc.add_job(result.job)
        job = svc.get_job(result.job.job_id)
        assert job is not None
        assert job.schedule.kind == ScheduleKind.CRON

    def test_nl_at_job_added(self, svc: SchedulerService, parser: NLScheduleParser) -> None:
        result = parser.parse("in 30 minutes")
        assert result.success
        assert result.job is not None
        result.job.action = "test action"
        svc.add_job(result.job)
        job = svc.get_job(result.job.job_id)
        assert job is not None
        assert job.schedule.kind == ScheduleKind.AT
        assert job.delete_after_run is True

    def test_nl_active_hours_preserved(
        self, svc: SchedulerService, parser: NLScheduleParser
    ) -> None:
        result = parser.parse("every 10 minutes during 09:00-18:00")
        assert result.success
        assert result.job is not None
        result.job.action = "test action"
        svc.add_job(result.job)
        job = svc.get_job(result.job.job_id)
        assert job is not None
        assert job.active_hours is not None
        assert job.active_hours.start == "09:00"
        assert job.active_hours.end == "18:00"

    def test_nl_invalid_expression_fails(self, parser: NLScheduleParser) -> None:
        result = parser.parse("")
        assert not result.success

    def test_persist_and_reload_nl_job(
        self,
        svc: SchedulerService,
        parser: NLScheduleParser,
        tmp_path: Path,
    ) -> None:
        result = parser.parse("every 2 hours")
        assert result.success and result.job
        result.job.action = "test action"
        svc.add_job(result.job)
        svc.save()

        svc2 = SchedulerService(
            store_path=tmp_path / "jobs.json",
            log_dir=tmp_path / "logs",
            enable_jitter=False,
        )
        svc2.load()
        job = svc2.get_job(result.job.job_id)
        assert job is not None
        assert job.schedule.every_ms == 7_200_000


# ---------------------------------------------------------------------------
# Predefined templates -> SchedulerService integration
# ---------------------------------------------------------------------------


class TestPredefinedToScheduler:
    """Test that predefined templates can be registered as scheduler jobs."""

    def test_cron_templates_registered(self, svc: SchedulerService) -> None:
        for tmpl in PREDEFINED_AUTOMATIONS:
            if tmpl.enabled and not tmpl.schedule.startswith("event:"):
                job = ScheduledJob(
                    job_id=f"predefined:{tmpl.id}",
                    name=tmpl.name,
                    schedule=Schedule(kind=ScheduleKind.CRON, cron_expr=tmpl.schedule),
                    enabled=tmpl.enabled,
                    action=f"run {tmpl.id}",
                    metadata={
                        "source": "predefined",
                        "template_id": tmpl.id,
                    },
                )
                svc.add_job(job)

        jobs = svc.list_jobs(include_disabled=True)
        assert len(jobs) > 0
        assert any(j.job_id.startswith("predefined:") for j in jobs)

    def test_predefined_duplicate_raises(self, svc: SchedulerService) -> None:
        tmpl = PREDEFINED_AUTOMATIONS[0]
        job = ScheduledJob(
            job_id=f"predefined:{tmpl.id}",
            name=tmpl.name,
            schedule=Schedule(kind=ScheduleKind.CRON, cron_expr=tmpl.schedule),
            enabled=True,
            action=f"run {tmpl.id}",
        )
        svc.add_job(job)
        with pytest.raises(ValueError, match="already exists"):
            svc.add_job(job)


# ---------------------------------------------------------------------------
# cmd_schedule enhanced sub-commands
# ---------------------------------------------------------------------------


class TestCmdScheduleEnhanced:
    """Test enhanced /schedule command with create/delete/status."""

    def test_list_shows_predefined(self, svc: SchedulerService) -> None:
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Templates" in output

    def test_list_shows_dynamic_jobs(self, svc: SchedulerService) -> None:
        job = ScheduledJob(
            job_id="dynamic:test1",
            name="Test Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            enabled=True,
            action="check status",
        )
        svc.add_job(job)
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("list", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Scheduled Jobs" in output
            assert "dynamic:test1" in output

    def test_create_with_nl_expression(self, svc: SchedulerService) -> None:
        initial_count = len(svc.list_jobs(include_disabled=True))
        with patch("core.cli.cmd_schedule.console"):
            cmd_schedule(
                'create "every 5 minutes" "check system health"',
                scheduler_service=svc,
            )
        assert len(svc.list_jobs(include_disabled=True)) == initial_count + 1

    def test_create_invalid_expression(self, svc: SchedulerService) -> None:
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("create", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Usage" in output

    def test_create_without_scheduler(self) -> None:
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("create every 5 minutes", scheduler_service=None)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "not available" in output

    def test_delete_existing_job(self, svc: SchedulerService) -> None:
        job = ScheduledJob(
            job_id="del-me",
            name="To Delete",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="test action",
        )
        svc.add_job(job)
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("delete del-me", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Deleted" in output
        assert svc.get_job("del-me") is None

    def test_delete_unknown_job(self, svc: SchedulerService) -> None:
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("delete nonexistent", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "not found" in output

    def test_status_predefined(self, svc: SchedulerService) -> None:
        tmpl_id = PREDEFINED_AUTOMATIONS[0].id
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule(f"status {tmpl_id}", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Template:" in output

    def test_status_dynamic_job(self, svc: SchedulerService) -> None:
        job = ScheduledJob(
            job_id="status-job",
            name="Status Test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=300_000),
            action="check drift",
            last_status="ok",
            last_duration_ms=42.5,
        )
        svc.add_job(job)
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("status status-job", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Status Test" in output
            assert "every" in output

    def test_status_not_found(self, svc: SchedulerService) -> None:
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("status ghost", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Not found" in output

    def test_enable_dynamic_job(self, svc: SchedulerService) -> None:
        job = ScheduledJob(
            job_id="toggle-me",
            name="Toggle",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="toggle test",
            enabled=False,
        )
        svc.add_job(job)
        with patch("core.cli.cmd_schedule.console"):
            cmd_schedule("enable toggle-me", scheduler_service=svc)
        got = svc.get_job("toggle-me")
        assert got is not None
        assert got.enabled is True

    def test_disable_dynamic_job(self, svc: SchedulerService) -> None:
        job = ScheduledJob(
            job_id="toggle-me2",
            name="Toggle2",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="toggle test 2",
            enabled=True,
        )
        svc.add_job(job)
        with patch("core.cli.cmd_schedule.console"):
            cmd_schedule("disable toggle-me2", scheduler_service=svc)
        got = svc.get_job("toggle-me2")
        assert got is not None
        assert got.enabled is False

    def test_run_dynamic_job(self, svc: SchedulerService) -> None:
        callback_called: list[dict[str, Any]] = []

        def cb(data: dict[str, Any]) -> None:
            callback_called.append(data)

        job = ScheduledJob(
            job_id="run-me",
            name="Run Test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            callback=cb,
        )
        svc.add_job(job)
        with patch("core.cli.cmd_schedule.console") as mock_console:
            cmd_schedule("run run-me", scheduler_service=svc)
            output = " ".join(str(c) for c in mock_console.print.call_args_list)
            assert "Executed" in output
        assert len(callback_called) == 1
