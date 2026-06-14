"""Unified tool dispatch — classify → gate → dispatch (PR-TOOL-DISPATCH-UNIFY).

The old `aexecute` short-circuited DANGEROUS tools to `_execute_dangerous_async`,
which only implemented `run_bash` — so `computer` (also DANGEROUS) returned
"Dangerous tool not implemented" and its registered `handle_computer` was never
reached. The refactor gates DANGEROUS tools (approval only) then dispatches every
tool through the SAME path, so a registered handler is always reachable.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent.tool_executor import ToolExecutor


def _run(coro):
    return asyncio.run(coro)


class TestComputerReachesHandler:
    """The core fix: a DANGEROUS tool with a registered handler is dispatched
    to that handler (computer-use was unreachable before)."""

    def test_computer_dispatches_to_handler(self) -> None:
        seen: dict = {}

        async def handle_computer(**kw):
            seen.update(kw)
            return {"result": "success", "screenshot": "IMG"}

        ex = ToolExecutor(action_handlers={"computer": handle_computer}, hitl_level=0)
        result = _run(ex.aexecute("computer", {"action": "screenshot"}))
        assert seen == {"action": "screenshot"}
        assert result["result"] == "success"

    def test_computer_denied_at_full_hitl_without_approval(self) -> None:
        async def handle_computer(**kw):
            return {"result": "success"}

        ex = ToolExecutor(action_handlers={"computer": handle_computer}, hitl_level=2)
        # deny the one-time session approval
        with patch.object(
            ex._approval, "confirm_computer_async", new=AsyncMock(return_value=False)
        ):
            result = _run(ex.aexecute("computer", {"action": "screenshot"}))
        assert result.get("denied") is True


class TestRunBashSplitGateExec:
    """run_bash: gate validates + approves, dispatch runs the subprocess."""

    def test_bash_runs_when_auto_approved(self) -> None:
        ex = ToolExecutor(hitl_level=0)  # hitl 0 → bash auto-approved
        with (
            patch.object(ex._bash, "validate", return_value=None),
            patch.object(ex._bash, "aexecute", new=AsyncMock(return_value=MagicMock())),
            patch.object(ex._bash, "to_tool_result", return_value={"stdout": "ok"}),
        ):
            result = _run(ex.aexecute("run_bash", {"command": "ls"}))
        assert result == {"stdout": "ok"}

    def test_bash_validation_block_short_circuits_in_gate(self) -> None:
        ex = ToolExecutor(hitl_level=0)
        with (
            patch.object(ex._bash, "validate", return_value="blocked-pattern"),
            patch.object(ex._bash, "to_tool_result", return_value={"error": "blocked"}),
            patch.object(ex._bash, "aexecute", new=AsyncMock()) as mock_exec,
        ):
            result = _run(ex.aexecute("run_bash", {"command": "rm -rf /"}))
        assert result == {"error": "blocked"}
        mock_exec.assert_not_awaited()  # never executed when validation blocks

    def test_bash_denied_when_user_rejects(self) -> None:
        ex = ToolExecutor(hitl_level=2)  # full HITL → prompts
        with (
            patch.object(ex._bash, "validate", return_value=None),
            patch.object(ex._approval, "is_bash_auto_approved", return_value=False),
            patch.object(
                ex._approval, "request_bash_approval_async", new=AsyncMock(return_value=False)
            ),
            patch.object(ex._bash, "aexecute", new=AsyncMock()) as mock_exec,
        ):
            result = _run(ex.aexecute("run_bash", {"command": "rm x"}))
        assert result.get("denied") is True
        mock_exec.assert_not_awaited()

    def test_empty_command_returns_no_command(self) -> None:
        ex = ToolExecutor(hitl_level=0)
        result = _run(ex.aexecute("run_bash", {"command": ""}))
        assert "No command" in result["error"]


class TestUnhandledDangerousFailsClosed:
    """A DANGEROUS tool with no explicit gate branch must FAIL CLOSED — even
    with a registered handler it must not dispatch unapproved (Codex MEDIUM:
    the gate must not fail open for a future DANGEROUS tool)."""

    def test_fails_closed_even_with_handler(self) -> None:
        ran = {"v": False}

        async def fake_handler(**kw):
            ran["v"] = True
            return {"ran": True}

        ex = ToolExecutor(action_handlers={"fake_danger": fake_handler}, hitl_level=0)
        with patch(
            "core.agent.tool_executor.executor.DANGEROUS_TOOLS",
            frozenset({"run_bash", "computer", "fake_danger"}),
        ):
            result = _run(ex.aexecute("fake_danger", {}))
        assert result.get("denied") is True
        assert "no approval gate" in result["error"]
        assert ran["v"] is False  # handler never ran (fail closed)

    def test_every_dangerous_tool_is_gated(self) -> None:
        """Forces a new DANGEROUS tool to get an explicit gate branch."""
        from core.agent.safety import DANGEROUS_TOOLS

        assert set(DANGEROUS_TOOLS) <= {"run_bash", "computer"}, (
            "A new DANGEROUS tool needs an explicit branch in "
            "ToolExecutor._gate_dangerous_async (fail-closed default otherwise)."
        )


class TestComputerSessionApproval:
    def test_auto_approved_under_open_hitl(self) -> None:
        from core.agent.approval import ApprovalWorkflow

        wf = ApprovalWorkflow(hitl_level=0)
        assert _run(wf.confirm_computer_async()) is True

    def test_prompt_once_then_remembered(self) -> None:
        from core.agent.approval import ApprovalWorkflow

        wf = ApprovalWorkflow(hitl_level=2)
        with patch.object(
            wf, "prompt_with_always_async", new=AsyncMock(return_value="y")
        ) as mock_prompt:
            assert _run(wf.confirm_computer_async()) is True
            # second call: remembered, no re-prompt
            assert _run(wf.confirm_computer_async()) is True
        mock_prompt.assert_awaited_once()


class TestGateConsolidation:
    """WRITE/EXPENSIVE/MCP still gated through the same single entry point."""

    def test_write_tool_still_gated(self) -> None:
        ex = ToolExecutor(action_handlers={"edit_file": lambda **k: {"ok": True}}, hitl_level=2)
        # deny the write gate → rejection returned, handler never called
        with patch.object(
            ex._approval,
            "apply_safety_gates_async",
            new=AsyncMock(return_value=({"denied": True}, False)),
        ):
            result = _run(ex.aexecute("edit_file", {"path": "x"}))
        assert result.get("denied") is True
