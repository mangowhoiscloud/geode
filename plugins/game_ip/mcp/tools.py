"""Game IP plugin — MCP tool registrations.

This module owns the four IP-specific MCP tools (``analyze_ip``,
``quick_score``, ``get_ip_signals``, ``list_fixtures``) and the
``geode://fixtures`` resource that previously lived in
``core/mcp_server.py``.

Step 6 of the domain-free-core refactor moves them out of ``core/`` so the
core MCP server shell only registers domain-agnostic tools (``query_memory``,
``get_health``, ``geode://soul``). ``GameIPDomain.register_mcp_tools`` calls
:func:`register_game_ip_mcp_tools` to attach these tools/resources to a
FastMCP server instance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)

# Plugin-local tool description registry (split from core/tools/mcp_tools.json
# in step 6 — generic descriptions stay in core, plugin-specific ones live
# alongside the plugin code that consumes them).
_MCP_TOOLS_PATH = Path(__file__).resolve().parent / "mcp_tools.json"
with _MCP_TOOLS_PATH.open(encoding="utf-8") as _f:
    _TOOL_DESCRIPTIONS: dict[str, str] = json.load(_f)


def register_game_ip_mcp_tools(server: Any) -> None:
    """Register the game-IP MCP tools and resources on ``server``.

    The plugin uses FastMCP decorators (``@server.tool()``,
    ``@server.resource()``) to attach its tools/resources at server-creation
    time. ``server`` is expected to be a ``mcp.server.fastmcp.FastMCP``
    instance, but we don't import it eagerly at module top (FastMCP is an
    optional runtime dependency). The ``cast`` to ``FastMCP`` below tells
    mypy the decorator types without affecting runtime.
    """
    mcp = cast("FastMCP", server)

    @mcp.tool(description=_TOOL_DESCRIPTIONS["analyze_ip"])
    def analyze_ip(ip_name: str, dry_run: bool = False) -> dict[str, Any]:
        """Run GEODE analysis pipeline on an IP."""
        from plugins.game_ip.fixtures import FIXTURE_MAP

        key = ip_name.lower().strip()
        if key not in FIXTURE_MAP:
            return {"error": f"IP '{ip_name}' not found. Use list_fixtures to see available IPs."}

        try:
            from core.runtime import GeodeRuntime

            runtime = GeodeRuntime.create(ip_name)
            graph = runtime.compile_graph()

            from core.config import settings

            initial_state: dict[str, Any] = {
                "ip_name": ip_name,
                "pipeline_mode": "full_pipeline",
                "dry_run": dry_run,
                "verbose": False,
                "analyses": [],
                "evaluations": {},
                "errors": [],
                # Ensemble config injection (L5 nodes read from state, not settings)
                "_ensemble_mode": settings.ensemble_mode,
                "_secondary_analysts": settings.secondary_analysts,
            }

            if not dry_run:
                tool_injection = runtime.get_tool_state_injection(mode="full_pipeline")
                initial_state.update(tool_injection)

            result = graph.invoke(initial_state, config=runtime.thread_config)  # type: ignore[call-overload]

            # Extract key results
            output: dict[str, Any] = {
                "ip_name": ip_name,
                "tier": result.get("tier", "?"),
                "final_score": result.get("final_score", 0),
                "dry_run": dry_run,
            }

            # B2: propagate pipeline errors to caller
            pipeline_errors = result.get("errors", [])
            if pipeline_errors:
                output["errors"] = pipeline_errors

            synthesis = result.get("synthesis")
            if synthesis:
                output["cause"] = synthesis.undervaluation_cause
                output["action"] = synthesis.action_type
                output["narrative"] = synthesis.value_narrative
                output["target_segment"] = synthesis.target_segment

            analyses = result.get("analyses", [])
            output["analysts"] = [
                {"type": a.analyst_type, "score": a.score, "finding": a.key_finding}
                for a in analyses
            ]

            runtime.shutdown()
            return output
        except Exception as exc:
            log.error("MCP analyze_ip failed: %s", exc)
            return {"error": str(exc)}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["quick_score"])
    def quick_score(ip_name: str) -> dict[str, Any]:
        """Run scoring-only mode for fast estimation."""
        result: dict[str, Any] = analyze_ip(ip_name, dry_run=True)
        return result

    @mcp.tool(description=_TOOL_DESCRIPTIONS["get_ip_signals"])
    def get_ip_signals(ip_name: str) -> dict[str, Any]:
        """Get community signals for an IP."""
        from plugins.game_ip.fixtures import FIXTURE_MAP, load_fixture

        key = ip_name.lower().strip()
        if key not in FIXTURE_MAP:
            return {"error": f"IP '{ip_name}' not found."}

        fixture = load_fixture(ip_name)
        return {
            "ip_name": ip_name,
            "signals": fixture.get("signals", {}),
            "source": "fixture",
        }

    @mcp.tool(description=_TOOL_DESCRIPTIONS["list_fixtures"])
    def list_fixtures() -> dict[str, Any]:
        """List all available IP fixtures."""
        from plugins.game_ip.fixtures import FIXTURE_MAP

        return {
            "count": len(FIXTURE_MAP),
            "ips": sorted(FIXTURE_MAP.keys()),
        }

    @mcp.resource("geode://fixtures")
    def fixtures_resource() -> str:
        """List all available IP fixtures."""
        from plugins.game_ip.fixtures import FIXTURE_MAP

        return json.dumps({"count": len(FIXTURE_MAP), "ips": sorted(FIXTURE_MAP.keys())})
