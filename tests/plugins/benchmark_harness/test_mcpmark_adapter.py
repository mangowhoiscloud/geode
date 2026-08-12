import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from plugins.benchmark_harness.mcpmark_geode_agent import (
    _CODEX_DISABLED_FEATURES,
    CodexMCPMarkAgent,
    GeodeMCPMarkAgent,
    MCPMarkGeodeTool,
    _build_loop,
    _codex_mcp_config,
    _codex_model,
    _codex_subscription_environment,
    _github_repo_visibility,
    _normalize_tool_arguments,
    _patch_mcpmark_github_visibility,
    _route_from_model,
    _summarize_codex_exec,
    _usage_dict,
    register_mcpmark_agent,
)
from plugins.benchmark_harness.trajectory_artifacts import (
    export_codex_mcpmark_trajectory,
    export_mcpmark_trajectory,
)


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


def _geode_agent_for_execute(monkeypatch, loop):
    class MCPServer:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def list_tools(self):
            return []

    agent = object.__new__(GeodeMCPMarkAgent)
    agent.litellm_input_model_name = "geode-gpt-5.4"
    agent.reasoning_effort = "high"
    agent.timeout = 0.01
    agent.usage_tracker = SimpleNamespace(update=lambda **_kwargs: None)
    agent._reset_progress = lambda: None
    agent._refresh_service_config = lambda: None

    async def create_server():
        return MCPServer()

    agent._create_mcp_server = create_server
    monkeypatch.setattr(
        "plugins.benchmark_harness.mcpmark_geode_agent._build_loop",
        lambda **_kwargs: loop,
    )
    return agent


def test_geode_mcpmark_timeout_is_a_performance_outcome(monkeypatch) -> None:
    class Loop:
        marked_error = False
        cognitive_state = SimpleNamespace(round_count=3)
        _tool_processor = SimpleNamespace(tool_log=[])

        async def arun(self, _instruction):
            assert os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] == "1"
            await asyncio.Event().wait()

        def _terminal_result(self, reason, text, *, rounds, error, tool_calls):
            return SimpleNamespace(
                text=text,
                rounds=rounds,
                error=str(reason) if error else None,
                termination_reason=reason,
                tool_calls=tool_calls,
                usage=None,
            )

        async def _afinalize_and_return(self, result, _instruction, _rounds):
            return result

        async def amark_session_error(self):
            self.marked_error = True

    loop = Loop()
    agent = _geode_agent_for_execute(monkeypatch, loop)
    monkeypatch.setenv("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "prior")

    result = asyncio.run(agent.execute("task"))

    assert result["success"] is False
    assert result["error"] == "time_budget_expired"
    assert result["turn_count"] == 3
    assert loop.marked_error is True
    assert os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] == "prior"


def test_geode_mcpmark_propagates_runtime_errors(monkeypatch) -> None:
    class Loop:
        marked_error = False

        async def arun(self, _instruction):
            raise RuntimeError("provider transport failed")

        async def amark_session_error(self):
            self.marked_error = True

    loop = Loop()
    agent = _geode_agent_for_execute(monkeypatch, loop)

    with pytest.raises(RuntimeError, match="provider transport failed"):
        asyncio.run(agent.execute("task"))

    assert loop.marked_error is True


def test_geode_mcpmark_does_not_misclassify_inner_timeout(monkeypatch) -> None:
    class Loop:
        async def arun(self, _instruction):
            raise TimeoutError("provider read timed out")

        async def amark_session_error(self):
            return None

    agent = _geode_agent_for_execute(monkeypatch, Loop())

    with pytest.raises(TimeoutError, match="provider read timed out"):
        asyncio.run(agent.execute("task"))


def test_codex_mcpmark_timeout_is_a_performance_outcome(monkeypatch) -> None:
    class Process:
        returncode = 0
        killed = False

        async def communicate(self, _input=None):
            if not self.killed:
                await asyncio.Event().wait()
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

    process = Process()

    async def create_process(*_args, **_kwargs):
        return process

    agent = object.__new__(CodexMCPMarkAgent)
    agent.litellm_input_model_name = "codex-gpt-5.4"
    agent.reasoning_effort = "high"
    agent.timeout = 0.01
    agent.mcp_service = "filesystem"
    agent.usage_tracker = SimpleNamespace(update=lambda **_kwargs: None)
    agent._reset_progress = lambda: None
    agent._refresh_service_config = lambda: None
    agent._create_stdio_server = lambda: SimpleNamespace(
        params=SimpleNamespace(command="npx", args=["server"])
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    result = asyncio.run(agent.execute("task"))

    assert result["success"] is False
    assert result["error"] == "codex exec exceeded MCPMark timeout (0.01s)"
    assert process.killed is True


def test_mcpmark_tool_returns_call_tool_result_as_data() -> None:
    class CallToolResult:
        def model_dump(self, *, by_alias: bool, exclude_none: bool) -> dict[str, object]:
            assert by_alias is True
            assert exclude_none is True
            return {
                "content": [{"type": "text", "text": '{"answer": 42}'}],
                "structuredContent": {"answer": 42},
                "isError": False,
            }

    class MCPServer:
        async def call_tool(self, _name: str, _arguments: dict[str, object]) -> CallToolResult:
            return CallToolResult()

    tool = MCPMarkGeodeTool(
        mcp_server=MCPServer(),
        schema={"name": "read", "inputSchema": {"type": "object"}},
    )

    result = asyncio.run(tool.aexecute())

    assert result["structuredContent"] == {"answer": 42}
    assert isinstance(result["content"], list)


def test_route_from_geode_model_label() -> None:
    assert _route_from_model("geode-gpt-5.5") == ("gpt-5.5", "openai", "subscription")
    assert _route_from_model("geode-claude-sonnet-4-6") == (
        "claude-sonnet-4-6",
        "anthropic",
        "subscription",
    )
    assert _route_from_model("geode-glm-4-6") == ("glm-4-6", "zhipuai", "api_key")


def test_usage_dict_translates_geode_usage_for_mcpmark_summary() -> None:
    result = SimpleNamespace(
        usage=SimpleNamespace(
            to_dict=lambda: {
                "input_tokens": 100,
                "output_tokens": 20,
                "thinking_tokens": 8,
                "cache_read_tokens": 40,
            }
        )
    )

    usage = _usage_dict(result)

    assert usage["total_tokens"] == 120
    assert usage["reasoning_tokens"] == 8
    assert usage["thinking_tokens"] == 8
    assert usage["cache_read_tokens"] == 40


def test_register_mcpmark_agent() -> None:
    registry: dict[str, object] = {}
    register_mcpmark_agent(registry)
    assert set(registry) == {"codex", "geode"}


def test_codex_mcpmark_command_contract() -> None:
    config = _codex_mcp_config("npx", ["-y", "server", "fixture"], 300)

    assert config == (
        '{command="npx",args=["-y", "server", "fixture"],'
        "startup_timeout_sec=120,tool_timeout_sec=300,required=true,"
        'default_tools_approval_mode="approve"}'
    )
    assert _codex_model("codex-gpt-5.4") == "gpt-5.4"
    assert _codex_model("openai/gpt-5.4") == "gpt-5.4"
    assert {"apps", "multi_agent", "shell_tool", "unified_exec"} <= set(_CODEX_DISABLED_FEATURES)


def test_codex_subscription_environment_drops_api_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("CODEX_API_KEY", "api-key")
    monkeypatch.setenv("OPENAI_API_KEY", "upstream-placeholder")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CODEX_HOME", "/kept/login-home")

    env = _codex_subscription_environment()

    assert "CODEX_ACCESS_TOKEN" not in env
    assert "CODEX_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert "OPENAI_BASE_URL" not in env
    assert env["CODEX_HOME"] == "/kept/login-home"


def test_summarize_codex_exec_keeps_usage_tools_and_failure() -> None:
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": "mcp_tool_call",
                "server": "mcpmark",
                "tool": "write_file",
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "item-2", "type": "agent_message", "text": "done"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "cache_write_input_tokens": 5,
                "output_tokens": 20,
                "reasoning_output_tokens": 8,
            },
        },
    ]
    summary = _summarize_codex_exec("\n".join(json.dumps(event) for event in events))

    assert summary == {
        "thread_id": "thread-1",
        "output": "done",
        "turn_count": 1,
        "mcp_tool_calls": 1,
        "token_usage": {
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "cache_write_input_tokens": 5,
            "output_tokens": 20,
            "reasoning_tokens": 8,
            "total_tokens": 120,
        },
        "error": "",
    }

    failed = _summarize_codex_exec(
        json.dumps({"type": "turn.failed", "error": {"message": "quota"}})
    )
    assert failed["error"] == "quota"


def test_codex_mcpmark_export_uses_shared_trajectory_schema(tmp_path) -> None:
    log_path = tmp_path / "execution.log"
    rows = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {
                "id": "call-1",
                "type": "mcp_tool_call",
                "server": "mcpmark",
                "tool": "write_file",
                "arguments": {"path": "private/file.txt", "content": "private"},
                "result": {"content": [{"type": "text", "text": "wrote private/file.txt"}]},
                "error": None,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "message-1", "type": "agent_message", "text": "private done"},
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    exported = export_codex_mcpmark_trajectory(
        exec_log_path=log_path,
        instruction="private benchmark task",
        model="gpt-5.4",
        effort="high",
    )
    artifact = json.loads(exported.read_text(encoding="utf-8"))

    assert artifact["schema_id"] == "geode.trajectory@1"
    assert artifact["source"]["session"] == "thread-1"
    assert artifact["integrity"]["quality"]["tool_pairing"]["paired"] == 1
    assert artifact["integrity"]["quality"]["replay_fidelity"] == "reduced"
    assert artifact["integrity"]["quality"]["payload_issue_events"] == 4
    assert artifact["outcome"]["protocol_violations"] == 0
    assert artifact["artifact_digests"][0]["path"] == f"{tmp_path.name}/execution.log"
    serialized = json.dumps(artifact)
    assert "private benchmark task" not in serialized
    assert "private/file.txt" not in serialized
    assert "private done" not in serialized


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
