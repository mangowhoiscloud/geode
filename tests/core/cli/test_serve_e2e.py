"""E2E tests for geode serve tool execution — verifies all tools work via bootstrap."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

load_dotenv(str(Path.home() / ".geode" / ".env"), override=False)


def _run_executor(executor: Any, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(executor.aexecute(tool_name, tool_input))


class TestServeToolExecution:
    """Test that serve's bootstrap path provides working tools."""

    def test_bootstrap_handlers_count(self) -> None:
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        assert len(boot.tool_handlers) >= 44
        assert "web_fetch" in boot.tool_handlers
        assert "general_web_search" in boot.tool_handlers
        assert "generate_data" in boot.tool_handlers
        assert "generate_report" in boot.tool_handlers
        assert "export_json" in boot.tool_handlers

    def test_web_fetch_http(self) -> None:
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        result = boot.tool_handlers["web_fetch"](url="http://example.com", max_chars=200)
        assert "result" in result
        assert "Example Domain" in result["result"]["content"]

    def test_web_fetch_https_ssl_fallback(self) -> None:
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        result = boot.tool_handlers["web_fetch"](url="https://example.com", max_chars=200)
        # Should succeed via SSL fallback
        assert "result" in result

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="Requires ANTHROPIC_API_KEY",
    )
    def test_general_web_search(self) -> None:
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        result = boot.tool_handlers["general_web_search"](query="test", max_results=1)
        assert "result" in result

    def test_executor_web_fetch(self) -> None:
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        executor = ToolExecutor(
            action_handlers=boot.tool_handlers,
            mcp_manager=boot.mcp_manager,
            hitl_level=0,
        )
        result = _run_executor(
            executor, "web_fetch", {"url": "http://example.com", "max_chars": 100}
        )
        assert "error" not in result

    def test_executor_generate_data(self) -> None:
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        executor = ToolExecutor(
            action_handlers=boot.tool_handlers,
            mcp_manager=boot.mcp_manager,
            hitl_level=0,
        )
        result = _run_executor(executor, "generate_data", {"count": 2, "genre": "demo"})
        assert "error" not in result
        assert result["result"]["count"] == 2
        assert result["result"]["records"][0]["label"] == "demo-1"

    def test_executor_output_tools(self, tmp_path: Path) -> None:
        """Serve bootstrap must wire output tools exposed to AgenticLoop."""
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        executor = ToolExecutor(
            action_handlers=boot.tool_handlers,
            mcp_manager=boot.mcp_manager,
            hitl_level=0,
        )

        report = _run_executor(executor, "generate_report", {"subject": "demo-subject"})
        assert "error" not in report
        assert report["result"]["title"] == "GEODE Analysis Report: demo-subject"

        exported = _run_executor(
            executor,
            "export_json",
            {
                "data": {"subject": "demo-subject"},
                "filename": "demo.json",
                "output_dir": str(tmp_path),
            },
        )
        assert "error" not in exported
        assert exported["result"]["exported"] is True

    def test_exposed_agentic_tools_are_executable(self) -> None:
        """Every non-special base tool exposed to the LLM has an executor path."""
        from core.cli.bootstrap import bootstrap_geode
        from core.tools.base import load_all_tool_definitions

        boot = bootstrap_geode(load_env=True)
        handlers = set(boot.tool_handlers)
        executor_special = {"run_bash", "delegate_task"}
        exposed = {tool["name"] for tool in load_all_tool_definitions()}
        missing = sorted(exposed - handlers - executor_special)
        assert missing == []

    def test_daemon_thread_handlers(self) -> None:
        """Simulate serve's daemon thread — handlers must work after propagate."""
        from core.cli.bootstrap import bootstrap_geode
        from core.cli.tool_handlers import _build_tool_handlers

        boot = bootstrap_geode(load_env=True)
        result = {}

        def daemon_work():
            boot.propagate_to_thread()
            handlers = _build_tool_handlers(
                mcp_manager=boot.mcp_manager,
                skill_registry=boot.skill_registry,
            )
            result["count"] = len(handlers)
            result["web_fetch"] = "web_fetch" in handlers
            r = handlers["web_fetch"](url="http://example.com", max_chars=100)
            result["fetch_ok"] = "result" in r

        t = threading.Thread(target=daemon_work, daemon=True)
        t.start()
        t.join(timeout=15)

        assert result.get("count", 0) >= 44
        assert result.get("web_fetch") is True
        assert result.get("fetch_ok") is True

    def test_executor_in_daemon_thread(self) -> None:
        """Full executor path in daemon thread — matches actual serve execution."""
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode
        from core.cli.tool_handlers import _build_tool_handlers

        boot = bootstrap_geode(load_env=True)
        result = {}

        def daemon_work():
            boot.propagate_to_thread()
            handlers = _build_tool_handlers(
                mcp_manager=boot.mcp_manager,
                skill_registry=boot.skill_registry,
            )
            executor = ToolExecutor(
                action_handlers=handlers,
                mcp_manager=boot.mcp_manager,
                hitl_level=0,
            )
            r = _run_executor(
                executor, "web_fetch", {"url": "http://example.com", "max_chars": 100}
            )
            result["ok"] = "error" not in r
            result["registered"] = len(executor.registered_tools)

        t = threading.Thread(target=daemon_work, daemon=True)
        t.start()
        t.join(timeout=15)

        assert result.get("ok") is True
        assert result.get("registered", 0) >= 44
