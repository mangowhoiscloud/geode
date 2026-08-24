"""Official GEODE runtime composition."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from core.tools.composition import compose_tool_plan


def build_policy_sources() -> Any:
    """Build the runtime policy bundle."""
    from core.config.runtime_policy_sources import build_policy_source_bundle

    return build_policy_source_bundle()


def build_middleware_registry(*, events: Any = None, policy_sources: Any = None) -> Any:
    """Build the runtime request-middleware registry."""
    from core.agent.policy_injection.in_context_wiring import (
        register_in_context_middleware,
    )
    from core.hooks import MiddlewareRegistry

    resolved_sources = build_policy_sources() if policy_sources is None else policy_sources
    registry = MiddlewareRegistry(events=events)
    register_in_context_middleware(registry, policy_sources=resolved_sources)
    return registry


def build_runtime(
    scheduler_callback: Callable[[str, str, bool, str], None] | None = None,
) -> Any:
    """Build the gateway runtime."""
    from core.runtime import GeodeRuntime

    return GeodeRuntime.create(
        "gateway",
        policy_sources=build_policy_sources(),
        middleware_builder=build_middleware_registry,
        scheduler_callback=scheduler_callback,
    )


def build_shared_services(**kwargs: Any) -> Any:
    """Build runtime services with native tools and workers."""
    from core.cli.commands import _get_cost_budget
    from core.server.supervised.services import build_shared_services as build_core_services

    if kwargs.get("policy_sources") is None:
        kwargs["policy_sources"] = build_policy_sources()
    kwargs.setdefault("middleware_builder", build_middleware_registry)
    kwargs.setdefault("cost_budget", _get_cost_budget())
    return build_core_services(
        **kwargs,
        tool_plan_builder=compose_tool_plan,
        worker_module="core.worker",
    )


def serve(
    poll_interval: float = typer.Option(
        3.0, "--poll", "-p", help="Gateway poll interval (seconds)"
    ),
) -> None:
    """Run the GEODE daemon."""
    from core.cli.typer_serve import run_serve

    run_serve(
        poll_interval,
        services_builder=build_shared_services,
        runtime_builder=build_runtime,
    )
