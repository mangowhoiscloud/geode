"""Tests for IsolatedRunner — isolated execution with PostToMain delivery."""

from __future__ import annotations

import asyncio
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
        result = asyncio.run(runner.arun(lambda: "ok"))
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
        r = IsolationResult(session_id="m", success=True, metadata={"subject": "Project Atlas"})
        assert r.metadata["subject"] == "Project Atlas"


# ---------------------------------------------------------------------------
# IsolatedRunner — synchronous run
# ---------------------------------------------------------------------------


class TestIsolatedRunnerSync:
    def test_success(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(lambda: "hello world"))
        assert result.success is True
        assert result.output == "hello world"
        assert result.error is None
        assert result.duration_ms > 0

    def test_exception_captured(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(_exploding))
        assert result.success is False
        assert result.error == "boom"
        assert result.output == ""

    def test_timeout_enforced(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(timeout_s=0.1)
        result = asyncio.run(runner.arun(_slow_fn, args=(5.0,), config=cfg))
        assert result.success is False
        assert result.error is not None
        assert "Timeout" in result.error

    def test_callable_with_args(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(_greet, args=("World",)))
        assert result.success is True
        assert result.output == "Hello, World!"

    def test_callable_with_kwargs(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(_greet, args=("World",), kwargs={"greeting": "Hi"}))
        assert result.success is True
        assert result.output == "Hi, World!"

    def test_callable_returns_none(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(lambda: None))
        assert result.success is True
        assert result.output == ""

    def test_callable_returns_int(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(lambda: 42))
        assert result.success is True
        assert result.output == "42"

    def test_empty_callable_output(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(lambda: ""))
        assert result.success is True
        assert result.output == ""

    def test_custom_session_id_preserved(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(session_id="my-custom-id")
        result = asyncio.run(runner.arun(lambda: "ok", config=cfg))
        assert result.session_id == "my-custom-id"

    def test_metadata_preserved(self) -> None:
        runner = IsolatedRunner()
        cfg = IsolationConfig(metadata={"subject": "Naruto", "tier": 1})
        result = asyncio.run(runner.arun(lambda: "ok", config=cfg))
        assert result.metadata == {"subject": "Naruto", "tier": 1}

    def test_timestamps(self) -> None:
        runner = IsolatedRunner()
        before = time.time()
        result = asyncio.run(runner.arun(lambda: "fast"))
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

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_mode=PostToMainMode.SUMMARY, prefix="TestRun")
        result = asyncio.run(runner.arun(lambda: "some output", config=cfg))

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

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_mode=PostToMainMode.FULL)
        asyncio.run(runner.arun(lambda: "full output text", config=cfg))

        assert len(captured) == 1
        assert captured[0]["mode"] == "full"
        assert captured[0]["message"] == "full output text"

    def test_full_mode_truncation(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_mode=PostToMainMode.FULL, max_chars=100)
        asyncio.run(runner.arun(_large_output, args=(500,), config=cfg))

        msg = captured[0]["message"]
        assert len(msg) <= 100
        assert "truncated" in msg

    def test_post_to_main_disabled(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(post_to_main=False)
        asyncio.run(runner.arun(lambda: "no posting", config=cfg))

        assert len(captured) == 0

    def test_no_hooks_runs_fine(self) -> None:
        """Runner with no hooks should still execute and return results."""
        runner = IsolatedRunner(hooks=None)
        result = asyncio.run(runner.arun(lambda: "ok"))
        assert result.success is True
        assert result.output == "ok"

    def test_custom_prefix(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        cfg = IsolationConfig(prefix="AnalysisTask")
        asyncio.run(runner.arun(lambda: "ok", config=cfg))

        assert captured[0]["prefix"] == "AnalysisTask"

    def test_duration_in_posted_data(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        asyncio.run(runner.arun(lambda: "ok"))

        assert "duration_ms" in captured[0]
        assert captured[0]["duration_ms"] >= 0

    def test_error_result_posts(self) -> None:
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def handler(event: Any, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.SUBAGENT_COMPLETED, handler, name="capture")
        runner = IsolatedRunner(hooks=hooks)
        asyncio.run(runner.arun(_exploding))

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
# Concurrent limit (async path)
# ---------------------------------------------------------------------------


class TestConcurrentLimit:
    def test_arun_respects_global_lane(self) -> None:
        """arun must return a 'limit reached' error result once the lane is full."""
        from core.orchestration.lane_queue import Lane

        lane = Lane("global", max_concurrent=1, timeout_s=30.0)
        runner = IsolatedRunner(lane=lane)
        orig = runner.SLOT_WAIT_S
        runner.SLOT_WAIT_S = 0.1
        try:
            # Pre-fill the slot by manually acquiring (simulates an in-flight run).
            assert lane.try_acquire("blocker") is True
            result = asyncio.run(runner.arun(lambda: "over-limit"))
            assert result.success is False
            assert "full" in (result.error or "").lower() or "limit" in (result.error or "").lower()
            lane.manual_release("blocker")
        finally:
            runner.SLOT_WAIT_S = orig


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_list_active_empty(self) -> None:
        runner = IsolatedRunner()
        assert runner.list_active() == []

    def test_active_count_zero(self) -> None:
        runner = IsolatedRunner()
        assert runner.active_count == 0

    def test_run_with_default_config(self) -> None:
        runner = IsolatedRunner()
        result = asyncio.run(runner.arun(lambda: "default config"))
        assert result.success is True

    def test_hook_handler_error_doesnt_crash_runner(self) -> None:
        """If the hook handler itself raises, the runner should not crash."""
        hooks = HookSystem()

        def bad_handler(event: Any, data: dict[str, Any]) -> None:
            raise ValueError("hook exploded")

        hooks.register(HookEvent.SUBAGENT_COMPLETED, bad_handler, name="bad")
        runner = IsolatedRunner(hooks=hooks)

        # Should not raise
        result = asyncio.run(runner.arun(lambda: "ok"))
        assert result.success is True


# ---------------------------------------------------------------------------
# C3 Regression: Semaphore leak on timeout (v0.35.1 fix)
# ---------------------------------------------------------------------------


class TestSlotLeakRegression:
    """Verify lane slot release on timeout/completion (no leak)."""

    def test_timeout_releases_slot_exactly_once(self) -> None:
        """After a timeout, the lane slot must be released exactly once."""
        from core.orchestration.lane_queue import Lane

        lane = Lane("global", max_concurrent=5, timeout_s=30.0)
        runner = IsolatedRunner(lane=lane)

        result = asyncio.run(
            runner.arun(
                lambda: time.sleep(5.0),
                config=IsolationConfig(timeout_s=0.1),
            )
        )

        assert not result.success
        # Lane should have 0 active (slot released)
        assert lane.active_count == 0

    def test_normal_completion_releases_slot(self) -> None:
        """Normal completion should release lane slot."""
        from core.orchestration.lane_queue import Lane

        lane = Lane("global", max_concurrent=5, timeout_s=30.0)
        runner = IsolatedRunner(lane=lane)

        result = asyncio.run(runner.arun(lambda: "fast"))

        assert result.success
        assert lane.active_count == 0
