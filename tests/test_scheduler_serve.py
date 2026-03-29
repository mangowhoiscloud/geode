"""Tests for scheduler integration in geode serve.

Verifies that the _drain_scheduler_queue() helper works correctly for both
serve mode (force_isolated=True) and REPL mode (force_isolated=False), and
that the SchedulerService lifecycle (init/load/save/stop) is correct.
"""

from __future__ import annotations

import queue
import threading
from unittest.mock import MagicMock

import pytest
from core.cli import _drain_scheduler_queue

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def action_queue() -> queue.Queue:
    return queue.Queue()


@pytest.fixture()
def mock_services() -> MagicMock:
    svc = MagicMock()
    mock_loop = MagicMock()
    mock_loop.run.return_value = MagicMock(text="result")
    svc.create_session.return_value = (MagicMock(), mock_loop)
    return svc


@pytest.fixture()
def mock_runner() -> MagicMock:
    runner = MagicMock()
    runner.run_async.return_value = "session-123"
    return runner


@pytest.fixture()
def semaphore() -> threading.Semaphore:
    return threading.Semaphore(2)


# ---------------------------------------------------------------------------
# _drain_scheduler_queue tests
# ---------------------------------------------------------------------------


class TestDrainSchedulerQueue:
    """Verify the shared drain helper for REPL and serve modes."""

    def test_empty_queue_returns_zero(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
        semaphore: threading.Semaphore,
    ) -> None:
        """Empty queue should drain nothing and return 0."""
        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=semaphore,
            force_isolated=True,
        )
        assert count == 0
        mock_runner.run_async.assert_not_called()

    def test_isolated_job_dispatched(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
        semaphore: threading.Semaphore,
    ) -> None:
        """Isolated job should be dispatched via runner.run_async()."""
        action_queue.put(("job-1", "do something", True))
        dispatched: list[str] = []

        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=semaphore,
            force_isolated=False,
            on_dispatch=lambda jid: dispatched.append(jid),
        )

        assert count == 1
        mock_runner.run_async.assert_called_once()
        assert dispatched == ["job-1"]

    def test_force_isolated_overrides_flag(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
        semaphore: threading.Semaphore,
    ) -> None:
        """In serve mode (force_isolated=True), non-isolated jobs run isolated."""
        action_queue.put(("job-2", "run report", False))  # isolated=False

        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=semaphore,
            force_isolated=True,  # serve mode
        )

        assert count == 1
        # Should still dispatch via runner (not main_loop)
        mock_runner.run_async.assert_called_once()

    def test_non_isolated_uses_main_loop(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
        semaphore: threading.Semaphore,
    ) -> None:
        """Non-isolated job in REPL mode should use main_loop.run()."""
        action_queue.put(("job-3", "check status", False))
        main_loop = MagicMock()
        main_runs: list[str] = []

        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=semaphore,
            force_isolated=False,
            main_loop=main_loop,
            on_main_run=lambda jid: main_runs.append(jid),
        )

        assert count == 1
        mock_runner.run_async.assert_not_called()
        main_loop.run.assert_called_once()
        assert "[scheduled-job:job-3]" in main_loop.run.call_args[0][0]
        assert main_runs == ["job-3"]

    def test_semaphore_full_skips_job(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
    ) -> None:
        """Jobs should be skipped when semaphore is exhausted."""
        sem = threading.Semaphore(0)  # zero capacity — always full
        action_queue.put(("job-4", "important task", True))
        skipped: list[str] = []

        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=sem,
            force_isolated=True,
            on_skip=lambda jid: skipped.append(jid),
        )

        assert count == 1
        mock_runner.run_async.assert_not_called()
        assert skipped == ["job-4"]

    def test_empty_action_skipped(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
        semaphore: threading.Semaphore,
    ) -> None:
        """Jobs with empty fired_action should be silently skipped."""
        action_queue.put(("job-5", "", True))

        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=semaphore,
            force_isolated=True,
        )

        assert count == 0  # empty action does not count
        mock_runner.run_async.assert_not_called()

    def test_multiple_jobs_drained(
        self,
        action_queue: queue.Queue,
        mock_services: MagicMock,
        mock_runner: MagicMock,
    ) -> None:
        """Multiple queued jobs should all be drained in one call."""
        action_queue.put(("j1", "task one", True))
        action_queue.put(("j2", "task two", True))
        action_queue.put(("j3", "task three", True))
        big_sem = threading.Semaphore(5)

        count = _drain_scheduler_queue(
            action_queue=action_queue,
            services=mock_services,
            runner=mock_runner,
            semaphore=big_sem,
            force_isolated=True,
        )

        assert count == 3
        assert mock_runner.run_async.call_count == 3
        assert action_queue.empty()


# ---------------------------------------------------------------------------
# SchedulerService lifecycle
# ---------------------------------------------------------------------------


class TestSchedulerServiceLifecycle:
    """Verify scheduler init/load/save/stop for serve mode."""

    def test_job_count_property(self) -> None:
        """job_count should reflect number of registered jobs."""
        from core.automation.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        svc = SchedulerService()
        assert svc.job_count == 0

        job = ScheduledJob(
            job_id="test-1",
            name="Test Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60000),
            action="do something",
        )
        svc.add_job(job)
        assert svc.job_count == 1

    def test_save_and_load_roundtrip(self, tmp_path: MagicMock) -> None:
        """Jobs should persist across save/load cycle."""
        from core.automation.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService

        store = tmp_path / "jobs.json"
        svc = SchedulerService(store_path=store)

        job = ScheduledJob(
            job_id="persist-1",
            name="Persist Job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=300000),
            action="persist action",
        )
        svc.add_job(job)
        svc.save()

        svc2 = SchedulerService(store_path=store)
        svc2.load()
        assert svc2.job_count == 1

    def test_start_stop(self) -> None:
        """start()/stop() should manage the background thread."""
        from core.automation.scheduler import SchedulerService

        svc = SchedulerService()
        assert not svc.is_running

        svc.start(interval_s=999)  # long interval to avoid tick during test
        assert svc.is_running

        svc.stop()
        assert not svc.is_running

    def test_graceful_shutdown_saves(self, tmp_path: MagicMock) -> None:
        """Graceful shutdown pattern: save() then stop()."""
        from core.automation.scheduler import SchedulerService

        store = tmp_path / "jobs.json"
        svc = SchedulerService(store_path=store)
        svc.start(interval_s=999)

        # Simulate serve shutdown
        svc.save()
        svc.stop()

        assert not svc.is_running
        assert store.exists()
