"""Goal decomposition helper — installs an explicit ``Plan`` on metrics.

PR-CL-A1-followup (2026-05-23) rewrite — the helper now calls
:func:`core.agent.plan.decompose_async` directly instead of going
through the legacy ``core/orchestration/goal_decomposer.py`` (DELETED
in this PR). The async dispatch matches the planner-LLM pattern already
established by ``replan_async`` so the loop has a single planner code
path.

Side-effect contract (preserved from PR-CL-A1):

- On a successful multi-step decomposition, installs the Plan on
  ``current_session_metrics().active_plan`` and returns ``None``.
- On a simple/single-tool request OR LLM failure, returns ``None``
  without installing a Plan.
- Caller (``arun``) reads the active Plan via
  :func:`core.agent.plan.render_plan_for_prompt` and prepends a
  ``<plan>...</plan>`` block to the system prompt.

The helper is **async** because it awaits ``decompose_async``; the
``AgenticLoop._try_decompose`` delegator is correspondingly async.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


async def try_decompose(loop: AgenticLoop, user_input: str) -> str | None:
    """Run the planner LLM (when warranted) and install the Plan.

    Returns ``None`` either way. Async because ``decompose_async``
    awaits ``loop._call_llm``. Pre-A1 callers received a markdown
    suffix string — that path is gone (Plan body now lives on
    ``SessionMetrics.active_plan`` and is rendered at ``arun`` entry
    via ``_consume_plan_hint``).
    """
    if not loop._enable_goal_decomposition:
        return None
    try:
        from core.agent.plan import decompose_async
        from core.observability.session_metrics import current_session_metrics

        plan = await decompose_async(loop, user_input, tools=loop._tools)
        if plan is None:
            return None

        # Install the explicit Plan on SessionMetrics so subsequent
        # ``arun`` invocations + the replan path read the same object.
        # ``reset_attempts=True`` because this is the initial install —
        # no prior step attempts to preserve.
        current_session_metrics().set_active_plan(plan, reset_attempts=True)

        # Emit structured events for thin client. ``emit_goal_decomposition``
        # is the legacy summary; ``emit_plan_step`` (PR-CL-A1) emits the
        # current-step detail so UIs can render "Step 1/N: …".
        from core.ui.agentic_ui import emit_goal_decomposition, emit_plan_step

        emit_goal_decomposition([step.description for step in plan.steps])
        first_step = plan.current_step()
        if first_step is not None:
            emit_plan_step(
                current=plan.current + 1,
                total=len(plan.steps),
                description=first_step.description,
                revision=plan.revision,
            )
        log.info(
            "decompose_async: installed %d-step Plan on SessionMetrics",
            len(plan.steps),
        )
        return None
    except Exception:
        log.debug("Goal decomposition skipped", exc_info=True)
        return None
