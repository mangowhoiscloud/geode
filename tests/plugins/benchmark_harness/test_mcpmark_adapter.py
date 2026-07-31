import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from plugins.benchmark_harness.mcpmark_geode_agent import (
    MCPMarkGeodeTool,
    _build_loop,
    _github_repo_visibility,
    _normalize_tool_arguments,
    _patch_mcpmark_github_visibility,
    _route_from_model,
    register_mcpmark_agent,
)
from plugins.benchmark_harness.trajectory_artifacts import export_mcpmark_trajectory


def test_mcpmark_loop_validates_colliding_tool_with_mcp_schema() -> None:
    class MCPServer:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def call_tool(self, name: str, arguments: dict[str, object]) -> str:
            self.calls.append((name, arguments))
            return "ok"

    server = MCPServer()
    tool = MCPMarkGeodeTool(
        mcp_server=server,
        schema={
            "name": "write_file",
            "description": "MCP filesystem writer",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    )
    loop = _build_loop(
        tools=[tool],
        instruction="write the answer",
        model="gpt-5.6-sol",
        provider="openai",
        source="subscription",
        effort="high",
        timeout=30,
    )

    result = asyncio.run(
        loop.executor.aexecute(
            "write_file",
            {"path": "fixture/answer.txt", "content": "answer"},
        )
    )
    compatibility_result = asyncio.run(
        loop.executor.aexecute(
            "write_file",
            {"file_path": "fixture/compatibility.txt", "content": "compatibility"},
        )
    )

    assert result == {"result": "ok"}
    assert compatibility_result == {"result": "ok"}
    assert server.calls == [
        ("write_file", {"path": "fixture/answer.txt", "content": "answer"}),
        (
            "write_file",
            {"path": "fixture/compatibility.txt", "content": "compatibility"},
        ),
    ]


def test_route_from_geode_model_label() -> None:
    assert _route_from_model("geode-gpt-5.5") == ("gpt-5.5", "openai", "subscription")
    assert _route_from_model("geode-claude-sonnet-4-6") == (
        "claude-sonnet-4-6",
        "anthropic",
        "subscription",
    )
    assert _route_from_model("geode-glm-4-6") == ("glm-4-6", "zhipuai", "api_key")


def test_register_mcpmark_agent() -> None:
    registry: dict[str, object] = {}
    register_mcpmark_agent(registry)
    assert "geode" in registry


def test_github_repo_visibility_defaults_private(monkeypatch) -> None:
    monkeypatch.delenv("GEODE_MCPMARK_GITHUB_REPO_VISIBILITY", raising=False)
    assert _github_repo_visibility() == "private"

    monkeypatch.setenv("GEODE_MCPMARK_GITHUB_REPO_VISIBILITY", "public")
    assert _github_repo_visibility() == "public"

    monkeypatch.setenv("GEODE_MCPMARK_GITHUB_REPO_VISIBILITY", "invalid")
    assert _github_repo_visibility() == "private"


def test_normalize_tool_arguments_maps_file_path_alias() -> None:
    schema = {"inputSchema": {"properties": {"path": {"type": "string"}}}}
    assert _normalize_tool_arguments(schema, {"file_path": "fixture/a"}) == {"path": "fixture/a"}

    assert _normalize_tool_arguments(schema, {"path": "fixture/a", "file_path": "fixture/b"}) == {
        "path": "fixture/a",
        "file_path": "fixture/b",
    }


def test_normalize_tool_arguments_drops_empty_start_cursor() -> None:
    schema = {"inputSchema": {"properties": {"start_cursor": {"type": "string"}}}}

    for empty_cursor in ("", "undefined", "null", "none", None, 0):
        assert _normalize_tool_arguments(
            schema, {"start_cursor": empty_cursor, "page_size": 100}
        ) == {
            "page_size": 100,
        }

    assert _normalize_tool_arguments(schema, {"start_cursor": "abc", "page_size": 100}) == {
        "start_cursor": "abc",
        "page_size": 100,
    }


def test_mcpmark_adapter_bootstraps_llm_adapters() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "benchmark_harness"
        / "mcpmark_geode_agent.py"
    ).read_text(encoding="utf-8")

    assert "bootstrap_builtins" in source
    assert "bootstrap_builtins()" in source


def test_mcpmark_adapter_keeps_service_specific_server_overrides() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "benchmark_harness"
        / "mcpmark_geode_agent.py"
    ).read_text(encoding="utf-8")

    assert "ghcr.io/github/github-mcp-server:v0.15.0" in source
    assert '"--python"' in source
    assert "sys.executable" in source


def test_mcpmark_adapter_supports_public_github_fixture_opt_in() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "benchmark_harness"
        / "mcpmark_geode_agent.py"
    ).read_text(encoding="utf-8")

    assert "GEODE_MCPMARK_GITHUB_REPO_VISIBILITY" in source
    assert '"PATCH"' in source
    assert 'json={"private": False}' in source


def test_mcpmark_export_uses_shared_trajectory_schema(tmp_path) -> None:
    from core.observability.session_timeline import SessionTimeline

    timeline = SessionTimeline("s-mcpmark")
    timeline.record_user_message("benchmark task")
    timeline.record_assistant_message("done")
    log_path = tmp_path / "tool-calls.json"
    log_path.write_text("[]\n")

    exported = export_mcpmark_trajectory(
        loop=SimpleNamespace(_session_id="s-mcpmark"),
        instruction="private benchmark task",
        result=SimpleNamespace(rounds=1),
        tool_call_log_file=str(log_path),
        model="gpt-5.6",
        provider="openai",
        source="subscription",
    )

    trajectory = json.loads(exported.read_text())
    assert trajectory["schema_id"] == "geode.trajectory@1"
    assert trajectory["source"]["harness"] == "mcpmark"
    assert trajectory["source"]["task"] != "private benchmark task"
    assert trajectory["integrity"]["record_count"] == 2


def test_public_github_fixture_patch_wraps_create_initial_state(monkeypatch) -> None:
    class GitHubStateManager:
        def __init__(self) -> None:
            self.requests = []

        def _create_initial_state(self, task):
            return SimpleNamespace(metadata={"owner": "owner", "repo_name": "repo"})

        def _request_with_retry(self, method, url, json):
            self.requests.append((method, url, json))
            return SimpleNamespace(status_code=200, text="ok")

    module = SimpleNamespace(GitHubStateManager=GitHubStateManager)
    monkeypatch.setitem(sys.modules, "src.mcp_services.github.github_state_manager", module)
    monkeypatch.setenv("GEODE_MCPMARK_GITHUB_REPO_VISIBILITY", "public")

    _patch_mcpmark_github_visibility()
    manager = GitHubStateManager()
    state_info = manager._create_initial_state(SimpleNamespace())

    assert state_info.metadata["visibility"] == "public"
    assert manager.requests == [
        ("PATCH", "https://api.github.com/repos/owner/repo", {"private": False})
    ]
