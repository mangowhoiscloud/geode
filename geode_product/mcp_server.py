"""Product-composed GEODE MCP entry point."""

from typing import Any

from core.cli.bootstrap import arun_agentic_oneshot
from core.mcp_server import main as run_mcp_server

from geode_product.self_improving.mcp import register_mcp_tools
from geode_product.tool_handlers import compose_tool_plan
from geode_product.wiring import (
    build_middleware_registry,
    build_policy_sources,
    current_activity_sink,
)


async def run_agent(prompt: str, **kwargs: Any) -> Any:
    """Run the MCP one-shot with the same product contributions as the daemon."""
    return await arun_agentic_oneshot(
        prompt,
        policy_sources=build_policy_sources(),
        middleware_builder=build_middleware_registry,
        activity_sink_provider=current_activity_sink,
        **kwargs,
    )


def main() -> None:
    run_mcp_server(
        compose_tool_plan,
        agent_runner=run_agent,
        feature_registrar=register_mcp_tools,
    )
