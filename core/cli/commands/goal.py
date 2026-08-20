"""``/goal`` user control over the persisted Goal projection."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.memory.goals import GoalStatus, GoalStore
from core.ui.console import console


def cmd_goal(
    arg: str,
    *,
    goal_store: GoalStore | None = None,
    session_id: str = "",
    timeline: Any = None,
) -> dict[str, Any]:
    """Show, set, or clear the active session's persisted Goal."""
    if goal_store is None:
        from core.cli.session_state import get_current_loop

        loop = get_current_loop()
        if loop is None or getattr(loop, "_goal_store", None) is None:
            raise ValueError("/goal requires an active AgenticLoop session")
        goal_store = loop._goal_store
        session_id = session_id or str(getattr(loop, "_session_id", ""))
        timeline = timeline or getattr(loop, "_timeline", None)
    if not session_id:
        raise ValueError("/goal requires an active session")

    objective = arg.strip()
    if not objective:
        goal = goal_store.get(session_id)
        state = goal.status if goal is not None else GoalStatus.EMPTY
        console.print()
        console.print(f"  [header]Goal[/header] · [bold]{state.value}[/bold]")
        if goal is not None:
            console.print(f"  {goal.objective}")
            console.print(
                f"  [muted]tokens={goal.tokens_used}"
                f" remaining={goal.remaining_tokens} id={goal.goal_id}[/muted]"
            )
        console.print()
        return {
            "status": "ok",
            "goal_status": state.value,
            "goal": goal.to_dict() if goal else None,
        }

    if objective.casefold() == "clear":
        prior = goal_store.clear(session_id)
        if prior is not None and timeline is not None:
            from core.observability.session_timeline import SessionEventKind

            timeline.record_goal_state(
                SessionEventKind.GOAL_UPDATED,
                replace(prior, status=GoalStatus.EMPTY),
                trigger="slash_clear",
            )
        console.print("  [success]Goal cleared.[/success]")
        console.print()
        return {"status": "ok", "goal_status": GoalStatus.EMPTY.value, "goal": None}

    goal = goal_store.create(session_id, objective)
    if timeline is not None:
        from core.observability.session_timeline import SessionEventKind

        timeline.record_goal_state(SessionEventKind.GOAL_CREATED, goal, trigger="slash_goal")
    console.print(f"  [success]Goal active:[/success] {goal.objective}")
    console.print(f"  [muted]{goal.goal_id} · no token budget[/muted]")
    console.print()
    return {"status": "ok", "goal_status": goal.status.value, "goal": goal.to_dict()}
