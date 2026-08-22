"""Runtime tool-handler composition without a CLI-owned catalog.

The neutral handler groups and collision-checking registrar live here. CLI
interaction handlers are supplied as explicit groups by an outer composition
root; this package never imports ``core.cli`` merely to assemble a runtime.

Handler groups:
- :mod:`delegated`      — registry-based wrappers for web/file/note/profile tools
- :mod:`mcp`            — install_mcp_server
- :mod:`observability`  — observability tools
- :mod:`single_tool`    — handlers that each wrap exactly one
                           tool class: calculate, generate_data, send_notification,
                           generate_report/export_json,
                           recall_tool_result, computer (env-gated),
                           calendar_list/create_event/sync_scheduler
                           (folded together in PR-CLEANUP-5).

Plus shared clarification helpers in :mod:`clarification`
(``_clarify``, ``_safe_delegate``) — renamed from the pre-PR-CLEANUP-5
``_helpers.py``.

CLI-owned plan, goal, feedback, context, command, scheduler, memory-command,
and task-session callbacks remain injectable interaction groups.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from core.tools.handlers.clarification import (
    _clarify,
    _safe_delegate,
)
from core.tools.handlers.delegated import (
    _DELEGATED_TOOLS,
    _build_delegated_handlers,
    _make_delegate_handler,
    make_delegate_handler,
)
from core.tools.handlers.mcp import _build_mcp_handler
from core.tools.handlers.observability import _build_observability_handlers
from core.tools.handlers.registration import UniqueEntries
from core.tools.handlers.single_tool import (
    _build_calendar_handlers,
    _build_computer_use_handler,
    _build_data_handlers,
    _build_math_handlers,
    _build_notification_handlers,
    _build_offload_handlers,
    _build_output_handlers,
    _build_use_skill_handler,
)
from core.tools.memory_tools import MemoryToolServices

if TYPE_CHECKING:
    from core.mcp.calendar_port import CalendarPort
    from core.mcp.notification_port import NotificationPort
    from core.memory.user_profile import FileBasedUserProfile
    from core.orchestration.tool_offload import ToolResultOffloadStore
    from core.scheduler.calendar_bridge import CalendarSchedulerBridge

__all__ = [
    "_DELEGATED_TOOLS",
    "ToolIntegrationServices",
    "ToolPersistenceServices",
    "_build_calendar_handlers",
    "_build_computer_use_handler",
    "_build_data_handlers",
    "_build_delegated_handlers",
    "_build_math_handlers",
    "_build_mcp_handler",
    "_build_notification_handlers",
    "_build_observability_handlers",
    "_build_offload_handlers",
    "_build_output_handlers",
    "_build_tool_handler_catalog",
    "_clarify",
    "_make_delegate_handler",
    "_safe_delegate",
    "make_delegate_handler",
    "neutral_handler_groups",
]


@dataclass(frozen=True, slots=True)
class ToolPersistenceServices:
    """Persistence dependencies consumed by native tool instances."""

    memory: MemoryToolServices = field(default_factory=MemoryToolServices)
    user_profile: FileBasedUserProfile | None = None
    offload_store: ToolResultOffloadStore | None = None


@dataclass(frozen=True, slots=True)
class ToolIntegrationServices:
    """External ports consumed by native tool instances."""

    calendar: CalendarPort | None = None
    notification: NotificationPort | None = None
    calendar_bridge: CalendarSchedulerBridge | None = None


@dataclass(frozen=True)
class _ToolHandlerCatalog:
    """Immutable handler snapshot with one traceable origin per tool name."""

    handlers: Mapping[str, Any]
    origins: Mapping[str, str]


class _HandlerRegistrar:
    """Fail-closed composer for runtime handler contribution groups.

    ``dict.update`` silently replaced an earlier handler when two builder
    groups claimed the same name.  That made runtime behavior depend on merge
    order and left architecture inventory unable to observe the collision.
    This registrar is the single composition point: every name keeps its
    source and duplicate registration aborts before a ``ToolExecutor`` exists.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}
        self._origins: dict[str, str] = {}

    def add(self, source: str, handlers: UniqueEntries[str, Any]) -> None:
        if not isinstance(handlers, UniqueEntries):
            raise TypeError(
                f"{source}: handler builders must return lossless UniqueEntries, "
                f"not {type(handlers).__name__}"
            )
        duplicates = sorted(set(handlers) & set(self._handlers))
        if duplicates:
            detail = ", ".join(
                f"{name!r} ({self._origins[name]} vs {source})" for name in duplicates
            )
            raise ValueError(f"duplicate tool handler registration: {detail}")
        self._handlers.update(handlers)
        self._origins.update(dict.fromkeys(handlers, source))

    def snapshot(self) -> _ToolHandlerCatalog:
        return _ToolHandlerCatalog(
            handlers=MappingProxyType(dict(self._handlers)),
            origins=MappingProxyType(dict(self._origins)),
        )


def neutral_handler_groups(
    *,
    mcp_manager: Any = None,
    skill_registry: Any = None,
    persistence: ToolPersistenceServices | None = None,
    integrations: ToolIntegrationServices | None = None,
) -> tuple[tuple[str, UniqueEntries[str, Any]], ...]:
    """Return the neutral contribution set for an outer composition root."""
    from core.tools.memory_tools import NoteReadTool, NoteSaveTool
    from core.tools.profile_tools import (
        ProfileLearnTool,
        ProfilePreferenceTool,
        ProfileShowTool,
        ProfileUpdateTool,
    )

    persistence = persistence or ToolPersistenceServices()
    integrations = integrations or ToolIntegrationServices()
    delegated_instances = {
        "note_save": NoteSaveTool(persistence.memory),
        "note_read": NoteReadTool(persistence.memory),
        "profile_show": ProfileShowTool(persistence.user_profile),
        "profile_update": ProfileUpdateTool(persistence.user_profile),
        "profile_preference": ProfilePreferenceTool(persistence.user_profile),
        "profile_learn": ProfileLearnTool(persistence.user_profile),
    }
    return (
        ("math", _build_math_handlers()),
        ("data", _build_data_handlers()),
        ("delegated", _build_delegated_handlers(delegated_instances)),
        ("output", _build_output_handlers()),
        ("notification", _build_notification_handlers(integrations.notification)),
        (
            "calendar",
            _build_calendar_handlers(integrations.calendar, integrations.calendar_bridge),
        ),
        ("mcp", _build_mcp_handler(mcp_manager)),
        ("offload", _build_offload_handlers(persistence.offload_store)),
        ("computer-use", _build_computer_use_handler()),
        ("observability", _build_observability_handlers()),
        ("skill", _build_use_skill_handler(skill_registry)),
    )


def _build_tool_handler_catalog(
    groups: Iterable[tuple[str, UniqueEntries[str, Any]]],
) -> _ToolHandlerCatalog:
    """Fold explicit contribution groups into one immutable catalog."""
    registrar = _HandlerRegistrar()
    for source, handlers in groups:
        registrar.add(source, handlers)
    return registrar.snapshot()
