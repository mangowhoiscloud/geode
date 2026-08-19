"""Product-composed subprocess worker entry point."""

from core.agent.worker import main

from geode_product.tool_handlers import build_tool_handlers

if __name__ == "__main__":
    main(build_tool_handlers)
