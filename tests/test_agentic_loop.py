"""Tests for AgenticLoop, ToolExecutor, and SubAgentManager."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.agent.bash_tool import BashResult, BashTool
from core.agent.conversation import ConversationContext
from core.agent.loop import AGENTIC_TOOLS, AgenticLoop, AgenticResult, get_agentic_tools
from core.agent.sub_agent import SubAgentManager, SubTask
from core.agent.tool_executor import (
    DANGEROUS_TOOLS,
    SAFE_TOOLS,
    WRITE_TOOLS,
    ToolCallProcessor,
    ToolExecutor,
)
from core.hooks import HookEvent, HookSystem
from core.orchestration.isolated_execution import IsolatedRunner
from core.tools.base import ToolContext


def _run_executor(
    executor: ToolExecutor, tool_name: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    return asyncio.run(executor.aexecute(tool_name, tool_input))


# ---------------------------------------------------------------------------
# ToolExecutor tests
# ---------------------------------------------------------------------------


class TestToolExecutor:
    """Unit tests for ToolExecutor."""

    def test_execute_registered_handler(self) -> None:
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"list_subjects": handler})
        result = _run_executor(executor, "list_subjects", {})
        handler.assert_called_once()
        assert result["status"] == "ok"

    def test_execute_unknown_tool(self) -> None:
        executor = ToolExecutor()
        result = _run_executor(executor, "nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_execute_handler_exception(self) -> None:
        handler = MagicMock(side_effect=ValueError("test error"))
        executor = ToolExecutor(action_handlers={"broken": handler})
        result = _run_executor(executor, "broken", {})
        assert "error" in result
        assert "test error" in result["error"]

    def test_bash_blocked_command(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = _run_executor(executor, "run_bash", {"command": "sudo rm -rf /", "reason": "test"})
        assert result.get("blocked") is True

    def test_bash_unsafe_requires_approval(self) -> None:
        """Non-safe bash commands require approval, even with auto_approve=True."""
        executor = ToolExecutor(auto_approve=True)
        with patch.object(
            executor, "_request_approval_async", AsyncMock(return_value=True)
        ) as mock_approve:
            result = _run_executor(
                executor, "run_bash", {"command": "npm install foo", "reason": "testing"}
            )
            mock_approve.assert_awaited_once()
            assert "error" not in result or "denied" not in result

    def test_bash_safe_skips_approval(self) -> None:
        """Safe read-only bash commands skip HITL approval."""
        executor = ToolExecutor(auto_approve=True)
        with patch.object(executor, "_request_approval_async", AsyncMock()) as mock_approve:
            _run_executor(executor, "run_bash", {"command": "echo test_123", "reason": "testing"})
            mock_approve.assert_not_awaited()

    def test_bash_denied_by_user(self) -> None:
        """Non-safe bash commands denied by user return error."""
        executor = ToolExecutor(auto_approve=True)
        with patch.object(executor, "_request_approval_async", AsyncMock(return_value=False)):
            result = _run_executor(
                executor, "run_bash", {"command": "npm install bar", "reason": "test"}
            )
            assert result.get("denied") is True

    def test_bash_empty_command(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = _run_executor(executor, "run_bash", {"command": "", "reason": "test"})
        assert "error" in result

    def test_registered_tools_property(self) -> None:
        executor = ToolExecutor(action_handlers={"a": MagicMock(), "b": MagicMock()})
        assert sorted(executor.registered_tools) == ["a", "b"]

    def test_aexecute_awaits_async_handler_on_event_loop(self) -> None:
        """Async-native handlers run on the event loop, not via the sync wrapper."""
        main_thread = threading.get_ident()

        async def handler() -> dict[str, Any]:
            return {"status": "ok", "thread": threading.get_ident()}

        executor = ToolExecutor(action_handlers={"async_tool": handler})
        result = asyncio.run(executor.aexecute("async_tool", {}))

        assert result == {"status": "ok", "thread": main_thread}

    def test_aexecute_adapts_sync_handler_in_worker_thread(self) -> None:
        """Legacy sync handlers are quarantined behind the executor adapter."""
        main_thread = threading.get_ident()

        def handler() -> dict[str, Any]:
            return {"status": "ok", "thread": threading.get_ident()}

        executor = ToolExecutor(action_handlers={"sync_tool": handler})
        result = asyncio.run(executor.aexecute("sync_tool", {}))

        assert result["status"] == "ok"
        assert result["thread"] != main_thread

    def test_aexecute_write_approval_uses_async_path(self) -> None:
        """Async safety gates should offload approval prompts and await async hooks."""
        main_thread = threading.get_ident()
        callback_thread = 0
        hook_events: list[HookEvent] = []

        def approval_callback(_tool: str, _detail: str, _level: str) -> str:
            nonlocal callback_thread
            callback_thread = threading.get_ident()
            return "y"

        async def record_hook(event: HookEvent, _data: dict[str, Any]) -> None:
            await asyncio.sleep(0)
            hook_events.append(event)

        hooks = HookSystem()
        hooks.register(HookEvent.TOOL_APPROVAL_REQUESTED, record_hook, name="requested")
        hooks.register(HookEvent.TOOL_APPROVAL_GRANTED, record_hook, name="granted")

        executor = ToolExecutor(
            action_handlers={"memory_save": MagicMock(return_value={"status": "ok"})},
            approval_callback=approval_callback,
            hooks=hooks,
        )
        result = asyncio.run(executor.aexecute("memory_save", {"content": "data"}))

        assert result["status"] == "ok"
        assert callback_thread != main_thread
        assert HookEvent.TOOL_APPROVAL_REQUESTED in hook_events
        assert HookEvent.TOOL_APPROVAL_GRANTED in hook_events

    def test_aexecute_bash_approval_uses_async_method(self) -> None:
        """Dangerous tools should not route through the sync approval method in aexecute()."""
        executor = ToolExecutor(auto_approve=True)
        with patch.object(
            executor, "_request_approval_async", AsyncMock(return_value=False)
        ) as mock_approve:
            result = asyncio.run(
                executor.aexecute("run_bash", {"command": "npm install foo", "reason": "test"})
            )

        mock_approve.assert_awaited_once()
        assert result.get("denied") is True

    def test_aexecute_bash_uses_async_bash_tool(self) -> None:
        """Approved bash execution should use BashTool.aexecute() in the async path."""
        bash = MagicMock(spec=BashTool)
        bash.validate.return_value = None
        bash.aexecute = AsyncMock(return_value=BashResult(stdout="ok\n", returncode=0))
        bash.execute = MagicMock(side_effect=AssertionError("sync bash path used"))
        bash.to_tool_result.side_effect = lambda result: {"stdout": result.stdout}

        executor = ToolExecutor(bash_tool=bash, hitl_level=0)
        result = asyncio.run(executor.aexecute("run_bash", {"command": "echo ok", "reason": ""}))

        bash.aexecute.assert_awaited_once_with("echo ok", timeout=30, cancellation=None)
        bash.execute.assert_not_called()
        assert result["stdout"] == "ok\n"

    def test_aexecute_bash_passes_cancellation_context(self) -> None:
        """Bash receives ToolContext cancellation for in-flight interruption."""
        cancellation = asyncio.Event()
        bash = MagicMock(spec=BashTool)
        bash.validate.return_value = None
        bash.aexecute = AsyncMock(return_value=BashResult(stdout="ok\n", returncode=0))
        bash.to_tool_result.side_effect = lambda result: {"stdout": result.stdout}

        executor = ToolExecutor(bash_tool=bash, hitl_level=0)
        result = asyncio.run(
            executor.aexecute(
                "run_bash",
                {"command": "echo ok", "reason": "", "timeout": 7},
                context=ToolContext(cancellation=cancellation),
            )
        )

        bash.aexecute.assert_awaited_once_with("echo ok", timeout=7, cancellation=cancellation)
        assert result["stdout"] == "ok\n"

    def test_aexecute_mcp_uses_async_manager_call(self) -> None:
        """MCP execution should prefer manager.acall_tool() in the async path."""
        mcp = MagicMock()
        mcp.find_server_for_tool.return_value = "srv"
        mcp.is_mcp_approved = MagicMock(return_value=True)
        mcp.acall_tool = AsyncMock(return_value={"result": "ok"})
        mcp.call_tool = MagicMock(side_effect=AssertionError("sync MCP path used"))

        executor = ToolExecutor(mcp_manager=mcp, auto_approve=True)
        result = asyncio.run(executor.aexecute("mcp_tool", {"x": 1}))

        mcp.acall_tool.assert_awaited_once_with("srv", "mcp_tool", {"x": 1})
        mcp.call_tool.assert_not_called()
        assert result == {"result": "ok"}

    def test_process_uses_executor_aexecute(self) -> None:
        """ToolCallProcessor should not wrap the whole sync executor in to_thread."""
        executor = MagicMock(spec=ToolExecutor)
        executor.aexecute = AsyncMock(return_value={"status": "ok"})
        executor.execute = MagicMock(side_effect=AssertionError("sync executor path used"))

        op_logger = MagicMock()
        op_logger.log_tool_call.return_value = True
        error_recovery = MagicMock()
        processor = ToolCallProcessor(
            executor=executor,
            op_logger=op_logger,
            error_recovery=error_recovery,
        )

        block = MagicMock()
        block.type = "tool_use"
        block.name = "list_subjects"
        block.input = {"limit": 2}
        block.id = "toolu_async"
        response = MagicMock(content=[block])

        results = asyncio.run(processor.process(response))

        executor.aexecute.assert_awaited_once_with("list_subjects", {"limit": 2})
        executor.execute.assert_not_called()
        assert results[0]["tool_use_id"] == "toolu_async"
        assert '"status": "ok"' in results[0]["content"]

    def test_process_awaits_async_hooks(self) -> None:
        """ToolCallProcessor should await async hook interceptors and result hooks."""
        executor = MagicMock(spec=ToolExecutor)
        executor.aexecute = AsyncMock(return_value={"status": "raw"})

        op_logger = MagicMock()
        op_logger.log_tool_call.return_value = True
        hooks = HookSystem()

        async def rewrite_input(_event: HookEvent, _data: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(0)
            return {"modify": {"tool_input": {"limit": 3}}}

        async def rewrite_result(_event: HookEvent, _data: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(0)
            return {"updated_result": {"status": "hooked"}}

        hooks.register(HookEvent.TOOL_EXEC_STARTED, rewrite_input, name="rewrite_input")
        hooks.register(HookEvent.TOOL_EXEC_ENDED, rewrite_result, name="rewrite_result")

        processor = ToolCallProcessor(
            executor=executor,
            op_logger=op_logger,
            error_recovery=MagicMock(),
            hooks=hooks,
        )

        block = MagicMock()
        block.type = "tool_use"
        block.name = "list_subjects"
        block.input = {"limit": 1}
        block.id = "toolu_hooks"
        response = MagicMock(content=[block])

        results = asyncio.run(processor.process(response))

        executor.aexecute.assert_awaited_once_with("list_subjects", {"limit": 3})
        assert '"status": "hooked"' in results[0]["content"]

    def test_serialize_offloaded_result_awaits_async_hook(self, tmp_path: Any) -> None:
        """Tool result offload observability should support async hooks."""
        from core.orchestration.tool_offload import (
            ToolResultOffloadStore,
            get_offload_store,
            set_offload_store,
        )

        hook_calls: list[dict[str, Any]] = []
        hooks = HookSystem()

        async def record_offload(_event: HookEvent, data: dict[str, Any]) -> None:
            await asyncio.sleep(0)
            hook_calls.append(data)

        hooks.register(HookEvent.TOOL_RESULT_OFFLOADED, record_offload, name="record_offload")
        processor = ToolCallProcessor(
            executor=MagicMock(spec=ToolExecutor),
            op_logger=MagicMock(),
            error_recovery=MagicMock(),
            hooks=hooks,
        )
        prev = get_offload_store()
        try:
            set_offload_store(
                ToolResultOffloadStore(
                    session_id="offload-test",
                    threshold=1,
                    base_dir=tmp_path / "offload",
                )
            )
            result = asyncio.run(
                processor._serialize_tool_result({"data": "x" * 1000}, "toolu_offload")
            )
        finally:
            set_offload_store(prev)

        assert result["tool_use_id"] == "toolu_offload"
        assert hook_calls and hook_calls[0]["ref_id"] == "toolu_offload"

    def test_safe_tools_classification(self) -> None:
        assert "memory_search" in SAFE_TOOLS
        assert "check_status" in SAFE_TOOLS
        assert "run_bash" not in SAFE_TOOLS

    def test_dangerous_tools_classification(self) -> None:
        assert "run_bash" in DANGEROUS_TOOLS

    def test_write_tools_classification(self) -> None:
        assert "memory_save" in WRITE_TOOLS
        assert "note_save" in WRITE_TOOLS
        assert "set_api_key" in WRITE_TOOLS
        assert "manage_auth" in WRITE_TOOLS

    def test_write_tools_require_confirmation(self) -> None:
        """Write tools require user confirmation when not auto-approved."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"memory_save": handler})
        with patch.object(
            executor._approval, "confirm_write_async", AsyncMock(return_value=False)
        ) as mock:
            result = _run_executor(executor, "memory_save", {"content": "test"})
            mock.assert_awaited_once()
            assert result.get("denied") is True
            handler.assert_not_called()

    def test_write_tools_always_require_confirmation_even_auto_approve(self) -> None:
        """Write tools always require confirmation, even with auto_approve=True."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"memory_save": handler}, auto_approve=True)
        with patch.object(
            executor._approval, "confirm_write_async", AsyncMock(return_value=True)
        ) as mock:
            result = _run_executor(executor, "memory_save", {"content": "test"})
            mock.assert_awaited_once()
            assert result["status"] == "ok"
            handler.assert_called_once()

    def test_write_tools_denied_even_with_auto_approve(self) -> None:
        """Write tools denied by user even when auto_approve=True."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"memory_save": handler}, auto_approve=True)
        with patch.object(executor._approval, "confirm_write_async", AsyncMock(return_value=False)):
            result = _run_executor(executor, "memory_save", {"content": "test"})
            assert result.get("denied") is True
            handler.assert_not_called()

    def test_delegate_task_no_manager(self) -> None:
        executor = ToolExecutor(auto_approve=True)
        result = _run_executor(
            executor,
            "delegate_task",
            {
                "task_description": "Test task",
                "task_type": "analyze",
                "args": {"subject_id": "Project Atlas"},
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
        return ToolExecutor(action_handlers={"list_subjects": handler})

    def test_sync_run_facade_removed(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """The breaking async migration removes the sync run facade."""
        loop = AgenticLoop(context, executor, quiet=True)

        assert not hasattr(loop, "run")

    def test_internal_sync_entrypoints_bridge_to_arun_not_run(self) -> None:
        """Production entrypoints should not route through AgenticLoop.run()."""
        from core.agent.worker import _run_agentic
        from core.cli.bootstrap import _build_agentic_stack_minimal
        from core.cli.commands.skills import cmd_skill_invoke
        from core.cli.scheduler_drain import drain_scheduler_queue
        from core.cli.typer_serve import serve
        from core.server.ipc_server.poller import CLIPoller

        forbidden = {
            "_build_agentic_stack_minimal": (
                inspect.getsource(_build_agentic_stack_minimal),
                ["return loop.run("],
            ),
            "drain_scheduler_queue": (
                inspect.getsource(drain_scheduler_queue),
                ["_loop.run(", "main_loop.run("],
            ),
            "serve": (inspect.getsource(serve), ["result = loop.run("]),
            "cmd_skill_invoke": (inspect.getsource(cmd_skill_invoke), ["_loop.run("]),
            "_run_agentic": (inspect.getsource(_run_agentic), ["loop.run("]),
            "_run_prompt_streaming": (
                inspect.getsource(CLIPoller._run_prompt_streaming),
                ["loop.run("],
            ),
        }

        for name, (source, patterns) in forbidden.items():
            for pattern in patterns:
                assert pattern not in source, f"{name} still uses sync AgenticLoop.run()"

    def test_run_text_only_response(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test that a text-only response returns immediately."""
        loop = AgenticLoop(context, executor, quiet=True)

        # Mock LLM returning text only (no tool_use)
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Here are the available subjects."
        mock_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", return_value=mock_response),
            patch.object(loop, "_track_usage"),
        ):
            result = asyncio.run(loop.arun("list subjects"))

        assert result.text == "Here are the available subjects."
        assert result.rounds == 1
        assert result.error is None
        assert result.termination_reason == "natural"

    def test_arun_awaits_async_lifecycle_hooks(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Async loop path awaits start/end/finalization lifecycle hooks."""
        hooks = HookSystem()
        observed: list[tuple[HookEvent, dict[str, Any]]] = []

        async def record(event: HookEvent, data: dict[str, Any]) -> None:
            await asyncio.sleep(0)
            observed.append((event, dict(data)))

        for event in (
            HookEvent.SESSION_STARTED,
            HookEvent.SESSION_ENDED,
            HookEvent.TURN_COMPLETED,
            HookEvent.REASONING_METRICS,
        ):
            hooks.register(event, record, name=f"record_{event.value}")

        loop = AgenticLoop(context, executor, hooks=hooks, quiet=True)
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Lifecycle complete."
        mock_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", return_value=mock_response),
            patch.object(loop, "_track_usage"),
        ):
            result = asyncio.run(loop.arun("hello"))

        assert result.text == "Lifecycle complete."
        assert [event for event, _ in observed] == [
            HookEvent.SESSION_STARTED,
            HookEvent.SESSION_ENDED,
            HookEvent.TURN_COMPLETED,
            HookEvent.REASONING_METRICS,
        ]
        assert observed[0][1]["session_id"] == loop._session_id
        assert observed[1][1]["termination_reason"] == "natural"
        assert observed[2][1]["text"] == "Lifecycle complete."
        assert observed[3][1]["total_rounds"] == 1

    def test_arun_awaits_async_user_input_interceptor(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Async user input interceptors can block before the first LLM call."""
        hooks = HookSystem()

        async def block_input(_event: HookEvent, _data: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(0)
            return {"block": True, "reason": "blocked async"}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, block_input, name="block_input")
        loop = AgenticLoop(
            context,
            executor,
            hooks=hooks,
            quiet=True,
            enable_goal_decomposition=False,
        )

        with patch.object(loop, "_call_llm", new=AsyncMock()) as mock_call:
            result = asyncio.run(loop.arun("blocked"))

        mock_call.assert_not_called()
        assert result.text == "blocked async"
        assert result.rounds == 0
        assert result.termination_reason == "input_blocked"

    def test_run_with_tool_use(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test tool_use → tool_result → text response flow."""
        loop = AgenticLoop(context, executor, quiet=True)

        # Round 1: LLM calls list_subjects tool
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.usage = MagicMock()
        tool_response.usage.input_tokens = 100
        tool_response.usage.output_tokens = 50

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_subjects"
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
        text_block.text = "Here are 16 available subjects."
        text_response.content = [text_block]

        with (
            patch.object(loop, "_call_llm", side_effect=[tool_response, text_response]),
            patch.object(loop, "_track_usage"),
        ):
            result = asyncio.run(loop.arun("subject 목록 보여줘"))

        assert result.rounds == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "list_subjects"
        assert result.error is None
        assert result.termination_reason == "natural"

    def test_run_max_rounds(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test max rounds limit."""
        loop = AgenticLoop(context, executor, max_rounds=2, quiet=True)

        # Always return tool_use → never ends
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.usage = MagicMock()
        tool_response.usage.input_tokens = 100
        tool_response.usage.output_tokens = 50

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "list_subjects"
        tool_block.input = {}
        tool_block.id = "toolu_abc"
        tool_response.content = [tool_block]

        with (
            patch.object(loop, "_call_llm", return_value=tool_response),
            patch.object(loop, "_track_usage"),
        ):
            result = asyncio.run(loop.arun("infinite loop test"))

        assert result.error == "max_rounds"
        assert result.rounds == 2
        assert result.termination_reason == "max_rounds"

    def test_run_llm_failure(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """LLM failures exhaust the retry cap and surface a model_action_required diagnostic.

        v0.90.0 — pre-fix the loop tried ``_try_model_escalation`` to
        silently swap models. That path is gone, so retries on the same
        model run until ``_LLM_RETRY_CAP`` and exit with the structured
        diagnostic instead of an opaque ``retry_exhausted`` reason.
        """
        from unittest.mock import AsyncMock

        loop = AgenticLoop(context, executor, quiet=True)

        with (
            patch.object(loop, "_call_llm", return_value=None),
            patch.object(loop, "_aggressive_context_recovery", new=AsyncMock(return_value=0)),
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            result = asyncio.run(loop.arun("test"))

        assert result.error == "model_action_required"
        assert result.termination_reason == "model_action_required"
        assert "/model" in result.text  # diagnostic points to user action

    def test_context_preserved(self, context: ConversationContext, executor: ToolExecutor) -> None:
        """Test that conversation context is maintained across runs."""
        loop = AgenticLoop(context, executor, quiet=True)

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
            asyncio.run(loop.arun("first message"))

        assert context.turn_count >= 1

    def test_default_max_rounds(self) -> None:
        """Verify DEFAULT_MAX_ROUNDS is 0 (unlimited — time-based control)."""
        assert AgenticLoop.DEFAULT_MAX_ROUNDS == 0

    def test_forced_text_on_last_round(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """On the last round, tool_choice=none forces text output."""
        loop = AgenticLoop(context, executor, max_rounds=3, quiet=True)

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
                block.name = "list_subjects"
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
            result = asyncio.run(loop.arun("test forced text"))

        assert result.rounds == 3
        assert result.termination_reason == "forced_text"
        assert result.text == "Forced text on last round."
        # Verify all 3 rounds were called with correct round_idx
        assert [kw["round_idx"] for kw in call_kwargs] == [0, 1, 2]

    def test_agentic_tools_include_all(self) -> None:
        """Verify AGENTIC_TOOLS includes base tools + bash + delegate."""
        tool_names = {t["name"] for t in AGENTIC_TOOLS}
        assert "memory_search" in tool_names
        assert "check_status" in tool_names
        assert "run_bash" in tool_names
        assert "delegate_task" in tool_names

    def test_key_gate_blocks_without_key(self) -> None:
        """Test key_registration_gate returns None on /quit."""
        from unittest.mock import patch as _patch

        from core.cli.onboarding import key_registration_gate

        with _patch("core.cli.onboarding.console") as mock_console:
            mock_console.input.return_value = "/quit"
            result = key_registration_gate()
            assert result is None

    def test_key_gate_accepts_valid_key(self) -> None:
        """Test key_registration_gate accepts pasted API key."""
        from unittest.mock import patch as _patch

        from core.cli.onboarding import key_registration_gate

        with (
            _patch("core.cli.onboarding.console") as mock_console,
            _patch("core.cli.onboarding._upsert_env"),
            _patch("core.cli.onboarding.settings") as mock_settings,
        ):
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.zai_api_key = ""
            mock_console.input.return_value = "sk-ant-test-key-12345678"
            result = key_registration_gate()
            assert result == "sk-ant-test-key-12345678"

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
            {"name": "memory_search", "description": "Duplicate", "input_schema": {}},
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
        loop = AgenticLoop(context, executor, quiet=True)
        prompt = loop._build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_track_usage_records(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _track_usage records to accumulator."""
        from core.llm.client import get_usage_accumulator, reset_usage_accumulator

        reset_usage_accumulator()
        loop = AgenticLoop(context, executor, quiet=True)

        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=500, output_tokens=200)

        loop._track_usage(mock_response)

        acc = get_usage_accumulator()
        assert acc.total_input_tokens == 500
        assert acc.total_output_tokens == 200
        assert len(acc.calls) == 1

    def test_track_usage_async_awaits_cost_hooks(
        self,
        context: ConversationContext,
        executor: ToolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Async usage tracking should emit cost hooks through the async hook path."""
        from core.config import settings
        from core.llm.token_tracker import reset_tracker

        reset_tracker()
        monkeypatch.setattr(settings, "cost_limit_usd", 0.000001, raising=False)
        hooks = HookSystem()
        observed: list[tuple[HookEvent, dict[str, Any]]] = []

        async def record(event: HookEvent, data: dict[str, Any]) -> None:
            await asyncio.sleep(0)
            observed.append((event, dict(data)))

        hooks.register(HookEvent.COST_LIMIT_EXCEEDED, record, name="cost_limit")
        loop = AgenticLoop(context, executor, hooks=hooks, quiet=True)
        mock_response = MagicMock()
        mock_response.usage = MagicMock(
            input_tokens=500_000,
            output_tokens=200_000,
            thinking_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        )

        asyncio.run(loop._track_usage_async(mock_response))

        assert observed
        assert observed[0][0] == HookEvent.COST_LIMIT_EXCEEDED
        assert observed[0][1]["limit_usd"] == 0.000001

    def test_track_usage_no_usage(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _track_usage with no usage data."""
        loop = AgenticLoop(context, executor, quiet=True)
        mock_response = MagicMock()
        mock_response.usage = None
        loop._track_usage(mock_response)  # should not raise

    def test_track_usage_exception_handled(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _track_usage swallows exceptions."""
        loop = AgenticLoop(context, executor, quiet=True)
        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch("core.llm.router.calculate_cost", side_effect=RuntimeError("boom")):
            loop._track_usage(mock_response)  # should not raise

    def test_track_usage_records_cache_tokens(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """F-A2 — cache_creation_tokens / cache_read_tokens must flow
        from ``response.usage`` (normalized ``ResponseUsage``) through
        ``_track_usage`` into ``TokenTracker.record``, where the cost
        path already handles them. Pre-F-A2 they were dropped and the
        ``~/.geode/usage`` JSONL undercounted prompt-cache spend."""
        from core.llm.token_tracker import get_tracker, reset_tracker

        reset_tracker()
        loop = AgenticLoop(context, executor, quiet=True)

        mock_response = MagicMock()
        mock_response.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=20,
            cache_read_tokens=80,
            thinking_tokens=10,
        )

        loop._track_usage(mock_response)

        last = get_tracker().accumulator.calls[-1]
        assert last.input_tokens == 100
        assert last.output_tokens == 50
        assert last.cache_creation_tokens == 20
        assert last.cache_read_tokens == 80
        assert last.thinking_tokens == 10

    def test_track_usage_logs_warning_on_schema_mismatch(
        self,
        context: ConversationContext,
        executor: ToolExecutor,
        caplog,
    ) -> None:
        """F-A2 — when the inner ``tracker.record`` raises (e.g. the
        wrapper has only ``input_tokens`` and downstream code trips),
        the swallowed exception must surface at WARNING level. Pre-F-A2
        it was DEBUG-level and the silent-skip was invisible in normal
        log output — Defect A's main symptom."""
        loop = AgenticLoop(context, executor, quiet=True)
        mock_response = MagicMock()
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with (
            caplog.at_level(logging.WARNING, logger="core.agent.loop._response"),
            patch("core.llm.token_tracker.TokenTracker.record", side_effect=RuntimeError("boom")),
        ):
            loop._track_usage(mock_response)  # should not raise

        assert any("Failed to track usage" in r.message for r in caplog.records), (
            "track_usage must log at WARNING when it swallows a record() failure"
        )

    def test_update_model_async_awaits_model_switched_hook(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Async model switching should use async hook emission."""
        hooks = HookSystem()
        observed: list[dict[str, Any]] = []

        async def record(_event: HookEvent, data: dict[str, Any]) -> None:
            await asyncio.sleep(0)
            observed.append(dict(data))

        hooks.register(HookEvent.MODEL_SWITCHED, record, name="model_switch")
        loop = AgenticLoop(context, executor, hooks=hooks, quiet=True)

        asyncio.run(loop.update_model_async("test-async-model", provider=loop._provider))

        assert len(observed) == 1
        assert observed[0]["from_model"] != "test-async-model"
        assert observed[0]["to_model"] == "test-async-model"
        assert observed[0]["reason"] == "user_switch"


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
            SubTask("t1", "Test task 1", "analyze", {"subject_id": "Test"}),
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
# adelegate — async sibling parity (PR-Async-Phase-C, 2026-05-22)
# ---------------------------------------------------------------------------


class TestSubAgentManagerAdelegate:
    """Behaviour-parity tests for async ``SubAgentManager.adelegate``.

    Mirrors the sync ``delegate`` test class so a future bulk-delete of
    the sync path (Phase C cleanup) keeps full coverage on the async
    survivor. Each test exercises the same input shape as its sync sibling.
    """

    def test_adelegate_empty_tasks(self) -> None:
        import asyncio

        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()
        manager = SubAgentManager(runner)
        results = asyncio.run(manager.adelegate([]))
        assert results == []

    def test_adelegate_with_handler(self) -> None:
        import asyncio

        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"processed": True, "type": task_type}

        manager = SubAgentManager(runner, task_handler=handler, timeout_s=10)
        tasks = [SubTask("t1", "Test task 1", "analyze", {"subject_id": "Test"})]
        results = asyncio.run(manager.adelegate(tasks))

        assert len(results) == 1
        assert results[0].task_id == "t1"
        assert results[0].success is True

    def test_adelegate_handler_failure(self) -> None:
        import asyncio

        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("task handler failed")

        manager = SubAgentManager(runner, task_handler=handler, timeout_s=10)
        tasks = [SubTask("t1", "Failing task", "analyze", {})]
        results = asyncio.run(manager.adelegate(tasks))

        assert len(results) == 1
        assert results[0].output.get("error") is not None

    def test_adelegate_fans_out_in_parallel(self) -> None:
        """Async fan-out must launch tasks concurrently via gather.

        Verifies the wall-clock duration is closer to a single task's
        runtime than to N × runtime — i.e., tasks ran in parallel.
        """
        import asyncio
        import time

        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            time.sleep(0.1)
            return {"ok": True}

        manager = SubAgentManager(runner, task_handler=handler, timeout_s=10)
        tasks = [SubTask(f"t{i}", f"Task {i}", "analyze", {}) for i in range(5)]

        started = time.time()
        results = asyncio.run(manager.adelegate(tasks))
        elapsed = time.time() - started

        assert len(results) == 5
        assert all(r.success for r in results)
        # 5 × 0.1s sequential = 0.5s; parallel should be ≤ 0.3s with
        # generous CI buffer.
        assert elapsed < 0.3, f"parallel fan-out too slow: {elapsed:.2f}s"

    def test_adelegate_depth_guard(self) -> None:
        """Depth limit returns synthetic failures without launching tasks."""
        import asyncio

        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, depth=2, max_depth=1)
        tasks = [SubTask("t1", "Should be rejected", "analyze", {})]
        results = asyncio.run(manager.adelegate(tasks))
        assert len(results) == 1
        assert results[0].success is False
        assert "depth limit exceeded" in (results[0].error or "").lower()

    def test_sync_delegate_emits_deprecation_warning(self) -> None:
        """The sync ``delegate`` must surface a DeprecationWarning so
        callers see the migration cue. ``adelegate`` is the survivor."""
        import warnings

        from core.orchestration.isolated_execution import IsolatedRunner

        runner = IsolatedRunner()
        manager = SubAgentManager(runner)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manager.delegate([])
        assert any(
            issubclass(w.category, DeprecationWarning) and "adelegate" in str(w.message)
            for w in caught
        )


# ---------------------------------------------------------------------------
# SubAgentManager — Orchestration Integration tests
# ---------------------------------------------------------------------------


class TestSubAgentOrchestration:
    """Tests for TaskGraph, HookSystem, and SubAgent integration."""

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
        tasks = [SubTask("t1", "Test task", "analyze", {"subject_id": "Project Atlas"})]
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

    def test_seen_set_dedup(self, handler: Any) -> None:
        """Verify seen-set dedup within a single delegate call."""
        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10)

        # Duplicate task_id in same batch — second should be filtered
        tasks = [
            SubTask("t1", "Task 1", "analyze", {}),
            SubTask("t1", "Task 1 again", "analyze", {}),
        ]
        results = manager.delegate(tasks)
        assert len(results) == 1

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


class TestAgenticLoopEdgeCases:
    """Tests covering previously untested paths in AgenticLoop."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler_a = MagicMock(return_value={"status": "ok", "action": "list"})
        handler_b = MagicMock(return_value={"data": [1, 2, 3]})
        return ToolExecutor(
            action_handlers={"list_subjects": handler_a, "search_subjects": handler_b}
        )

    def test_multiple_tool_calls_in_single_response(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test response with 2+ tool_use blocks processed in one round."""
        loop = AgenticLoop(context, executor, quiet=True)

        # Round 1: LLM calls 2 tools simultaneously
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.usage = MagicMock(input_tokens=100, output_tokens=80)

        tool_block_1 = MagicMock()
        tool_block_1.type = "tool_use"
        tool_block_1.name = "list_subjects"
        tool_block_1.input = {}
        tool_block_1.id = "toolu_aaa"

        tool_block_2 = MagicMock()
        tool_block_2.type = "tool_use"
        tool_block_2.name = "search_subjects"
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
            result = asyncio.run(loop.arun("list and search"))

        assert result.rounds == 2
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0]["tool"] == "list_subjects"
        assert result.tool_calls[1]["tool"] == "search_subjects"

    def test_serialize_content_mixed(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _serialize_content with mixed text + tool_use blocks."""
        loop = AgenticLoop(context, executor, quiet=True)

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Let me help."

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_xyz"
        tool_block.name = "list_subjects"
        tool_block.input = {"filter": "active"}

        serialized = loop._serialize_content([text_block, tool_block])

        assert len(serialized) == 2
        assert serialized[0] == {"type": "text", "text": "Let me help."}
        assert serialized[1]["type"] == "tool_use"
        assert serialized[1]["name"] == "list_subjects"
        assert serialized[1]["id"] == "toolu_xyz"

    def test_extract_text_empty_content(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _extract_text with no text blocks (only tool_use blocks)."""
        loop = AgenticLoop(context, executor, quiet=True)

        tool_block = MagicMock()
        tool_block.type = "tool_use"

        response = MagicMock()
        response.content = [tool_block]
        assert loop._extract_text(response) == ""

    def test_extract_text_multiple_text_blocks(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Test _extract_text joins multiple text blocks."""
        loop = AgenticLoop(context, executor, quiet=True)

        block1 = MagicMock()
        block1.type = "text"
        block1.text = "Part 1"
        block2 = MagicMock()
        block2.type = "text"
        block2.text = "Part 2"

        response = MagicMock()
        response.content = [block1, block2]
        assert loop._extract_text(response) == "Part 1\nPart 2"

    def test_adapter_initialized_at_construction(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Verify agentic adapter is created at construction time."""
        loop = AgenticLoop(context, executor, quiet=True)
        assert loop._adapter is not None
        assert loop._adapter.provider_name == "anthropic"


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
        assert "goal" in schema["properties"]
        assert "goal" in schema["required"]
        assert "subject" in schema["properties"]

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
        executor = ToolExecutor(action_handlers={"analyze_subject": handler}, auto_approve=True)
        loop = AgenticLoop(ctx, executor, quiet=True)

        # Build a response with tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "analyze_subject"
        tool_block.input = {"subject_id": "Project Atlas"}
        tool_block.id = "tool_123"

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        import asyncio

        with patch.object(
            loop._tool_processor._op_logger, "log_tool_call", return_value=True
        ) as mock_log:
            asyncio.run(loop._tool_processor.process(mock_response))
            mock_log.assert_called_once_with("analyze_subject", {"subject_id": "Project Atlas"})

    def test_tool_result_renders_dict(self) -> None:
        """Dict results should trigger render_tool_result."""
        ctx = ConversationContext()
        handler = MagicMock(return_value={"tier": "S", "score": 81.3})
        executor = ToolExecutor(action_handlers={"analyze_subject": handler}, auto_approve=True)
        loop = AgenticLoop(ctx, executor, quiet=True)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "analyze_subject"
        tool_block.input = {"subject_id": "Project Atlas"}
        tool_block.id = "tool_123"

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        with (
            patch.object(loop._tool_processor._op_logger, "log_tool_call", return_value=True),
            patch.object(loop._tool_processor._op_logger, "log_tool_result") as mock_log_result,
        ):
            import asyncio

            asyncio.run(loop._tool_processor.process(mock_response))
            mock_log_result.assert_called_once_with(
                "analyze_subject", {"tier": "S", "score": 81.3}, visible=True
            )


# ---------------------------------------------------------------------------
# Message pruning + repair tests (orphaned tool_result fix)
# ---------------------------------------------------------------------------


def _tu(tid: str, name: str = "a") -> dict[str, Any]:
    """Helper: build a tool_use content block."""
    return {
        "type": "tool_use",
        "id": tid,
        "name": name,
        "input": {},
    }


def _tr(tid: str) -> dict[str, Any]:
    """Helper: build a tool_result content block."""
    return {
        "type": "tool_result",
        "tool_use_id": tid,
        "content": "ok",
    }


def _txt(text: str) -> dict[str, Any]:
    """Helper: build a text content block."""
    return {"type": "text", "text": text}


class TestMessagePruning:
    """Tests for _maybe_prune_messages — must never create orphaned tool_results."""

    def _make_loop(self) -> AgenticLoop:
        ctx = ConversationContext()
        executor = ToolExecutor(action_handlers={}, auto_approve=True)
        return AgenticLoop(ctx, executor, quiet=True)

    def test_no_prune_under_threshold(self) -> None:
        """Messages <= 10 should not be pruned."""
        loop = self._make_loop()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [_txt("hi")]},
        ]
        loop._maybe_prune_messages(messages)
        assert len(messages) == 2

    def test_prune_skips_orphaned_tool_result(self) -> None:
        """Pruning must not leave a tool_result without matching tool_use."""
        loop = self._make_loop()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": [_tu("t1")]},
            {"role": "user", "content": [_tr("t1")]},
            {"role": "assistant", "content": [_txt("done1")]},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": [_tu("t2", "b")]},
            {"role": "user", "content": [_tr("t2")]},
            {"role": "assistant", "content": [_txt("done2")]},
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": [_tu("t3", "c")]},
            {"role": "user", "content": [_tr("t3")]},
            {"role": "assistant", "content": [_txt("done3")]},
            {"role": "user", "content": "q4"},
        ]
        loop._maybe_prune_messages(messages)
        # After pruning, no tool_result should be orphaned
        for i, msg in enumerate(messages):
            if msg["role"] != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            tr_ids = {
                b["tool_use_id"]
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result"
            }
            if not tr_ids:
                continue
            assert i > 0
            assert messages[i - 1]["role"] == "assistant"
            prev = messages[i - 1].get("content", [])
            tu_ids = {
                b.get("id") for b in prev if isinstance(b, dict) and b.get("type") == "tool_use"
            }
            assert tr_ids <= tu_ids, f"Orphaned tool_result at {i}"

    def test_prune_finds_safe_cut(self) -> None:
        """Pruning should cut at a plain user text message."""
        loop = self._make_loop()
        # Build enough messages to exceed prune threshold (30)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": [_tu("t1")]},
            {"role": "user", "content": [_tr("t1")]},
            {"role": "assistant", "content": [_txt("done1")]},
        ]
        # Pad with plain user/assistant pairs to exceed threshold
        for i in range(14):
            messages.append({"role": "user", "content": f"pad_q{i}"})
            messages.append({"role": "assistant", "content": f"pad_a{i}"})
        messages.extend(
            [
                {"role": "user", "content": "q_final"},
                {"role": "assistant", "content": [_txt("done_final")]},
                {"role": "user", "content": "q_last"},
            ]
        )
        assert len(messages) > 30
        loop._maybe_prune_messages(messages)
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        # After pruning, no orphaned tool_result in first user msg
        content = messages[2].get("content") if len(messages) > 2 else None
        if isinstance(content, list):
            assert not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


class TestRepairMessages:
    """Tests for _repair_messages — fixes orphaned tool_result."""

    def test_removes_orphaned_tool_result(self) -> None:
        """Orphaned tool_result should be removed."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [_txt("bridge")]},
            {"role": "user", "content": [_tr("orphan")]},
            {"role": "assistant", "content": [_txt("resp")]},
            {"role": "user", "content": "next question"},
        ]
        AgenticLoop._repair_messages(messages)
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                assert not any(
                    isinstance(b, dict)
                    and b.get("type") == "tool_result"
                    and b.get("tool_use_id") == "orphan"
                    for b in content
                )

    def test_keeps_valid_tool_result(self) -> None:
        """tool_result with matching tool_use should be kept."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [_tu("t1")]},
            {"role": "user", "content": [_tr("t1")]},
            {"role": "assistant", "content": [_txt("done")]},
        ]
        original_len = len(messages)
        AgenticLoop._repair_messages(messages)
        assert len(messages) == original_len


# ---------------------------------------------------------------------------
# SubAgent Session Isolation tests (G7 fix)
# ---------------------------------------------------------------------------


class TestSubAgentSessionIsolation:
    """Tests for OpenClaw-style session key isolation in SubAgent parallel execution."""

    def test_subagent_session_key_format(self) -> None:
        """Verify build_subagent_session_key produces correct format."""
        from core.memory.session_key import build_subagent_session_key

        key = build_subagent_session_key("demo", "t1")
        assert key == "subject:demo:pipeline:subagent:t1"

    def test_subagent_context_threadlocal(self) -> None:
        """Verify thread-local context is set during handler execution and cleared after."""
        from core.agent.sub_agent import SubAgentManager, SubTask, get_subagent_context

        captured: list[tuple[bool, str]] = []

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            captured.append(get_subagent_context())
            return {"ok": True}

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [SubTask("t1", "Test task", "analyze", {"subject_id": "demo"})]
        manager.delegate(tasks)

        # Handler should have received (True, child_key)
        assert len(captured) == 1
        is_sub, child_key = captured[0]
        assert is_sub is True
        assert "subagent" in child_key
        assert "demo" in child_key

        # Main thread should get (False, "")
        main_is_sub, main_key = get_subagent_context()
        assert main_is_sub is False
        assert main_key == ""

    def test_subagent_run_records(self) -> None:
        """Verify run records are created and updated for delegated tasks."""
        from core.agent.sub_agent import SubAgentManager, SubTask

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"result": "done"}

        runner = IsolatedRunner()
        manager = SubAgentManager(runner, handler, timeout_s=10)
        tasks = [
            SubTask("t1", "Task 1", "analyze", {"subject_id": "Project Atlas"}),
            SubTask("t2", "Task 2", "search", {"subject_id": "Project Orion"}),
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
