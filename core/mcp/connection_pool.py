"""MCP stdio connection ownership, health, and reconnection."""

from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.extensions import (
    ExtensionDecision,
    ExtensionDescriptor,
    ExtensionExecution,
    ExtensionPolicy,
    ExtensionState,
    ExtensionSurface,
    decide_extension,
)
from core.mcp.config_catalog import MCPConfigCatalog
from core.mcp.sandbox import resolve_mcp_sandbox_argv
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
        extension_policy: ExtensionPolicy,
    ) -> None:
        self.catalog = catalog
        self.clients: dict[str, StdioMCPClient] = {}
        self.failed_at: dict[str, float] = {}
        self.connection_epoch = 0
        self.extension_decisions: dict[str, ExtensionDecision] = {}
        self._respawn_lock = threading.Lock()
        self._client_factory = client_factory
        self._event_sink = event_sink
        self._extension_policy = extension_policy

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
        decision = self.extension_decisions.get(server_name) or self._authorize(server_name, config)
        self.extension_decisions[server_name] = decision
        if decision.state is not ExtensionState.GRANTED:
            log.warning(
                "MCP extension %s: %s (%s)",
                decision.descriptor.extension_id,
                decision.state,
                decision.reason,
            )
            return None
        if not (decision.may_launch_brokered or decision.may_load_in_process):
            self.extension_decisions[server_name] = decision.degraded(
                "MCP execution must be trusted or brokered"
            )
            return None
        env = self.catalog.resolve_env(config.get("env", {}))
        missing = [key for key, value in env.items() if not value]
        if missing:
            self.extension_decisions[server_name] = decision.degraded(
                f"missing environment: {', '.join(missing)}"
            )
            log.debug("MCP server '%s' skipped — missing env: %s", server_name, ", ".join(missing))
            return None

        from core.hooks import HookEvent

        command = config.get("command", "")
        args = config.get("args", [])
        if decision.may_launch_brokered:
            scratch = tempfile.mkdtemp(prefix="geode-mcp-")
            argv, error = resolve_mcp_sandbox_argv(command, args, scratch=Path(scratch))
            if error or argv is None:
                shutil.rmtree(scratch, ignore_errors=True)
                self.extension_decisions[server_name] = decision.degraded(
                    error or "brokered MCP sandbox unavailable"
                )
                self.failed_at[server_name] = time.monotonic()
                return None
            try:
                client = self._client_factory(
                    command=argv[0],
                    args=argv[1:],
                    env=env,
                    inherit_env=False,
                    working_dir=scratch,
                    cleanup_working_dir=True,
                )
            except Exception as exc:
                shutil.rmtree(scratch, ignore_errors=True)
                self.extension_decisions[server_name] = decision.degraded(
                    f"client construction failed: {type(exc).__name__}"
                )
                return None
        else:
            client = self._client_factory(command=command, args=args, env=env)
        try:
            connected = client.connect()
        except Exception as exc:
            with contextlib.suppress(Exception):
                client.close()
            self.extension_decisions[server_name] = decision.degraded(
                f"connection failed: {type(exc).__name__}"
            )
            connected = False
        if connected:
            self.clients[server_name] = client
            self.connection_epoch += 1
            self.failed_at.pop(server_name, None)
            self._event_sink(HookEvent.MCP_SERVER_CONNECTED, {"server_name": server_name})
            return client

        with contextlib.suppress(Exception):
            client.close()
        self.failed_at[server_name] = time.monotonic()
        self.extension_decisions[server_name] = decision.degraded("connection failed")
        self._event_sink(
            HookEvent.MCP_SERVER_FAILED,
            {"server_name": server_name, "error": "Connection failed"},
        )
        log.debug("MCP server not available (skipped): %s", server_name)
        return None

    def refresh_decisions(self) -> tuple[ExtensionDecision, ...]:
        """Rebuild the manifest-only decision snapshot without launching servers."""
        self.extension_decisions = {
            name: self._authorize(name, config) for name, config in self.catalog.servers.items()
        }
        return tuple(self.extension_decisions[name] for name in sorted(self.extension_decisions))

    def _authorize(self, server_name: str, config: dict[str, Any]) -> ExtensionDecision:
        origin = self.catalog.origins.get(server_name, "runtime configuration")
        try:
            if unknown := sorted(
                set(config)
                - {
                    "command",
                    "args",
                    "env",
                    "enabled",
                    "execution",
                    "capabilities",
                    "resource_keys",
                }
            ):
                raise ValueError(f"unknown MCP manifest fields: {unknown}")
            command = config.get("command")
            args = config.get("args", [])
            env = config.get("env", {})
            if not isinstance(command, str) or not command.strip():
                raise TypeError("MCP command must be a non-empty string")
            if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
                raise TypeError("MCP args must be a list of strings")
            if not isinstance(env, dict) or any(
                not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()
            ):
                raise TypeError("MCP env must map strings to strings")
            descriptor = ExtensionDescriptor(
                name=server_name,
                surface=ExtensionSurface.MCP,
                origin=origin,
                execution=ExtensionExecution(config.get("execution", "brokered")),
                enabled=config.get("enabled", True),
                capabilities=config.get("capabilities", ()),
                resource_keys=config.get("resource_keys", ()),
            )
            return decide_extension(descriptor, self._extension_policy)
        except (TypeError, ValueError) as exc:
            descriptor = ExtensionDescriptor(
                name=server_name,
                surface=ExtensionSurface.MCP,
                origin=origin,
                execution=ExtensionExecution.BROKERED,
            )
            return decide_extension(descriptor, ExtensionPolicy.empty()).degraded(
                f"invalid manifest: {exc}"
            )

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
