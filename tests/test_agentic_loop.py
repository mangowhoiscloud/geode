"""Tests for AgenticLoop, ToolExecutor, and SubAgentManager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.cli.agentic_loop import AGENTIC_TOOLS, AgenticLoop
from core.cli.conversation import ConversationContext
from core.cli.sub_agent import SubAgentManager, SubTask
from core.cli.tool_executor import DANGEROUS_TOOLS, SAFE_TOOLS, ToolExecutor

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

        with patch.object(loop, "_call_llm", return_value=mock_response), \
             patch.object(loop, "_track_usage"):
            result = loop.run("list IPs")

        assert result.text == "Here are the available IPs."
        assert result.rounds == 1
        assert result.error is None

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

        with patch.object(loop, "_call_llm", side_effect=[tool_response, text_response]), \
             patch.object(loop, "_track_usage"):
            result = loop.run("IP 목록 보여줘")

        assert result.rounds == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "list_ips"
        assert result.error is None

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

        with patch.object(loop, "_call_llm", return_value=tool_response), \
             patch.object(loop, "_track_usage"):
            result = loop.run("infinite loop test")

        assert result.error == "max_rounds"
        assert result.rounds == 2

    def test_run_llm_failure(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test graceful handling of LLM call failure."""
        loop = AgenticLoop(context, executor)

        with patch.object(loop, "_call_llm", return_value=None):
            result = loop.run("test")

        assert result.error == "llm_call_failed"

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

        with patch.object(loop, "_call_llm", return_value=mock_response), \
             patch.object(loop, "_track_usage"):
            loop.run("first message")

        assert context.turn_count >= 1

    def test_agentic_tools_include_all(self) -> None:
        """Verify AGENTIC_TOOLS includes base tools + bash + delegate."""
        tool_names = {t["name"] for t in AGENTIC_TOOLS}
        assert "list_ips" in tool_names
        assert "analyze_ip" in tool_names
        assert "run_bash" in tool_names
        assert "delegate_task" in tool_names


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
        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, task_handler=None, timeout_s=10)
        tasks = [SubTask("t1", "No handler", "analyze", {})]
        results = manager.delegate(tasks)

        assert len(results) == 1
        assert results[0].success is True  # IsolationResult is success, but output has error
