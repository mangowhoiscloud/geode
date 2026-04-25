"""Tests for Phase 2 structural defect fixes (C3, H2, M1, M2, M3).

C3: File lock on jobs.json (fcntl.flock)
H2: Scheduler → LaneQueue (try_acquire / manual_release)
M1: Config-driven poller registration
M2: Scheduler PolicyChain (DANGEROUS tool filtering)
M3: Stuck job detection
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# C3: File lock on jobs.json
# ---------------------------------------------------------------------------


class TestC3FileLock:
    """Verify inter-process file lock on scheduler save/load."""

    def test_save_atomic_write(self, tmp_path: Path) -> None:
        """save() should atomically write job store using O_EXCL lock."""
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        store = tmp_path / "jobs.json"
        svc = SchedulerService(store_path=store, enable_jitter=False)
        svc.add_job(
            ScheduledJob(
                job_id="c3-1",
                name="Lock test",
                schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
                action="test",
            )
        )
        svc.save()

        assert store.exists()
        # Lock file is transient (O_EXCL + release), so not persisted after save
        assert not (tmp_path / "scheduled_tasks.lock").exists()

    def test_load_with_lock(self, tmp_path: Path) -> None:
        """load() should work correctly with file locking."""
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        store = tmp_path / "jobs.json"
        svc1 = SchedulerService(store_path=store, enable_jitter=False)
        svc1.add_job(
            ScheduledJob(
                job_id="c3-2",
                name="Lock load test",
                schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
                action="test",
            )
        )
        svc1.save()

        svc2 = SchedulerService(store_path=store, enable_jitter=False)
        svc2.load()
        assert svc2.job_count == 1
        assert svc2.get_job("c3-2") is not None

    def test_save_load_roundtrip_with_running_since(self, tmp_path: Path) -> None:
        """running_since_ms should persist through save/load."""
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        store = tmp_path / "jobs.json"
        svc = SchedulerService(store_path=store, enable_jitter=False)
        job = ScheduledJob(
            job_id="c3-3",
            name="Running test",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            action="test",
            running_since_ms=1000.0,
        )
        svc.add_job(job)
        svc.save()

        svc2 = SchedulerService(store_path=store, enable_jitter=False)
        svc2.load()
        loaded = svc2.get_job("c3-3")
        assert loaded is not None
        assert loaded.running_since_ms == 1000.0


# ---------------------------------------------------------------------------
# H2: Lane try_acquire / manual_release
# ---------------------------------------------------------------------------


class TestH2LaneQueue:
    """Verify Lane.try_acquire() / manual_release() for scheduler."""

    def test_try_acquire_success(self) -> None:
        from core.orchestration.lane_queue import Lane

        lane = Lane("scheduler", max_concurrent=2)
        assert lane.try_acquire("job-1")
        assert lane.active_count == 1

    def test_try_acquire_full_returns_false(self) -> None:
        from core.orchestration.lane_queue import Lane

        lane = Lane("scheduler", max_concurrent=1)
        assert lane.try_acquire("job-1")
        assert not lane.try_acquire("job-2")  # full

    def test_manual_release_frees_slot(self) -> None:
        from core.orchestration.lane_queue import Lane

        lane = Lane("scheduler", max_concurrent=1)
        assert lane.try_acquire("job-1")
        assert not lane.try_acquire("job-2")  # full
        lane.manual_release("job-1")
        assert lane.try_acquire("job-2")  # freed

    def test_active_tracking(self) -> None:
        from core.orchestration.lane_queue import Lane

        lane = Lane("scheduler", max_concurrent=3)
        lane.try_acquire("a")
        lane.try_acquire("b")
        active = lane.get_active()
        assert "a" in active
        assert "b" in active
        lane.manual_release("a")
        active = lane.get_active()
        assert "a" not in active
        assert "b" in active

    def test_stats_tracked(self) -> None:
        from core.orchestration.lane_queue import Lane

        lane = Lane("scheduler", max_concurrent=2)
        lane.try_acquire("j1")
        lane.manual_release("j1")
        stats = lane.stats.to_dict()
        assert stats["acquired"] == 1
        assert stats["released"] == 1

    def test_try_acquire_zero_capacity_tracks_timeout(self) -> None:
        from core.orchestration.lane_queue import Lane

        lane = Lane("scheduler", max_concurrent=0)
        assert not lane.try_acquire("j1")
        assert lane.stats.to_dict()["timeouts"] == 1


# ---------------------------------------------------------------------------
# M1: Config-driven poller registration
# ---------------------------------------------------------------------------


class TestM1ConfigDrivenPollers:
    """Verify config-driven poller registration."""

    def test_poller_registry_has_three_defaults(self) -> None:
        from core.lifecycle.adapters import _DEFAULT_POLLERS, _POLLER_REGISTRY

        assert set(_DEFAULT_POLLERS) == {"slack", "discord", "telegram"}
        for name in _DEFAULT_POLLERS:
            assert name in _POLLER_REGISTRY

    def test_load_poller_class_resolves(self) -> None:
        from core.lifecycle.adapters import _load_poller_class

        cls = _load_poller_class("core.server.supervised.slack_poller:SlackPoller")
        from core.server.supervised.slack_poller import SlackPoller

        assert cls is SlackPoller

    def test_load_poller_class_invalid_raises(self) -> None:
        from core.lifecycle.adapters import _load_poller_class

        with pytest.raises(ModuleNotFoundError):
            _load_poller_class("nonexistent.module:Cls")


# ---------------------------------------------------------------------------
# M2: Scheduler PolicyChain (DANGEROUS tool filtering)
# ---------------------------------------------------------------------------


class TestM2SchedulerPolicyChain:
    """Verify DANGEROUS tools are filtered in headless modes."""

    def test_headless_denied_tools_defined(self) -> None:
        from core.server.supervised.services import _HEADLESS_DENIED_TOOLS

        assert "run_bash" in _HEADLESS_DENIED_TOOLS
        assert "delegate_task" in _HEADLESS_DENIED_TOOLS

    def test_scheduler_mode_filters_dangerous(self) -> None:
        """create_session(SCHEDULER) should exclude DANGEROUS tools."""
        from core.server.supervised.services import SessionMode, SharedServices

        services = SharedServices(
            tool_handlers={
                "web_search": MagicMock(),
                "run_bash": MagicMock(),
                "delegate_task": MagicMock(),
                "memory_search": MagicMock(),
            },
            hook_system=MagicMock(),
        )

        with (
            patch("core.server.supervised.services.SharedServices._build_sub_agent_manager"),
            patch("core.agent.agentic_loop.AgenticLoop.__init__", return_value=None),
            patch("core.agent.tool_executor.ToolExecutor.__init__", return_value=None) as te_init,
            patch("core.cli.session_state.set_current_loop"),
        ):
            services.create_session(SessionMode.SCHEDULER)
            # ToolExecutor should receive filtered handlers
            call_kwargs = te_init.call_args
            handlers = call_kwargs.kwargs.get(
                "action_handlers", call_kwargs.args[0] if call_kwargs.args else {}
            )
            assert "run_bash" not in handlers
            assert "delegate_task" not in handlers
            assert "web_search" in handlers
            assert "memory_search" in handlers

    def test_repl_mode_keeps_all_tools(self) -> None:
        """create_session(REPL) should NOT filter tools."""
        from core.server.supervised.services import SessionMode, SharedServices

        services = SharedServices(
            tool_handlers={
                "web_search": MagicMock(),
                "run_bash": MagicMock(),
                "memory_search": MagicMock(),
            },
            hook_system=MagicMock(),
        )

        with (
            patch("core.server.supervised.services.SharedServices._build_sub_agent_manager"),
            patch("core.agent.agentic_loop.AgenticLoop.__init__", return_value=None),
            patch("core.agent.tool_executor.ToolExecutor.__init__", return_value=None) as te_init,
            patch("core.cli.session_state.set_current_loop"),
        ):
            services.create_session(SessionMode.REPL)
            call_kwargs = te_init.call_args
            handlers = call_kwargs.kwargs.get(
                "action_handlers", call_kwargs.args[0] if call_kwargs.args else {}
            )
            assert "run_bash" in handlers


# ---------------------------------------------------------------------------
# M3: Stuck job detection
# ---------------------------------------------------------------------------


class TestM3StuckJobDetection:
    """Verify stuck job detection in scheduler tick loop."""

    def test_detect_stuck_marks_status(self) -> None:
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        svc = SchedulerService(enable_jitter=False)
        job = ScheduledJob(
            job_id="stuck-1",
            name="Stuck Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            action="test",
            running_since_ms=1.0,  # started at epoch + 1ms
        )
        svc.add_job(job)

        # Simulate 20 minutes later
        now_ms = 1.0 + 1_200_000
        stuck = svc.detect_stuck_jobs(now_ms=now_ms)

        assert stuck == ["stuck-1"]
        assert job.last_status == "stuck"
        assert job.running_since_ms is None

    def test_not_stuck_below_threshold(self) -> None:
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        svc = SchedulerService(enable_jitter=False)
        now = time.time() * 1000
        job = ScheduledJob(
            job_id="ok-1",
            name="OK Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            action="test",
            running_since_ms=now - 1000,  # started 1s ago
        )
        svc.add_job(job)

        stuck = svc.detect_stuck_jobs(now_ms=now)
        assert stuck == []
        assert job.running_since_ms is not None  # unchanged

    def test_no_running_jobs_returns_empty(self) -> None:
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        svc = SchedulerService(enable_jitter=False)
        job = ScheduledJob(
            job_id="idle-1",
            name="Idle Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            action="test",
            running_since_ms=None,  # not running
        )
        svc.add_job(job)

        stuck = svc.detect_stuck_jobs()
        assert stuck == []

    def test_execute_job_tracks_running_since(self) -> None:
        """_execute_job should set and clear running_since_ms."""
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        svc = SchedulerService(enable_jitter=False)
        job = ScheduledJob(
            job_id="track-1",
            name="Track Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            callback=lambda d: None,
        )
        svc.add_job(job)
        svc._execute_job(job)

        # After execution, running_since_ms should be cleared
        assert job.running_since_ms is None
        assert job.last_status == "ok"

    def test_stuck_timeout_configurable(self) -> None:
        from core.scheduler.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        svc = SchedulerService(enable_jitter=False)
        svc.STUCK_TIMEOUT_MS = 5000  # 5 seconds

        now = time.time() * 1000
        job = ScheduledJob(
            job_id="short-1",
            name="Short Timeout",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            action="test",
            running_since_ms=now - 10_000,  # started 10s ago
        )
        svc.add_job(job)

        stuck = svc.detect_stuck_jobs(now_ms=now)
        assert stuck == ["short-1"]
