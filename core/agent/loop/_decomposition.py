"""Goal decomposition helper for compound user requests.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loop import AgenticLoop

log = logging.getLogger(__name__)


def try_decompose(loop: AgenticLoop, user_input: str) -> str | None:
    """Attempt to decompose a compound user request into sub-goals.

    Returns a system prompt suffix describing the execution plan,
    or None if the request is simple (single tool call).

    Uses GoalDecomposer with ANTHROPIC_BUDGET (Haiku) for low-cost
    decomposition. Only triggered when compound indicators are present
    in the user input.
    """
    if not loop._enable_goal_decomposition:
        return None

    try:
        from core.orchestration.goal_decomposer import GoalDecomposer

        if loop._goal_decomposer is None:
            loop._goal_decomposer = GoalDecomposer(
                tool_definitions=loop._tools,
            )

        result = loop._goal_decomposer.decompose(
            user_input,
            tool_definitions=loop._tools,
        )

        if result is None:
            return None

        # Build execution plan hint for the system prompt
        lines = [
            "## Goal Decomposition Plan",
            "",
            f"The user's request has been decomposed into {len(result.goals)} sub-goals.",
            "Execute them in dependency order. For each step, call the specified tool.",
            "If a step depends on a previous step's output, use the result from that step.",
            "",
        ]
        for goal in result.goals:
            deps = ""
            if goal.depends_on:
                deps = f" (depends on: {', '.join(goal.depends_on)})"
            args_str = ""
            if goal.tool_args:
                args_str = ", ".join(f"{k}={v!r}" for k, v in goal.tool_args.items())
            lines.append(
                f"- **{goal.id}**: {goal.description} → `{goal.tool_name}({args_str})`{deps}"
            )

        if result.reasoning:
            lines.append("")
            lines.append(f"Reasoning: {result.reasoning}")

        plan_text = "\n".join(lines)

        # Emit structured event for thin client
        from core.ui.agentic_ui import emit_goal_decomposition

        emit_goal_decomposition([g.description for g in result.goals])
        log.info(
            "GoalDecomposer: injecting %d-step plan into system prompt",
            len(result.goals),
        )
        return plan_text

    except Exception:
        log.debug("Goal decomposition skipped", exc_info=True)
        return None
