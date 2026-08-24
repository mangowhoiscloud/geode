"""Official native subprocess-worker composition."""

from core.agent.worker import main as run_worker
from core.tools.composition import compose_tool_plan
from core.wiring.runtime import build_middleware_registry


def main() -> None:
    run_worker(compose_tool_plan, middleware_builder=build_middleware_registry)


if __name__ == "__main__":
    main()
