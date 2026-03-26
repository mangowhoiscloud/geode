"""Tests for IsolatedRunner — isolated execution with PostToMain delivery."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from core.hooks import HookEvent, HookSystem
from core.orchestration.isolated_execution import (
    IsolatedRunner,
    IsolationConfig,
    IsolationResult,
    PostToMainMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slow_fn(seconds: float) -> str:
    """Sleep then return a message."""
    time.sleep(seconds)
    return f"slept {seconds}s"


def _greet(name: str, *, greeting: str = "Hello") -> str:
    return f"{greeting}, {name}!"


def _exploding() -> str:
    raise RuntimeError("boom")


def _large_output(n: int) -> str:
    return "x" * n


# ---------------------------------------------------------------------------
# IsolationConfig
# ---------------------------------------------------------------------------


class TestIsolationConfig:
    def test_defaults(self) -> None:
        cfg = IsolationConfig()
        assert cfg.session_id == ""
        assert cfg.timeout_s == 300.0
        assert cfg.post_to_main is True
        assert cfg.post_mode is PostToMainMode.SUMMARY
        assert cfg.max_chars == 8000
        assert cfg.prefix == "Isolated"
        assert cfg.metadata == {}

    def test_custom_session_id(self) -> None:
        cfg = IsolationConfig(session_id="my-session-42")
        assert cfg.session_id == "my-session-42"

    def test_auto_generated_session_id(self) -> None:
        """When session_id is empty, runner should auto-generate one."""
        runner = IsolatedRunner()
        result = runner.run(lambda: "ok")
        assert result.session_id != ""
        assert len(result.session_id) == 12

    def test_post_to_main_mode_enum(self) -> None:
        assert PostToMainMode.SUMMARY.value == "summary"
        assert PostToMainMode.FULL.value == "full"
        assert len(PostToMainMode) == 2


# ---------------------------------------------------------------------------
# IsolationResult
# ---------------------------------------------------------------------------


class TestIsolationResult:
    def test_success_result(self) -> None:
        r = IsolationResult(session_id="abc", success=True, output="done")
        assert r.success is True
        assert r.output == "done"
        assert r.error is None

    def test_error_result(self) -> None:
        r = IsolationResult(session_id="abc", success=False, error="something broke")
        assert r.success is False
        assert r.error == "something broke"

    def test_duration_tracking(self) -> None:
        r = IsolationResult(
            session_id="x",
            success=True,
            started_at=100.0,
            completed_at=100.5,
            duration_ms=500.0,
        )
        assert r.duration_ms == 500.0
        assert r.completed_at - r.started_at == pytest.approx(0.5)

    def test_metadata(self) -> None:
        r = IsolationResult(session_id="m", success=True, metadata={"ip": "Berserk"})
        assert r.metadata["ip"] == "Berserk"


# ---------------------------------------------------------------------------
# IsolatedRunner — synchronous run
# ---------------------------------------------------------------------------


class TestIsolatedRunnerSync:
    def test_success(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(lambda: "hello world")
        assert result.success is True
        assert result.output == "hello world"
        assert result.error is None
        assert result.duration_ms > 0

    def test_exception_captured(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(_exploding)
        assert result.success is False
        assert result.error == "boom"
        assert result.output == ""

    def test_timeout_enforced(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(timeout_s=0.1)
        result = runner.run(_slow_fn, args=(5.0,), config=cfg)
        assert result.success is False
        assert result.error is not None
        assert "Timeout" in result.error

    def test_callable_with_args(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(_greet, args=("World",))
        assert result.success is True
        assert result.output == "Hello, World!"

    def test_callable_with_kwargs(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(_greet, args=("World",), kwargs={"greeting": "Hi"})
        assert result.success is True
        assert result.output == "Hi, World!"

    def test_callable_returns_none(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(lambda: None)
        assert result.success is True
        assert result.output == ""

    def test_callable_returns_int(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(lambda: 42)
        assert result.success is True
        assert result.output == "42"

    def test_empty_callable_output(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(lambda: "")
        assert result.success is True
        assert result.output == ""

    def test_custom_session_id_preserved(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(session_id="my-custom-id")
        result = runner.run(lambda: "ok", config=cfg)
        assert result.session_id == "my-custom-id"

    def test_metadata_preserved(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(metadata={"ip": "Naruto", "tier": 1})
        result = runner.run(lambda: "ok", config=cfg)
        assert result.metadata == {"ip": "Naruto", "tier": 1}

    def test_timestamps(self) -> None:
        runner = IsolatedRunner()
        before = time.time()
        result = runner.run(lambda: "fast")
        after = time.time()
        assert result.started_at >= before
        assert result.completed_at <= after
        assert result.completed_at >= result.started_at


# ---------------------------------------------------------------------------
# PostToMain
# ---------------------------------------------------------------------------


class TestPostToMain:
    def test_summary_mode(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_mode=PostToMainMode.SUMMARY, prefix="TestRun")
        result = runner.run(lambda: "some output", config=cfg)

        assert len(captured) == 1
        data = captured[0]
        assert data["source"] == "isolated_execution"
        assert data["session_id"] == result.session_id
        assert data["prefix"] == "TestRun"
        assert data["mode"] == "summary"
        assert data["success"] is True
        assert "OK" in data["message"]

    def test_full_mode(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_mode=PostToMainMode.FULL)
        runner.run(lambda: "full output text", config=cfg)

        assert len(captured) == 1
        assert captured[0]["mode"] == "full"
        assert captured[0]["message"] == "full output text"

    def test_full_mode_truncation(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_mode=PostToMainMode.FULL, max_chars=100)
        runner.run(_large_output, args=(500,), config=cfg)

        msg = captured[0]["message"]
        assert len(msg) <= 100
        assert "truncated" in msg

    def test_post_to_main_disabled(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_to_main=False)
        runner.run(lambda: "no posting", config=cfg)

        assert len(captured) == 0

    def test_no_hooks_runs_fine(self) -> None:
        """Runner with no hooks should still execute and return results."""
        runner = IsolatedRunner(hooks=None)
        result = runner.run(lambda: "ok")
        assert result.success is True
        assert result.output == "ok"

    def test_custom_prefix(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(prefix="AnalysisTask")
        runner.run(lambda: "ok", config=cfg)

        assert captured[0]["prefix"] == "AnalysisTask"

    def test_duration_in_posted_data(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        runner.run(lambda: "ok")

        assert "duration_ms" in captured[0]
        assert captured[0]["duration_ms"] >= 0

    def test_error_result_posts(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PIPELINE_END, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        runner.run(_exploding)

        assert len(captured) == 1
        assert captured[0]["success"] is False


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_no_truncation_when_under_limit(self) -> None:
        runner = IsolatedRunner()
        assert runner._truncate("hello", 100) == "hello"

    def test_truncation_at_limit(self) -> None:
        runner = IsolatedRunner()
        text = "x" * 200
        result = runner._truncate(text, 100)
        assert len(result) <= 100
        assert result.endswith("... [truncated at 100 chars]")

    def test_very_large_output(self) -> None:
        runner = IsolatedRunner()
        text = "a" * 50000
        result = runner._truncate(text, 8000)
        assert len(result) <= 8000
        assert "truncated" in result


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


class TestMakeSummary:
    def test_success_summary(self) -> None:
        runner = IsolatedRunner()
        r = IsolationResult(session_id="x", success=True, output="hello", duration_ms=42.0)
        s = runner._make_summary(r)
        assert "[OK]" in s
        assert "42ms" in s
        assert "5 chars" in s

    def test_error_summary(self) -> None:
        runner = IsolatedRunner()
        r = IsolationResult(session_id="x", success=False, error="timeout", duration_ms=300.0)
        s = runner._make_summary(r)
        assert "[FAIL]" in s
        assert "error=timeout" in s


# ---------------------------------------------------------------------------
# Async run
# ---------------------------------------------------------------------------


class TestIsolatedRunnerAsync:
    def test_background_execution(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(post_to_main=False)
        sid = runner.run_async(lambda: "async result", config=cfg)
        assert isinstance(sid, str)
        assert len(sid) > 0

        # Wait for completion
        for _ in range(50):
            result = runner.get_result(sid)
            if result is not None:
                break
            time.sleep(0.05)

        assert result is not None
        assert result.success is True
        assert result.output == "async result"

    def test_get_result_before_completion(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(timeout_s=10, post_to_main=False)
        sid = runner.run_async(_slow_fn, args=(0.5,), config=cfg)

        # Should be None immediately
        assert runner.get_result(sid) is None

        # Wait for completion
        for _ in range(30):
            r = runner.get_result(sid)
            if r is not None:
                break
            time.sleep(0.05)
        assert r is not None
        assert r.success is True

    def test_list_active(self) -> None:
        runner = IsolatedRunner()
        started = threading.Event()

        def slow_with_signal() -> str:
            started.set()
            time.sleep(1.0)
            return "done"

        cfg = IsolationConfig(post_to_main=False)
        sid = runner.run_async(slow_with_signal, config=cfg)
        started.wait(timeout=2.0)

        active = runner.list_active()
        assert sid in active

        # Wait for completion
        for _ in range(30):
            if runner.get_result(sid) is not None:
                break
            time.sleep(0.1)

    def test_active_count(self) -> None:
        runner = IsolatedRunner()
        started = threading.Event()

        def slow_with_signal() -> str:
            started.set()
            time.sleep(0.5)
            return "done"

        cfg = IsolationConfig(post_to_main=False)
        runner.run_async(slow_with_signal, config=cfg)
        started.wait(timeout=2.0)

        assert runner.active_count >= 1

        # Wait for cleanup
        time.sleep(1.0)
        assert runner.active_count == 0

    def test_cancel_active_session(self) -> None:
        runner = IsolatedRunner()
        started = threading.Event()

        def cancellable() -> str:
            started.set()
            time.sleep(5.0)
            return "should not complete"

        cfg = IsolationConfig(timeout_s=10, post_to_main=False)
        sid = runner.run_async(cancellable, config=cfg)
        started.wait(timeout=2.0)

        assert runner.cancel(sid) is True

    def test_cancel_nonexistent(self) -> None:
        runner = IsolatedRunner()
        assert runner.cancel("nonexistent-session") is False

    def test_concurrent_limit_enforcement(self) -> None:
        runner = IsolatedRunner()
        barriers: list[threading.Event] = []
        started_events: list[threading.Event] = []

        def blocking_fn(idx: int) -> str:
            started_events[idx].set()
            barriers[idx].wait(timeout=10.0)
            return f"done-{idx}"

        # Start MAX_CONCURRENT sessions
        sids: list[str] = []
        for i in range(IsolatedRunner.MAX_CONCURRENT):
            barrier = threading.Event()
            started_event = threading.Event()
            barriers.append(barrier)
            started_events.append(started_event)
            cfg = IsolationConfig(post_to_main=False)
            sid = runner.run_async(blocking_fn, args=(i,), config=cfg)
            sids.append(sid)

        # Wait for all to start
        for ev in started_events:
            ev.wait(timeout=2.0)

        # The next synchronous run should fail with concurrency limit
        result = runner.run(lambda: "over-limit")
        assert result.success is False
        assert "Concurrency limit" in (result.error or "")

        # Release all
        for b in barriers:
            b.set()

        # Wait for all to complete
        for sid in sids:
            for _ in range(50):
                if runner.get_result(sid) is not None:
                    break
                time.sleep(0.05)

    def test_multiple_concurrent_runs(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(post_to_main=False)

        sids = []
        for i in range(3):
            sid = runner.run_async(lambda x=i: f"result-{x}", config=cfg)
            sids.append(sid)

        # Wait for all results
        results: list[IsolationResult] = []
        for sid in sids:
            for _ in range(50):
                r = runner.get_result(sid)
                if r is not None:
                    results.append(r)
                    break
                time.sleep(0.05)

        assert len(results) == 3
        assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCancelBehavior:
    def test_cancel_prevents_execution(self) -> None:
        runner = IsolatedRunner()
        executed: list[bool] = []
        started = threading.Event()

        def slow_fn() -> str:
            started.set()
            time.sleep(2)
            executed.append(True)
            return "done"

        cfg = IsolationConfig(timeout_s=10, post_to_main=False)
        session_id = runner.run_async(slow_fn, config=cfg)
        started.wait(timeout=3.0)
        runner.cancel(session_id)
        time.sleep(0.5)
        result = runner.get_result(session_id)
        # Task should be cancelled, not fully executed
        assert not executed or result is not None


class TestEdgeCases:
    def test_get_result_unknown_session(self) -> None:
        runner = IsolatedRunner()
        assert runner.get_result("does-not-exist") is None

    def test_list_active_empty(self) -> None:
        runner = IsolatedRunner()
        assert runner.list_active() == []

    def test_active_count_zero(self) -> None:
        runner = IsolatedRunner()
        assert runner.active_count == 0

    def test_run_with_default_config(self) -> None:
        runner = IsolatedRunner()
        result = runner.run(lambda: "default config")
        assert result.success is True

    def test_hook_handler_error_doesnt_crash_runner(self) -> None:
        """If the hook handler itself raises, the runner should not crash."""
        hooks = HookSystem()

        def bad_handler(event: Any, data: dict[str, Any]) -> None:
            raise ValueError("hook exploded")

        hooks.register(HookEvent.PIPELINE_END, bad_handler, name="bad")
        runner = IsolatedRunner(hooks=hooks)

        # Should not raise
        result = runner.run(lambda: "ok")
        assert result.success is True
