"""Goal decomposition helper — converts user input into an explicit ``Plan``.

PR-CL-A1 (2026-05-23) rewrite — the helper now installs a structured
:class:`core.agent.plan.Plan` on the current SessionMetrics instead of
returning a system-prompt suffix string. Callers (``arun``) read the
plan back via ``current_session_metrics().active_plan`` and render the
current-step hint via :func:`core.agent.plan.render_plan_for_prompt`.
That centralises plan state so the replan path (PR-CL-A1
``_maybe_replan_async``) can swap the plan in place without
re-decomposing from scratch.

Pre-A1 callers that consumed the returned ``str`` suffix get ``None``
when a Plan was installed (signalling "plan handled — no suffix
needed"); existing tests asserting on the suffix still work because
``GoalDecomposer.decompose`` returning ``None`` continues to short-circuit
with ``None``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def try_decompose(loop: AgenticLoop, user_input: str) -> str | None:
    """Decompose a compound user request into an explicit :class:`Plan`.

    Returns ``None`` either when:

    - The request is simple (single tool call) — ``GoalDecomposer`` itself
      returns ``None`` and we propagate.
    - A multi-step plan was produced and *installed on SessionMetrics* —
      caller's system-prompt injection path then uses
      :func:`core.agent.plan.render_plan_for_prompt` instead of receiving
      a suffix string.

    Pre-A1 callers received a markdown bullet list as the suffix; that
    path is gone — the plan body now lives on ``SessionMetrics.active_plan``
    and is rendered at ``arun`` entry via ``_consume_plan_hint``.

    Uses ``settings.plan_model`` (PR-CL-A6 knob) so an operator running
    Opus-plan + Sonnet-act sees the right cost/quality split for planning.
    """
    if not loop._enable_goal_decomposition:
        return None

    try:
        from core.agent.plan import build_plan_from_decomposition
        from core.config import settings
        from core.observability.session_metrics import current_session_metrics
        from core.orchestration.goal_decomposer import GoalDecomposer

        plan_model_raw = getattr(settings, "plan_model", "")
        plan_model = (
            plan_model_raw.strip() if isinstance(plan_model_raw, str) else ""
        ) or loop.model
        if loop._goal_decomposer is None:
            loop._goal_decomposer = GoalDecomposer(
                model=plan_model,
                tool_definitions=loop._tools,
            )

        result = loop._goal_decomposer.decompose(
            user_input,
            tool_definitions=loop._tools,
        )
        if result is None:
            return None

        plan = build_plan_from_decomposition(result)
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
            "GoalDecomposer: installed %d-step Plan on SessionMetrics",
            len(plan.steps),
        )
        # Returning None signals "plan handled — caller skips the suffix".
        # The system-prompt block is rendered from SessionMetrics in
        # ``_consume_plan_hint`` at the start of every ``arun``, so we
        # don't need to thread a suffix string through here.
        return None

    except Exception:
        log.debug("Goal decomposition skipped", exc_info=True)
        return None
