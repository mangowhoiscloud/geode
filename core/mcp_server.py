"""GEODE MCP Server — expose analysis pipeline as MCP tools and resources."""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Use lazy imports to avoid circular dependencies
_TOOL_DESCRIPTIONS = {
    "analyze_ip": (
        "Run GEODE analysis pipeline on an IP. Returns tier, score, cause, and narrative."
    ),
    "quick_score": "Run scoring-only mode for fast tier/score estimation without full analysis.",
    "query_memory": "Search GEODE memory across tiers (session, project, organization).",
    "get_ip_signals": "Get community signals (YouTube, Reddit, trends) for an IP.",
    "list_fixtures": "List all available IP fixtures in the GEODE database.",
    "get_health": "Get GEODE pipeline health status and component stats.",
}


def create_mcp_server() -> Any:
    """Create and configure the GEODE MCP server.

    Returns a FastMCP Server instance with tools and resources registered.
    Requires the ``mcp`` package to be installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires the 'mcp' package. Install with: uv add mcp"
        ) from None

    mcp = FastMCP("geode-analysis")

    @mcp.tool(description=_TOOL_DESCRIPTIONS["analyze_ip"])  # type: ignore[untyped-decorator]
    def analyze_ip(ip_name: str, dry_run: bool = False) -> dict[str, Any]:
        """Run GEODE analysis pipeline on an IP."""
        from core.fixtures import FIXTURE_MAP

        key = ip_name.lower().strip()
        if key not in FIXTURE_MAP:
            return {"error": f"IP '{ip_name}' not found. Use list_fixtures to see available IPs."}

        try:
            from core.runtime import GeodeRuntime

            runtime = GeodeRuntime.create(ip_name)
            graph = runtime.compile_graph()

            initial_state: dict[str, Any] = {
                "ip_name": ip_name,
                "pipeline_mode": "full_pipeline",
                "dry_run": dry_run,
                "verbose": False,
                "analyses": [],
                "evaluations": {},
                "errors": [],
            }

            if not dry_run:
                tool_injection = runtime.get_tool_state_injection(mode="full_pipeline")
                initial_state.update(tool_injection)

            result = graph.invoke(initial_state, config=runtime.thread_config)  # type: ignore[arg-type]

            # Extract key results
            output: dict[str, Any] = {
                "ip_name": ip_name,
                "tier": result.get("tier", "?"),
                "final_score": result.get("final_score", 0),
                "dry_run": dry_run,
            }

            synthesis = result.get("synthesis")
            if synthesis:
                output["cause"] = synthesis.undervaluation_cause
                output["action"] = synthesis.action_type
                output["narrative"] = synthesis.value_narrative
                output["target_segment"] = synthesis.target_gamer_segment

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

    @mcp.tool(description=_TOOL_DESCRIPTIONS["quick_score"])  # type: ignore[untyped-decorator]
    def quick_score(ip_name: str) -> dict[str, Any]:
        """Run scoring-only mode for fast estimation."""
        result: dict[str, Any] = analyze_ip(ip_name, dry_run=True)
        return result

    @mcp.tool(description=_TOOL_DESCRIPTIONS["get_ip_signals"])  # type: ignore[untyped-decorator]
    def get_ip_signals(ip_name: str) -> dict[str, Any]:
        """Get community signals for an IP."""
        from core.fixtures import FIXTURE_MAP, load_fixture

        key = ip_name.lower().strip()
        if key not in FIXTURE_MAP:
            return {"error": f"IP '{ip_name}' not found."}

        fixture = load_fixture(ip_name)
        return {
            "ip_name": ip_name,
            "signals": fixture.get("signals", {}),
            "source": "fixture",
        }

    @mcp.tool(description=_TOOL_DESCRIPTIONS["list_fixtures"])  # type: ignore[untyped-decorator]
    def list_fixtures() -> dict[str, Any]:
        """List all available IP fixtures."""
        from core.fixtures import FIXTURE_MAP

        return {
            "count": len(FIXTURE_MAP),
            "ips": sorted(FIXTURE_MAP.keys()),
        }

    # Shared ProjectMemory instance (created once per server lifetime)
    _project_memory: Any = None

    @mcp.tool(description=_TOOL_DESCRIPTIONS["query_memory"])  # type: ignore[untyped-decorator]
    def query_memory(query: str) -> dict[str, Any]:
        """Search GEODE memory."""
        nonlocal _project_memory
        if _project_memory is None:
            from core.memory.project import ProjectMemory

            _project_memory = ProjectMemory()
        context = _project_memory.get_context_for_ip(query)
        return {"query": query, "context": context}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["get_health"])  # type: ignore[untyped-decorator]
    def get_health() -> dict[str, Any]:
        """Get pipeline health status."""
        from core.config import settings

        return {
            "model": settings.model,
            "ensemble_mode": settings.ensemble_mode,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }

    # Resources
    @mcp.resource("geode://fixtures")  # type: ignore[untyped-decorator]
    def fixtures_resource() -> str:
        """List all available IP fixtures."""
        from core.fixtures import FIXTURE_MAP

        return json.dumps({"count": len(FIXTURE_MAP), "ips": sorted(FIXTURE_MAP.keys())})

    @mcp.resource("geode://soul")  # type: ignore[untyped-decorator]
    def soul_resource() -> str:
        """Get SOUL.md content."""
        from core.memory.organization import DEFAULT_SOUL_PATH

        if DEFAULT_SOUL_PATH.exists():
            return DEFAULT_SOUL_PATH.read_text(encoding="utf-8")
        return ""

    return mcp


def main() -> None:
    """Entry point for running the MCP server."""
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = create_mcp_server()
    server.run()


if __name__ == "__main__":
    main()
