"""Public MCP manager facade over lifecycle-owned collaborators."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.mcp.config_catalog import MCPConfigCatalog
from core.mcp.connection_pool import MCPConnectionPool
from core.mcp.lifecycle import MCPLifecycle
from core.mcp.stdio_client import StdioMCPClient
from core.mcp.tool_runtime import (
    ADAPTER_ONLY_MCP_SERVERS as _ADAPTER_ONLY_MCP_SERVERS,
)
from core.mcp.tool_runtime import (
    MCPToolDiscovery,
    MCPToolInvoker,
    MCPTraceStore,
    normalise_mcp_tool,
    normalise_mcp_tool_args,
)
from core.paths import GLOBAL_ENV_FILE, get_project_root

log = logging.getLogger(__name__)

ADAPTER_ONLY_MCP_SERVERS = _ADAPTER_ONLY_MCP_SERVERS
_GLOBAL_DOTENV_PATH = GLOBAL_ENV_FILE

_mcp_hooks: Any = None


def set_mcp_hooks(hooks: Any) -> None:
    """Inject HookSystem for MCP server lifecycle events."""
    global _mcp_hooks
    _mcp_hooks = hooks


def clear_mcp_hooks(expected: Any) -> bool:
    """Clear the binding only when it still points at ``expected``."""
    global _mcp_hooks
    if _mcp_hooks is not expected:
        return False
    _mcp_hooks = None
    return True


def _fire_mcp_hook(event: Any, data: dict[str, Any]) -> None:
    from core.hooks.dispatch import fire_hook

    fire_hook(_mcp_hooks, event, data)


class MCPServerManager:
    """Compatibility facade for MCP configuration, discovery, and dispatch."""

    def __init__(self, config_path: Path | None = None) -> None:
        path = config_path or (get_project_root() / ".claude" / "mcp_servers.json")
        self._catalog = MCPConfigCatalog(
            path,
            global_env_path=lambda: _GLOBAL_DOTENV_PATH,
            project_root=lambda: get_project_root(),
        )
        self._trace = MCPTraceStore(lambda event, data: _fire_mcp_hook(event, data))
        self._pool = MCPConnectionPool(
            self._catalog,
            client_factory=lambda **kwargs: StdioMCPClient(**kwargs),
            event_sink=self._trace.fire,
        )
        self._discovery = MCPToolDiscovery(
            self._catalog,
            self._pool,
            get_client=lambda name: self._get_client(name),
            connect_all=lambda: self._connect_all(),
        )
        self._invoker = MCPToolInvoker(
            self._trace,
            get_client=lambda name: self._get_client(name),
            respawn=lambda name: self._respawn_after_death(name),
        )
        self._lifecycle = MCPLifecycle(lambda: _is_main_thread())

    @property
    def server_count(self) -> int:
        return len(self._catalog.servers)

    @property
    def connected_count(self) -> int:
        return len(self._pool.clients)

    def startup(
        self,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        if not self._catalog.servers:
            self.load_config()
        connected = self._connect_all(on_progress=on_progress)
        self._install_signal_handlers()
        log.info("MCP startup complete: %d/%d servers connected", connected, self.server_count)
        return connected

    def shutdown(self) -> None:
        if self._lifecycle.shutdown_called:
            return
        self._lifecycle.shutdown_called = True
        log.info("MCP shutdown initiated")
        self.close_all()
        self._uninstall_signal_handlers()
        log.info("MCP shutdown complete")

    def load_config(self) -> int:
        self._pool.failed_at.clear()
        return self._catalog.load()

    def get_status(self) -> dict[str, Any]:
        return self._catalog.status()

    def get_all_tools(self) -> list[dict[str, Any]]:
        return self._discovery.get_all_tools()

    @property
    def connection_epoch(self) -> int:
        return self._pool.connection_epoch

    def last_known_server_for_tool(self, tool_name: str) -> str | None:
        return self._discovery.last_seen_tools.get(tool_name)

    async def acall_tool(
        self, server_name: str, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._invoker.call(server_name, tool_name, args)

    def find_server_for_tool(self, tool_name: str) -> str | None:
        return self._discovery.find_server(tool_name)

    def list_servers(self) -> list[dict[str, Any]]:
        return self._pool.list_servers()

    def check_health(self, *, auto_restart: bool = False) -> dict[str, bool]:
        return self._pool.check_health(auto_restart=auto_restart, connector=self._get_client)

    def add_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        self._pool.failed_at.pop(name, None)
        return self._catalog.add(name, command, args=args, env=env)

    def reload_config(self) -> int:
        self.close_all()
        self._catalog.servers.clear()
        return self.load_config()

    def close_all(self) -> None:
        self._pool.close_all()

    # Compatibility forwarding for existing internal callers and tests. The
    # collaborators above remain the sole state owners.
    def _connect_all(
        self,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        return self._pool.connect_all(connector=self._get_client, on_progress=on_progress)

    def _get_client(self, server_name: str) -> StdioMCPClient | None:
        return self._pool.get_client(server_name)

    def _respawn_after_death(self, server_name: str) -> StdioMCPClient | None:
        return self._pool.respawn(server_name, connector=self._get_client)

    def _install_signal_handlers(self) -> None:
        self._lifecycle.install(self.shutdown, self._atexit_cleanup)

    def _uninstall_signal_handlers(self) -> None:
        self._lifecycle.uninstall()

    def _atexit_cleanup(self) -> None:
        if not self._lifecycle.shutdown_called:
            log.debug("MCP atexit cleanup triggered")
            self.close_all()

    def _resolve_env(self, env: dict[str, str]) -> dict[str, str]:
        return self._catalog.resolve_env(env)


_singleton_instance: MCPServerManager | None = None
_singleton_lock = threading.Lock()


def get_mcp_manager(
    config_path: Path | None = None,
    *,
    auto_startup: bool = False,
) -> MCPServerManager:
    """Return the process-wide compatibility MCP facade."""
    global _singleton_instance
    if _singleton_instance is not None:
        if auto_startup and not _singleton_instance.connected_count:
            _singleton_instance.startup()
        return _singleton_instance
    with _singleton_lock:
        if _singleton_instance is None:
            manager = MCPServerManager(config_path=config_path)
            if auto_startup:
                manager.startup()
            _singleton_instance = manager
        return _singleton_instance


def _normalise_mcp_tool(raw: dict[str, Any]) -> dict[str, Any]:
    """Compatibility alias for the discovery normalizer."""
    return normalise_mcp_tool(raw)


def _normalise_mcp_tool_args(
    *, tool_name: str, args: dict[str, Any], raw_tool: dict[str, Any] | None
) -> dict[str, Any]:
    """Compatibility alias for the invocation normalizer."""
    return normalise_mcp_tool_args(tool_name=tool_name, args=args, raw_tool=raw_tool)


def _is_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()
