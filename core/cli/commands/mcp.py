"""``/mcp`` slash command — list/manage MCP servers.

Hosts ``cmd_mcp`` and the ``_mcp_add`` helper. Extracted from the
monolithic ``core/cli/commands.py`` (Tier 3 #9) — every function body is
preserved byte-identical from the legacy module.
"""

from __future__ import annotations

import logging
from typing import Any as _Any

log = logging.getLogger(__name__)


def cmd_mcp(arg: str, *, mcp_manager: _Any | None = None) -> None:
    """Handle /mcp command — list/manage MCP servers.

    /mcp or /mcp status  → server connection status + tool counts
    /mcp tools           → list all MCP tool names
    /mcp reload          → reload config and reconnect
    """
    from core.cli import commands as _pkg
    from core.mcp.manager import MCPServerManager

    mgr: MCPServerManager
    if mcp_manager is not None:
        mgr = mcp_manager
    else:
        mgr = MCPServerManager()
        mgr.load_config()

    sub = arg.strip().lower() if arg else ""

    if not sub or sub in ("status", "list"):
        servers = mgr.list_servers()
        if not servers:
            _pkg.console.print("  [muted]No MCP servers configured.[/muted]")
            _pkg.console.print("  [muted]Add servers to .claude/mcp_servers.json[/muted]")
            _pkg.console.print()
            return

        _pkg.console.print()
        _pkg.console.print("  [header]MCP Servers[/header]")
        for s in servers:
            connected = s["connected"]
            status = "[success]connected[/success]" if connected else "[muted]off[/muted]"
            _pkg.console.print(
                f"  {s['name']:20s} {status}  "
                f"[muted]{s['command']} ({s['tool_count']} tools)[/muted]"
            )
        _pkg.console.print()
        return

    if sub == "tools":
        all_tools = mgr.get_all_tools()
        if not all_tools:
            _pkg.console.print("  [muted]No MCP tools available.[/muted]")
            _pkg.console.print()
            return

        _pkg.console.print()
        _pkg.console.print("  [header]MCP Tools[/header]")
        for tool in all_tools:
            server = tool.get("_mcp_server", "unknown")
            name = tool.get("name", "?")
            desc = tool.get("description", "")[:60]
            _pkg.console.print(f"  [label]{name:30s}[/label] [muted]{server}[/muted]  {desc}")
        _pkg.console.print()
        return

    if sub == "reload":
        count = mgr.reload_config()
        _pkg.console.print(f"  [success]MCP config reloaded: {count} server(s)[/success]")
        _pkg.console.print()
        return

    if sub.startswith("add"):
        _mcp_add(mgr, sub[3:].strip())
        return

    _pkg.console.print(f"  [muted]MCP subcommand not recognized: {arg}[/muted]")
    _pkg.console.print("  [muted]Usage: /mcp [status|tools|reload|add][/muted]")
    _pkg.console.print()


def _mcp_add(mgr: _Any, raw: str) -> None:
    """Handle /mcp add <name> <command> [args...].

    Example: /mcp add brave-search npx -y @anthropic/mcp-server-brave-search
    """
    from core.cli import commands as _pkg

    parts = raw.split() if raw else []
    if len(parts) < 2:
        _pkg.console.print("  [warning]Usage: /mcp add <name> <command> [args...][/warning]")
        _pkg.console.print(
            "  [muted]Example: /mcp add brave-search npx"
            " -y @anthropic/mcp-server-brave-search[/muted]"
        )
        _pkg.console.print()
        return

    name = parts[0]
    command = parts[1]
    cmd_args = parts[2:] if len(parts) > 2 else []

    if mgr.add_server(name, command, args=cmd_args):
        _pkg.console.print(f"  [success]Added MCP server: {name}[/success]")
        _pkg.console.print(f"  [muted]Command: {command} {' '.join(cmd_args)}[/muted]")
        _pkg.console.print("  [muted]Saved to .claude/mcp_servers.json[/muted]")
    else:
        _pkg.console.print(f"  [warning]Failed to add MCP server: {name}[/warning]")
    _pkg.console.print()
