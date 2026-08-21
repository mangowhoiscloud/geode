"""Product-composed subprocess worker entry point."""

from core.agent.worker import main

from geode_product.tool_handlers import compose_tool_plan
from geode_product.wiring import (
    bind_worker_activity,
    build_middleware_registry,
    current_activity_sink,
)

if __name__ == "__main__":
    main(
        compose_tool_plan,
        middleware_builder=build_middleware_registry,
        activity_sink_provider=current_activity_sink,
        worker_activity_binder=bind_worker_activity,
    )
