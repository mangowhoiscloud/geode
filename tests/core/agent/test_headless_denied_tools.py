"""Tests for the headless tool denylist (PR-EXEC-HARDENING).

The canonical denylist lives in ``core.agent.safety`` and is applied at BOTH
headless entry points: ``SharedServices.create_session`` (scheduler/daemon) and
the MCP ``run_agent`` fork (``core.cli.bootstrap.arun_agentic_oneshot``).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


def test_headless_denied_tools_contents() -> None:
    from core.agent.safety import COMPUTER_USE_TOOLS, HEADLESS_DENIED_TOOLS, SENSITIVE_TOOLS

    assert "run_bash" in HEADLESS_DENIED_TOOLS
    assert "delegate_task" in HEADLESS_DENIED_TOOLS
    assert "computer" in HEADLESS_DENIED_TOOLS
    assert "computer_use" in HEADLESS_DENIED_TOOLS
    assert {"computer", "computer_use"} == COMPUTER_USE_TOOLS
    assert COMPUTER_USE_TOOLS < HEADLESS_DENIED_TOOLS
    assert SENSITIVE_TOOLS <= HEADLESS_DENIED_TOOLS


def test_run_agent_fork_excludes_denied_tools() -> None:
    """The MCP run_agent fork is headless — its executor must never receive
    run_bash / delegate_task / computer handlers."""
    from core.cli import bootstrap

    fork_handlers = {
        "web_fetch": MagicMock(),
        "run_bash": MagicMock(),
        "delegate_task": MagicMock(),
        "computer": MagicMock(),
        "computer_use": MagicMock(),
        "memory_search": MagicMock(),
    }

    captured: dict[str, object] = {}

    def _capture_executor(*, action_handlers: dict[str, object], **kw: object) -> MagicMock:
        captured["handlers"] = action_handlers
        captured["denied_tools"] = kw.get("denied_tools")
        return MagicMock()

    class _FakeLoop:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        async def arun(self, _prompt: str) -> str:
            return "ok"

    with (
        patch.object(bootstrap, "_build_tool_handlers_for_fork", return_value=fork_handlers),
        patch("core.agent.tool_executor.ToolExecutor", side_effect=_capture_executor),
        patch("core.agent.loop.AgenticLoop", _FakeLoop),
        patch("core.llm.adapters.registry.bootstrap_builtins"),
    ):
        asyncio.run(bootstrap.arun_agentic_oneshot("hi"))

    handlers = captured["handlers"]
    assert isinstance(handlers, dict)
    assert "run_bash" not in handlers
    assert "delegate_task" not in handlers
    assert "computer" not in handlers
    assert "computer_use" not in handlers
    # Non-denied tools survive the filter.
    assert "web_fetch" in handlers
    assert "memory_search" in handlers
    # The REAL enforcement: denied_tools is passed to the executor (the handler
    # filter alone cannot stop the special-cased run_bash / delegate_task).
    from core.agent.safety import HEADLESS_DENIED_TOOLS

    assert captured["denied_tools"] == HEADLESS_DENIED_TOOLS


def test_executor_denied_tools_refuses_run_bash_at_top() -> None:
    """run_bash is special-cased ahead of handler lookup and auto-approved at
    hitl_level=0, so only the executor-level denied_tools check can stop it.
    Proves the headless gap is actually closed (Codex MCP review)."""
    from core.agent.tool_executor.executor import ToolExecutor

    executor = ToolExecutor(hitl_level=0, denied_tools=frozenset({"run_bash"}))
    result = asyncio.run(executor.aexecute("run_bash", {"command": "echo pwned"}))
    assert result.get("denied") is True
    assert "not available" in result.get("error", "")
