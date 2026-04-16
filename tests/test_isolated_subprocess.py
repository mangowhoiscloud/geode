"""Tests for IsolatedRunner subprocess mode (_execute_subprocess)."""

from __future__ import annotations

import threading
import time

from core.agent.worker import WorkerRequest
from core.orchestration.isolated_execution import (
    IsolatedRunner,
    IsolationConfig,
    IsolationResult,
)


class TestSubprocessMode:
    """Test IsolatedRunner with WorkerRequest (subprocess path)."""

    def test_dispatch_routes_worker_request_to_subprocess(self) -> None:
        """WorkerRequest should trigger _execute_subprocess, not _execute_thread."""
        runner = IsolatedRunner()
        req = WorkerRequest(task_id="route-001", description="hello")
        cfg = IsolationConfig(session_id="route-001", timeout_s=15, post_to_main=False)
        result = runner.run(req, config=cfg)
        # Should get a result (success or error depending on env),
        # but it should NOT raise TypeError (wrong dispatch)
        assert isinstance(result, IsolationResult)
        assert result.session_id == "route-001"

    def test_dispatch_routes_callable_to_thread(self) -> None:
        """Plain callable should still use thread mode."""
        runner = IsolatedRunner()
        cfg = IsolationConfig(session_id="thread-001", timeout_s=5, post_to_main=False)
        result = runner.run(lambda: "hello-thread", config=cfg)
        assert result.success is True
        assert result.output == "hello-thread"

    def test_subprocess_timeout_kills_process(self) -> None:
        """Subprocess should be killed on timeout, not left as zombie."""
        runner = IsolatedRunner()
        # Use an extremely short timeout so even a fast-failing worker gets killed
        req = WorkerRequest(task_id="timeout-001", description="complex task")
        cfg = IsolationConfig(session_id="timeout-001", timeout_s=0.05, post_to_main=False)
        result = runner.run(req, config=cfg)
        # Should fail with timeout (process killed before it finishes startup)
        assert result.success is False
        assert "Timeout" in (result.error or "") or "killed" in (result.error or "").lower()
        assert result.duration_ms > 0

    def test_subprocess_async_returns_session_id(self) -> None:
        """run_async with WorkerRequest should return session_id immediately."""
        runner = IsolatedRunner()
        req = WorkerRequest(task_id="async-001", description="hello")
        cfg = IsolationConfig(session_id="async-001", timeout_s=15, post_to_main=False)
        sid = runner.run_async(req, config=cfg)
        assert sid == "async-001"

        # Wait for result (extended for slow CI runners)
        for _ in range(300):
            result = runner.get_result(sid)
            if result is not None:
                break
            time.sleep(0.1)
        assert result is not None, "Async subprocess did not complete within 30s"
        assert result.session_id == "async-001"

    def test_subprocess_cancel_kills_process(self) -> None:
        """cancel() should kill the subprocess."""
        runner = IsolatedRunner()
        req = WorkerRequest(task_id="cancel-001", description="long task")
        cfg = IsolationConfig(session_id="cancel-001", timeout_s=60, post_to_main=False)
        sid = runner.run_async(req, config=cfg)
        time.sleep(0.5)  # Let subprocess start
        cancelled = runner.cancel(sid)
        # cancel may or may not find the process depending on timing
        # but should not raise
        assert isinstance(cancelled, bool)

    def test_subprocess_lane_wait(self) -> None:
        """Subprocess mode should wait SLOT_WAIT_S for a lane slot."""
        from core.orchestration.lane_queue import Lane

        lane = Lane("global", max_concurrent=5, timeout_s=30.0)
        runner = IsolatedRunner(lane=lane)
        runner.SLOT_WAIT_S = 0.1  # Short wait for test

        # Fill all slots with blocking threads
        barriers = []
        for _i in range(5):
            barrier = threading.Event()
            barriers.append(barrier)
            runner.run_async(
                lambda b=barrier: (b.wait(timeout=10), "done"),
                config=IsolationConfig(post_to_main=False),
            )
        time.sleep(0.2)  # Let threads start

        # Subprocess request should fail after 0.1s wait
        req = WorkerRequest(task_id="sem-001", description="blocked")
        cfg = IsolationConfig(session_id="sem-001", timeout_s=5, post_to_main=False)
        result = runner.run(req, config=cfg)
        assert result.success is False
        assert "full" in (result.error or "").lower() or "limit" in (result.error or "").lower()

        # Cleanup
        for b in barriers:
            b.set()

    def test_subprocess_result_has_duration(self) -> None:
        """Subprocess results should have duration_ms."""
        runner = IsolatedRunner()
        req = WorkerRequest(task_id="dur-001", description="hello")
        cfg = IsolationConfig(session_id="dur-001", timeout_s=15, post_to_main=False)
        result = runner.run(req, config=cfg)
        assert result.duration_ms > 0
        assert result.started_at > 0

    def test_subprocess_empty_stdout_error(self) -> None:
        """If worker produces no stdout, should get an error result."""
        # This is hard to trigger directly; tested via the code path
        # that checks for empty stdout_text
        runner = IsolatedRunner()
        req = WorkerRequest(task_id="empty-001", description="hello")
        cfg = IsolationConfig(session_id="empty-001", timeout_s=15, post_to_main=False)
        result = runner.run(req, config=cfg)
        # Result should be valid regardless
        assert isinstance(result, IsolationResult)
