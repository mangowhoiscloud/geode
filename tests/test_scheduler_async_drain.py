"""Tests for async scheduled job execution via IsolatedRunner.

Verifies that the REPL drain loop dispatches isolated scheduled jobs
to background threads instead of blocking the main REPL thread.
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock

import pytest
from core.orchestration.isolated_execution import (
    IsolatedRunner,
    IsolationConfig,
)


class TestAsyncScheduledDrain:
    """Verify non-blocking dispatch of isolated scheduled jobs."""

    def test_run_async_returns_immediately(self) -> None:
        """run_async() should return a session_id without blocking."""
        runner = IsolatedRunner()
        started = time.monotonic()

        def slow_job() -> str:
            time.sleep(2.0)
            return "done"

        session_id = runner.run_async(slow_job)
        elapsed = time.monotonic() - started

        assert session_id  # non-empty string
        assert elapsed < 0.5  # must return immediately, not wait 2s

        # Wait for completion to avoid dangling threads
        for _ in range(30):
            if runner.get_result(session_id) is not None:
                break
            time.sleep(0.1)
        result = runner.get_result(session_id)
        assert result is not None
        assert result.success

    def test_multiple_async_jobs_concurrent(self) -> None:
        """Multiple async jobs should run concurrently, not sequentially."""
        runner = IsolatedRunner()
        call_times: list[float] = []
        lock = threading.Lock()

        def timed_job() -> str:
            with lock:
                call_times.append(time.monotonic())
            time.sleep(0.5)
            return "ok"

        ids = [runner.run_async(timed_job) for _ in range(3)]

        # Wait for all to complete
        for sid in ids:
            for _ in range(20):
                if runner.get_result(sid) is not None:
                    break
                time.sleep(0.1)

        # All 3 should have started within 0.2s of each other (concurrent)
        assert len(call_times) == 3
        spread = max(call_times) - min(call_times)
        assert spread < 0.3, f"Jobs started sequentially (spread={spread:.2f}s)"

    def test_async_job_result_available_after_completion(self) -> None:
        """Completed async job result should be retrievable via get_result()."""
        runner = IsolatedRunner()

        def quick_job() -> str:
            return "hello from scheduled job"

        sid = runner.run_async(quick_job)
        # Poll for result
        for _ in range(20):
            result = runner.get_result(sid)
            if result is not None:
                break
            time.sleep(0.05)

        assert result is not None
        assert result.success
        assert "hello from scheduled job" in result.output

    def test_async_job_error_captured(self) -> None:
        """Errors in async jobs should be captured, not crash the runner."""
        runner = IsolatedRunner()

        def failing_job() -> str:
            raise ValueError("scheduled job failed")

        sid = runner.run_async(failing_job)
        for _ in range(20):
            result = runner.get_result(sid)
            if result is not None:
                break
            time.sleep(0.05)

        assert result is not None
        assert not result.success
        assert "scheduled job failed" in (result.error or "")

    def test_async_job_timeout(self) -> None:
        """Jobs exceeding timeout should be marked as failed."""
        runner = IsolatedRunner()

        def stuck_job() -> str:
            time.sleep(10.0)
            return "never"

        sid = runner.run_async(
            stuck_job,
            config=IsolationConfig(timeout_s=0.5),
        )
        for _ in range(30):
            result = runner.get_result(sid)
            if result is not None:
                break
            time.sleep(0.1)

        assert result is not None
        assert not result.success
        assert "Timeout" in (result.error or "")

    def test_post_to_main_disabled(self) -> None:
        """Scheduled jobs should not post to HookSystem when post_to_main=False."""
        hooks = MagicMock()
        runner = IsolatedRunner(hooks=hooks)

        def simple_job() -> str:
            return "result"

        sid = runner.run_async(
            simple_job,
            config=IsolationConfig(post_to_main=False),
        )
        for _ in range(20):
            if runner.get_result(sid) is not None:
                break
            time.sleep(0.05)

        # HookSystem.trigger should NOT have been called with PIPELINE_END
        for call in hooks.trigger.call_args_list:
            # Allow other hook calls but not PIPELINE_END
            from core.hooks import HookEvent

            if len(call.args) >= 1 and call.args[0] == HookEvent.PIPELINE_END:
                pytest.fail("post_to_main=False should suppress PIPELINE_END hook")

    def test_queue_drain_nonblocking_pattern(self) -> None:
        """Simulate the REPL drain pattern: queue → run_async → immediate return."""
        action_queue: queue.Queue[tuple[str, str, bool]] = queue.Queue()
        runner = IsolatedRunner()

        # Enqueue 2 scheduled jobs
        action_queue.put(("job-1", "do something", True))
        action_queue.put(("job-2", "do another", True))

        dispatched: list[str] = []
        started = time.monotonic()

        # Simulate drain loop (isolated path only)
        try:
            while True:
                job_id, action, isolated = action_queue.get_nowait()
                if not action or not isolated:
                    continue

                def _run(*, _jid: str = job_id) -> str:
                    time.sleep(1.0)  # simulate LLM call
                    return f"result-{_jid}"

                runner.run_async(
                    _run,
                    config=IsolationConfig(post_to_main=False, timeout_s=10.0),
                )
                dispatched.append(job_id)
        except queue.Empty:
            pass

        drain_time = time.monotonic() - started

        # Drain should be near-instant (< 0.3s), not 2s (sequential blocking)
        assert len(dispatched) == 2
        assert drain_time < 0.5, f"Drain blocked for {drain_time:.2f}s"

        # Jobs still running in background
        assert runner.active_count >= 1
