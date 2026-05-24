"""Goal-decomposition planner dispatcher for ``AgenticLoop``.

Split out of ``_helpers.py`` in PR-HELPERS-3SPLIT (2026-05-24) per
the new Naming CANNOT row that forbids ``_helpers`` filenames once a
caller appears. The function was originally extracted into a sibling
``_decomposition.py`` (Tier 3 #7) and later absorbed back into
``_helpers.py`` by PR-CLEANUP-1 (2026-05-23) on the rationale that
three under-100-LOC siblings shared a single caller. This split
reverses that fold along the actual ownership line — the planner
LLM dispatch + Plan installation is its own subsystem (PR-CL-A1
verbal-RL pattern), distinct from the tool factory and the
sub-agent announce poller that ``_helpers.py`` also hosted.

The module surfaces exactly one async coroutine — ``try_decompose``
— which ``AgenticLoop._try_decompose`` awaits when
``settings.enable_goal_decomposition`` is on. Returns ``None`` either
way; success path installs a :class:`core.agent.plan.Plan` on
``SessionMetrics.active_plan`` so the next ``arun`` reads the same
object and renders the current-step hint via ``_consume_plan_hint``.
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
