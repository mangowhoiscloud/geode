"""Claude Code-style agentic UI — minimal, informative tool call rendering.

Renders tool calls, plan steps, sub-agent dispatch, and token usage
in a clean, compact format inspired by Claude Code's output style.

Originally a single 1160-LOC module (``core/ui/agentic_ui.py``); split
into one file per concern while preserving the public API surface
(every name listed in ``__all__``) and the names imported by external
callers (``OperationLogger``, ``SessionMeter``, the ``render_*``,
``emit_*``, and ``init_session_meter``/``mark_turn_start`` accessors,
plus the thread-local globals ``_ipc_writer_local``, ``_meter_local``,
``_pipeline_ip_local``, and ``_turn_snapshot``).

Sub-modules:

- :mod:`_state`             — pipeline IP context + ``SessionMeter`` + meter accessors
- :mod:`_operation_logger`  — ``OperationLogger`` progressive tree log
- :mod:`render`             — ``render_*`` functions (tool call/result, tokens,
                              plan, sub-agent, status, context event)
- :mod:`summary`            — ``render_turn_summary`` / ``render_action_summary`` /
                              ``mark_turn_start`` (per-turn snapshot lifecycle)
- :mod:`events`             — ``emit_*`` IPC event emitters

The module-level ``console`` and ``_fmt_tokens`` re-exports preserve test
fixtures that patch ``core.ui.agentic_ui.console`` and import
``_fmt_tokens`` from this package.

Usage::

    from core.ui.agentic_ui import render_tool_call, render_tool_result, render_tokens

    render_tool_call("analyze_ip", {"ip_name": "Berserk"})
    # ▸ analyze_ip(ip_name="Berserk")

    render_tool_result("analyze_ip", {"tier": "S", "score": 81.3})
    # ✓ analyze_ip → S (81.3)

    render_tokens(model="claude-opus-4-6", input_tokens=1200, output_tokens=350, elapsed_s=2.1)
    # ✢ claude-opus-4-6 · ↓1.2k ↑350 · 2.1s
"""

from __future__ import annotations

from typing import Any

from core.ui.agentic_ui._operation_logger import OperationLogger
from core.ui.agentic_ui._state import (
    SessionMeter,
    _get_pipeline_ip,
    _ipc_writer_local,
    _meter_local,
    _pipeline_ip_local,
    get_session_meter,
    init_session_meter,
    set_pipeline_ip,
    update_session_model,
)
from core.ui.agentic_ui.events import (
    emit_billing_error,
    emit_budget_warning,
    emit_checkpoint_saved,
    emit_convergence_detected,
    emit_cost_budget_exceeded,
    emit_feedback_loop,
    emit_goal_decomposition,
    emit_llm_error,
    emit_llm_retry,
    emit_model_escalation,
    emit_model_switched,
    emit_node_skipped,
    emit_oauth_login_failed,
    emit_oauth_login_pending,
    emit_oauth_login_started,
    emit_oauth_login_success,
    emit_pipeline_analysis,
    emit_pipeline_evaluation,
    emit_pipeline_gather,
    emit_pipeline_score,
    emit_pipeline_verification,
    emit_quota_exhausted,
    emit_reasoning_summary,
    emit_retry_wait,
    emit_time_budget_expired,
    emit_tool_backpressure,
    emit_tool_diversity_forced,
)
from core.ui.agentic_ui.render import (
    render_context_event,
    render_plan_steps,
    render_session_cost_summary,
    render_status_line,
    render_subagent_complete,
    render_subagent_dispatch,
    render_subagent_progress,
    render_tokens,
    render_tool_call,
    render_tool_result,
)
from core.ui.agentic_ui.summary import (
    mark_turn_start,
    render_action_summary,
    render_turn_summary,
)

# Re-exports referenced by tests via ``core.ui.agentic_ui.<name>`` patches
# and by the original module-level imports (``console`` was imported from
# ``core.ui.console`` and ``_fmt_tokens`` from ``core.ui.event_renderer``).
from core.ui.console import console as console
from core.ui.event_renderer import _fmt_tokens as _fmt_tokens

# Per-turn snapshot state — set by ``mark_turn_start()`` (in ``summary.py``)
# and read by ``render_status_line()`` (in ``render.py``).  Lives at the
# package level so test fixtures patching ``mod._turn_snapshot`` flow
# through to the readers, which look it up via the package namespace.
_turn_snapshot: Any = None  # UsageSnapshot | None

__all__ = [
    "OperationLogger",
    "SessionMeter",
    "_fmt_tokens",
    "_get_pipeline_ip",
    "_ipc_writer_local",
    "_meter_local",
    "_pipeline_ip_local",
    "_turn_snapshot",
    "console",
    "emit_billing_error",
    "emit_budget_warning",
    "emit_checkpoint_saved",
    "emit_convergence_detected",
    "emit_cost_budget_exceeded",
    "emit_feedback_loop",
    "emit_goal_decomposition",
    "emit_llm_error",
    "emit_llm_retry",
    "emit_model_escalation",
    "emit_model_switched",
    "emit_node_skipped",
    "emit_oauth_login_failed",
    "emit_oauth_login_pending",
    "emit_oauth_login_started",
    "emit_oauth_login_success",
    "emit_pipeline_analysis",
    "emit_pipeline_evaluation",
    "emit_pipeline_gather",
    "emit_pipeline_score",
    "emit_pipeline_verification",
    "emit_quota_exhausted",
    "emit_reasoning_summary",
    "emit_retry_wait",
    "emit_time_budget_expired",
    "emit_tool_backpressure",
    "emit_tool_diversity_forced",
    "get_session_meter",
    "init_session_meter",
    "mark_turn_start",
    "render_action_summary",
    "render_context_event",
    "render_plan_steps",
    "render_session_cost_summary",
    "render_status_line",
    "render_subagent_complete",
    "render_subagent_dispatch",
    "render_subagent_progress",
    "render_tokens",
    "render_tool_call",
    "render_tool_result",
    "render_turn_summary",
    "set_pipeline_ip",
    "update_session_model",
]
