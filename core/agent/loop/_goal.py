"""Persisted-goal continuation around one physical AgenticLoop turn."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from core.memory.goals import GoalStatus

from .models import AgenticResult, is_successful_task_termination

log = logging.getLogger(__name__)
_MAX_AUTOMATIC_CONTINUATIONS = 32

if TYPE_CHECKING:
    from core.hooks import HookCorrelation

    from .agent_loop import AgenticLoop


def _merge_results(results: list[AgenticResult]) -> AgenticResult:
    """Return the last turn while preserving public-arun usage."""
    final = results[-1]
    if len(results) == 1:
        return final
    final.tool_calls = [call for result in results for call in result.tool_calls]
    final.rounds = sum(result.rounds for result in results)
    usages = [result.usage for result in results if result.usage is not None]
    if usages:
        from core.llm.token_tracker import LLMUsage

        final.usage = LLMUsage(
            model=usages[-1].model,
            input_tokens=sum(item.input_tokens for item in usages),
            output_tokens=sum(item.output_tokens for item in usages),
            thinking_tokens=sum(item.thinking_tokens for item in usages),
            cache_creation_tokens=sum(item.cache_creation_tokens for item in usages),
            cache_read_tokens=sum(item.cache_read_tokens for item in usages),
            cost_usd=sum(item.cost_usd for item in usages),
        )
    return final


async def run(
    loop: AgenticLoop,
    user_input: str,
    *,
    verify_continuation: HookCorrelation | None = None,
) -> AgenticResult:
    """Run a user turn, then successful continuations for an active Goal."""
    if verify_continuation is not None:
        return await loop._arun_once(
            user_input,
            _verify_continuation=verify_continuation,
        )

    goal_before = loop._goal_store.get(loop._session_id) if loop._goal_store else None
    return await _run_turns(
        loop,
        user_input,
        goal_before=goal_before,
        continuation_goal=None,
        continuation_trigger="active_goal",
    )


async def continue_active(
    loop: AgenticLoop,
    *,
    trigger: str,
) -> AgenticResult | None:
    """Continue the active Goal without manufacturing a user turn."""
    goal = loop._goal_store.get(loop._session_id) if loop._goal_store else None
    if goal is None or goal.status is not GoalStatus.ACTIVE:
        return None
    return await _run_turns(
        loop,
        goal.objective,
        goal_before=goal,
        continuation_goal=goal,
        continuation_trigger=trigger,
    )


async def _run_turns(
    loop: AgenticLoop,
    user_input: str,
    *,
    goal_before: Any | None,
    continuation_goal: Any | None,
    continuation_trigger: str,
) -> AgenticResult:
    """Run physical turns until the current Goal reaches a safe boundary."""
    results: list[AgenticResult] = []
    prior_idle_text = ""
    while True:
        started = time.monotonic()
        result = await loop._arun_once(
            user_input,
            _goal_continuation=continuation_goal,
            _goal_continuation_trigger=continuation_trigger,
        )
        results.append(result)
        goal_after = loop._goal_store.get(loop._session_id) if loop._goal_store else None
        activated = goal_after is not None and (
            goal_before is None or goal_before.goal_id != goal_after.goal_id
        )
        if (
            loop._goal_store is not None
            and goal_after is not None
            and (activated or (goal_before is not None and goal_before.status is GoalStatus.ACTIVE))
        ):
            usage = result.usage
            tokens = int(getattr(usage, "input_tokens", 0)) + int(
                getattr(usage, "output_tokens", 0)
            )
            goal_after = loop._goal_store.account(
                loop._session_id,
                goal_id=goal_after.goal_id,
                tokens=tokens,
                elapsed_seconds=time.monotonic() - started,
            )
            if loop._timeline is not None and goal_after is not None:
                from core.observability.session_timeline import SessionEventKind

                loop._timeline.record_goal_state(
                    SessionEventKind.GOAL_UPDATED,
                    goal_after,
                    trigger="turn_accounting",
                )
        if (
            goal_after is None
            or goal_after.status is not GoalStatus.ACTIVE
            or not is_successful_task_termination(result.termination_reason)
        ):
            return _merge_results(results)
        idle_text = result.text.strip()
        if continuation_goal is not None and not result.tool_calls and idle_text == prior_idle_text:
            log.warning("Goal continuation made no observable progress; leaving goal active")
            return _merge_results(results)
        if len(results) > _MAX_AUTOMATIC_CONTINUATIONS:
            log.warning("Goal continuation safety cap reached; leaving goal active")
            return _merge_results(results)
        prior_idle_text = idle_text if not result.tool_calls else ""
        goal_before = goal_after
        continuation_goal = goal_after
        user_input = goal_after.objective
