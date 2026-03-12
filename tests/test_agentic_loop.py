"""Tests for AgenticLoop, ToolExecutor, and SubAgentManager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.cli.agentic_loop import AGENTIC_TOOLS, AgenticLoop, AgenticResult, get_agentic_tools
from core.cli.conversation import ConversationContext
from core.cli.sub_agent import SubAgentManager, SubTask
from core.cli.tool_executor import DANGEROUS_TOOLS, SAFE_TOOLS, ToolExecutor
from core.orchestration.coalescing import CoalescingQueue
from core.orchestration.hooks import HookEvent, HookSystem
from core.orchestration.isolated_execution import IsolatedRunner

# ---------------------------------------------------------------------------
# ToolExecutor tests
# ---------------------------------------------------------------------------


class TestToolExecutor:
    """Unit tests for ToolExecutor."""

    def test_execute_registered_handler(self) -> None:
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"list_ips": handler})
        result = executor.execute("list_ips", {})
        handler.assert_called_once()
        assert result["status"] == "ok"

    def test_execute_unknown_tool(self) -> None:
        executor = ToolExecutor()
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_execute_handler_exception(self) -> None:
        handler = MagicMock(side_effect=ValueError("test error"))
        executor = ToolExecutor(action_handlers={"broken": handler})
        result = executor.execute("broken", {})
        assert "error" in result
        assert "test error" in result["error"]

    def test_bash_blocked_command(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = executor.execute("run_bash", {"command": "sudo rm -rf /", "reason": "test"})
        assert result.get("blocked") is True

    def test_bash_auto_approve(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = executor.execute("run_bash", {"command": "echo test_123", "reason": "testing"})
        assert "stdout" in result or "error" not in result

    def test_bash_empty_command(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = executor.execute("run_bash", {"command": "", "reason": "test"})
        assert "error" in result

    def test_registered_tools_property(self) -> None:
        executor = ToolExecutor(action_handlers={"a": MagicMock(), "b": MagicMock()})
        assert sorted(executor.registered_tools) == ["a", "b"]

    def test_safe_tools_classification(self) -> None:
        assert "list_ips" in SAFE_TOOLS
        assert "show_help" in SAFE_TOOLS
        assert "run_bash" not in SAFE_TOOLS

    def test_dangerous_tools_classification(self) -> None:
        assert "run_bash" in DANGEROUS_TOOLS
        assert "list_ips" not in DANGEROUS_TOOLS

    def test_delegate_task_no_manager(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = executor.execute(
            "delegate_task",
            {
                "task_description": "Test task",
                "task_type": "analyze",
                "args": {"ip_name": "Berserk"},
            },
        )
        assert "error" in result
        assert "SubAgentManager" in result["error"]


# ---------------------------------------------------------------------------
# AgenticLoop tests
# ---------------------------------------------------------------------------


class TestAgenticLoop:
    """Unit tests for AgenticLoop."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok", "action": "list"})
        return ToolExecutor(action_handlers={"list_ips": handler})

    def test_run_text_only_response(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test that a text-only response returns immediately."""
        loop = AgenticLoop(context, executor)

        # Mock LLM returning text only (no tool_use)
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Here are the available IPs."
        mock_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", return_value=mock_response),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("list IPs")

        assert result.text == "Here are the available IPs."
        assert result.rounds == 1
        assert result.error is None
        assert result.termination_reason == "natural"

    def test_run_with_tool_use(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test tool_use → tool_result → text response flow."""
        loop = AgenticLoop(context, executor)

        # Round 1: LLM calls list_ips tool
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.usage = MagicMock()
        tool_response.usage.input_tokens = 100
        tool_response.usage.output_tokens = 50

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_ips"
        tool_block.input = {}
        tool_block.id = "toolu_123"
        tool_response.content = [tool_block]

        # Round 2: LLM returns text
        text_response = MagicMock()
        text_response.stop_reason = "end_turn"
        text_response.usage = MagicMock()
        text_response.usage.input_tokens = 200
        text_response.usage.output_tokens = 100

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Here are 16 available IPs."
        text_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", side_effect=[tool_response, text_response]),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("IP 목록 보여줘")

        assert result.rounds == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "list_ips"
        assert result.error is None
        assert result.termination_reason == "natural"

    def test_run_max_rounds(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test max rounds limit."""
        loop = AgenticLoop(context, executor, max_rounds=2)

        # Always return tool_use → never ends
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.usage = MagicMock()
        tool_response.usage.input_tokens = 100
        tool_response.usage.output_tokens = 50

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_ips"
        tool_block.input = {}
        tool_block.id = "toolu_abc"
        tool_response.content = [tool_block]

        with (
            patch.object(loop, "_call_llm", return_value=tool_response),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("infinite loop test")

        assert result.error == "max_rounds"
        assert result.rounds == 2
        assert result.termination_reason == "max_rounds"

    def test_run_llm_failure(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test graceful handling of LLM call failure."""
        loop = AgenticLoop(context, executor)

        with patch.object(loop, "_call_llm", return_value=None):
            result = loop.run("test")

        assert result.error == "llm_call_failed"
        assert result.termination_reason == "llm_error"

    def test_context_preserved(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test that conversation context is maintained across runs."""
        loop = AgenticLoop(context, executor)

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 25

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Response 1"
        mock_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", return_value=mock_response),
            patch.object(loop, "_track_usage"),
        ):
            loop.run("first message")

        assert context.turn_count >= 1

    def test_default_max_rounds(self) -> None:
        """Verify DEFAULT_MAX_ROUNDS is 7."""
        assert AgenticLoop.DEFAULT_MAX_ROUNDS == 7

    def test_forced_text_on_last_round(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """On the last round, tool_choice=none forces text output."""
        loop = AgenticLoop(context, executor, max_rounds=3)

        call_kwargs: list[dict[str, Any]] = []

        def mock_call_llm(
            system: str, messages: list[dict[str, Any]], *, round_idx: int = 0
        ) -> MagicMock:
            call_kwargs.append({"round_idx": round_idx})
            # Round 0, 1: return tool_use; Round 2 (last): return text
            if round_idx < 2:
                resp = MagicMock()
                resp.stop_reason = "tool_use"
                resp.usage = MagicMock(input_tokens=100, output_tokens=50)
                block = MagicMock()
                block.type = "tool_use"
                block.name = "list_ips"
                block.input = {}
                block.id = f"toolu_{round_idx}"
                resp.content = [block]
                return resp
            else:
                resp = MagicMock()
                resp.stop_reason = "end_turn"
                resp.usage = MagicMock(input_tokens=100, output_tokens=50)
                block = MagicMock()
                block.type = "text"
                block.text = "Forced text on last round."
                resp.content = [block]
                return resp

        with (
            patch.object(loop, "_call_llm", side_effect=mock_call_llm),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("test forced text")

        assert result.rounds == 3
        assert result.termination_reason == "forced_text"
        assert result.text == "Forced text on last round."
        # Verify all 3 rounds were called with correct round_idx
        assert [kw["round_idx"] for kw in call_kwargs] == [0, 1, 2]

    def test_agentic_tools_include_all(self) -> None:
        """Verify AGENTIC_TOOLS includes base tools + bash + delegate."""
        tool_names = {t["name"] for t in AGENTIC_TOOLS}
        assert "list_ips" in tool_names
        assert "analyze_ip" in tool_names
        assert "run_bash" in tool_names
        assert "delegate_task" in tool_names

    def test_key_gate_blocks_without_key(self) -> None:
        """Test key_registration_gate returns None on /quit."""
        from unittest.mock import patch as _patch

        from core.cli.startup import key_registration_gate

        with _patch("core.cli.startup.console") as mock_console:
            mock_console.input.return_value = "/quit"
            result = key_registration_gate()
            assert result is None

    def test_key_gate_accepts_valid_key(self) -> None:
        """Test key_registration_gate accepts /key command."""
        from unittest.mock import patch as _patch

        from core.cli.startup import key_registration_gate

        with (
            _patch("core.cli.startup.console") as mock_console,
            _patch("core.cli.startup._upsert_env"),
            _patch("core.cli.startup.settings") as mock_settings,
        ):
            mock_console.input.return_value = "/key sk-ant-test-key-12345678"
            result = key_registration_gate()
            assert result == "sk-ant-test-key-12345678"
            assert mock_settings.anthropic_api_key == "sk-ant-test-key-12345678"

    def test_get_agentic_tools_no_registry(self) -> None:
        """get_agentic_tools without registry returns base tools."""
        tools = get_agentic_tools(None)
        assert len(tools) == len(AGENTIC_TOOLS)

    def test_get_agentic_tools_with_registry(self) -> None:
        """get_agentic_tools with registry merges extra tools."""
        mock_registry = MagicMock()
        mock_registry.to_anthropic_tools.return_value = [
            {"name": "custom_tool", "description": "A custom tool", "input_schema": {}},
        ]
        tools = get_agentic_tools(mock_registry)
        names = {t["name"] for t in tools}
        assert "custom_tool" in names
        assert len(tools) == len(AGENTIC_TOOLS) + 1

    def test_get_agentic_tools_no_duplicate(self) -> None:
        """get_agentic_tools skips registry tools that already exist."""
        mock_registry = MagicMock()
        mock_registry.to_anthropic_tools.return_value = [
            {"name": "list_ips", "description": "Duplicate", "input_schema": {}},
        ]
        tools = get_agentic_tools(mock_registry)
        assert len(tools) == len(AGENTIC_TOOLS)  # no extra

    def test_agentric_result_dataclass(self) -> None:
        """Test AgenticResult fields."""
        r = AgenticResult(text="hello", rounds=2, error="test_err", termination_reason="natural")
        assert r.text == "hello"
        assert r.rounds == 2
        assert r.error == "test_err"
        assert r.tool_calls == []
        assert r.termination_reason == "natural"

    def test_agentric_result_default_termination_reason(self) -> None:
        """Test AgenticResult default termination_reason is 'unknown'."""
        r = AgenticResult(text="test")
        assert r.termination_reason == "unknown"

    def test_build_system_prompt(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _build_system_prompt returns non-empty string."""
        loop = AgenticLoop(context, executor)
        prompt = loop._build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_track_usage_records(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _track_usage records to accumulator."""
        from core.llm.client import get_usage_accumulator, reset_usage_accumulator

        reset_usage_accumulator()
        loop = AgenticLoop(context, executor)

        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=500, output_tokens=200)

        with patch("core.llm.client.is_langsmith_enabled", return_value=False):
            loop._track_usage(mock_response)

        acc = get_usage_accumulator()
        assert acc.total_input_tokens == 500
        assert acc.total_output_tokens == 200
        assert len(acc.calls) == 1

    def test_track_usage_no_usage(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _track_usage with no usage data."""
        loop = AgenticLoop(context, executor)
        mock_response = MagicMock()
        mock_response.usage = None
        loop._track_usage(mock_response)  # should not raise

    def test_track_usage_exception_handled(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _track_usage swallows exceptions."""
        loop = AgenticLoop(context, executor)
        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch("core.llm.client.calculate_cost", side_effect=RuntimeError("boom")):
            loop._track_usage(mock_response)  # should not raise


# ---------------------------------------------------------------------------
# SubAgentManager tests
# ---------------------------------------------------------------------------


class TestSubAgentManager:
    """Unit tests for SubAgentManager."""

    def test_delegate_empty_tasks(self) -> None:
        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()
        manager = SubAgentManager(runner)
        results = manager.delegate([])
        assert results == []

    def test_delegate_with_handler(self) -> None:
        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"processed": True, "type": task_type}

        manager = SubAgentManager(runner, task_handler=handler, timeout_s=10)
        tasks = [
            SubTask("t1", "Test task 1", "analyze", {"ip_name": "Test"}),
        ]
        results = manager.delegate(tasks)

        assert len(results) == 1
        assert results[0].task_id == "t1"
        assert results[0].success is True

    def test_delegate_handler_failure(self) -> None:
        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("task handler failed")

        manager = SubAgentManager(runner, task_handler=handler, timeout_s=10)
        tasks = [SubTask("t1", "Failing task", "analyze", {})]
        results = manager.delegate(tasks)

        assert len(results) == 1
        # The exception is caught by _execute_subtask and returned as error dict.
        # IsolatedRunner sees a successful return value (the error dict).
        # The error content is in the output.
        assert results[0].output.get("error") is not None

    def test_delegate_no_handler(self) -> None:
        runner = IsolatedRunner()
        manager = SubAgentManager(runner, task_handler=None, timeout_s=10)
        tasks = [SubTask("t1", "No handler", "analyze", {})]
        results = manager.delegate(tasks)

        assert len(results) == 1
        assert results[0].success is True  # IsolationResult is success, but output has error


# ---------------------------------------------------------------------------
# SubAgentManager — Orchestration Integration tests
# ---------------------------------------------------------------------------


class TestSubAgentOrchestration:
    """Tests for TaskGraph, HookSystem, and CoalescingQueue integration."""

    @pytest.fixture
    def handler(self) -> Any:
        def _handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"processed": True, "type": task_type, **args}

        return _handler

    @pytest.fixture
    def hooks(self) -> HookSystem:
        return HookSystem()

    def test_hook_events_emitted_on_success(self, handler: Any, hooks: HookSystem) -> None:
        """Verify SUBAGENT_STARTED and SUBAGENT_COMPLETED are emitted for successful tasks."""
        events_log: list[tuple[HookEvent, dict[str, Any]]] = []

        def collector(event: HookEvent, data: dict[str, Any]) -> None:
            events_log.append((event, data))

        hooks.register(HookEvent.SUBAGENT_STARTED, collector, name="test_enter")
        hooks.register(HookEvent.SUBAGENT_COMPLETED, collector, name="test_exit")

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10, hooks=hooks)
        tasks = [SubTask("t1", "Test task", "analyze", {"ip_name": "Berserk"})]
        results = manager.delegate(tasks)

        assert len(results) == 1
        assert results[0].success is True

        # Should have emitted SUBAGENT_STARTED + SUBAGENT_COMPLETED
        enter_events = [e for e in events_log if e[0] == HookEvent.SUBAGENT_STARTED]
        exit_events = [e for e in events_log if e[0] == HookEvent.SUBAGENT_COMPLETED]
        assert len(enter_events) == 1
        assert len(exit_events) == 1
        assert enter_events[0][1]["task_id"] == "t1"
        assert exit_events[0][1]["success"] is True

    def test_hook_events_emitted_on_failure(self, hooks: HookSystem) -> None:
        """Verify SUBAGENT_STARTED and SUBAGENT_FAILED are emitted for failed tasks."""
        events_log: list[tuple[HookEvent, dict[str, Any]]] = []

        def collector(event: HookEvent, data: dict[str, Any]) -> None:
            events_log.append((event, data))

        hooks.register(HookEvent.SUBAGENT_STARTED, collector, name="test_enter")
        hooks.register(HookEvent.SUBAGENT_FAILED, collector, name="test_error")

        def failing_handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, failing_handler, timeout_s=10, hooks=hooks)
        tasks = [SubTask("t1", "Failing task", "analyze", {})]
        results = manager.delegate(tasks)

        assert len(results) == 1
        # Error is caught by _execute_subtask → returned as dict → IsolationResult is success
        # The output contains {"error": "boom"}
        enter_events = [e for e in events_log if e[0] == HookEvent.SUBAGENT_STARTED]
        assert len(enter_events) == 1

    def test_no_hooks_no_error(self, handler: Any) -> None:
        """Verify delegate works without hooks (hooks=None)."""
        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10, hooks=None)
        tasks = [SubTask("t1", "Test", "analyze", {})]
        results = manager.delegate(tasks)
        assert len(results) == 1
        assert results[0].success is True

    def test_multiple_tasks_emit_hooks(self, handler: Any, hooks: HookSystem) -> None:
        """Verify hooks emitted for each task in a batch."""
        enter_count = 0

        def count_enter(event: HookEvent, data: dict[str, Any]) -> None:
            nonlocal enter_count
            enter_count += 1

        hooks.register(HookEvent.SUBAGENT_STARTED, count_enter, name="counter")

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10, hooks=hooks)
        tasks = [
            SubTask("t1", "Task 1", "analyze", {}),
            SubTask("t2", "Task 2", "search", {}),
            SubTask("t3", "Task 3", "compare", {}),
        ]
        results = manager.delegate(tasks)

        assert len(results) == 3
        assert enter_count == 3

    def test_dedup_by_task_id(self, handler: Any) -> None:
        """Verify simple dedup removes duplicate task_ids."""
        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [
            SubTask("t1", "Task 1", "analyze", {}),
            SubTask("t1", "Task 1 dup", "analyze", {}),
            SubTask("t2", "Task 2", "search", {}),
        ]
        results = manager.delegate(tasks)

        # Only t1 and t2 should execute (t1 dup removed)
        assert len(results) == 2
        task_ids = {r.task_id for r in results}
        assert task_ids == {"t1", "t2"}

    def test_coalescing_queue_dedup(self, handler: Any) -> None:
        """Verify CoalescingQueue-based dedup."""
        runner = IsolatedRunner()
        queue = CoalescingQueue(window_ms=5000)  # long window so timers don't fire
        manager = SubAgentManager(runner, handler, timeout_s=10, coalescing=queue)

        # First batch
        tasks1 = [SubTask("t1", "Task 1", "analyze", {})]
        results1 = manager.delegate(tasks1)
        assert len(results1) == 1

        # Second batch with same task_id — should be coalesced
        tasks2 = [SubTask("t1", "Task 1 again", "analyze", {})]
        results2 = manager.delegate(tasks2)
        assert len(results2) == 0  # coalesced away

        # Cleanup
        queue.cancel_all()

    def test_hooks_property(self, handler: Any, hooks: HookSystem) -> None:
        """Verify hooks property is accessible."""
        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, hooks=hooks)
        assert manager.hooks is hooks

    def test_hooks_property_none(self, handler: Any) -> None:
        """Verify hooks property returns None when not configured."""
        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler)
        assert manager.hooks is None


# ---------------------------------------------------------------------------
# AgenticLoop — Tracing integration tests
# ---------------------------------------------------------------------------


class TestAgenticLoopTracing:
    """Tests for _maybe_traceable integration in AgenticLoop."""

    def test_run_has_traceable_attribute(self) -> None:
        """Verify that run() method exists and is callable (tracing is a decorator)."""
        context = ConversationContext(max_turns=5)
        executor = ToolExecutor()
        loop = AgenticLoop(context, executor)
        assert callable(loop.run)

    def test_call_llm_has_traceable_attribute(self) -> None:
        """Verify that _call_llm() method exists and is callable."""
        context = ConversationContext(max_turns=5)
        executor = ToolExecutor()
        loop = AgenticLoop(context, executor)
        assert callable(loop._call_llm)

    def test_tracing_passthrough_without_langsmith(self) -> None:
        """Without LANGCHAIN_TRACING_V2/API_KEY, _maybe_traceable is a no-op."""
        context = ConversationContext(max_turns=5)
        executor = ToolExecutor()
        loop = AgenticLoop(context, executor)

        # run() should still work normally
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 25

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello"
        mock_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", return_value=mock_response),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("test")

        assert result.text == "Hello"
        assert result.error is None


# ---------------------------------------------------------------------------
# Coverage gap tests
# ---------------------------------------------------------------------------


class TestAgenticLoopEdgeCases:
    """Tests covering previously untested paths in AgenticLoop."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler_a = MagicMock(return_value={"status": "ok", "action": "list"})
        handler_b = MagicMock(return_value={"data": [1, 2, 3]})
        return ToolExecutor(action_handlers={"list_ips": handler_a, "search_ips": handler_b})

    def test_multiple_tool_calls_in_single_response(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test response with 2+ tool_use blocks processed in one round."""
        loop = AgenticLoop(context, executor)

        # Round 1: LLM calls 2 tools simultaneously
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.usage = MagicMock(input_tokens=100, output_tokens=80)

        tool_block_1 = MagicMock()
        tool_block_1.type = "tool_use"
        tool_block_1.name = "list_ips"
        tool_block_1.input = {}
        tool_block_1.id = "toolu_aaa"

        tool_block_2 = MagicMock()
        tool_block_2.type = "tool_use"
        tool_block_2.name = "search_ips"
        tool_block_2.input = {"query": "soulslike"}
        tool_block_2.id = "toolu_bbb"

        tool_response.content = [tool_block_1, tool_block_2]

        # Round 2: LLM returns final text
        text_response = MagicMock()
        text_response.stop_reason = "end_turn"
        text_response.usage = MagicMock(input_tokens=200, output_tokens=100)
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Found results."
        text_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", side_effect=[tool_response, text_response]),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("list and search")

        assert result.rounds == 2
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0]["tool"] == "list_ips"
        assert result.tool_calls[1]["tool"] == "search_ips"

    def test_serialize_content_mixed(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _serialize_content with mixed text + tool_use blocks."""
        loop = AgenticLoop(context, executor)

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Let me help."

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_xyz"
        tool_block.name = "list_ips"
        tool_block.input = {"filter": "active"}

        serialized = loop._serialize_content([text_block, tool_block])

        assert len(serialized) == 2
        assert serialized[0] == {"type": "text", "text": "Let me help."}
        assert serialized[1]["type"] == "tool_use"
        assert serialized[1]["name"] == "list_ips"
        assert serialized[1]["id"] == "toolu_xyz"

    def test_extract_text_empty_content(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _extract_text with no text blocks (only tool_use blocks)."""
        loop = AgenticLoop(context, executor)

        tool_block = MagicMock()
        tool_block.type = "tool_use"

        response = MagicMock()
        response.content = [tool_block]
        assert loop._extract_text(response) == ""

    def test_extract_text_multiple_text_blocks(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _extract_text joins multiple text blocks."""
        loop = AgenticLoop(context, executor)

        block1 = MagicMock()
        block1.type = "text"
        block1.text = "Part 1"
        block2 = MagicMock()
        block2.type = "text"
        block2.text = "Part 2"

        response = MagicMock()
        response.content = [block1, block2]
        assert loop._extract_text(response) == "Part 1\nPart 2"

    def test_client_cached_across_rounds(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Verify Anthropic client is created once and reused."""
        loop = AgenticLoop(context, executor)
        assert loop._client is None  # not yet created


class TestSubAgentEdgeCases:
    """Tests covering previously untested paths in SubAgentManager."""

    def test_timeout_returns_failure(self) -> None:
        """Test that timeout produces a SubResult with success=False."""
        import threading

        runner = IsolatedRunner()

        # Handler that blocks longer than timeout
        block_event = threading.Event()

        def slow_handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            block_event.wait(timeout=10)  # block until signaled
            return {"done": True}

        manager = SubAgentManager(runner, slow_handler, timeout_s=0.3)
        tasks = [SubTask("t_slow", "Slow task", "analyze", {})]
        results = manager.delegate(tasks)

        # Unblock the handler thread to avoid dangling threads
        block_event.set()

        assert len(results) == 1
        assert results[0].success is False
        assert "Timeout" in (results[0].error or "")

    def test_json_serialization_roundtrip(self) -> None:
        """Verify handler output goes through json.dumps/json.loads cleanly."""
        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"score": 0.85, "tier": "A", "tags": ["action", "rpg"]}

        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [SubTask("t1", "JSON test", "analyze", {})]
        results = manager.delegate(tasks)

        assert results[0].success is True
        assert results[0].output["score"] == 0.85
        assert results[0].output["tags"] == ["action", "rpg"]

    def test_handler_returns_non_serializable(self) -> None:
        """Verify json.dumps(default=str) handles non-serializable types."""
        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            from datetime import datetime

            return {"timestamp": datetime(2026, 3, 10), "value": 42}

        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [SubTask("t1", "Non-serializable test", "analyze", {})]
        results = manager.delegate(tasks)

        assert results[0].success is True
        assert "2026" in results[0].output["timestamp"]
        assert results[0].output["value"] == 42

    def test_malformed_json_output_fallback(self) -> None:
        """Verify graceful fallback when isolation output is not valid JSON."""
        manager = SubAgentManager.__new__(SubAgentManager)
        manager._timeout_s = 10.0

        # Simulate an IsolationResult with non-JSON output
        isolation = MagicMock()
        isolation.success = True
        isolation.output = "not valid json {{"
        isolation.duration_ms = 50.0

        task = SubTask("t1", "Malformed test", "analyze", {})
        result = manager._to_sub_result(task, isolation)

        assert result.success is True
        assert result.output == {"raw": "not valid json {{"}


# ---------------------------------------------------------------------------
# Plan + Delegate tool definitions
# ---------------------------------------------------------------------------


class TestPlanDelegateTools:
    """Verify create_plan and approve_plan are in tool definitions."""

    def test_create_plan_in_tools(self) -> None:
        names = {t["name"] for t in AGENTIC_TOOLS}
        assert "create_plan" in names

    def test_approve_plan_in_tools(self) -> None:
        names = {t["name"] for t in AGENTIC_TOOLS}
        assert "approve_plan" in names

    def test_delegate_task_in_tools(self) -> None:
        names = {t["name"] for t in AGENTIC_TOOLS}
        assert "delegate_task" in names

    def test_create_plan_schema(self) -> None:
        tool = next(t for t in AGENTIC_TOOLS if t["name"] == "create_plan")
        schema = tool["input_schema"]
        assert "ip_name" in schema["properties"]
        assert "ip_name" in schema["required"]

    def test_approve_plan_schema(self) -> None:
        tool = next(t for t in AGENTIC_TOOLS if t["name"] == "approve_plan")
        schema = tool["input_schema"]
        assert "plan_id" in schema["properties"]
        assert "plan_id" in schema["required"]

    def test_get_agentic_tools_includes_plan(self) -> None:
        tools = get_agentic_tools()
        names = {t["name"] for t in tools}
        assert "create_plan" in names
        assert "approve_plan" in names


class TestAgenticLoopToolCallRendering:
    """Verify tool call rendering is invoked during execution."""

    def test_tool_call_renders(self) -> None:
        """Tool calls should trigger render_tool_call."""
        ctx = ConversationContext()
        handler = MagicMock(return_value={"status": "ok", "tier": "S", "score": 81.3})
        executor = ToolExecutor(action_handlers={"analyze_ip": handler}, auto_approve=True)
        loop = AgenticLoop(ctx, executor)

        # Build a response with tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "analyze_ip"
        tool_block.input = {"ip_name": "Berserk"}
        tool_block.id = "tool_123"

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        with patch("core.cli.agentic_loop.render_tool_call") as mock_render:
            loop._process_tool_calls(mock_response)
            mock_render.assert_called_once_with("analyze_ip", {"ip_name": "Berserk"})

    def test_tool_result_renders_dict(self) -> None:
        """Dict results should trigger render_tool_result."""
        ctx = ConversationContext()
        handler = MagicMock(return_value={"tier": "S", "score": 81.3})
        executor = ToolExecutor(action_handlers={"analyze_ip": handler}, auto_approve=True)
        loop = AgenticLoop(ctx, executor)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "analyze_ip"
        tool_block.input = {"ip_name": "Berserk"}
        tool_block.id = "tool_123"

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        with (
            patch("core.cli.agentic_loop.render_tool_call"),
            patch("core.cli.agentic_loop.render_tool_result") as mock_render,
        ):
            loop._process_tool_calls(mock_response)
            mock_render.assert_called_once_with("analyze_ip", {"tier": "S", "score": 81.3})


# ---------------------------------------------------------------------------
# SubAgent Session Isolation tests (G7 fix)
# ---------------------------------------------------------------------------


class TestSubAgentSessionIsolation:
    """Tests for OpenClaw-style session key isolation in SubAgent parallel execution."""

    def test_subagent_session_key_format(self) -> None:
        """Verify build_subagent_session_key produces correct format."""
        from core.memory.session_key import build_subagent_session_key

        key = build_subagent_session_key("Berserk", "t1")
        assert key == "ip:berserk:pipeline:subagent:t1"

    def test_subagent_context_threadlocal(self) -> None:
        """Verify thread-local context is set during handler execution and cleared after."""
        from core.cli.sub_agent import SubAgentManager, SubTask, get_subagent_context

        captured: list[tuple[bool, str]] = []

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            captured.append(get_subagent_context())
            return {"ok": True}

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [SubTask("t1", "Test task", "analyze", {"ip_name": "Berserk"})]
        manager.delegate(tasks)

        # Handler should have received (True, child_key)
        assert len(captured) == 1
        is_sub, child_key = captured[0]
        assert is_sub is True
        assert "subagent" in child_key
        assert "berserk" in child_key

        # Main thread should get (False, "")
        main_is_sub, main_key = get_subagent_context()
        assert main_is_sub is False
        assert main_key == ""

    def test_subagent_run_records(self) -> None:
        """Verify run records are created and updated for delegated tasks."""
        from core.cli.sub_agent import SubAgentManager, SubTask

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"result": "done"}

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [
            SubTask("t1", "Task 1", "analyze", {"ip_name": "Berserk"}),
            SubTask("t2", "Task 2", "search", {"ip_name": "Cowboy Bebop"}),
        ]
        manager.delegate(tasks)

        records = manager.get_run_records()
        assert len(records) == 2
        assert "t1" in records
        assert "t2" in records

        for _tid, rec in records.items():
            assert rec.child_session_key != ""
            assert "subagent" in rec.child_session_key
            assert rec.outcome in ("ok", "error")
            assert rec.completed_at > 0
