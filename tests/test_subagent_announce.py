"""Tests for Sub-agent Announce mechanism (OpenClaw Spawn+Announce pattern).

Validates that:
1. SubAgentResult gains an `announced` field (default False).
2. SubAgentManager._announce_result() pushes results to the announce queue.
3. drain_announced_results() retrieves and clears pending results.
4. AgenticLoop._check_announced_results() injects announcements into conversation.
5. ConversationContext.add_system_event() adds structured system messages.
6. SUBAGENT_COMPLETED hook data includes the result summary.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.agent.agentic_loop import AgenticLoop
from core.agent.conversation import ConversationContext
from core.agent.sub_agent import (
    SubAgentManager,
    SubAgentResult,
    SubTask,
    _announce_lock,
    _announce_queue,
    drain_announced_results,
)
from core.agent.tool_executor import ToolExecutor
from core.orchestration.hooks import HookEvent, HookSystem
from core.orchestration.isolated_execution import IsolatedRunner

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_announce_queue() -> Any:
    """Ensure announce queue is empty before and after each test."""
    with _announce_lock:
        _announce_queue.clear()
    yield
    with _announce_lock:
        _announce_queue.clear()


@pytest.fixture
def parent_key() -> str:
    return "ip:berserk:pipeline:parent"


@pytest.fixture
def hooks() -> HookSystem:
    return HookSystem()


@pytest.fixture
def runner() -> IsolatedRunner:
    return IsolatedRunner()


# ---------------------------------------------------------------------------
# SubAgentResult.announced field
# ---------------------------------------------------------------------------


class TestSubAgentResultAnnounced:
    """SubAgentResult has an `announced` field with default False."""

    def test_default_announced_false(self) -> None:
        result = SubAgentResult(task_id="t1", task_type="analyze")
        assert result.announced is False

    def test_announced_explicit_true(self) -> None:
        result = SubAgentResult(task_id="t1", task_type="analyze", announced=True)
        assert result.announced is True

    def test_announced_in_to_dict(self) -> None:
        result = SubAgentResult(task_id="t1", task_type="analyze", announced=True)
        d = result.to_dict()
        assert d["announced"] is True

    def test_announced_false_in_to_dict(self) -> None:
        """announced=False is a falsy value but still present (it's not None)."""
        result = SubAgentResult(task_id="t1", task_type="analyze", announced=False)
        d = result.to_dict()
        # to_dict omits None-valued fields but False is not None
        assert "announced" in d

    def test_backward_compat_existing_fields(self) -> None:
        """Existing fields remain intact after adding `announced`."""
        result = SubAgentResult(
            task_id="t1",
            task_type="search",
            status="ok",
            summary="found 3 results",
            data={"count": 3},
            duration_ms=150.0,
        )
        assert result.task_id == "t1"
        assert result.task_type == "search"
        assert result.status == "ok"
        assert result.summary == "found 3 results"
        assert result.data == {"count": 3}
        assert result.duration_ms == 150.0
        assert result.announced is False


# ---------------------------------------------------------------------------
# Announce queue module-level functions
# ---------------------------------------------------------------------------


class TestAnnounceQueue:
    """Tests for the module-level announce queue and drain_announced_results."""

    def test_drain_empty_queue(self, parent_key: str) -> None:
        results = drain_announced_results(parent_key)
        assert results == []

    def test_drain_returns_results(self, parent_key: str) -> None:
        r1 = SubAgentResult(task_id="t1", task_type="analyze", summary="done")
        r2 = SubAgentResult(task_id="t2", task_type="search", summary="found")
        with _announce_lock:
            _announce_queue[parent_key] = [r1, r2]

        results = drain_announced_results(parent_key)
        assert len(results) == 2
        assert results[0].task_id == "t1"
        assert results[1].task_id == "t2"

    def test_drain_clears_queue(self, parent_key: str) -> None:
        r1 = SubAgentResult(task_id="t1", task_type="analyze", summary="done")
        with _announce_lock:
            _announce_queue[parent_key] = [r1]

        drain_announced_results(parent_key)
        # Second drain returns empty
        assert drain_announced_results(parent_key) == []

    def test_drain_isolates_sessions(self) -> None:
        """Different parent keys have independent queues."""
        r1 = SubAgentResult(task_id="t1", task_type="analyze", summary="a")
        r2 = SubAgentResult(task_id="t2", task_type="search", summary="b")
        with _announce_lock:
            _announce_queue["parent_a"] = [r1]
            _announce_queue["parent_b"] = [r2]

        results_a = drain_announced_results("parent_a")
        results_b = drain_announced_results("parent_b")
        assert len(results_a) == 1
        assert results_a[0].task_id == "t1"
        assert len(results_b) == 1
        assert results_b[0].task_id == "t2"

    def test_drain_thread_safety(self, parent_key: str) -> None:
        """Concurrent drains from multiple threads don't lose results."""
        n = 50
        results_to_add = [
            SubAgentResult(task_id=f"t{i}", task_type="analyze", summary=f"s{i}") for i in range(n)
        ]
        with _announce_lock:
            _announce_queue[parent_key] = list(results_to_add)

        collected: list[SubAgentResult] = []
        lock = threading.Lock()

        def drain() -> None:
            drained = drain_announced_results(parent_key)
            with lock:
                collected.extend(drained)

        threads = [threading.Thread(target=drain) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All results should be drained exactly once across all threads
        assert len(collected) == n


# ---------------------------------------------------------------------------
# SubAgentManager._announce_result
# ---------------------------------------------------------------------------


class TestSubAgentManagerAnnounce:
    """Tests for SubAgentManager._announce_result()."""

    def test_announce_pushes_to_queue(self, parent_key: str, runner: IsolatedRunner) -> None:
        mgr = SubAgentManager(runner, parent_session_key=parent_key)
        result = SubAgentResult(task_id="t1", task_type="analyze", summary="done")

        mgr._announce_result(parent_key, result)

        queued = drain_announced_results(parent_key)
        assert len(queued) == 1
        assert queued[0].task_id == "t1"
        assert queued[0].announced is True

    def test_announce_marks_announced(self, parent_key: str, runner: IsolatedRunner) -> None:
        mgr = SubAgentManager(runner, parent_session_key=parent_key)
        result = SubAgentResult(task_id="t1", task_type="analyze", summary="done")
        assert result.announced is False

        mgr._announce_result(parent_key, result)
        assert result.announced is True

    def test_double_announce_prevented(self, parent_key: str, runner: IsolatedRunner) -> None:
        """Calling _announce_result twice only enqueues once."""
        mgr = SubAgentManager(runner, parent_session_key=parent_key)
        result = SubAgentResult(task_id="t1", task_type="analyze", summary="done")

        mgr._announce_result(parent_key, result)
        mgr._announce_result(parent_key, result)

        queued = drain_announced_results(parent_key)
        assert len(queued) == 1

    def test_announce_disabled_without_parent_key(self, runner: IsolatedRunner) -> None:
        """Manager without parent_session_key has announce disabled."""
        mgr = SubAgentManager(runner, parent_session_key="")
        assert mgr._announce_enabled is False

    def test_announce_enabled_with_parent_key(
        self, parent_key: str, runner: IsolatedRunner
    ) -> None:
        mgr = SubAgentManager(runner, parent_session_key=parent_key)
        assert mgr._announce_enabled is True

    def test_delegate_announces_on_completion(
        self, parent_key: str, runner: IsolatedRunner, hooks: HookSystem
    ) -> None:
        """After delegate() completes, results are announced to parent."""
        handler = MagicMock(return_value={"summary": "analysis complete", "tier": "S"})
        mgr = SubAgentManager(
            runner,
            task_handler=handler,
            timeout_s=5.0,
            hooks=hooks,
            parent_session_key=parent_key,
        )
        tasks = [SubTask(task_id="t1", description="analyze berserk", task_type="analyze")]
        mgr.delegate(tasks)

        # Results should be in announce queue
        announced = drain_announced_results(parent_key)
        assert len(announced) == 1
        assert announced[0].task_id == "t1"
        assert announced[0].announced is True

    def test_delegate_announces_failed_results(
        self, parent_key: str, runner: IsolatedRunner, hooks: HookSystem
    ) -> None:
        """Tasks with errors are also announced so parent knows about failures.

        When the handler raises, _execute_subtask catches the exception and
        returns a JSON error payload.  The IsolatedRunner still reports success
        (the function returned), but the output contains an 'error' key.
        The announce mechanism records whatever sub_result the delegate produces.
        """
        handler = MagicMock(side_effect=TimeoutError("too slow"))
        mgr = SubAgentManager(
            runner,
            task_handler=handler,
            timeout_s=5.0,
            hooks=hooks,
            parent_session_key=parent_key,
        )
        tasks = [SubTask(task_id="t-fail", description="will fail", task_type="analyze")]
        mgr.delegate(tasks)

        announced = drain_announced_results(parent_key)
        assert len(announced) == 1
        assert announced[0].task_id == "t-fail"
        assert announced[0].announced is True
        # The handler exception is caught by _execute_subtask and returned as
        # {"error": "..."} — so the IsolatedRunner reports success, but the
        # output contains the error payload. The announce still fires.
        assert announced[0].summary  # non-empty summary

    def test_delegate_multiple_tasks_all_announced(
        self, parent_key: str, runner: IsolatedRunner
    ) -> None:
        """Multiple tasks in a single delegate() call are all announced."""
        handler = MagicMock(return_value={"summary": "ok", "status": "ok"})
        mgr = SubAgentManager(
            runner, task_handler=handler, timeout_s=5.0, parent_session_key=parent_key
        )
        tasks = [
            SubTask(task_id=f"t{i}", description=f"task {i}", task_type="analyze") for i in range(3)
        ]
        mgr.delegate(tasks)

        announced = drain_announced_results(parent_key)
        assert len(announced) == 3
        announced_ids = {r.task_id for r in announced}
        assert announced_ids == {"t0", "t1", "t2"}


# ---------------------------------------------------------------------------
# SUBAGENT_COMPLETED hook includes summary
# ---------------------------------------------------------------------------


class TestHookDataSummary:
    """SUBAGENT_COMPLETED hook data includes the result summary."""

    def test_completed_hook_has_summary(
        self, parent_key: str, runner: IsolatedRunner, hooks: HookSystem
    ) -> None:
        captured: list[dict[str, Any]] = []
        hooks.register(
            HookEvent.SUBAGENT_COMPLETED,
            lambda _evt, data: captured.append(data),
            name="test_capture",
        )

        handler = MagicMock(return_value={"summary": "Berserk is S-tier", "tier": "S"})
        mgr = SubAgentManager(
            runner,
            task_handler=handler,
            timeout_s=5.0,
            hooks=hooks,
            parent_session_key=parent_key,
        )
        tasks = [SubTask(task_id="t1", description="analyze", task_type="analyze")]
        mgr.delegate(tasks)

        assert len(captured) == 1
        assert "summary" in captured[0]
        assert "Berserk" in captured[0]["summary"] or captured[0]["summary"] != ""


# ---------------------------------------------------------------------------
# ConversationContext.add_system_event
# ---------------------------------------------------------------------------


class TestConversationSystemEvent:
    """Tests for ConversationContext.add_system_event()."""

    def test_system_event_added_as_user_message(self) -> None:
        ctx = ConversationContext(max_turns=200)
        ctx.add_system_event("subagent_completed", "Task t1 done: S-tier")

        assert len(ctx.messages) == 1
        msg = ctx.messages[0]
        assert msg["role"] == "user"
        assert "[system:subagent_completed]" in msg["content"]
        assert "Task t1 done: S-tier" in msg["content"]

    def test_system_event_preserves_existing_messages(self) -> None:
        ctx = ConversationContext(max_turns=200)
        ctx.add_user_message("hello")
        ctx.add_system_event("test_event", "test content")

        assert len(ctx.messages) == 2
        assert ctx.messages[0]["content"] == "hello"
        assert "[system:test_event]" in ctx.messages[1]["content"]

    def test_system_event_format(self) -> None:
        ctx = ConversationContext(max_turns=200)
        ctx.add_system_event("my_type", "my_content")
        assert ctx.messages[0]["content"] == "[system:my_type] my_content"

    def test_system_event_trimming(self) -> None:
        """System events respect max_turns trimming."""
        ctx = ConversationContext(max_turns=2)
        for i in range(10):
            ctx.add_system_event("evt", f"event {i}")
        # max_turns * 2 = 4 messages max
        assert len(ctx.messages) <= 4


# ---------------------------------------------------------------------------
# AgenticLoop._check_announced_results
# ---------------------------------------------------------------------------


class TestAgenticLoopCheckAnnounced:
    """Tests for AgenticLoop._check_announced_results()."""

    def _make_loop(self, parent_key: str = "") -> AgenticLoop:
        ctx = ConversationContext(max_turns=200)
        executor = ToolExecutor()
        loop = AgenticLoop(
            ctx,
            executor,
            max_rounds=5,
            parent_session_key=parent_key,
        )
        return loop

    def test_no_parent_key_returns_zero(self) -> None:
        loop = self._make_loop(parent_key="")
        messages: list[dict[str, Any]] = []
        count = loop._check_announced_results(messages)
        assert count == 0

    def test_no_pending_returns_zero(self) -> None:
        loop = self._make_loop(parent_key="ip:test:pipeline")
        messages: list[dict[str, Any]] = []
        count = loop._check_announced_results(messages)
        assert count == 0

    def test_injects_announced_results(self) -> None:
        parent_key = "ip:test:pipeline"
        loop = self._make_loop(parent_key=parent_key)

        # Enqueue an announced result
        r = SubAgentResult(task_id="t1", task_type="analyze", summary="S-tier result")
        with _announce_lock:
            _announce_queue.setdefault(parent_key, []).append(r)

        messages: list[dict[str, Any]] = []
        count = loop._check_announced_results(messages)
        assert count == 1

        # Should be injected into both messages list and context
        assert len(messages) == 1
        assert "[system:subagent_completed]" in messages[0]["content"]
        assert "t1" in messages[0]["content"]
        assert "S-tier result" in messages[0]["content"]

        # Also in conversation context
        assert loop.context.turn_count >= 1

    def test_injects_multiple_results(self) -> None:
        parent_key = "ip:multi:pipeline"
        loop = self._make_loop(parent_key=parent_key)

        results = [
            SubAgentResult(task_id=f"t{i}", task_type="analyze", summary=f"result {i}")
            for i in range(3)
        ]
        with _announce_lock:
            _announce_queue[parent_key] = results

        messages: list[dict[str, Any]] = []
        count = loop._check_announced_results(messages)
        assert count == 3
        assert len(messages) == 3

    def test_failed_result_includes_error(self) -> None:
        parent_key = "ip:err:pipeline"
        loop = self._make_loop(parent_key=parent_key)

        r = SubAgentResult(
            task_id="t-err",
            task_type="search",
            status="error",
            summary="failed to search",
            error_message="API timeout",
        )
        with _announce_lock:
            _announce_queue.setdefault(parent_key, []).append(r)

        messages: list[dict[str, Any]] = []
        loop._check_announced_results(messages)

        assert len(messages) == 1
        content = messages[0]["content"]
        assert "failed" in content
        assert "API timeout" in content

    def test_drain_is_one_shot(self) -> None:
        """After _check_announced_results drains, second call returns 0."""
        parent_key = "ip:oneshot:pipeline"
        loop = self._make_loop(parent_key=parent_key)

        r = SubAgentResult(task_id="t1", task_type="analyze", summary="done")
        with _announce_lock:
            _announce_queue.setdefault(parent_key, []).append(r)

        messages: list[dict[str, Any]] = []
        count1 = loop._check_announced_results(messages)
        count2 = loop._check_announced_results(messages)
        assert count1 == 1
        assert count2 == 0


# ---------------------------------------------------------------------------
# Integration: delegate -> announce -> check
# ---------------------------------------------------------------------------


class TestAnnounceIntegration:
    """End-to-end integration: SubAgentManager delegates, announces, parent loop checks."""

    def test_full_flow(self) -> None:
        parent_key = "ip:berserk:pipeline:parent"
        handler = MagicMock(return_value={"summary": "Berserk S-tier 81.3", "tier": "S"})

        mgr = SubAgentManager(
            IsolatedRunner(),
            task_handler=handler,
            timeout_s=5.0,
            parent_session_key=parent_key,
        )

        # 1. Delegate tasks
        tasks = [SubTask(task_id="analyze-1", description="analyze Berserk", task_type="analyze")]
        mgr.delegate(tasks)

        # 2. Parent loop checks for announced results
        ctx = ConversationContext(max_turns=200)
        executor = ToolExecutor()
        loop = AgenticLoop(ctx, executor, max_rounds=5, parent_session_key=parent_key)

        messages: list[dict[str, Any]] = []
        count = loop._check_announced_results(messages)

        assert count == 1
        assert len(messages) == 1
        assert "analyze-1" in messages[0]["content"]
        assert "Berserk" in messages[0]["content"]

        # 3. Conversation context also has the event
        assert loop.context.turn_count == 1

    def test_no_announce_without_parent_key(self) -> None:
        """Manager without parent key does not populate the queue."""
        handler = MagicMock(return_value={"summary": "ok"})
        mgr = SubAgentManager(
            IsolatedRunner(),
            task_handler=handler,
            timeout_s=5.0,
            parent_session_key="",
        )
        tasks = [SubTask(task_id="t1", description="test", task_type="analyze")]
        mgr.delegate(tasks)

        # No results in any queue
        with _announce_lock:
            assert len(_announce_queue) == 0
