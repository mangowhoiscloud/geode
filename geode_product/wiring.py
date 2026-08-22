"""First-party product composition over the closed kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from geode_product.tool_handlers import compose_tool_plan


def build_policy_sources() -> Any:
    """Build the first-party self-improving policy bundle."""
    from geode_product.self_improving.policy_sources import build_policy_source_bundle

    return build_policy_source_bundle()


def build_middleware_registry(*, events: Any = None, policy_sources: Any = None) -> Any:
    """Build the kernel registry and add first-party request middleware."""
    from core.hooks import MiddlewareRegistry

    from geode_product.self_improving.loop.inject.in_context_wiring import (
        register_in_context_middleware,
    )

    resolved_sources = build_policy_sources() if policy_sources is None else policy_sources
    registry = MiddlewareRegistry(events=events)
    register_in_context_middleware(registry, policy_sources=resolved_sources)
    return registry


def current_activity_sink() -> Any:
    """Return the active first-party run-event projection, when bound."""
    from geode_product.self_improving.loop.observe.run_timeline import current_run_timeline

    return current_run_timeline()


def bind_worker_activity(run_dir: Path) -> None:
    """Bind a worker process to the orchestrator's run-event projection."""
    from geode_product.self_improving.loop.observe.run_timeline import (
        RunTimeline,
        set_current_run_timeline,
    )

    set_current_run_timeline(
        RunTimeline(
            session_id=run_dir.name,
            gen_tag="",
            component="seed-generation",
            path=run_dir / "events.jsonl",
        )
    )


def register_hooks(hooks: Any) -> None:
    """Bind product mutation events to one kernel-owned hook system."""
    from geode_product.self_improving.loop._hooks import (
        clear_self_improving_loop_hooks,
        set_self_improving_loop_hooks,
    )

    set_self_improving_loop_hooks(hooks)
    hooks.add_owner_cleanup(
        "self_improving_loop_hooks",
        clear_self_improving_loop_hooks,
        replace=True,
    )


def register_scheduling(trigger_manager: Any, hooks: Any) -> None:
    """Register the opt-in first-party auto-trigger contribution."""
    from geode_product.self_improving.config import load_self_improving_loop_config
    from geode_product.self_improving.loop.auto_trigger import register_auto_trigger

    config = load_self_improving_loop_config().scheduler
    register_auto_trigger(
        trigger_manager,
        enabled=config.enabled,
        cron=config.cron,
        min_interval_minutes=config.min_interval_minutes,
        max_generation=config.max_generation,
        hooks=hooks,
    )


def build_runtime() -> Any:
    """Build the gateway runtime with first-party feature contributions."""
    from core.runtime import GeodeRuntime

    return GeodeRuntime.create(
        "gateway",
        policy_sources=build_policy_sources(),
        middleware_builder=build_middleware_registry,
        activity_sink_provider=current_activity_sink,
        feature_hook_registrar=register_hooks,
        scheduling_registrar=register_scheduling,
    )


def build_shared_services(**kwargs: Any) -> Any:
    """Build kernel services with product tools, workers, and agent prompts."""
    from core.server.supervised.services import build_shared_services as build_core_services
    from core.slash_routing import compose_command_registry

    from geode_product.geo_state import GeoStore
    from geode_product.slash_commands import PRODUCT_COMMAND_SPECS

    if kwargs.get("policy_sources") is None:
        kwargs["policy_sources"] = build_policy_sources()
    kwargs.setdefault("middleware_builder", build_middleware_registry)
    kwargs.setdefault("activity_sink_provider", current_activity_sink)
    kwargs.setdefault("feature_hook_registrar", register_hooks)
    kwargs.setdefault("command_registry", compose_command_registry(PRODUCT_COMMAND_SPECS))
    return build_core_services(
        **kwargs,
        tool_plan_builder=compose_tool_plan,
        worker_module="geode_product.worker",
        agent_search_dirs=(Path(__file__).parent / "seed_generation" / "agents",),
        control_state_factories={"geo": GeoStore},
    )


def serve(
    poll_interval: float = typer.Option(
        3.0, "--poll", "-p", help="Gateway poll interval (seconds)"
    ),
) -> None:
    """Run the GEODE daemon with first-party product composition."""
    from core.cli.typer_serve import run_serve

    run_serve(
        poll_interval,
        services_builder=build_shared_services,
        runtime_builder=build_runtime,
    )
