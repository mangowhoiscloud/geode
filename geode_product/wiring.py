"""First-party product composition over the closed kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from geode_product.tool_handlers import build_tool_handlers


def build_shared_services(**kwargs: Any) -> Any:
    """Build kernel services with product tools, workers, and agent prompts."""
    from core.server.supervised.services import build_shared_services as build_core_services

    return build_core_services(
        **kwargs,
        tool_handler_builder=build_tool_handlers,
        worker_module="geode_product.worker",
        agent_search_dirs=(Path(__file__).parent / "seed_generation" / "agents",),
    )


def serve(
    poll_interval: float = typer.Option(
        3.0, "--poll", "-p", help="Gateway poll interval (seconds)"
    ),
) -> None:
    """Run the GEODE daemon with first-party product composition."""
    from core.cli.typer_serve import run_serve

    run_serve(poll_interval, services_builder=build_shared_services)
