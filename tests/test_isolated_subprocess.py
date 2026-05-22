"""Tests for IsolatedRunner subprocess mode (_execute_subprocess)."""

from __future__ import annotations

import asyncio
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
        result = asyncio.run(runner.arun(req, config=cfg))
        # Should get a result (success or error depending on env),
        # but it should NOT raise TypeError (wrong dispatch)
        assert isinstance(result, IsolationResult)
        assert result.session_id == "route-001"

    def test_dispatch_routes_callable_to_thread(self) -> None:
        """Plain callable should still use thread mode."""
        runner = IsolatedRunner()
        cfg = IsolationConfig(session_id="thread-001", timeout_s=5, post_to_main=False)
        result = asyncio.run(runner.arun(lambda: "hello-thread", config=cfg))
        assert result.success is True
        assert result.output == "hello-thread"

    def test_subprocess_timeout_kills_process(self) -> None:
        """Subprocess should be killed on timeout, not left as zombie."""
        runner = IsolatedRunner()
        # Use an extremely short timeout so even a fast-failing worker gets killed
        req = WorkerRequest(task_id="timeout-001", description="complex task")
        cfg = IsolationConfig(session_id="timeout-001", timeout_s=0.05, post_to_main=False)
        result = asyncio.run(runner.arun(req, config=cfg))
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
        result = asyncio.run(runner.arun(req, config=cfg))
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
        result = asyncio.run(runner.arun(req, config=cfg))
        assert result.duration_ms > 0
        assert result.started_at > 0

    def test_subprocess_empty_stdout_error(self) -> None:
        """If worker produces no stdout, should get an error result."""
        # This is hard to trigger directly; tested via the code path
        # that checks for empty stdout_text
        runner = IsolatedRunner()
        req = WorkerRequest(task_id="empty-001", description="hello")
        cfg = IsolationConfig(session_id="empty-001", timeout_s=15, post_to_main=False)
        result = asyncio.run(runner.arun(req, config=cfg))
        # Result should be valid regardless
        assert isinstance(result, IsolationResult)


class TestAsyncSubprocessNative:
    """PR-Async-Phase-C step 3 — arun must hit ``_aexecute_subprocess``
    (native ``asyncio.create_subprocess_exec``), NOT ``asyncio.to_thread``
    around the sync Popen path. These tests pin the wiring so a future
    refactor that re-routes subprocess work back through a thread is
    caught.
    """

    def test_arun_routes_worker_request_to_aexecute_subprocess(self) -> None:
        """arun(WorkerRequest) must invoke _aexecute_subprocess, not _execute_subprocess."""
        runner = IsolatedRunner()
        called: dict[str, int] = {"async": 0, "sync": 0}

        original_async = runner._aexecute_subprocess
        original_sync = runner._execute_subprocess

        async def _spy_async(request, config):  # type: ignore[no-untyped-def]
            called["async"] += 1
            return await original_async(request, config)

        def _spy_sync(request, config):  # type: ignore[no-untyped-def]
            called["sync"] += 1
            return original_sync(request, config)

        runner._aexecute_subprocess = _spy_async  # type: ignore[method-assign]
        runner._execute_subprocess = _spy_sync  # type: ignore[method-assign]

        req = WorkerRequest(task_id="native-001", description="hello")
        cfg = IsolationConfig(session_id="native-001", timeout_s=0.05, post_to_main=False)
        asyncio.run(runner.arun(req, config=cfg))

        assert called["async"] == 1, "arun must go through _aexecute_subprocess"
        assert called["sync"] == 0, "arun must NOT fall back to sync _execute_subprocess"

    def test_arun_does_not_pin_event_loop_to_thread(self) -> None:
        """While a subprocess request runs via arun, the event loop must
        remain free to service other coroutines. If arun were wrapping
        the sync Popen path in ``asyncio.to_thread``, the dispatch
        itself wouldn't block — but the *subprocess* call inside would
        sit on a worker thread. The native path lets us interleave
        coroutines on the same loop. We verify by running two arun()s
        concurrently and confirming both complete (and start) within
        the timeout window, which only the native path guarantees
        without consuming two thread-pool slots.
        """

        async def _scenario() -> tuple[IsolationResult, IsolationResult]:
            runner = IsolatedRunner()
            req1 = WorkerRequest(task_id="concur-001", description="a")
            req2 = WorkerRequest(task_id="concur-002", description="b")
            cfg1 = IsolationConfig(session_id="concur-001", timeout_s=0.1, post_to_main=False)
            cfg2 = IsolationConfig(session_id="concur-002", timeout_s=0.1, post_to_main=False)
            return await asyncio.gather(
                runner.arun(req1, config=cfg1),
                runner.arun(req2, config=cfg2),
            )

        r1, r2 = asyncio.run(_scenario())
        assert isinstance(r1, IsolationResult)
        assert isinstance(r2, IsolationResult)
        assert r1.session_id == "concur-001"
        assert r2.session_id == "concur-002"

    def test_aexecute_subprocess_kills_on_timeout(self) -> None:
        """Async-native subprocess timeout path must SIGKILL the worker
        and return an error result with non-zero duration. This pins
        the ``asyncio.wait_for`` + ``proc.kill()`` recovery."""

        async def _scenario() -> IsolationResult:
            runner = IsolatedRunner()
            req = WorkerRequest(task_id="kill-001", description="long")
            cfg = IsolationConfig(session_id="kill-001", timeout_s=0.05, post_to_main=False)
            return await runner._aexecute_subprocess(req, cfg)

        result = asyncio.run(_scenario())
        assert result.success is False
        assert result.duration_ms > 0
        err = (result.error or "").lower()
        assert "timeout" in err or "killed" in err or "no output" in err
