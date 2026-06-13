"""Tests for L5 Tool Protocol and ToolRegistry."""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any

import pytest
from core.tools.base import Tool
from core.tools.registry import ToolRegistry


def _run_registry(registry: ToolRegistry, name: str, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(registry.aexecute(name, **kwargs))


class DummyTool:
    """A minimal tool implementation for testing."""

    @property
    def name(self) -> str:
        return "dummy_tool"

    @property
    def description(self) -> str:
        return "A dummy tool for testing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Test input"},
            },
            "required": ["input"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"result": f"processed: {kwargs.get('input', '')}"}

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        return self.execute(**kwargs)


class AnotherTool:
    """Second tool for multi-registration tests."""

    @property
    def name(self) -> str:
        return "another_tool"

    @property
    def description(self) -> str:
        return "Another test tool."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"result": "done"}


class AsyncPreferredTool:
    """Tool with an async-native execution path."""

    @property
    def name(self) -> str:
        return "async_preferred"

    @property
    def description(self) -> str:
        return "Async preferred test tool."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("sync execute path used")

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"result": "async"}


class TestToolProtocol:
    def test_dummy_satisfies_protocol(self):
        """DummyTool satisfies Tool protocol (runtime_checkable)."""
        tool = DummyTool()
        assert isinstance(tool, Tool)

    def test_protocol_properties(self):
        tool = DummyTool()
        assert tool.name == "dummy_tool"
        assert "dummy" in tool.description.lower()
        assert tool.parameters["type"] == "object"

    def test_protocol_execute(self):
        tool = DummyTool()
        result = tool.execute(input="hello")
        assert result == {"result": "processed: hello"}


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)
        assert registry.get("dummy_tool") is tool

    def test_get_nonexistent(self):
        registry = ToolRegistry()
        assert registry.get("nope") is None

    def test_duplicate_registration_raises(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(DummyTool())

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        tools = registry.list_tools()
        assert sorted(tools) == ["another_tool", "dummy_tool"]

    def test_to_anthropic_tools(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        tools = registry.to_anthropic_tools()

        assert len(tools) == 1
        tool_def = tools[0]
        assert tool_def["name"] == "dummy_tool"
        assert "description" in tool_def
        assert tool_def["input_schema"]["type"] == "object"
        assert "input" in tool_def["input_schema"]["properties"]

    def test_to_anthropic_tools_multiple(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        tools = registry.to_anthropic_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"dummy_tool", "another_tool"}

    def test_execute_by_name(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        result = _run_registry(registry, "dummy_tool", input="test")
        assert result == {"result": "processed: test"}

    def test_aexecute_prefers_async_tool_path(self):
        registry = ToolRegistry()
        registry.register(AsyncPreferredTool())
        result = asyncio.run(registry.aexecute("async_preferred"))
        assert result == {"result": "async"}

    def test_aexecute_rejects_sync_only_tool(self):
        class ThreadReportingTool(DummyTool):
            async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
                raise AttributeError("sync-only")

            def execute(self, **kwargs: Any) -> dict[str, Any]:
                return {"thread": threading.get_ident()}

        registry = ToolRegistry()
        registry.register(ThreadReportingTool())
        with pytest.raises(AttributeError, match="sync-only"):
            asyncio.run(registry.aexecute("dummy_tool"))

    def test_execute_nonexistent_raises(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            _run_registry(registry, "nonexistent")

    def test_aexecute_nonexistent_raises(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            asyncio.run(registry.aexecute("nonexistent"))

    def test_migrated_tool_handlers_do_not_call_sync_execute(self):
        from core.cli.tool_handlers.single_tool import (
            _build_calendar_handlers,
            _build_notification_handlers,
        )

        calendar_source = inspect.getsource(_build_calendar_handlers)
        notification_source = inspect.getsource(_build_notification_handlers)

        assert "list_tool.execute(" not in calendar_source
        assert "create_tool.execute(" not in calendar_source
        assert "notification_tool.execute(" not in notification_source
        assert ".aexecute(" in calendar_source
        assert ".aexecute(" in notification_source

    def test_len(self):
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(DummyTool())
        assert len(registry) == 1

    def test_contains(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        assert "dummy_tool" in registry
        assert "nope" not in registry

    def test_to_openai_tools(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        tools = registry.to_openai_tools()

        assert len(tools) == 1
        tool_def = tools[0]
        assert tool_def["type"] == "function"
        assert tool_def["function"]["name"] == "dummy_tool"
        assert "description" in tool_def["function"]
        assert tool_def["function"]["parameters"]["type"] == "object"
        assert "input" in tool_def["function"]["parameters"]["properties"]

    def test_to_openai_tools_multiple(self):
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        tools = registry.to_openai_tools()
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"dummy_tool", "another_tool"}

    def test_to_openai_tools_matches_anthropic_count(self):
        """OpenAI and Anthropic tool lists have the same tools."""
        registry = ToolRegistry()
        registry.register(DummyTool())
        registry.register(AnotherTool())
        anthropic_tools = registry.to_anthropic_tools()
        openai_tools = registry.to_openai_tools()
        assert len(anthropic_tools) == len(openai_tools)
        anthropic_names = {t["name"] for t in anthropic_tools}
        openai_names = {t["function"]["name"] for t in openai_tools}
        assert anthropic_names == openai_names
