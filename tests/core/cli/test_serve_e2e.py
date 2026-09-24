"""E2E tests for geode serve tool execution — verifies all tools work via bootstrap."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest


def _run_executor(executor: Any, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(executor.aexecute(tool_name, tool_input))


@pytest.fixture
def example_http(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Keep bootstrap, async delegation, and HTML extraction; isolate HTTP only."""

    def respond(url: str, **kwargs: Any) -> httpx.Response:
        assert url in {"http://example.com", "https://example.com"}
        assert kwargs.get("follow_redirects", True) is True
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            headers={"content-type": "text/html"},
            text="<html><body><h1>Example Domain</h1><p>Offline fixture.</p></body></html>",
        )

    get = MagicMock(side_effect=respond)
    monkeypatch.setattr(httpx, "get", get)
    return get


class TestServeToolExecution:
    """Test that serve's bootstrap path provides working tools."""

    def test_bootstrap_handlers_count(self) -> None:
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode()
        assert len(boot.tool_handlers) >= 44
        assert "calculate" in boot.tool_handlers
        assert "web_fetch" in boot.tool_handlers
        assert "general_web_search" in boot.tool_handlers
        assert "generate_data" in boot.tool_handlers
        assert "generate_report" in boot.tool_handlers
        assert "export_json" in boot.tool_handlers

    def test_web_fetch_http(self, example_http: MagicMock) -> None:
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode()
        # PR-LOOP-POLLUTION-FIX (2026-06-12) — delegated handlers are async now.
        result = asyncio.run(
            boot.tool_handlers["web_fetch"](url="http://example.com", max_chars=200)
        )
        assert "result" in result
        assert "Example Domain" in result["result"]["content"]
        assert "<h1>" not in result["result"]["content"]
        assert result["result"]["tls_verified"] is True
        example_http.assert_called_once_with(
            "http://example.com", timeout=10.0, follow_redirects=True
        )

    def test_web_fetch_https_ssl_fallback(self, example_http: MagicMock) -> None:
        from core.cli.bootstrap import bootstrap_geode

        response = example_http.side_effect("https://example.com")
        example_http.side_effect = [httpx.ConnectError("fixture certificate failure"), response]
        boot = bootstrap_geode()
        result = asyncio.run(
            boot.tool_handlers["web_fetch"](url="https://example.com", max_chars=200)
        )
        assert "result" in result
        assert "Example Domain" in result["result"]["content"]
        assert result["result"]["tls_verified"] is False
        assert example_http.call_count == 2
        assert "verify" not in example_http.call_args_list[0].kwargs
        assert example_http.call_args_list[1].kwargs["verify"] is False

    @pytest.mark.live
    def test_general_web_search(self) -> None:
        from dotenv import load_dotenv

        load_dotenv(str(Path.home() / ".geode" / ".env"), override=False)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("Requires ANTHROPIC_API_KEY")

        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode(load_env=True)
        result = asyncio.run(boot.tool_handlers["general_web_search"](query="test", max_results=1))
        assert "result" in result

    def test_executor_web_fetch(self, example_http: MagicMock) -> None:
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode()
        executor = ToolExecutor(
            action_handlers=boot.tool_handlers,
            mcp_manager=boot.mcp_manager,
            hitl_level=0,
        )
        result = _run_executor(
            executor, "web_fetch", {"url": "http://example.com", "max_chars": 100}
        )
        assert "error" not in result
        assert "Example Domain" in result["result"]["content"]
        example_http.assert_called_once()

    def test_executor_generate_data(self) -> None:
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode()
        executor = ToolExecutor(
            action_handlers=boot.tool_handlers,
            mcp_manager=boot.mcp_manager,
            hitl_level=0,
        )
        result = _run_executor(executor, "generate_data", {"count": 2, "genre": "demo"})
        assert "error" not in result
        assert result["result"]["count"] == 2
        assert result["result"]["records"][0]["label"] == "demo-1"

    def test_executor_calculate(self) -> None:
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode()
        executor = ToolExecutor(
            action_handlers=boot.tool_handlers,
            mcp_manager=boot.mcp_manager,
            hitl_level=0,
        )
        result = _run_executor(executor, "calculate", {"expression": "1/8 + 0.125"})
        assert "error" not in result
        assert result["result"]["value"] == "1/4"
        assert result["result"]["exact"] is True

    def test_executor_output_tools(self, tmp_path: Path) -> None:
        """Serve bootstrap must wire output tools exposed to AgenticLoop."""
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode

        boot = bootstrap_geode()
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
        """The native runtime advertises exactly its executable bound plan."""
        from core.tools.composition import compose_tool_plan

        bound, _transient = compose_tool_plan()
        assert tuple(bound.schema_map) == tuple(bound.execution_map)

    def test_daemon_thread_handlers(self, example_http: MagicMock) -> None:
        """Simulate serve's daemon thread — handlers must work after propagate."""
        from core.cli.bootstrap import bootstrap_geode
        from core.cli.tool_handlers import _build_tool_handlers

        boot = bootstrap_geode()
        result = {}

        def daemon_work():
            boot.propagate_to_thread()
            handlers = _build_tool_handlers(
                mcp_manager=boot.mcp_manager,
                skill_registry=boot.skill_registry,
            )
            result["count"] = len(handlers)
            result["web_fetch"] = "web_fetch" in handlers
            r = asyncio.run(handlers["web_fetch"](url="http://example.com", max_chars=100))
            result["fetch_ok"] = "result" in r

        t = threading.Thread(target=daemon_work, daemon=True)
        t.start()
        t.join(timeout=15)

        assert not t.is_alive()
        assert result.get("count", 0) >= 44
        assert result.get("web_fetch") is True
        assert result.get("fetch_ok") is True
        example_http.assert_called_once()

    def test_executor_in_daemon_thread(self, example_http: MagicMock) -> None:
        """Full executor path in daemon thread — matches actual serve execution."""
        from core.agent.tool_executor import ToolExecutor
        from core.cli.bootstrap import bootstrap_geode
        from core.cli.tool_handlers import _build_tool_handlers

        boot = bootstrap_geode()
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

        assert not t.is_alive()
        assert result.get("ok") is True
        assert result.get("registered", 0) >= 44
        example_http.assert_called_once()
