"""Codex-side MCP bridge plumbing (CSA-2c — codex-cli mirror of CSA-2).

Where CSA-2's claude side passes ``--mcp-config <path>`` pointing at a
JSON file that materialises ``{"mcpServers": {"bridge": {...}}}``, the
codex side achieves the same wiring via repeated ``-c key=value`` flags
on ``codex exec``. The TOML config format codex uses for MCP servers
(under ``[mcp_servers.<name>]`` in ``~/.codex/config.toml``) is the
same shape, so each leaf field becomes one ``-c`` override.

This module owns the codex-specific argv emission. It deliberately
reuses :class:`plugins.petri_audit.mcp_bridge.lifecycle.BridgeInvocation`
unchanged — the bridge subprocess + tempdir + tools JSON are all
provider-agnostic; only the CLI invocation surface differs.

Tool-use event shape (codex JSONL):
``{"type": "item.completed", "item": {"type": "function_call",
"name": "mcp__bridge__<tool>", "arguments": "{...}",
"call_id": "..."}}`` — the ``name`` carries the same
``mcp__<server>__<tool>`` prefix convention as the claude side, so the
existing :func:`plugins.petri_audit.mcp_bridge.lifecycle.strip_mcp_prefix`
helper applies unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plugins.petri_audit.mcp_bridge.lifecycle import BridgeInvocation

log = logging.getLogger(__name__)

__all__ = [
    "build_codex_cli_mcp_overrides",
    "extract_codex_tool_calls",
]


def build_codex_cli_mcp_overrides(invocation: BridgeInvocation) -> list[str]:
    """Render the bridge invocation into ``-c key=value`` argv tokens.

    Codex parses values as TOML, so all strings must be quoted; list
    args use TOML array syntax. The keys mirror what would live under
    ``[mcp_servers.bridge]`` in ``~/.codex/config.toml``::

        [mcp_servers.bridge]
        command = "python"
        args = ["-m", "plugins.petri_audit.mcp_bridge.bridge_server"]
        env = { GEODE_AUDIT_BRIDGE_TOOLS_JSON = "/tmp/.../tools.json" }

    Reads the bridge config from :attr:`BridgeInvocation.mcp_config_json`
    (the same JSON file the claude side hands to ``--mcp-config``) so a
    single ``prepare_bridge`` call materialises the resources both CLI
    sides need. Returns a flat list of argv tokens ready to splice into
    the ``codex exec`` command line.
    """
    # The "bridge" server name is the convention pinned by
    # :data:`plugins.petri_audit.mcp_bridge.bridge_server.BRIDGE_SERVER_NAME`.
    server_name = "bridge"
    payload = json.loads(invocation.mcp_config_json.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers") or {}
    if server_name not in servers:
        raise ValueError(
            f"mcp_config.mcpServers must contain {server_name!r} key for codex overrides; "
            f"found {list(servers.keys())}"
        )
    spec = servers[server_name]

    tokens: list[str] = []
    tokens += ["-c", f"mcp_servers.{server_name}.command={json.dumps(spec['command'])}"]
    tokens += ["-c", f"mcp_servers.{server_name}.args={json.dumps(spec['args'])}"]
    env = spec.get("env") or {}
    for env_key, env_value in env.items():
        tokens += [
            "-c",
            f"mcp_servers.{server_name}.env.{env_key}={json.dumps(env_value)}",
        ]
    return tokens


def extract_codex_tool_calls(events: list[dict[str, Any]]) -> list[Any]:
    """Scan codex JSONL events for ``item.completed`` of type
    ``function_call`` and return ``inspect_ai.tool.ToolCall`` instances.

    The ``name`` field on each function_call carries the
    ``mcp__bridge__<tool>`` prefix convention codex shares with claude's
    MCP integration, so :func:`strip_mcp_prefix` from the shared
    lifecycle module restores the bare tool name. ``arguments`` is a
    JSON string per codex's event schema — parsed here; parse failures
    surface as ``parse_error`` on the returned ToolCall instead of
    raising (matching the claude side's tolerant contract).

    Returns an empty list when no function_call items are present —
    the caller treats that as "model emitted text only, no tools".
    """
    tool_call_cls: Any | None
    try:
        from inspect_ai import tool as inspect_tool
    except ImportError:
        # inspect_ai is part of the [audit] extra; without it we can
        # still parse but cannot construct ToolCall instances. Return
        # the raw dicts so callers in test contexts can introspect.
        log.debug("inspect_ai unavailable — returning raw tool_call dicts")
        tool_call_cls = None
    else:
        tool_call_cls = inspect_tool.ToolCall

    from plugins.petri_audit.mcp_bridge.lifecycle import strip_mcp_prefix

    calls: list[Any] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") != "function_call":
            continue
        raw_name = item.get("name", "") or ""
        bare_name = strip_mcp_prefix(raw_name)
        arguments_raw = item.get("arguments", "")
        parse_error: str | None = None
        arguments: dict[str, Any]
        try:
            arguments = json.loads(arguments_raw) if arguments_raw else {}
            if not isinstance(arguments, dict):
                parse_error = (
                    f"arguments must decode to a JSON object, got {type(arguments).__name__}"
                )
                arguments = {}
        except json.JSONDecodeError as exc:
            parse_error = f"arguments JSON decode failed: {exc}"
            arguments = {}

        call_id = item.get("call_id") or item.get("id") or ""

        if tool_call_cls is None:
            calls.append(
                {
                    "id": call_id,
                    "function": bare_name,
                    "arguments": arguments,
                    "parse_error": parse_error,
                    "type": "function",
                }
            )
        else:
            calls.append(
                tool_call_cls(
                    id=call_id,
                    function=bare_name,
                    arguments=arguments,
                    parse_error=parse_error,
                    type="function",
                )
            )

    return calls
