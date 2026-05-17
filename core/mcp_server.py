"""GEODE MCP Server — expose generic GEODE tools and let the active domain
plugin register its own tools/resources via :meth:`DomainPort.register_mcp_tools`.

This module keeps the FastMCP server shell, the two domain-agnostic tools
(``query_memory``, ``get_health``), the ``geode://soul`` resource, and the
``main()`` stdio entry point.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Load core-generic MCP tool descriptions from centralized JSON.
# Plugin-specific descriptions live alongside their plugin module.
_MCP_TOOLS_PATH = Path(__file__).resolve().parent / "tools" / "mcp_tools.json"
with _MCP_TOOLS_PATH.open(encoding="utf-8") as _f:
    _TOOL_DESCRIPTIONS: dict[str, str] = json.load(_f)


def create_mcp_server() -> Any:
    """Create and configure the GEODE MCP server.

    Returns a FastMCP Server instance with the generic core tools/resources
    registered. The active domain plugin (if any) gets a chance to register
    its own tools/resources via ``domain.register_mcp_tools(server)`` before
    the server is returned.

    Requires the ``mcp`` package to be installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires the 'mcp' package. Install with: uv add mcp"
        ) from None

    mcp = FastMCP("geode-analysis")

    # Shared ProjectMemory instance (created once per server lifetime)
    _project_memory: Any = None

    @mcp.tool(description=_TOOL_DESCRIPTIONS["query_memory"])
    def query_memory(query: str) -> dict[str, Any]:
        """Search GEODE memory."""
        nonlocal _project_memory
        if _project_memory is None:
            from core.memory.project import ProjectMemory

            _project_memory = ProjectMemory()
        context = _project_memory.get_context_for_ip(query)
        return {"query": query, "context": context}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["get_health"])
    def get_health() -> dict[str, Any]:
        """Get pipeline health status."""
        from core.config import settings

        return {
            "model": settings.model,
            "ensemble_mode": settings.ensemble_mode,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }

    @mcp.resource("geode://soul")
    def soul_resource() -> str:
        """Get SOUL.md content."""
        from core.memory.organization import DEFAULT_SOUL_PATH

        if DEFAULT_SOUL_PATH.exists():
            return DEFAULT_SOUL_PATH.read_text(encoding="utf-8")
        return ""

    # Domain-plugin extension point — let the active domain (if any)
    # register its own MCP tools/resources on the server. Failures are
    # logged at debug level so a broken plugin doesn't take the server
    # down (the generic tools above stay functional regardless).
    from core.domains.port import get_domain_or_none

    domain = get_domain_or_none()
    if domain is not None:
        register = getattr(domain, "register_mcp_tools", None)
        if callable(register):
            try:
                register(mcp)
            except Exception:
                log.debug("Domain MCP tool registration skipped", exc_info=True)

    return mcp


def main() -> None:
    """Entry point for running the MCP server."""
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = create_mcp_server()
    server.run()


if __name__ == "__main__":
    main()
