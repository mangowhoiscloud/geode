"""MCP server installation handler."""

from __future__ import annotations

from typing import Any

from core.cli.tool_handlers.registration import UniqueEntries


def _build_mcp_handler(
    mcp_manager: Any,
) -> UniqueEntries[str, Any]:
    """Build MCP server installation handler."""

    def handle_install_mcp_server(**kwargs: Any) -> dict[str, Any]:
        from core.mcp.registry import search_registry

        query = kwargs.get("query", "")
        matches = search_registry(query)
        if not matches:
            return {
                "status": "not_found",
                "message": f"No MCP server found for '{query}'. Try a different keyword.",
            }

        best = matches[0]

        # Already installed?
        if mcp_manager is not None:
            existing = {s["name"] for s in mcp_manager.list_servers()}
            if best.name in existing:
                return {
                    "status": "already_installed",
                    "server": best.name,
                    "message": f"{best.name} is already installed.",
                }

        return {
            "status": "found",
            "server": best.name,
            "title": best.title,
            "description": best.description,
            "repository_url": best.repository_url,
            "message": (
                f"Found: {best.title} ({best.name}). "
                f"Add it to .geode/config.toml [mcp.servers.{best.name}] "
                f"with the appropriate command and args."
            ),
        }

    return UniqueEntries[str, Any]((("install_mcp_server", handle_install_mcp_server),))
