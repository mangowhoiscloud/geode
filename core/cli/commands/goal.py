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
    active_loop: Any = None
    if goal_store is None:
        from core.cli.session_state import get_current_loop

        active_loop = get_current_loop()
        if active_loop is None or getattr(active_loop, "_goal_store", None) is None:
            raise ValueError("/goal requires an active AgenticLoop session")
        goal_store = active_loop._goal_store
        session_id = session_id or str(getattr(active_loop, "_session_id", ""))
        timeline = timeline or getattr(active_loop, "_timeline", None)
    if not session_id:
        raise ValueError("/goal requires an active session")

    def _checkpoint(value: str) -> None:
        save = getattr(active_loop, "_save_checkpoint", None)
        if callable(save):
            save(value, round_idx=0)

    def _mark_prompt_dirty() -> None:
        if active_loop is not None:
            active_loop._prompt_dirty = True

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

    if timeline is not None:
        timeline.begin_control_turn()

    command = objective.casefold()
    if command == "clear":
        current = goal_store.get(session_id)
        prior = goal_store.clear(
            session_id,
            expected_goal_id=current.goal_id if current is not None else None,
            expected_revision=current.revision if current is not None else None,
        )
        if prior is not None and timeline is not None:
            from core.observability.session_timeline import SessionEventKind

            timeline.record_goal_state(
                SessionEventKind.GOAL_UPDATED,
                replace(prior, status=GoalStatus.EMPTY),
                trigger="slash_clear",
            )
        console.print("  [success]Goal cleared.[/success]")
        console.print()
        _checkpoint("/goal clear")
        _mark_prompt_dirty()
        return {"status": "ok", "goal_status": GoalStatus.EMPTY.value, "goal": None}

    action = ""
    edited_objective = ""
    if command in {"pause", "resume"}:
        action = command
    elif command.startswith("edit "):
        action = "edit"
        edited_objective = objective[5:].strip()
    if action:
        current = goal_store.get(session_id)
        if current is None:
            raise ValueError(f"/goal {action} requires an existing goal")
        goal = goal_store.update_operator(
            session_id,
            action,
            expected_goal_id=current.goal_id,
            expected_revision=current.revision,
            objective=edited_objective,
        )
        if timeline is not None:
            from core.observability.session_timeline import SessionEventKind

            timeline.record_goal_state(
                SessionEventKind.GOAL_UPDATED,
                goal,
                trigger=f"slash_{action}",
            )
        console.print(f"  [success]Goal {action}:[/success] {goal.objective}")
        console.print()
        _checkpoint(f"/goal {objective}")
        _mark_prompt_dirty()
        return {"status": "ok", "goal_status": goal.status.value, "goal": goal.to_dict()}

    goal = goal_store.create(session_id, objective)
    if timeline is not None:
        from core.observability.session_timeline import SessionEventKind

        timeline.record_goal_state(SessionEventKind.GOAL_CREATED, goal, trigger="slash_goal")
    console.print(f"  [success]Goal active:[/success] {goal.objective}")
    console.print(f"  [muted]{goal.goal_id} · no token budget[/muted]")
    console.print()
    _checkpoint(f"/goal {objective}")
    _mark_prompt_dirty()
    return {"status": "ok", "goal_status": goal.status.value, "goal": goal.to_dict()}
