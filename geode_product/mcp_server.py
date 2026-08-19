"""Product-composed GEODE MCP entry point."""

from core.mcp_server import main as run_mcp_server

from geode_product.tool_handlers import build_tool_handlers


def main() -> None:
    run_mcp_server(build_tool_handlers)
