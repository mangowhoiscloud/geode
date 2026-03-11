"""MCP Server Manager — load config, discover tools, and call MCP servers.

Manages external MCP server connections using stdio-based JSON-RPC protocol.
Configuration is loaded from .claude/mcp_servers.json.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from core.infrastructure.adapters.mcp.stdio_client import StdioMCPClient

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / ".claude" / "mcp_servers.json"


class MCPServerManager:
    """Manages multiple MCP server connections and tool dispatch."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _CONFIG_PATH
        self._servers: dict[str, dict[str, Any]] = {}
        self._clients: dict[str, StdioMCPClient] = {}

    def load_config(self) -> int:
        """Load MCP server configurations. Returns number of servers loaded."""
        if not self._config_path.exists():
            log.debug("MCP config not found: %s", self._config_path)
            return 0

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            self._servers = json.loads(raw)
            log.info("Loaded %d MCP server configs", len(self._servers))
            return len(self._servers)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load MCP config: %s", exc)
            return 0

    def _resolve_env(self, env: dict[str, str]) -> dict[str, str]:
        """Resolve ${VAR} references in env values."""
        resolved: dict[str, str] = {}
        for key, value in env.items():
            if value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                resolved[key] = os.environ.get(var_name, "")
            else:
                resolved[key] = value
        return resolved

    def _get_client(self, server_name: str) -> StdioMCPClient | None:
        """Get or create a client for a server."""
        if server_name in self._clients:
            client = self._clients[server_name]
            if client.is_connected():
                return client

        config = self._servers.get(server_name)
        if config is None:
            return None

        command = config.get("command", "")
        args = config.get("args", [])
        env = self._resolve_env(config.get("env", {}))

        client = StdioMCPClient(command=command, args=args, env=env)
        if client.connect():
            self._clients[server_name] = client
            return client

        log.warning("Failed to connect to MCP server: %s", server_name)
        return None

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Gather tool definitions from all configured MCP servers."""
        all_tools: list[dict[str, Any]] = []
        for server_name in self._servers:
            client = self._get_client(server_name)
            if client is None:
                continue
            tools = client.list_tools()
            for tool in tools:
                tool["_mcp_server"] = server_name
                all_tools.append(tool)
        return all_tools

    def call_tool(self, server_name: str, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on a specific MCP server."""
        client = self._get_client(server_name)
        if client is None:
            return {"error": f"MCP server '{server_name}' not available"}

        try:
            return client.call_tool(tool_name, args)
        except Exception as exc:
            log.error("MCP tool call failed: %s/%s: %s", server_name, tool_name, exc)
            return {"error": f"MCP tool call failed: {exc}"}

    def find_server_for_tool(self, tool_name: str) -> str | None:
        """Find which server provides a given tool."""
        for server_name in self._servers:
            client = self._get_client(server_name)
            if client is None:
                continue
            for tool in client.list_tools():
                if tool.get("name") == tool_name:
                    return server_name
        return None

    def list_servers(self) -> list[dict[str, Any]]:
        """List configured servers with their status."""
        result: list[dict[str, Any]] = []
        for name, config in self._servers.items():
            client = self._clients.get(name)
            result.append(
                {
                    "name": name,
                    "command": config.get("command", ""),
                    "connected": client.is_connected() if client else False,
                    "tool_count": len(client.list_tools())
                    if client and client.is_connected()
                    else 0,
                }
            )
        return result

    def check_health(self) -> dict[str, bool]:
        """Return connection health status for each configured server."""
        result: dict[str, bool] = {}
        for name in self._servers:
            client = self._clients.get(name)
            result[name] = client.is_connected() if client else False
        return result

    def reload_config(self) -> int:
        """Close all connections, reload config, and return new server count."""
        self.close_all()
        self._servers.clear()
        return self.load_config()

    def close_all(self) -> None:
        """Close all MCP server connections."""
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                client.close()
        self._clients.clear()
