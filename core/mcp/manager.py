"""MCP Server Manager — load config, discover tools, and call MCP servers.

Manages external MCP server connections using stdio-based JSON-RPC protocol.
Configuration is loaded from two sources (priority order):
  1. .geode/config.toml [mcp.servers] — primary, explicit configuration
  2. .claude/mcp_servers.json — fallback / legacy / install target

Lifecycle:
  startup()  — load config + connect all + register signal handlers
  shutdown() — graceful close all + unregister signal handlers
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from core.mcp.stdio_client import StdioMCPClient

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / ".claude" / "mcp_servers.json"
_DOTENV_PATH = _PROJECT_ROOT / ".env"
_GLOBAL_DOTENV_PATH = Path.home() / ".geode" / ".env"

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}

# Singleton instance — prevents duplicate MCP server processes
_singleton_instance: MCPServerManager | None = None
_singleton_lock = __import__("threading").Lock()


def get_mcp_manager(
    config_path: Path | None = None,
    *,
    auto_startup: bool = False,
) -> MCPServerManager:
    """Return the singleton MCPServerManager instance.

    First call creates the instance. If ``auto_startup`` is True and
    the instance hasn't been started yet, calls ``startup()`` which
    loads config AND connects all servers.

    Subsequent calls return the same instance regardless of arguments,
    preventing duplicate MCP server processes.
    """
    global _singleton_instance
    if _singleton_instance is not None:
        if auto_startup and not _singleton_instance._clients:
            _singleton_instance.startup()
        return _singleton_instance
    with _singleton_lock:
        if _singleton_instance is None:
            mgr = MCPServerManager(config_path=config_path)
            if auto_startup:
                mgr.startup()
            _singleton_instance = mgr
        return _singleton_instance


def _normalise_mcp_tool(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert an MCP tool dict to Anthropic API format.

    MCP spec returns ``inputSchema`` (camelCase); Anthropic requires
    ``input_schema`` (snake_case).  Missing schema is replaced with a
    minimal ``{"type": "object", "properties": {}}``.
    """
    schema = raw.get("input_schema") or raw.get("inputSchema") or _EMPTY_SCHEMA
    return {
        "name": raw.get("name", ""),
        "description": raw.get("description", ""),
        "input_schema": schema,
    }


class MCPServerManager:
    """Manages multiple MCP server connections and tool dispatch.

    Provides lifecycle hooks (startup/shutdown) with signal-handler
    registration so that MCP subprocess cleanup happens even on
    SIGTERM/SIGINT, preventing orphan processes.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _CONFIG_PATH
        self._servers: dict[str, dict[str, Any]] = {}
        self._clients: dict[str, StdioMCPClient] = {}
        self._dotenv_cache: dict[str, str | None] = {}
        self._signal_installed = False
        self._prev_sigterm: Any = None
        self._prev_sigint: signal.Handlers | None = None
        self._atexit_registered = False
        self._shutdown_called = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(
        self,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Full lifecycle startup: load config, connect all servers, register signal handlers.

        Args:
            on_progress: Optional callback ``(done, total, server_name)`` invoked
                each time a server finishes connecting (success or failure).

        Returns the number of servers that connected successfully.
        """
        if not self._servers:
            self.load_config()
        connected = self._connect_all(on_progress=on_progress)
        self._install_signal_handlers()
        log.info("MCP startup complete: %d/%d servers connected", connected, len(self._servers))
        return connected

    def shutdown(self) -> None:
        """Full lifecycle shutdown: close all servers, unregister signal handlers.

        Safe to call multiple times (idempotent).
        """
        if self._shutdown_called:
            return
        self._shutdown_called = True
        log.info("MCP shutdown initiated")
        self.close_all()
        self._uninstall_signal_handlers()
        log.info("MCP shutdown complete")

    def _connect_all(
        self,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Connect to all configured servers in parallel.

        Uses ThreadPoolExecutor to start all MCP subprocess connections
        concurrently. Each server takes ~10s (npx startup + JSON-RPC
        handshake), so parallel execution reduces total from N×10s to ~10-15s.

        Args:
            on_progress: Optional callback ``(done, total, server_name)`` invoked
                each time a server finishes connecting (success or failure).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        server_names = list(self._servers.keys())
        if not server_names:
            return 0

        connected = 0
        done = 0
        total = len(server_names)
        max_workers = min(total, 8)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._get_client, name): name for name in server_names}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    client = future.result()
                    if client is not None:
                        connected += 1
                except Exception:
                    log.debug("MCP parallel connect failed: %s", name, exc_info=True)
                done += 1
                if on_progress:
                    on_progress(done, total, name)

        return connected

    def _install_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT handlers for graceful cleanup.

        Chains with existing handlers so other shutdown logic still runs.
        Also registers an atexit handler as a safety net.
        """
        if self._signal_installed:
            return

        # Only install signal handlers in the main thread
        try:
            if not _is_main_thread():
                log.debug("MCP signal handlers skipped (not main thread)")
                return
        except Exception:
            return

        def _signal_shutdown(signum: int, frame: Any) -> None:
            """Signal handler that ensures MCP cleanup before exit."""
            log.info("MCP received signal %d, shutting down servers", signum)
            self.shutdown()
            # Chain to previous handler
            prev = self._prev_sigterm if signum == signal.SIGTERM else self._prev_sigint
            if prev and callable(prev):
                prev(signum, frame)
            elif prev == signal.SIG_DFL:
                # Re-raise with default handler
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            self._prev_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _signal_shutdown)
            # Note: SIGINT is typically managed by the REPL's own handler.
            # We save a reference but only install a SIGTERM handler to
            # avoid interfering with KeyboardInterrupt handling.
            self._signal_installed = True
            log.debug("MCP SIGTERM handler installed")
        except (OSError, ValueError):
            # Cannot set signal handler (e.g., not main thread, or restricted env)
            log.debug("MCP signal handler installation failed", exc_info=True)

        # Atexit safety net
        if not self._atexit_registered:
            atexit.register(self._atexit_cleanup)
            self._atexit_registered = True

    def _atexit_cleanup(self) -> None:
        """Atexit fallback — ensures cleanup even if signals were not caught."""
        if not self._shutdown_called:
            log.debug("MCP atexit cleanup triggered")
            self.close_all()

    def _uninstall_signal_handlers(self) -> None:
        """Restore previous signal handlers."""
        if not self._signal_installed:
            return

        try:
            if not _is_main_thread():
                return
        except Exception:
            return

        try:
            if self._prev_sigterm is not None:
                signal.signal(signal.SIGTERM, self._prev_sigterm)
            self._signal_installed = False
            log.debug("MCP signal handlers restored")
        except (OSError, ValueError):
            log.debug("MCP signal handler restoration failed", exc_info=True)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def load_config(self) -> int:
        """Load MCP server configurations from config.toml + json fallback.

        Priority order:
          1. .geode/config.toml [mcp.servers] — explicit configuration (wins)
          2. .claude/mcp_servers.json — legacy fallback, install target

        Returns total number of servers loaded.
        """
        import tomllib

        self._servers = {}

        # Layer 1: .geode/config.toml [mcp.servers]
        config_toml = _PROJECT_ROOT / ".geode" / "config.toml"
        if config_toml.exists():
            try:
                with open(config_toml, "rb") as f:
                    toml_data = tomllib.load(f)
                mcp_section = toml_data.get("mcp", {}).get("servers", {})
                for name, cfg in mcp_section.items():
                    entry: dict[str, Any] = {"command": cfg["command"]}
                    if "args" in cfg:
                        entry["args"] = cfg["args"]
                    if "env" in cfg:
                        entry["env"] = cfg["env"]
                    self._servers[name] = entry
                if mcp_section:
                    log.info("MCP config.toml: %d servers", len(mcp_section))
            except Exception as exc:
                log.debug("Failed to load MCP from config.toml: %s", exc)

        # Layer 2: .claude/mcp_servers.json (fallback — toml entries take priority)
        if self._config_path.exists():
            try:
                raw = self._config_path.read_text(encoding="utf-8")
                file_servers: dict[str, dict[str, Any]] = json.loads(raw)
                added = 0
                for name, cfg in file_servers.items():
                    if name not in self._servers:
                        self._servers[name] = cfg
                        added += 1
                if added > 0:
                    log.info("MCP mcp_servers.json: %d additional servers", added)
            except (json.JSONDecodeError, OSError) as exc:
                log.debug("Failed to load MCP config file: %s", exc)

        total = len(self._servers)
        if total > 0:
            log.info("MCP total: %d servers configured", total)
        else:
            log.debug("MCP: no servers configured")
        return total

    def get_status(self) -> dict[str, Any]:
        """Build MCP status report: active servers + available-but-inactive.

        Returns:
            active: servers currently configured (from config.toml + json)
            available_inactive: catalog entries with missing env vars
        """
        from core.mcp.catalog import MCP_CATALOG

        self._load_dotenv_cache()

        active: list[dict[str, str]] = []
        for name in sorted(self._servers):
            entry = MCP_CATALOG.get(name)
            desc = entry.description if entry else ""
            active.append({"name": name, "description": desc})

        # Available but inactive: catalog entries with env_keys not configured
        available_inactive: list[dict[str, Any]] = []
        for name, entry in sorted(MCP_CATALOG.items()):
            if name in self._servers or not entry.env_keys:
                continue
            missing = [
                k
                for k in entry.env_keys
                if not (os.environ.get(k) or self._dotenv_cache.get(k))
            ]
            if missing:
                available_inactive.append(
                    {
                        "name": name,
                        "description": entry.description,
                        "missing_env": missing,
                    }
                )

        return {
            "active": active,
            "active_count": len(active),
            "available_inactive": available_inactive,
            "available_inactive_count": len(available_inactive),
            "catalog_total": len(MCP_CATALOG),
        }

    def _load_dotenv_cache(self) -> None:
        """Populate dotenv cache if empty.

        Cascade: ~/.geode/.env (global) → CWD/.env (project, non-empty only).
        """
        if not self._dotenv_cache:
            if _GLOBAL_DOTENV_PATH.exists():
                self._dotenv_cache.update(dotenv_values(str(_GLOBAL_DOTENV_PATH)))
            if _DOTENV_PATH.exists():
                for k, v in dotenv_values(str(_DOTENV_PATH)).items():
                    if v:  # skip empty/None — must not clobber global keys
                        self._dotenv_cache[k] = v

    def _resolve_env(self, env: dict[str, str]) -> dict[str, str]:
        """Resolve ${VAR} references in env values.

        Checks os.environ first, then falls back to .env file values.
        pydantic-settings loads .env into Settings fields but NOT into
        os.environ, so MCP keys defined only in .env would be invisible.
        """
        self._load_dotenv_cache()

        resolved: dict[str, str] = {}
        for key, value in env.items():
            if value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                resolved[key] = os.environ.get(var_name, self._dotenv_cache.get(var_name) or "")
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
        # SECURITY: resolved env may contain API keys — never log env values.
        env = self._resolve_env(config.get("env", {}))

        # Skip server if any required env var resolved to empty string
        missing = [k for k, v in env.items() if not v]
        if missing:
            log.debug(
                "MCP server '%s' skipped — missing env: %s",
                server_name,
                ", ".join(missing),
            )
            return None

        client = StdioMCPClient(command=command, args=args, env=env)
        if client.connect():
            self._clients[server_name] = client
            return client

        log.debug("MCP server not available (skipped): %s", server_name)
        return None

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Gather tool definitions from all configured MCP servers.

        MCP spec uses camelCase (``inputSchema``), but Anthropic API
        requires snake_case (``input_schema``).  This method normalises
        each tool dict so it can be passed directly to ``messages.create(tools=...)``.

        If servers haven't been connected yet, triggers parallel connection
        via ``_connect_all()`` to avoid sequential ~10s-per-server latency.
        """
        # Lazy parallel connect: avoid sequential _get_client() per server
        if self._servers and not self._clients:
            self._connect_all()

        all_tools: list[dict[str, Any]] = []
        for server_name in self._servers:
            client = self._get_client(server_name)
            if client is None:
                continue
            tools = client.list_tools()
            for tool in tools:
                normalised = _normalise_mcp_tool(tool)
                normalised["_mcp_server"] = server_name
                all_tools.append(normalised)
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

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

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

    def check_health(self, *, auto_restart: bool = False) -> dict[str, bool]:
        """Return connection health status for each configured server.

        Args:
            auto_restart: If True, attempt to reconnect dead servers.
        """
        result: dict[str, bool] = {}
        for name in self._servers:
            client = self._clients.get(name)
            alive = client.is_connected() if client else False

            if not alive and auto_restart:
                log.info("MCP server '%s' is down, attempting restart", name)
                # Remove dead client reference
                self._clients.pop(name, None)
                new_client = self._get_client(name)
                alive = new_client is not None and new_client.is_connected()
                if alive:
                    log.info("MCP server '%s' restarted successfully", name)
                else:
                    log.warning("MCP server '%s' restart failed", name)

            result[name] = alive
        return result

    def add_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        """Add a new MCP server and persist to config file.

        Returns True if successfully added and saved.
        """
        entry: dict[str, Any] = {"command": command}
        if args:
            entry["args"] = args
        if env:
            entry["env"] = env

        self._servers[name] = entry

        # Persist to config file
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                json.dumps(self._servers, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            log.info("Added MCP server '%s' and saved config", name)
            return True
        except OSError as exc:
            log.error("Failed to save MCP config after adding '%s': %s", name, exc)
            return False

    def reload_config(self) -> int:
        """Close all connections, reload config, and return new server count."""
        self.close_all()
        self._servers.clear()
        return self.load_config()

    def close_all(self) -> None:
        """Close all MCP server connections."""
        for name, client in self._clients.items():
            with contextlib.suppress(Exception):
                log.debug("Closing MCP server '%s' (PID %s)", name, client.pid)
                client.close()
        self._clients.clear()


def _is_main_thread() -> bool:
    """Check if current thread is the main thread."""
    import threading

    return threading.current_thread() is threading.main_thread()
