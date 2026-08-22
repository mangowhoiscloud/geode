"""Server-owned ``/plan`` advisory planning surface."""

from __future__ import annotations

from typing import Any


def format_advisory_plan(plan: Any) -> str:
    """Render the selected plan without implying execution."""
    lines = ["## Advisory plan"]
    if plan.reasoning:
        lines.extend(("", plan.reasoning))
    lines.append("")
    for index, step in enumerate(plan.steps, 1):
        outcome = f" — verify: {step.expected_outcome}" if step.expected_outcome else ""
        lines.append(f"{index}. {step.description}{outcome}")
    lines.extend(("", "This plan is installed for guidance; no step was executed."))
    return "\n".join(lines)


async def run_plan_slash(loop: Any, objective: str) -> tuple[str, Any | None, bool]:
    """Show the active plan or create and install a no-tool plan."""
    from core.observability.session_metrics import set_current_session_metrics

    metrics = loop._session_metrics
    set_current_session_metrics(metrics)
    if not objective.strip():
        plan = metrics.active_plan
        if plan is None:
            return "No advisory plan is active. Usage: /plan <objective>", None, False
        return format_advisory_plan(plan), plan, False

    if loop._timeline is not None:
        loop._timeline.begin_control_turn()

    from core.agent.plan import plan_async

    plan = await plan_async(loop, objective)
    if plan is None:
        raise RuntimeError("Planner returned no valid structured plan")
    previous_plan = metrics.active_plan
    previous_attempts = metrics.replan_attempts_on_current_step
    metrics.set_active_plan(plan, reset_attempts=True)
    save_checkpoint = getattr(loop, "_save_checkpoint", None)
    saved = callable(save_checkpoint) and save_checkpoint(objective, round_idx=0)
    if not saved:
        metrics.set_active_plan(previous_plan)
        metrics.replan_attempts_on_current_step = previous_attempts
        raise RuntimeError("Advisory plan checkpoint failed; plan was not installed")
    if loop._timeline is not None:
        from core.observability.session_timeline import SessionEventKind

        loop._timeline.record_plan_state(
            SessionEventKind.PLAN_CREATED,
            plan,
            trigger="slash_plan",
        )
    return format_advisory_plan(plan), plan, True
