"""Tests for the headless tool denylist (PR-EXEC-HARDENING).

The canonical denylist lives in ``core.agent.safety`` and is applied at BOTH
headless entry points: ``SharedServices.create_session`` (scheduler/daemon) and
the MCP ``run_agent`` fork (``core.cli.bootstrap.arun_agentic_oneshot``).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch


def test_headless_denied_tools_contents() -> None:
    from core.agent.safety import (
        COLLABORATION_TOOLS,
        COMPUTER_USE_TOOLS,
        HEADLESS_DENIED_TOOLS,
        SENSITIVE_TOOLS,
    )

    assert "run_bash" in HEADLESS_DENIED_TOOLS
    assert "delegate_task" in HEADLESS_DENIED_TOOLS
    assert COLLABORATION_TOOLS < HEADLESS_DENIED_TOOLS
    assert "computer" in HEADLESS_DENIED_TOOLS
    assert "computer_use" in HEADLESS_DENIED_TOOLS
    assert {"computer", "computer_use"} == COMPUTER_USE_TOOLS
    assert COMPUTER_USE_TOOLS < HEADLESS_DENIED_TOOLS
    assert SENSITIVE_TOOLS <= HEADLESS_DENIED_TOOLS


def test_run_agent_fork_excludes_denied_tools() -> None:
    """The MCP run_agent fork is headless — its executor must never receive
    run_bash / delegate_task / computer handlers."""
    from core.cli import bootstrap
    from core.tools.plan import (
        ExecutionBinding,
        SafetyPolicy,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    ordinary_names = ("web_fetch", "computer_use", "memory_search")
    special_names = ("run_bash", "delegate_task")
    specs = tuple(
        (ToolSpec(name, f"{name} description", {}), "test")
        for name in (*ordinary_names, *special_names)
    )
    bindings = tuple(
        ExecutionBinding(name, "test", route="handler") for name in ordinary_names
    ) + tuple(ExecutionBinding(name, "test", route="special") for name in special_names)
    handlers = {name: MagicMock() for name in ordinary_names}
    bound = bind_tool_plan(
        compile_tool_plan(
            specs,
            bindings,
            safety={
                name: SafetyPolicy(allow_headless=name in {"web_fetch", "memory_search"})
                for name in (*ordinary_names, *special_names)
            },
        ),
        handlers,
    )
    transient_handlers = {"computer": MagicMock()}

    built_with: dict[str, object] = {}

    def _build_tool_plan(**kwargs: object):
        built_with.update(kwargs)
        return bound, transient_handlers

    captured: dict[str, object] = {}

    def _capture_executor(*, bound_tool_plan, transient_handlers, **kw: object) -> MagicMock:
        captured["bound_tool_plan"] = bound_tool_plan
        captured["transient_handlers"] = transient_handlers
        captured["denied_tools"] = kw.get("denied_tools")
        return MagicMock()

    class _FakeLoop:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        async def arun(self, _prompt: str) -> str:
            return "ok"

    with (
        patch("core.agent.tool_executor.ToolExecutor", side_effect=_capture_executor),
        patch("core.agent.loop.AgenticLoop", _FakeLoop),
        patch("core.llm.adapters.registry.bootstrap_builtins"),
        patch("core.wiring.bootstrap.ensure_user_profile") as ensure_user_profile,
    ):
        profile = ensure_user_profile.return_value
        asyncio.run(bootstrap.arun_agentic_oneshot("hi", tool_plan_builder=_build_tool_plan))

    ensure_user_profile.assert_called_once_with()
    assert built_with["persistence"].user_profile is profile
    filtered_bound = captured["bound_tool_plan"]
    assert "run_bash" not in filtered_bound.tool_names
    assert "delegate_task" not in filtered_bound.tool_names
    assert "computer_use" not in filtered_bound.tool_names
    assert "computer" not in captured["transient_handlers"]
    # Non-denied tools survive the filter.
    assert "web_fetch" in filtered_bound.tool_names
    assert "memory_search" in filtered_bound.tool_names
    # The REAL enforcement: denied_tools is passed to the executor (the handler
    # filter alone cannot stop the special-cased run_bash / delegate_task).
    assert {"run_bash", "delegate_task", "computer"} <= captured["denied_tools"]


def test_plan_metadata_denies_future_headless_tool_without_static_name_edit() -> None:
    from core.agent.safety import headless_denied_tools
    from core.tools.plan import (
        ExecutionBinding,
        SafetyPolicy,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    name = "future_private_read"
    plan = compile_tool_plan(
        ((ToolSpec(name, "Future", {}), "test"),),
        (ExecutionBinding(name, "test"),),
        safety={name: SafetyPolicy(allow_headless=False)},
    )
    bound = bind_tool_plan(plan, {name: MagicMock()})

    assert headless_denied_tools(bound) == {name}


def test_plan_headless_allow_overrides_legacy_name_fallback() -> None:
    from core.agent.safety import (
        HEADLESS_DENIED_TOOLS,
        headless_denied_tools,
        residual_denied_tools,
    )
    from core.tools.plan import (
        ExecutionBinding,
        SafetyPolicy,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    name = "run_bash"
    plan = compile_tool_plan(
        ((ToolSpec(name, "Compatibility-name probe", {}), "test"),),
        (ExecutionBinding(name, "test", route="special"),),
        safety={name: SafetyPolicy(allow_headless=True)},
    )
    bound = bind_tool_plan(plan, {})

    assert name not in headless_denied_tools(bound)
    assert name not in residual_denied_tools(HEADLESS_DENIED_TOOLS, bound)


def test_executor_denied_tools_refuses_run_bash_at_top() -> None:
    """run_bash is special-cased ahead of handler lookup and auto-approved at
    hitl_level=0, so only the executor-level denied_tools check can stop it.
    Proves the headless gap is actually closed (Codex MCP review)."""
    from core.agent.tool_executor.executor import ToolExecutor

    executor = ToolExecutor(hitl_level=0, denied_tools=frozenset({"run_bash"}))
    result = asyncio.run(
        executor.aexecute(
            "run_bash",
            {"command": "echo pwned", "reason": "regression"},
        )
    )
    assert result.get("denied") is True
    assert "not available" in result.get("error", "")


def test_executor_allowlist_covers_handlers_and_special_tools() -> None:
    """A binding allowlist is an execution rail, not a model prompt hint."""
    from core.agent.tool_executor.executor import ToolExecutor

    allowed = MagicMock(return_value={"result": "ok"})
    blocked = MagicMock(return_value={"result": "unexpected"})
    executor = ToolExecutor(
        action_handlers={"allowed": allowed, "blocked": blocked},
        auto_approve=True,
        allowed_tools=frozenset({"allowed"}),
    )

    assert asyncio.run(executor.aexecute("allowed", {})) == {"result": "ok"}
    denied = asyncio.run(executor.aexecute("blocked", {}))
    special_denied = asyncio.run(executor.aexecute("run_bash", {"command": "echo nope"}))

    assert denied["denied"] is True
    assert special_denied["denied"] is True
    allowed.assert_called_once_with()
    blocked.assert_not_called()
