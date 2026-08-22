"""MCP stdio connection ownership, health, and reconnection."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from core.mcp.config_catalog import MCPConfigCatalog
from core.mcp.stdio_client import StdioMCPClient

log = logging.getLogger(__name__)

_FAILED_RETRY_COOLDOWN_S = 300.0


class MCPConnectionPool:
    """Own one reusable stdio client per configured server."""

    def __init__(
        self,
        catalog: MCPConfigCatalog,
        *,
        client_factory: Callable[..., StdioMCPClient],
        event_sink: Callable[[Any, dict[str, Any]], None],
    ) -> None:
        self.catalog = catalog
        self.clients: dict[str, StdioMCPClient] = {}
        self.failed_at: dict[str, float] = {}
        self.connection_epoch = 0
        self._respawn_lock = threading.Lock()
        self._client_factory = client_factory
        self._event_sink = event_sink

    def get_client(self, server_name: str) -> StdioMCPClient | None:
        existing = self.clients.get(server_name)
        if existing is not None:
            if existing.is_connected():
                return existing
            self.clients.pop(server_name, None)
            existing.close()

        failed_at = self.failed_at.get(server_name)
        if failed_at is not None and time.monotonic() - failed_at < _FAILED_RETRY_COOLDOWN_S:
            return None

        config = self.catalog.servers.get(server_name)
        if config is None:
            return None
        env = self.catalog.resolve_env(config.get("env", {}))
        missing = [key for key, value in env.items() if not value]
        if missing:
            log.debug("MCP server '%s' skipped — missing env: %s", server_name, ", ".join(missing))
            return None

        from core.hooks import HookEvent

        client = self._client_factory(
            command=config.get("command", ""),
            args=config.get("args", []),
            env=env,
        )
        if client.connect():
            self.clients[server_name] = client
            self.connection_epoch += 1
            self.failed_at.pop(server_name, None)
            self._event_sink(HookEvent.MCP_SERVER_CONNECTED, {"server_name": server_name})
            return client

        self.failed_at[server_name] = time.monotonic()
        self._event_sink(
            HookEvent.MCP_SERVER_FAILED,
            {"server_name": server_name, "error": "Connection failed"},
        )
        log.debug("MCP server not available (skipped): %s", server_name)
        return None

    def connect_all(
        self,
        *,
        connector: Callable[[str], StdioMCPClient | None] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        names = list(self.catalog.servers)
        if not names:
            return 0
        get_client = connector or self.get_client
        connected = 0
        done = 0
        with ThreadPoolExecutor(max_workers=min(len(names), 8)) as pool:
            futures = {pool.submit(get_client, name): name for name in names}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    connected += future.result() is not None
                except Exception:
                    log.debug("MCP parallel connect failed: %s", name, exc_info=True)
                done += 1
                if on_progress:
                    on_progress(done, len(names), name)
        return connected

    def respawn(
        self,
        server_name: str,
        *,
        connector: Callable[[str], StdioMCPClient | None] | None = None,
    ) -> StdioMCPClient | None:
        with self._respawn_lock:
            existing = self.clients.get(server_name)
            if existing is not None and existing.is_connected():
                return existing
            stale = self.clients.pop(server_name, None)
            if stale is not None:
                stale.close()
            return (connector or self.get_client)(server_name)

    def list_servers(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name, config in self.catalog.servers.items():
            client = self.clients.get(name)
            connected = client.is_connected() if client else False
            result.append(
                {
                    "name": name,
                    "command": config.get("command", ""),
                    "connected": connected,
                    "tool_count": len(client.list_tools()) if client and connected else 0,
                }
            )
        return result

    def check_health(
        self,
        *,
        auto_restart: bool = False,
        connector: Callable[[str], StdioMCPClient | None] | None = None,
    ) -> dict[str, bool]:
        get_client = connector or self.get_client
        result: dict[str, bool] = {}
        for name in self.catalog.servers:
            client = self.clients.get(name)
            alive = client.is_connected() if client else False
            if not alive and auto_restart:
                log.info("MCP server '%s' is down, attempting restart", name)
                dead = self.clients.pop(name, None)
                if dead is not None:
                    dead.close()
                self.failed_at.pop(name, None)
                fresh = get_client(name)
                alive = fresh is not None and fresh.is_connected()
                if alive:
                    log.info("MCP server '%s' restarted successfully", name)
                else:
                    log.warning("MCP server '%s' restart failed", name)
            result[name] = alive
        return result

    def close_all(self) -> None:
        for name, client in self.clients.items():
            with contextlib.suppress(Exception):
                log.debug("Closing MCP server '%s' (PID %s)", name, client.pid)
                client.close()
        self.clients.clear()
