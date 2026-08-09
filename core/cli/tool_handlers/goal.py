"""Explicit persisted-goal tool handlers."""

from __future__ import annotations

from typing import Any

from core.cli.tool_handlers.registration import UniqueEntries
from core.memory.goals import GoalStatus, GoalStore


def _build_goal_handlers(store: GoalStore | None = None) -> UniqueEntries[str, Any]:
    """Build create/get/update handlers over one session-scoped goal."""
    goal_store = store or GoalStore()

    def _session_id() -> str:
        from core.agent.cognitive_state_ctx import get_session_id

        return get_session_id()

    def _record(goal: Any, *, created: bool, trigger: str) -> None:
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
            )

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
        return {"status": "ok", "goal": goal.to_dict()}

    def handle_get_goal(**_: Any) -> dict[str, Any]:
        goal = goal_store.get(_session_id())
        return {"status": "ok", "goal": goal.to_dict() if goal is not None else None}

    def handle_update_goal(**kwargs: Any) -> dict[str, Any]:
        raw_status = str(kwargs.get("status") or "")
        try:
            status = GoalStatus(raw_status)
            goal = goal_store.update_terminal(_session_id(), status)
        except ValueError as exc:
            return {"error": str(exc)}
        _record(goal, created=False, trigger="update_goal")
        return {"status": "ok", "goal": goal.to_dict()}

    return UniqueEntries(
        (
            ("create_goal", handle_create_goal),
            ("get_goal", handle_get_goal),
            ("update_goal", handle_update_goal),
        )
    )
