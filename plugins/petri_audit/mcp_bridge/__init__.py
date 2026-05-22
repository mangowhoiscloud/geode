"""Paperclip-pattern MCP bridge (CSA-2) — auditor tool_use support.

The :mod:`plugins.petri_audit.claude_cli_provider` ``generate(tools=[...])``
path drives one local MCP stdio server per call. The bridge exposes
inspect_ai ``ToolInfo[]`` as MCP tools so the claude CLI subprocess
(spawned with ``--mcp-config`` / ``--strict-mcp-config`` / ``--allowed-tools``)
can see them at planning time and emit ``tool_use`` content blocks
under ``--max-turns 1`` without ever actually executing them — the
real execution stays with inspect_petri's solver in the parent process.

Wire-protocol shim only: bridge handlers return a no-exec sentinel
that should never be observed under the provider's ``--max-turns 1``
boundary. If a sentinel ever shows up in a ``ChatMessageTool`` result
that means the boundary failed; surface it as a provider error.

See :mod:`plugins.petri_audit.mcp_bridge.tool_translator`,
:mod:`bridge_server`, :mod:`lifecycle`, and
:mod:`stream_parser_ext` for the per-module contracts.
"""

from __future__ import annotations

from plugins.petri_audit.mcp_bridge.bridge_server import (
    BRIDGE_SERVER_NAME,
    BRIDGE_TOOLS_ENV,
)
from plugins.petri_audit.mcp_bridge.lifecycle import (
    BRIDGE_KEEP_TEMP_ENV,
    BridgeInvocation,
    allowed_tool_names,
    build_mcp_config,
    prepare_bridge,
    release_bridge,
    strip_mcp_prefix,
)
from plugins.petri_audit.mcp_bridge.stream_parser_ext import (
    ToolUseAccumulator,
    extract_tool_calls,
)
from plugins.petri_audit.mcp_bridge.tool_translator import (
    deserialise_tool_specs,
    serialise_tool_infos_for_bridge,
    tool_info_to_mcp_tool,
    tool_info_to_spec_dict,
    tool_infos_to_mcp_tools,
)

__all__ = [
    "BRIDGE_KEEP_TEMP_ENV",
    "BRIDGE_SERVER_NAME",
    "BRIDGE_TOOLS_ENV",
    "BridgeInvocation",
    "ToolUseAccumulator",
    "allowed_tool_names",
    "build_mcp_config",
    "deserialise_tool_specs",
    "extract_tool_calls",
    "prepare_bridge",
    "release_bridge",
    "serialise_tool_infos_for_bridge",
    "strip_mcp_prefix",
    "tool_info_to_mcp_tool",
    "tool_info_to_spec_dict",
    "tool_infos_to_mcp_tools",
]
