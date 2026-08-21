"""CLI interaction contributions and legacy handler-map forwarders.

The collision-checked runtime catalog lives in :mod:`core.tools.handlers`.
This package owns callbacks that depend on CLI, UI, or session process state,
plus the private dictionary builder retained for CLI and test compatibility.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.cli.tool_handlers.context import _build_context_handlers
from core.cli.tool_handlers.execution import _build_execution_handlers
from core.cli.tool_handlers.goal import _build_goal_handlers
from core.cli.tool_handlers.hitl import _build_hitl_handlers
from core.cli.tool_handlers.memory import _build_memory_handlers
from core.cli.tool_handlers.plan import _build_plan_handlers
from core.cli.tool_handlers.system import _build_system_handlers
from core.cli.tool_handlers.task import _build_task_handlers
from core.tools.handlers import (
    _build_tool_handler_catalog as _compose_handler_catalog,
)
from core.tools.handlers import _HandlerRegistrar, _ToolHandlerCatalog, neutral_handler_groups
from core.tools.handlers.registration import UniqueEntries

__all__ = [
    "_HandlerRegistrar",
    "_ToolHandlerCatalog",
    "_build_context_handlers",
    "_build_execution_handlers",
    "_build_goal_handlers",
    "_build_hitl_handlers",
    "_build_memory_handlers",
    "_build_plan_handlers",
    "_build_system_handlers",
    "_build_task_handlers",
    "_build_tool_handler_catalog",
    "_build_tool_handlers",
    "build_tool_handlers",
    "cli_handler_groups",
]


# Shared CLI plan store. Kept lazy so tests and alternate roots can replace
# the configured plans path before the first handler catalog is composed.
_PLAN_STORE: Any | None = None


def _get_plan_store() -> Any:
    """Return the process-wide disk-persistent CLI plan store."""
    global _PLAN_STORE
    if _PLAN_STORE is None:
        from core.orchestration.plan_store import PlanStore

        _PLAN_STORE = PlanStore()
    return _PLAN_STORE


def cli_handler_groups(
    *,
    mcp_manager: Any = None,
    command_registry: Any = None,
) -> tuple[tuple[str, UniqueEntries[str, Any]], ...]:
    """Return callbacks that deliberately cross into CLI interaction state."""
    from core.cli import _get_readiness

    readiness = _get_readiness()
    force_dry = readiness.force_dry_run if readiness else True
    return (
        ("plan", _build_plan_handlers()),
        ("goal", _build_goal_handlers()),
        ("hitl", _build_hitl_handlers()),
        ("memory", _build_memory_handlers()),
        (
            "system",
            _build_system_handlers(readiness, force_dry, mcp_manager, command_registry),
        ),
        ("execution", _build_execution_handlers()),
        ("context", _build_context_handlers()),
        ("task", _build_task_handlers()),
    )


def _build_tool_handler_catalog(
    *,
    mcp_manager: Any = None,
    skill_registry: Any = None,
    command_registry: Any = None,
    extra_groups: Iterable[tuple[str, UniqueEntries[str, Any]]] = (),
) -> _ToolHandlerCatalog:
    """Compatibility composer over the neutral runtime registrar."""
    return _compose_handler_catalog(
        (
            *neutral_handler_groups(
                mcp_manager=mcp_manager,
                skill_registry=skill_registry,
            ),
            *cli_handler_groups(
                mcp_manager=mcp_manager,
                command_registry=command_registry,
            ),
            *extra_groups,
        )
    )


def _build_tool_handlers(
    verbose: bool = False,
    *,
    mcp_manager: Any = None,
    skill_registry: Any = None,
    command_registry: Any = None,
    extra_groups: Iterable[tuple[str, UniqueEntries[str, Any]]] = (),
) -> dict[str, Any]:
    """Return a mutable copy for legacy CLI-only consumers."""
    _ = verbose
    catalog = _build_tool_handler_catalog(
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        command_registry=command_registry,
        extra_groups=extra_groups,
    )
    return dict(catalog.handlers)


build_tool_handlers = _build_tool_handlers
