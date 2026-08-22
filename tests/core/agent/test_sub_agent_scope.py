"""Tests for SubAgentManager denied_tools (sandbox hardening)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.agent.sub_agent import SUBAGENT_DENIED_TOOLS, SubAgentManager
from core.orchestration.isolated_execution import IsolatedRunner
from core.tools.plan import (
    ExecutionBinding,
    SafetyPolicy,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _make_handler(name: str) -> Any:
    """Create a simple mock handler."""
    return MagicMock(return_value={"status": "ok", "tool": name})


class TestSubAgentDeniedTools:
    """Test denied_tools filtering in SubAgentManager."""

    def test_denied_tools_stored(self) -> None:
        runner = IsolatedRunner()
        denied = {"set_api_key", "manage_auth"}
        mgr = SubAgentManager(runner, denied_tools=denied)
        assert mgr._protocol.denied_tools == SUBAGENT_DENIED_TOOLS | denied

    def test_denied_tools_default_to_security_baseline(self) -> None:
        runner = IsolatedRunner()
        mgr = SubAgentManager(runner)
        assert mgr._protocol.denied_tools == SUBAGENT_DENIED_TOOLS

    def test_default_subagent_denied_tools_defined(self) -> None:
        """SUBAGENT_DENIED_TOOLS constant contains expected tools."""
        assert "set_api_key" in SUBAGENT_DENIED_TOOLS
        assert "manage_auth" in SUBAGENT_DENIED_TOOLS
        assert "delegate_task" in SUBAGENT_DENIED_TOOLS
        assert "calendar_create_event" in SUBAGENT_DENIED_TOOLS

    def test_plan_metadata_denies_future_subagent_tool(self) -> None:
        name = "future_parent_only"
        plan = compile_tool_plan(
            ((ToolSpec(name, "Future", {}), "test"),),
            (ExecutionBinding(name, "test"),),
            safety={name: SafetyPolicy(allow_subagents=False)},
        )
        bound = bind_tool_plan(plan, {name: _make_handler(name)})

        mgr = SubAgentManager(IsolatedRunner(), bound_tool_plan=bound)

        assert name in mgr._protocol.denied_tools

    def test_plan_subagent_allow_overrides_legacy_name_fallback(self) -> None:
        name = "delegate_task"
        plan = compile_tool_plan(
            ((ToolSpec(name, "Compatibility-name probe", {}), "test"),),
            (ExecutionBinding(name, "test"),),
            safety={name: SafetyPolicy(allow_subagents=True)},
        )
        bound = bind_tool_plan(plan, {name: _make_handler(name)})

        mgr = SubAgentManager(IsolatedRunner(), bound_tool_plan=bound)

        assert name not in mgr._protocol.denied_tools

    def test_denied_tools_not_in_safe_set(self) -> None:
        """Denied tools should not overlap with commonly-needed tools."""
        safe_tools = {"memory_search", "web_search", "analyze_subject", "list_subjects"}
        assert SUBAGENT_DENIED_TOOLS.isdisjoint(safe_tools)

    def test_filtered_handlers_exclude_denied(self) -> None:
        """When _execute_with_agentic_loop filters, denied tools are removed."""
        handlers = {
            "set_api_key": _make_handler("set_api_key"),
            "memory_search": _make_handler("memory_search"),
            "web_search": _make_handler("web_search"),
            "manage_auth": _make_handler("manage_auth"),
        }
        denied = {"set_api_key", "manage_auth"}
        filtered = {k: v for k, v in handlers.items() if k not in denied}
        assert "set_api_key" not in filtered
        assert "manage_auth" not in filtered
        assert "memory_search" in filtered
        assert "web_search" in filtered

    def test_no_denied_tools_passes_all(self) -> None:
        """With no denied_tools, all handlers pass through."""
        handlers = {
            "set_api_key": _make_handler("set_api_key"),
            "memory_search": _make_handler("memory_search"),
        }
        denied: set[str] = set()
        filtered = {k: v for k, v in handlers.items() if k not in denied}
        assert len(filtered) == 2
