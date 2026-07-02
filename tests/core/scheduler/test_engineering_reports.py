"""PR-MEMORY-LIFECYCLE — scheduled read-only engineering report collectors.

Each collector runs on fixture data and must write
``.geode/reports/<job>/<date>.md`` + return a summary string. Registration
pins the exec-hardening shape: callback path only (no action prompt → no
AgenticLoop/ToolExecutor), ``budget_usd=0.0``, disabled by default.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from core.scheduler.engineering_reports import (
    ENGINEERING_REPORT_JOBS,
    dependency_drift_report,
    docs_link_report,
    register_engineering_report_jobs,
    runtime_warning_triage,
    todo_aging_report,
)
from core.scheduler.models import Schedule, ScheduledJob, ScheduleKind
from core.scheduler.serialization import _job_from_dict, _job_to_dict
from core.scheduler.service import SchedulerService

_NOW = datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)
_DATE = "2026-07-03"


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 — fixture repo setup, argv from test constants
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607  # nosec B607
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def git_root(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


class TestTodoAgingReport:
    def test_counts_markers_and_writes_report(self, git_root: Path):
        (git_root / "mod.py").write_text(
            "# TODO fix scheduling edge\nx = 1  # FIXME drop legacy path\n",
            encoding="utf-8",
        )
        _git(git_root, "add", ".")
        _git(git_root, "commit", "-q", "-m", "add module")

        summary = todo_aging_report(git_root, now=_NOW)
        report = git_root / ".geode" / "reports" / "todo_aging_report" / f"{_DATE}.md"
        assert report.is_file()
        body = report.read_text(encoding="utf-8")
        assert "Total markers: 2" in body
        assert "| age bucket | count |" in body
        assert "`mod.py:1`" in body
        assert "2 markers" in summary and str(report) in summary

    def test_zero_markers_is_ok(self, git_root: Path):
        (git_root / "clean.py").write_text("x = 1\n", encoding="utf-8")
        _git(git_root, "add", ".")
        _git(git_root, "commit", "-q", "-m", "clean")
        summary = todo_aging_report(git_root, now=_NOW)
        assert "0 markers" in summary


class TestDependencyDriftReport:
    def test_first_run_establishes_baseline(self, tmp_path: Path):
        (tmp_path / "uv.lock").write_text(
            '[[package]]\nname = "foo"\nversion = "1.0.0"\n', encoding="utf-8"
        )
        summary = dependency_drift_report(tmp_path, now=_NOW)
        report = tmp_path / ".geode" / "reports" / "dependency_drift_report" / f"{_DATE}.md"
        assert report.is_file()
        assert "First run — baseline snapshot established" in report.read_text(encoding="utf-8")
        assert "+0/-0/~0" in summary

    def test_second_run_detects_drift(self, tmp_path: Path):
        (tmp_path / "uv.lock").write_text(
            '[[package]]\nname = "foo"\nversion = "1.0.0"\n', encoding="utf-8"
        )
        dependency_drift_report(tmp_path, now=_NOW)
        (tmp_path / "uv.lock").write_text(
            '[[package]]\nname = "foo"\nversion = "2.0.0"\n\n'
            '[[package]]\nname = "bar"\nversion = "0.1"\n',
            encoding="utf-8",
        )
        summary = dependency_drift_report(tmp_path, now=_NOW)
        report = tmp_path / ".geode" / "reports" / "dependency_drift_report" / f"{_DATE}.md"
        body = report.read_text(encoding="utf-8")
        assert "- added: `bar` 0.1" in body
        assert "- changed: `foo` 1.0.0 -> 2.0.0" in body
        assert "+1/-0/~1" in summary

    def test_missing_lockfile_fails_loud(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            dependency_drift_report(tmp_path, now=_NOW)


class TestDocsLinkReport:
    def test_skips_honestly_when_script_missing(self, tmp_path: Path):
        summary = docs_link_report(tmp_path, now=_NOW)
        report = tmp_path / ".geode" / "reports" / "docs_link_report" / f"{_DATE}.md"
        assert report.is_file()
        assert "SKIPPED" in summary
        assert "does not exist" in report.read_text(encoding="utf-8")

    def test_pass_and_fail_capture_exit_code(self, tmp_path: Path):
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        checker = scripts / "check_docs_links.py"

        checker.write_text("print('all 42 links ok')\n", encoding="utf-8")
        summary = docs_link_report(tmp_path, now=_NOW)
        report = tmp_path / ".geode" / "reports" / "docs_link_report" / f"{_DATE}.md"
        assert "PASS" in summary
        assert "all 42 links ok" in report.read_text(encoding="utf-8")

        checker.write_text(
            "import sys\nprint('broken: /docs/nope')\nsys.exit(1)\n", encoding="utf-8"
        )
        summary = docs_link_report(tmp_path, now=_NOW)
        assert "FAIL (exit 1)" in summary
        assert "broken: /docs/nope" in report.read_text(encoding="utf-8")


class TestRuntimeWarningTriage:
    def test_groups_warnings_by_logger(self, tmp_path: Path):
        log_file = tmp_path / "serve.log"
        log_file.write_text(
            "2026-07-01 23:05:16,235 core.llm.adapters.codex_oauth WARNING empty output\n"
            "2026-07-01 23:05:17,000 core.wiring.bootstrap WARNING LLM call slow\n"
            "2026-07-01 23:05:18,000 core.wiring.bootstrap WARNING LLM call slow again\n"
            "2026-07-01 23:05:19,000 core.foo INFO all fine\n",
            encoding="utf-8",
        )
        summary = runtime_warning_triage(tmp_path, log_path=log_file, now=_NOW)
        report = tmp_path / ".geode" / "reports" / "runtime_warning_triage" / f"{_DATE}.md"
        body = report.read_text(encoding="utf-8")
        assert "| `core.wiring.bootstrap` | 2 |" in body
        assert "| `core.llm.adapters.codex_oauth` | 1 |" in body
        assert "core.foo" not in body  # INFO lines are not triaged
        assert "3 warnings across 2 loggers" in summary

    def test_missing_log_file_reports_honestly(self, tmp_path: Path):
        summary = runtime_warning_triage(tmp_path, log_path=tmp_path / "absent.log", now=_NOW)
        report = tmp_path / ".geode" / "reports" / "runtime_warning_triage" / f"{_DATE}.md"
        assert "does not exist" in report.read_text(encoding="utf-8")
        assert "0 warnings" in summary

    def test_tail_respects_max_lines(self, tmp_path: Path):
        log_file = tmp_path / "serve.log"
        old = "2026-07-01 00:00:00,000 core.old WARNING ancient\n" * 50
        new = "2026-07-01 23:59:59,000 core.new WARNING recent\n" * 5
        log_file.write_text(old + new, encoding="utf-8")
        runtime_warning_triage(tmp_path, log_path=log_file, max_lines=5, now=_NOW)
        report = tmp_path / ".geode" / "reports" / "runtime_warning_triage" / f"{_DATE}.md"
        body = report.read_text(encoding="utf-8")
        assert "core.new" in body
        assert "core.old" not in body


# ---------------------------------------------------------------------------
# Registration — schedulable job types on the existing machinery
# ---------------------------------------------------------------------------


class TestRegistration:
    def _service(self, tmp_path: Path) -> SchedulerService:
        return SchedulerService(
            store_path=tmp_path / "jobs.json",
            log_dir=tmp_path / "logs",
            enable_jitter=False,
        )

    def test_registers_four_readonly_callback_jobs(self, tmp_path: Path):
        svc = self._service(tmp_path)
        registered = register_engineering_report_jobs(svc, project_root=tmp_path)
        assert len(registered) == len(ENGINEERING_REPORT_JOBS) == 4
        for spec in ENGINEERING_REPORT_JOBS:
            job = svc.get_job(spec.job_id)
            assert job is not None
            assert job.enabled is False  # opt-in via /schedule enable
            assert job.callback is not None
            # No action prompt → the AgenticLoop/ToolExecutor dispatch path
            # is unreachable; every tool is structurally denied.
            assert job.action == ""
            assert job.budget_usd == 0.0  # pure collector — no LLM calls in v1
            assert job.metadata["read_only"] is True
            assert job.metadata["denied_tools"] == "*"
            assert job.schedule.kind is ScheduleKind.CRON

    def test_registration_is_idempotent(self, tmp_path: Path):
        svc = self._service(tmp_path)
        assert len(register_engineering_report_jobs(svc, project_root=tmp_path)) == 4
        assert register_engineering_report_jobs(svc, project_root=tmp_path) == []
        assert svc.job_count == 4

    def test_run_now_executes_collector_and_writes_report(self, tmp_path: Path):
        svc = self._service(tmp_path)
        log_file = tmp_path / "serve.log"
        log_file.write_text(
            "2026-07-01 23:05:17,000 core.wiring.bootstrap WARNING slow\n", encoding="utf-8"
        )
        register_engineering_report_jobs(svc, project_root=tmp_path)
        result = svc.run_now("engineering:runtime_warning_triage")
        assert result["status"] == "ok"
        reports = list((tmp_path / ".geode" / "reports" / "runtime_warning_triage").glob("*.md"))
        assert len(reports) == 1

    def test_collector_failure_surfaces_as_job_error(self, tmp_path: Path):
        svc = self._service(tmp_path)
        register_engineering_report_jobs(svc, project_root=tmp_path)
        # dependency_drift_report fails loud without a uv.lock.
        result = svc.run_now("engineering:dependency_drift_report")
        assert result["status"] == "error"
        assert "uv.lock" in result["error"]

    def test_budget_usd_serialization_roundtrip(self):
        job = ScheduledJob(
            job_id="j1",
            name="budgeted",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=1000.0),
            action="do something",
            budget_usd=1.25,
        )
        restored = _job_from_dict(_job_to_dict(job))
        assert restored.budget_usd == 1.25
        # Legacy payloads without the field default to 0.0.
        legacy = _job_to_dict(job)
        legacy.pop("budget_usd")
        assert _job_from_dict(legacy).budget_usd == 0.0
