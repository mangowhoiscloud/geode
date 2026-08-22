"""MCP tool discovery, guarded invocation, and bounded trace state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.mcp.config_catalog import MCPConfigCatalog
from core.mcp.connection_pool import MCPConnectionPool
from core.mcp.stdio_client import StdioMCPClient

log = logging.getLogger(__name__)

ADAPTER_ONLY_MCP_SERVERS: frozenset[str] = frozenset({"google-calendar", "caldav"})
_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
_MCP_TOOL_DESCRIPTION_NOTES: dict[str, str] = {
    "read_multiple_files": (
        "For exact file-copy or text-conversion work, do not infer source EOF from "
        "combined display separators. GEODE tracks local source EOF metadata after "
        "successful reads and preserves it for same-name writes when possible."
    ),
    "read_text_file": (
        "For whole-file reads, omit head and tail. Do not pass head and tail together."
    ),
    "write_file": (
        "Use the server schema's path argument when it is present; GEODE also accepts "
        "file_path as a compatibility alias for path and preserves cached source EOF "
        "for same-name text writes when possible."
    ),
}


def normalise_mcp_tool(raw: dict[str, Any]) -> dict[str, Any]:
    schema = raw.get("input_schema") or raw.get("inputSchema") or _EMPTY_SCHEMA
    tool = {
        "name": raw.get("name", ""),
        "description": raw.get("description", ""),
        "input_schema": schema,
    }
    name = str(tool["name"] or "")
    note = _MCP_TOOL_DESCRIPTION_NOTES.get(name)
    if note and note not in str(tool["description"] or ""):
        separator = " " if tool["description"] else ""
        tool["description"] = f"{tool['description']}{separator}GEODE note: {note}"
    return tool


def normalise_mcp_tool_args(
    *, tool_name: str, args: dict[str, Any], raw_tool: dict[str, Any] | None
) -> dict[str, Any]:
    normalised = dict(args)
    schema = (raw_tool or {}).get("input_schema") or (raw_tool or {}).get("inputSchema") or {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    if (
        "path" in properties
        and "file_path" not in properties
        and "path" not in normalised
        and "file_path" in normalised
    ):
        normalised["path"] = normalised.pop("file_path")
    if tool_name == "read_text_file" and "head" in normalised and "tail" in normalised:
        normalised.pop("head", None)
        normalised.pop("tail", None)
    return normalised


class MCPTraceStore:
    """Own hook emission and the bounded read/write compatibility cache."""

    def __init__(self, event_sink: Callable[[Any, dict[str, Any]], None]) -> None:
        self.event_sink = event_sink
        self.text_read_cache: dict[tuple[str, str], str] = {}

    def fire(self, event: Any, data: dict[str, Any]) -> None:
        self.event_sink(event, data)

    def record_text_read(
        self,
        *,
        server_name: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if result.get("isError") or result.get("error"):
            return
        paths: list[str] = []
        if tool_name in {"read_file", "read_text_file"} and isinstance(args.get("path"), str):
            paths.append(args["path"])
        elif tool_name == "read_multiple_files" and isinstance(args.get("paths"), list):
            paths.extend(path for path in args["paths"] if isinstance(path, str))
        else:
            return
        fallback = _result_text(result)
        for path in paths:
            text = _read_local_text(path)
            if text is None and len(paths) == 1 and tool_name in {"read_file", "read_text_file"}:
                text = fallback
            if text is not None:
                self.text_read_cache[(server_name, Path(path).name)] = text

    def normalise_text_write(
        self, *, server_name: str, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        if tool_name != "write_file":
            return args
        content = args.get("content")
        path = args.get("path") or args.get("file_path")
        if not isinstance(content, str) or not isinstance(path, str) or not content.endswith("\n"):
            return args
        source = self.text_read_cache.get((server_name, Path(path).name))
        candidate = content[:-1]
        if (
            source is None
            or source.endswith("\n")
            or candidate
            not in {
                source,
                source.upper(),
                source.lower(),
            }
        ):
            return args
        normalised = dict(args)
        normalised["content"] = candidate
        return normalised


class MCPToolDiscovery:
    """Own visible tool discovery and last-seen server routing."""

    def __init__(
        self,
        catalog: MCPConfigCatalog,
        pool: MCPConnectionPool,
        *,
        get_client: Callable[[str], StdioMCPClient | None],
        connect_all: Callable[[], int],
    ) -> None:
        self.catalog = catalog
        self.pool = pool
        self.last_seen_tools: dict[str, str] = {}
        self._get_client = get_client
        self._connect_all = connect_all

    def get_all_tools(self) -> list[dict[str, Any]]:
        if self.catalog.servers and not self.pool.clients:
            self._connect_all()
        all_tools: list[dict[str, Any]] = []
        for server_name in self.catalog.servers:
            if server_name in ADAPTER_ONLY_MCP_SERVERS:
                continue
            client = self._get_client(server_name)
            if client is None:
                continue
            for raw_tool in client.list_tools():
                tool = normalise_mcp_tool(raw_tool)
                tool["_mcp_server"] = server_name
                name = tool.get("name")
                if isinstance(name, str):
                    self.last_seen_tools[name] = server_name
                all_tools.append(tool)
        return all_tools

    def find_server(self, tool_name: str) -> str | None:
        for server_name in self.catalog.servers:
            if server_name in ADAPTER_ONLY_MCP_SERVERS:
                continue
            client = self._get_client(server_name)
            if client is None:
                continue
            if any(tool.get("name") == tool_name for tool in client.list_tools()):
                self.last_seen_tools[tool_name] = server_name
                return server_name
        return None


class MCPToolInvoker:
    """Invoke tools with schema compatibility and idempotency-safe retry."""

    _FALLBACK_HINTS = {
        "playwriter": "playwright (playwright__browser_navigate, etc.)",
        "puppeteer": "playwright (playwright__browser_navigate, etc.)",
    }

    def __init__(
        self,
        trace: MCPTraceStore,
        *,
        get_client: Callable[[str], StdioMCPClient | None],
        respawn: Callable[[str], StdioMCPClient | None],
    ) -> None:
        self.trace = trace
        self._get_client = get_client
        self._respawn = respawn

    async def call(self, server_name: str, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        from core.tools.base import tool_error

        client = await asyncio.to_thread(self._get_client, server_name)
        if client is None:
            hint = self._FALLBACK_HINTS.get(server_name, "")
            return tool_error(
                f"MCP server '{server_name}' not available",
                error_type="connection",
                hint=f"Use {hint} instead" if hint else "Check server configuration.",
                context={"server": server_name, "tool": tool_name},
            )
        try:
            raw_tool = _raw_tool(client, tool_name)
            normalised_args = normalise_mcp_tool_args(
                tool_name=tool_name, args=args, raw_tool=raw_tool
            )
            normalised_args = self.trace.normalise_text_write(
                server_name=server_name, tool_name=tool_name, args=normalised_args
            )
            try:
                result = await client.acall_tool(tool_name, normalised_args)
                died_mid_call = (
                    isinstance(result, dict)
                    and bool(result.get("error"))
                    and not client.is_connected()
                )
            except ConnectionError:
                result = {}
                died_mid_call = True
            if died_mid_call:
                annotations = (raw_tool or {}).get("annotations") or {}
                if not (annotations.get("readOnlyHint") or annotations.get("idempotentHint")):
                    raise ConnectionError(
                        f"MCP server '{server_name}' died during '{tool_name}'; "
                        "the tool is not marked read-only/idempotent so it was not "
                        "retried — outcome unknown"
                    )
                fresh = await asyncio.to_thread(self._respawn, server_name)
                if fresh is None:
                    raise ConnectionError(
                        f"MCP server '{server_name}' died mid-call and did not reconnect"
                    )
                log.info("MCP server '%s' respawned mid-call; retrying %s", server_name, tool_name)
                result = await fresh.acall_tool(tool_name, normalised_args)
            self.trace.record_text_read(
                server_name=server_name,
                tool_name=tool_name,
                args=normalised_args,
                result=result,
            )
            return result
        except Exception as exc:
            log.error("MCP async tool call failed: %s/%s: %s", server_name, tool_name, exc)
            hint = self._FALLBACK_HINTS.get(server_name, "")
            detail = f" ({exc})" if str(exc) else ""
            return tool_error(
                f"MCP tool call failed: {tool_name}{detail}",
                error_type="timeout" if "timeout" in str(exc).lower() else "connection",
                hint=f"Use {hint} instead" if hint else "Retry or use an alternative tool.",
                context={"server": server_name, "tool": tool_name},
            )


def _raw_tool(client: StdioMCPClient, tool_name: str) -> dict[str, Any] | None:
    try:
        tools = client.list_tools()
    except Exception:
        log.debug("MCP tool schema lookup failed: %s", tool_name, exc_info=True)
        return None
    return next((tool for tool in tools if tool.get("name") == tool_name), None)


def _result_text(result: dict[str, Any]) -> str | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            return text
    return None


def _read_local_text(path: str) -> str | None:
    try:
        file_path = Path(path)
        return file_path.read_text(encoding="utf-8") if file_path.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None
