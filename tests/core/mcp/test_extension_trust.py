"""Trust-before-launch and deny-default MCP broker tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.extensions import ExtensionPolicy, ExtensionState
from core.mcp.config_catalog import MCPConfigCatalog
from core.mcp.manager import MCPServerManager
from core.mcp.sandbox import resolve_mcp_sandbox_argv
from core.mcp.stdio_client import StdioMCPClient


def _policy(name: str, execution: str, *, capabilities: list[str] | None = None):
    return ExtensionPolicy.from_mapping(
        {
            "version": 1,
            "extensions": {
                f"mcp:{name}": {
                    "enabled": True,
                    "trusted": execution == "trusted",
                    "execution": execution,
                    "capabilities": capabilities or [],
                }
            },
        }
    )


def test_missing_policy_never_constructs_mcp_client() -> None:
    manager = MCPServerManager(extension_policy=ExtensionPolicy.empty())
    manager._catalog.servers["poison"] = {"command": "poison"}
    manager._pool._client_factory = MagicMock()

    assert manager._get_client("poison") is None

    manager._pool._client_factory.assert_not_called()
    assert manager.extension_decisions[0].state is ExtensionState.REJECTED


def test_brokered_server_without_os_sandbox_is_degraded_before_spawn() -> None:
    manager = MCPServerManager(extension_policy=_policy("confined", "brokered"))
    manager._catalog.servers["confined"] = {
        "command": "server",
        "execution": "brokered",
    }
    manager._pool._client_factory = MagicMock()

    with patch(
        "core.mcp.connection_pool.resolve_mcp_sandbox_argv",
        return_value=(None, "sandbox unavailable"),
    ):
        assert manager._get_client("confined") is None

    manager._pool._client_factory.assert_not_called()
    decision = manager.extension_decisions[0]
    assert decision.state is ExtensionState.DEGRADED
    assert decision.reason == "sandbox unavailable"


def test_mcp_manifest_typos_degrade_before_client_construction() -> None:
    manager = MCPServerManager(extension_policy=_policy("confined", "brokered"))
    manager._catalog.servers["confined"] = {
        "command": "server",
        "execution": "brokered",
        "enabledd": False,
    }
    manager._pool._client_factory = MagicMock()

    assert manager._get_client("confined") is None
    manager._pool._client_factory.assert_not_called()
    assert manager.extension_decisions[0].reason.startswith("invalid manifest:")


def test_brokered_server_uses_only_explicit_environment(tmp_path: Path) -> None:
    manager = MCPServerManager(extension_policy=_policy("confined", "brokered"))
    manager._catalog.servers["confined"] = {
        "command": "server",
        "args": ["--stdio"],
        "env": {"EXPLICIT_TOKEN": "value"},
        "execution": "brokered",
    }
    client = MagicMock()
    client.connect.return_value = True
    factory = MagicMock(return_value=client)
    manager._pool._client_factory = factory

    with (
        patch("core.mcp.connection_pool.tempfile.mkdtemp", return_value=str(tmp_path)),
        patch(
            "core.mcp.connection_pool.resolve_mcp_sandbox_argv",
            return_value=(["/sandbox", "--", "/usr/bin/server", "--stdio"], None),
        ),
    ):
        assert manager._get_client("confined") is client

    factory.assert_called_once_with(
        command="/sandbox",
        args=["--", "/usr/bin/server", "--stdio"],
        env={"EXPLICIT_TOKEN": "value"},
        inherit_env=False,
        working_dir=str(tmp_path),
        cleanup_working_dir=True,
    )


def test_stdio_client_clean_environment_reaches_popen(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AMBIENT_SECRET", "must-not-leak")
    process = MagicMock()
    process.pid = 42
    process.poll.return_value = None
    process.stderr = None
    client = StdioMCPClient(
        command="/sandbox",
        env={"EXPLICIT": "yes"},
        timeout_s=0,
        inherit_env=False,
        working_dir=str(tmp_path),
    )

    with (
        patch("core.mcp.stdio_client.subprocess.Popen", return_value=process) as popen,
        patch.object(
            client,
            "_send_request",
            side_effect=[{"protocolVersion": "2025-06-18"}, {"tools": []}],
        ),
        patch.object(client, "_send_notification"),
    ):
        assert client.connect() is True

    assert popen.call_args.kwargs["env"] == {"EXPLICIT": "yes"}
    assert popen.call_args.kwargs["cwd"] == str(tmp_path)
    assert "AMBIENT_SECRET" not in popen.call_args.kwargs["env"]


def test_macos_broker_profile_is_deny_default(monkeypatch, tmp_path: Path) -> None:
    from core.mcp import sandbox

    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _command: "/usr/bin/server")
    monkeypatch.setattr(
        sandbox, "sandbox_binary_status", lambda: ("sandbox-exec", "/usr/bin/sandbox-exec")
    )

    argv, error = resolve_mcp_sandbox_argv("server", ["--stdio"], scratch=tmp_path)

    assert error is None and argv is not None
    profile = argv[argv.index("-p") + 1]
    assert "(deny default)" in profile
    assert "(allow network" not in profile
    assert str(Path.home()) not in profile


def test_linux_broker_uses_closed_namespaces_and_system_roots(monkeypatch, tmp_path: Path) -> None:
    from core.mcp import sandbox

    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _command: "/usr/bin/server")
    monkeypatch.setattr(sandbox.os.path, "exists", lambda path: path in {"/usr", "/bin"})
    monkeypatch.setattr(sandbox, "sandbox_binary_status", lambda: ("bwrap", "/usr/bin/bwrap"))

    argv, error = resolve_mcp_sandbox_argv("server", ["--stdio"], scratch=tmp_path)

    assert error is None and argv is not None
    assert argv[:4] == ["/usr/bin/bwrap", "--unshare-all", "--new-session", "--die-with-parent"]
    assert argv[4:7] == ["--ro-bind", "/usr", "/usr"]
    assert "--share-net" not in argv
    assert argv[-3:] == ["--", "/usr/bin/server", "--stdio"]


def test_config_precedence_reports_collision(tmp_path: Path, monkeypatch) -> None:
    import core.mcp.config_catalog as catalog_module

    global_config = tmp_path / "global.toml"
    project = tmp_path / "project"
    project_config = project / ".geode" / "config.toml"
    project_config.parent.mkdir(parents=True)
    global_config.write_text('[mcp.servers.same]\ncommand = "global"\n', encoding="utf-8")
    project_config.write_text('[mcp.servers.same]\ncommand = "project"\n', encoding="utf-8")
    monkeypatch.setattr(catalog_module, "GLOBAL_CONFIG_TOML", global_config)
    catalog = MCPConfigCatalog(
        tmp_path / "absent.json",
        project_root=lambda: project,
    )

    assert catalog.load() == 1
    assert catalog.servers["same"]["command"] == "project"
    assert catalog.collisions == [
        {
            "name": "same",
            "replaced": str(global_config),
            "selected": str(project_config),
        }
    ]


def test_mutating_mcp_tool_requires_declared_resource_keys() -> None:
    from core.agent.tool_executor import ToolExecutor

    manager = MCPServerManager(extension_policy=_policy("writer", "trusted"))
    manager._catalog.servers["writer"] = {
        "command": "writer",
        "execution": "trusted",
    }
    manager._pool.refresh_decisions()
    client = MagicMock()
    client.is_connected.return_value = True
    client.list_tools.return_value = [{"name": "mutate", "inputSchema": {}}]
    manager._pool.clients["writer"] = client
    executor = ToolExecutor(
        action_handlers={},
        mcp_manager=manager,
        hitl_level=0,
        auto_approve=True,
    )

    result = asyncio.run(executor.aexecute("mutate", {}))

    assert result["error_type"] == "resource_key_resolution"
    assert result["denied"] is True


def test_mcp_read_only_and_declared_resource_key_projections_are_distinct() -> None:
    policy = _policy("server", "trusted")
    manager = MCPServerManager(extension_policy=policy)
    manager._catalog.servers["server"] = {
        "command": "server",
        "execution": "trusted",
        "resource_keys": ["shared-account"],
    }
    manager._pool.refresh_decisions()
    client = MagicMock()
    client.is_connected.return_value = True
    client.list_tools.return_value = [
        {"name": "read", "annotations": {"readOnlyHint": True}},
        {"name": "write", "annotations": {}},
    ]
    manager._pool.clients["server"] = client
    manager._discovery.last_seen_tools.update({"read": "server", "write": "server"})

    assert manager.resource_keys_for_tool("read") == ()
    write_keys = manager.resource_keys_for_tool("write")
    assert write_keys is not None and len(write_keys) == 1
    assert len(write_keys[0]) == 64
