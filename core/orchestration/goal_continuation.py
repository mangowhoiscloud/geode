"""Serve-owned continuation for explicit persisted Goals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.memory.goals import GoalStatus, GoalStore, ThreadGoal

if TYPE_CHECKING:
    from core.memory.session_checkpoint import SessionCheckpoint


class GoalContinuationHost:
    """Admit one idle continuation per observed active-Goal state."""

    def __init__(
        self,
        services: Any,
        checkpoint: SessionCheckpoint,
        *,
        session_mode: Any,
        time_budget_s: float,
        gateway_system_suffix: str = "",
        gateway_max_turns: int = 0,
    ) -> None:
        self._services = services
        self._checkpoint = checkpoint
        self._goals = GoalStore(checkpoint.session_dir / "sessions.db")
        self._session_mode = session_mode
        self._time_budget_s = time_budget_s
        self._gateway_system_suffix = gateway_system_suffix
        self._gateway_max_turns = gateway_max_turns
        self._attempted: dict[str, tuple[str, int, float]] = {}

    @staticmethod
    def _signature(goal: ThreadGoal) -> tuple[str, int, float]:
        return goal.goal_id, goal.tokens_used, goal.updated_at

    def _remember(self, goal: ThreadGoal) -> None:
        self._attempted[goal.session_id] = self._signature(goal)

    async def continue_next_if_idle(self) -> str | None:
        """Restore and continue the oldest eligible Goal, if all lanes are idle."""
        lanes = self._services.lane_queue
        if lanes is None:
            return None
        session_lane = lanes.session_lane
        global_lane = lanes.get_lane("global")
        if (session_lane is not None and session_lane.active_count) or (
            global_lane is not None and global_lane.active_count
        ):
            return None

        active = self._goals.list_active()
        active_sessions = {goal.session_id for goal in active}
        self._attempted = {
            session_id: signature
            for session_id, signature in self._attempted.items()
            if session_id in active_sessions
        }
        selected = next(
            (
                goal
                for goal in active
                if self._attempted.get(goal.session_id) != self._signature(goal)
            ),
            None,
        )
        if selected is None:
            return None

        lane_names = ["session"]
        if global_lane is not None:
            lane_names.append("global")
        async with lanes.acquire_all_async(selected.session_id, lane_names):
            current = self._goals.get(selected.session_id)
            if current is None or current.status is not GoalStatus.ACTIVE:
                return None
            if self._attempted.get(current.session_id) == self._signature(current):
                return None

            state = self._checkpoint.load(current.session_id)
            if state is None or str(state.status) != "active":
                self._remember(current)
                return None

            from core.agent.conversation import ConversationContext
            from core.observability.session_metrics import session_metrics_scope

            conversation = (
                ConversationContext(max_turns=self._gateway_max_turns)
                if current.session_id.startswith("s-gw-")
                else ConversationContext()
            )
            with session_metrics_scope(
                session_id=current.session_id,
                component="goal_continuation",
            ):
                conversation.messages = list(state.messages)
                _, loop = self._services.create_session(
                    self._session_mode,
                    conversation=conversation,
                    system_suffix=(
                        self._gateway_system_suffix
                        if current.session_id.startswith("s-gw-")
                        else ""
                    ),
                    time_budget_override=self._time_budget_s,
                    propagate_context=True,
                    session_id=current.session_id,
                )
                loop.restore_from_checkpoint(state)
                if state.model and state.model != loop.model:
                    await loop.update_model_async(state.model)
                result = await loop.acontinue_goal(trigger="serve_idle")
            latest = self._goals.get(current.session_id)
            self._remember(latest or current)
            return current.session_id if result is not None else None
