"""Tool handler factory — builds tool name -> handler function mapping.

Originally a single 1472-LOC module (``core/cli/tool_handlers.py``); split
into one file per handler group while preserving the public API surface
(``_build_tool_handlers``) and the names imported by external callers.

Handler groups:
- :mod:`memory`         — memory_search, memory_save, manage_rule
- :mod:`plan`           — create/approve/reject/modify/list_plan
- :mod:`hitl`           — rate/accept/reject_result, rerun_node
- :mod:`system`         — show_help, check_status, switch_model, set_api_key,
                           manage_auth, manage_login, doctor_slack
- :mod:`execution`      — schedule_job, trigger_event
- :mod:`delegated`      — registry-based wrappers for web/file/note/profile tools
- :mod:`data`           — generate_data
- :mod:`mcp`            — install_mcp_server
- :mod:`context`        — manage_context (status/compact/clear)
- :mod:`task`           — task_create/update/get/list/stop
- :mod:`output`         — generate_report, export_json
- :mod:`notification`   — send_notification
- :mod:`calendar`       — calendar_list/create_event, calendar_sync_scheduler
- :mod:`offload`        — recall_tool_result
- :mod:`computer_use`   — computer (when enabled)

Plus shared utilities in :mod:`_helpers` (``_clarify``, ``_safe_delegate``).

The disk-persistent ``PlanStore`` singleton (``_PLAN_STORE`` /
``_get_plan_store``) lives at this package level so test fixtures can
``monkeypatch.setattr(th, "_PLAN_STORE", ...)`` without reaching into a
sub-module — see ``tests/test_plan_mode.py`` for the fixture pattern.
"""

from __future__ import annotations

from typing import Any

from core.cli.tool_handlers._helpers import (
    _clarify,
    _safe_delegate,
)
from core.cli.tool_handlers.audit import _build_audit_handlers
from core.cli.tool_handlers.calendar import _build_calendar_handlers
from core.cli.tool_handlers.computer_use import _build_computer_use_handler
from core.cli.tool_handlers.context import _build_context_handlers
from core.cli.tool_handlers.data import _build_data_handlers
from core.cli.tool_handlers.delegated import (
    _DELEGATED_TOOLS,
    _build_delegated_handlers,
    _make_delegate_handler,
)
from core.cli.tool_handlers.execution import _build_execution_handlers
from core.cli.tool_handlers.hitl import _build_hitl_handlers
from core.cli.tool_handlers.mcp import _build_mcp_handler
from core.cli.tool_handlers.memory import _build_memory_handlers
from core.cli.tool_handlers.notification import _build_notification_handlers
from core.cli.tool_handlers.observability import _build_observability_handlers
from core.cli.tool_handlers.offload import _build_offload_handlers
from core.cli.tool_handlers.output import _build_output_handlers
from core.cli.tool_handlers.plan import _build_plan_handlers
from core.cli.tool_handlers.system import _build_system_handlers
from core.cli.tool_handlers.task import _build_task_handlers

__all__ = [
    "_DELEGATED_TOOLS",
    "_PLAN_STORE",
    "_build_audit_handlers",
    "_build_calendar_handlers",
    "_build_computer_use_handler",
    "_build_context_handlers",
    "_build_data_handlers",
    "_build_delegated_handlers",
    "_build_execution_handlers",
    "_build_hitl_handlers",
    "_build_mcp_handler",
    "_build_memory_handlers",
    "_build_notification_handlers",
    "_build_observability_handlers",
    "_build_offload_handlers",
    "_build_output_handlers",
    "_build_plan_handlers",
    "_build_system_handlers",
    "_build_task_handlers",
    "_build_tool_handlers",
    "_clarify",
    "_get_plan_store",
    "_make_delegate_handler",
    "_safe_delegate",
]


# v0.53.3 — module-level disk-persistent PlanStore. Replaces the
# v0.53.2-and-earlier closure-bound ``_plan_cache: dict = {}`` that had
# two compounding bugs:
#   B1: Each ``_build_tool_handlers`` invocation produced a fresh closure
#       with its own dict → ``create_plan`` and ``list_plans`` could end
#       up bound to different dicts and the user saw "0 items" after a
#       successful ``create_plan``.
#   Persistence: in-memory only → daemon restart wiped all plan history.
# ``PlanStore`` lives at ``.geode/plans.json`` (atomic write via
# tmp+rename, mirrors ``core/scheduler/scheduler.py:save``) and is shared
# across factories.
_PLAN_STORE: Any | None = None


def _get_plan_store() -> Any:
    """Lazy singleton accessor for the disk-persistent PlanStore.

    Lazy so test fixtures that monkeypatch ``PROJECT_PLANS_FILE`` (or that
    reset ``_PLAN_STORE`` to None) take effect on the next call.
    """
    global _PLAN_STORE
    if _PLAN_STORE is None:
        from core.orchestration.plan_store import PlanStore

        _PLAN_STORE = PlanStore()
    return _PLAN_STORE


def _build_tool_handlers(
    verbose: bool = False,
    *,
    mcp_manager: Any = None,
    skill_registry: Any = None,
) -> dict[str, Any]:
    """Build tool name -> handler function mapping for ToolExecutor.

    Each handler receives tool_input kwargs and returns a dict result.
    ``mcp_manager`` is used by install_mcp_server.
    ``skill_registry`` is used by generate_report for skill-enhanced narrative.

    Delegates to group-specific builder functions and merges the results.
    """
    from core.cli import _get_readiness

    readiness = _get_readiness()
    force_dry = readiness.force_dry_run if readiness else True

    handlers: dict[str, Any] = {}
    handlers.update(_build_memory_handlers())
    handlers.update(_build_plan_handlers(force_dry))
    handlers.update(_build_hitl_handlers())
    handlers.update(_build_system_handlers(readiness, force_dry, mcp_manager))
    handlers.update(_build_execution_handlers())
    handlers.update(_build_data_handlers())
    handlers.update(_build_delegated_handlers())
    handlers.update(_build_output_handlers())
    handlers.update(_build_notification_handlers())
    handlers.update(_build_calendar_handlers())
    handlers.update(_build_mcp_handler(mcp_manager))
    handlers.update(_build_context_handlers())
    handlers.update(_build_task_handlers())
    handlers.update(_build_offload_handlers())
    handlers.update(_build_computer_use_handler())
    handlers.update(_build_audit_handlers())
    handlers.update(_build_observability_handlers())
    return handlers
