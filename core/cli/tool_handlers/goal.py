"""Explicit persisted-goal tool handlers."""

from __future__ import annotations

from typing import Any

from core.memory.goals import GoalStatus, GoalStore
from core.tools.handlers.registration import UniqueEntries


def _build_goal_handlers(store: GoalStore | None = None) -> UniqueEntries[str, Any]:
    """Build create/get/update handlers over one session-scoped goal."""
    goal_store = store or GoalStore()

    def _session_id() -> str:
        from core.agent.cognitive_state_ctx import get_session_id

        return get_session_id()

    def _record(goal: Any, *, created: bool, trigger: str) -> None:
        from core.agent.cognitive_state_ctx import get_tool_call_id
        from core.observability.session_timeline import (
            SessionEventKind,
            current_session_timeline,
        )

        timeline = current_session_timeline()
        if timeline is not None:
            timeline.record_goal_state(
                SessionEventKind.GOAL_CREATED if created else SessionEventKind.GOAL_UPDATED,
                goal,
                trigger=trigger,
                call_id=get_tool_call_id(),
            )

    def _mark_prompt_dirty(context: Any = None) -> None:
        loop = getattr(context, "agent_loop", None)
        if loop is not None:
            loop._prompt_dirty = True

    def handle_create_goal(**kwargs: Any) -> dict[str, Any]:
        budget = kwargs.get("token_budget")
        try:
            parsed_budget = int(budget) if budget is not None else None
            goal = goal_store.create(
                _session_id(),
                str(kwargs.get("objective") or ""),
                token_budget=parsed_budget,
            )
        except (TypeError, ValueError) as exc:
            return {"error": str(exc)}
        _record(goal, created=True, trigger="create_goal")
        _mark_prompt_dirty(kwargs.get("_tool_context"))
        return {"status": "ok", "goal_status": goal.status.value, "goal": goal.to_dict()}

    def handle_get_goal(**_: Any) -> dict[str, Any]:
        session_id = _session_id()
        goal = goal_store.get(session_id)
        return {
            "status": "ok",
            "goal_status": (goal.status if goal is not None else GoalStatus.EMPTY).value,
            "goal": goal.to_dict() if goal is not None else None,
        }

    def handle_update_goal(**kwargs: Any) -> dict[str, Any]:
        raw_status = str(kwargs.get("status") or "")
        try:
            status = GoalStatus(raw_status)
            session_id = _session_id()
            current = goal_store.get(session_id)
            if current is None:
                raise ValueError("no active goal exists for this session")
            goal = goal_store.update_terminal(
                session_id,
                status,
                expected_goal_id=current.goal_id,
                expected_revision=current.revision,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        _record(goal, created=False, trigger="update_goal")
        _mark_prompt_dirty(kwargs.get("_tool_context"))
        return {"status": "ok", "goal_status": goal.status.value, "goal": goal.to_dict()}

    return UniqueEntries(
        (
            ("create_goal", handle_create_goal),
            ("get_goal", handle_get_goal),
            ("update_goal", handle_update_goal),
        )
    )
