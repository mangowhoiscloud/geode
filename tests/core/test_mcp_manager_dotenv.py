"""MCP dotenv expansion follows the GEODE secret precedence."""

from __future__ import annotations

from pathlib import Path

from core.mcp.manager import MCPServerManager


def test_mcp_env_resolution_global_secret_beats_project_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import core.mcp.manager as manager_mod

    project = tmp_path / "project"
    project.mkdir()
    global_env = tmp_path / "home" / ".env"
    global_env.parent.mkdir()
    project_env = project / ".env"

    global_env.write_text("MCP_TOKEN=global\n", encoding="utf-8")
    project_env.write_text("MCP_TOKEN=project\n", encoding="utf-8")
    monkeypatch.setattr(manager_mod, "_GLOBAL_DOTENV_PATH", global_env)
    monkeypatch.setattr(manager_mod, "get_project_root", lambda: project)
    monkeypatch.delenv("MCP_TOKEN", raising=False)

    manager = MCPServerManager(config_path=tmp_path / "mcp_servers.json")

    assert manager._resolve_env({"TOKEN": "${MCP_TOKEN}"}) == {"TOKEN": "global"}


def test_mcp_env_resolution_project_env_fills_global_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import core.mcp.manager as manager_mod

    project = tmp_path / "project"
    project.mkdir()
    global_env = tmp_path / "home" / ".env"
    global_env.parent.mkdir()
    project_env = project / ".env"

    project_env.write_text("MCP_TOKEN=project\n", encoding="utf-8")
    monkeypatch.setattr(manager_mod, "_GLOBAL_DOTENV_PATH", global_env)
    monkeypatch.setattr(manager_mod, "get_project_root", lambda: project)
    monkeypatch.delenv("MCP_TOKEN", raising=False)

    manager = MCPServerManager(config_path=tmp_path / "mcp_servers.json")

    assert manager._resolve_env({"TOKEN": "${MCP_TOKEN}"}) == {"TOKEN": "project"}
