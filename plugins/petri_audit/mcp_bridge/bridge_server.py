"""Stdio MCP server that exposes inspect_ai tool schemas to the claude CLI subprocess.

CSA-2 paperclip-pattern bridge. Spawned by the claude CLI via
``--mcp-config`` as ``python -m plugins.petri_audit.mcp_bridge.bridge_server``;
reads tool schemas from a JSON file pointed at by the
``GEODE_AUDIT_BRIDGE_TOOLS_JSON`` env var; advertises those schemas via
the MCP ``tools/list`` handler; returns a sentinel no-exec result from
``tools/call`` (which should never fire under the parent provider's
``--max-turns 1`` constraint).

Why this exists
===============

* Claude CLI under ``--max-turns 1`` stops at the ``stop_reason=tool_use``
  boundary — the assistant message includes the tool_use content blocks
  but the CLI exits before executing them.
* inspect_ai's solver wants to receive those tool_use blocks as
  ``ChatMessageAssistant.tool_calls`` so the controller can dispatch
  them through its own tool-execution machinery.
* The bridge is the wire-protocol shim that makes ``tools=[...]`` from
  inspect_ai's ``generate()`` reachable to claude's planner. The actual
  tool execution stays in inspect_petri's solver in the parent process.

Independence from inspect_ai
============================

This module deliberately does NOT import inspect_ai. Tool schemas
arrive as plain dicts (see :mod:`tool_translator`), so the bridge
starts in milliseconds rather than seconds.

Operator-visible env
====================

``GEODE_AUDIT_BRIDGE_TOOLS_JSON`` — path to the JSON file containing
the serialised ``list[ToolSpec]``. The parent process writes this
before spawning the claude subprocess; the bridge subprocess reads it
on startup. Required. Missing → exit code 2 + stderr line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("plugins.petri_audit.mcp_bridge.bridge_server")

__all__ = ["BRIDGE_SERVER_NAME", "BRIDGE_TOOLS_ENV", "main"]


BRIDGE_SERVER_NAME = "bridge"
"""MCP server name advertised in the ``--mcp-config`` JSON. Claude
prefixes tool names with ``mcp__<server_name>__`` so the auditor sees
``mcp__bridge__send_message`` etc. The provider's response parser
strips this prefix before constructing :class:`ToolCall`."""

BRIDGE_TOOLS_ENV = "GEODE_AUDIT_BRIDGE_TOOLS_JSON"
"""Env var pointing at the serialised tool-spec JSON file."""

_NO_EXEC_SENTINEL = {
    "_bridge_no_exec": True,
    "reason": (
        "GEODE audit MCP bridge does not execute tools; "
        "inspect_petri's solver owns dispatch. "
        "If you see this payload, the provider's --max-turns 1 boundary "
        "may not be effective — check claude CLI version."
    ),
}


def _read_tool_specs(path_str: str) -> list[dict[str, Any]]:
    """Load the bridge-tools JSON file and validate the top-level shape.

    Raises :class:`ValueError` with a human-readable message on any
    schema mismatch — the caller in :func:`main` translates that into
    an exit code + stderr.
    """
    path = Path(path_str)
    if not path.is_file():
        raise ValueError(f"{BRIDGE_TOOLS_ENV}={path_str!r} but file does not exist")
    payload = path.read_text(encoding="utf-8")
    from plugins.petri_audit.mcp_bridge.tool_translator import deserialise_tool_specs

    return deserialise_tool_specs(payload)


async def _serve(tool_specs: list[dict[str, Any]]) -> None:
    """Run the MCP stdio server until claude disconnects.

    The handlers close over ``tool_specs`` (read-only) so there is no
    shared mutable state across the server lifecycle. claude calls
    ``tools/list`` once during the initialize handshake; ``tools/call``
    should never fire under the provider's ``--max-turns 1`` constraint
    but we return a sentinel payload anyway so the LLM has something
    visible to react to if the boundary fails."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    from mcp import types as mcp_types

    server: Server = Server(BRIDGE_SERVER_NAME)

    @server.list_tools()  # type: ignore[no-untyped-call, misc, unused-ignore]
    async def _list() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["inputSchema"],
            )
            for spec in tool_specs
        ]

    @server.call_tool()  # type: ignore[no-untyped-call, misc, unused-ignore]
    async def _call(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        log.warning(
            "bridge call_tool fired (--max-turns 1 should prevent this): tool=%s",
            name,
        )
        sentinel = {**_NO_EXEC_SENTINEL, "tool": name, "arguments": arguments}
        return [mcp_types.TextContent(type="text", text=json.dumps(sentinel))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    """Entry point invoked as ``python -m plugins.petri_audit.mcp_bridge.bridge_server``.

    Exit codes:
      * ``0`` — clean shutdown (claude disconnected).
      * ``2`` — missing/invalid ``GEODE_AUDIT_BRIDGE_TOOLS_JSON``.
      * ``3`` — MCP library import failure (audit extra not installed).
    """
    tools_path = os.environ.get(BRIDGE_TOOLS_ENV)
    if not tools_path:
        sys.stderr.write(
            f"bridge_server: missing env {BRIDGE_TOOLS_ENV} — "
            "lifecycle.prepare_bridge() must set this before spawning claude\n"
        )
        sys.exit(2)
    try:
        tool_specs = _read_tool_specs(tools_path)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"bridge_server: could not load tool specs: {exc}\n")
        sys.exit(2)
    try:
        asyncio.run(_serve(tool_specs))
    except ImportError as exc:
        sys.stderr.write(
            f"bridge_server: mcp library import failed ({exc}); "
            "install with `uv sync --extra audit`\n"
        )
        sys.exit(3)


if __name__ == "__main__":  # pragma: no cover
    main()
