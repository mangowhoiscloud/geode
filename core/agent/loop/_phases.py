"""The six explicit phases of one physical agent turn.

The public loop remains :class:`AgenticLoop`; these functions only own the
bounded work between its state transitions.  They intentionally use the
existing loop helpers instead of introducing a second runtime abstraction.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from core.hooks import HookCorrelation, HookEvent
from core.llm.adapters.base import EmptyModelOutputError
from core.llm.agentic_response import AgenticResponse
from core.ui.status import TextSpinner

from . import _context
from .models import (
    AgenticResult,
    StepSnapshot,
    TerminationReason,
    TurnState,
    _ContextExhaustedError,
)

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


@dataclass(slots=True)
class PreparedTurn:
    """Inputs shared by every round of one physical turn."""

    user_input: str
    messages: list[dict[str, Any]]
    turn_state: TurnState
    system_prompt: str
    reflection_hint: str
    verification_hint: str
    verification_continuation: bool


@dataclass(slots=True)
class PreparedModelCall:
    """One prepared provider call plus its presentation owner."""

    system_prompt: str
    spinner: TextSpinner
    ipc_writer: Any | None
    step_snapshot: StepSnapshot | None = None


def tool_args_signature(tool_input: Any) -> str:
    """Return a short stable signature for diversity detection."""
    try:
        canonical = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = repr(tool_input)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


async def prepare_input(
    loop: AgenticLoop,
    user_input: str,
    *,
    verify_continuation: HookCorrelation | None,
    goal_continuation: Any | None,
    goal_continuation_trigger: str,
) -> PreparedTurn | AgenticResult:
    """Cross input/interceptor boundaries and freeze turn-level inputs."""
    user_input, blocked = await loop._begin_turn(
        user_input,
        verify_continuation,
        internal_continuation=goal_continuation is not None,
    )
    if blocked is not None:
        return await loop._finalize_blocked_turn(blocked)

    from .agent_loop import _set_conversation_context

    _set_conversation_context(loop.context)
    loop._refresh_mcp_tools_at_turn_start()
    intercepted = await loop._open_turn(
        user_input,
        verification_continuation=verify_continuation is not None,
        goal_continuation=goal_continuation,
        goal_continuation_trigger=goal_continuation_trigger,
    )
    if intercepted is not None:
        return intercepted

    verification_continuation = verify_continuation is not None
    task_input = (
        loop._verify_root_user_input or user_input if verification_continuation else user_input
    )
    verification_hint = (
        _context.render_verification_continuation_hint(user_input)
        if verification_continuation
        else ""
    )
    goal_hint = (
        _context.render_goal_continuation_hint(goal_continuation)
        if goal_continuation is not None
        else ""
    )
    loop._preflight_hint = loop._prepare_task_preflight(task_input)

    messages = loop.context.get_messages()
    turn_state = loop._bind_turn_messages(messages)
    messages.extend(_context.goal_continuation_messages(goal_hint))

    reflection_hint = loop._consume_reflection_hint()
    plan_hint = loop._consume_plan_hint()
    loop._last_plan_hint = plan_hint
    system_prompt = _context.inject_runtime_hints(
        loop._build_system_prompt(),
        loop._preflight_hint,
        reflection_hint,
        verification_hint,
        plan_hint,
    )
    loop._maybe_prune_messages(messages)

    loop._loop_start_time = time.monotonic()
    from core.llm.token_tracker import get_tracker

    loop._usage_snapshot = get_tracker().snapshot()
    return PreparedTurn(
        user_input=user_input,
        messages=messages,
        turn_state=turn_state,
        system_prompt=system_prompt,
        reflection_hint=reflection_hint,
        verification_hint=verification_hint,
        verification_continuation=verification_continuation,
    )


async def prepare_model_call(
    loop: AgenticLoop,
    turn: PreparedTurn,
    round_idx: int,
) -> PreparedModelCall | AgenticResult:
    """Prepare the prompt, context, cognitive event, and call presentation."""
    loop._op_logger.begin_round("AgenticLoop")
    await loop._maybe_replan_async(
        round_idx,
        failure_context=(turn.user_input if turn.verification_continuation else ""),
    )
    turn.system_prompt = await loop._sync_model_and_rebuild_prompt(
        turn.system_prompt,
        reflection_hint=turn.reflection_hint,
        verification_hint=turn.verification_hint,
    )
    loop._admit_collaboration_messages(
        turn.messages,
        user_input=turn.user_input,
        round_idx=round_idx,
    )

    try:
        await loop._check_context_overflow(turn.system_prompt, turn.messages)
    except _ContextExhaustedError:
        log.warning("Pre-call context exhausted — attempting aggressive recovery")
        recovered = await loop._aggressive_context_recovery(
            turn.system_prompt,
            turn.messages,
        )
        if recovered:
            loop._notify_context_event(
                "prune",
                original_count=len(turn.messages) + recovered,
                new_count=len(turn.messages),
            )
            log.info("Pre-call recovery succeeded — proceeding with pruned context")
        else:
            return await loop._finalize_context_exhausted(
                turn.user_input,
                turn.messages,
                round_idx,
            )

    await loop._emit_cognitive(
        HookEvent.COGNITIVE_PLAN,
        round=round_idx + 1,
        model=loop.model,
    )

    from core.ui.agentic_ui import _ipc_writer_local

    ipc_writer = getattr(_ipc_writer_local, "writer", None)
    if ipc_writer is not None and not loop._quiet:
        ipc_writer.send_event(
            "thinking_start",
            model=loop.model,
            round=round_idx + 1,
            reflection=bool(turn.reflection_hint),
        )
        spinner = TextSpinner("", quiet=True)
    else:
        verb = "Reflecting..." if turn.reflection_hint else "Thinking..."
        label = verb if round_idx == 0 else f"{verb} (round {round_idx + 1})"
        spinner = TextSpinner(label, quiet=loop._quiet)
    spinner.start()
    return PreparedModelCall(turn.system_prompt, spinner, ipc_writer)


async def call_provider(
    loop: AgenticLoop,
    turn: PreparedTurn,
    call: PreparedModelCall,
    round_idx: int,
) -> AgenticResponse | AgenticResult | None:
    """Call the provider and decide whether to return, retry, or continue."""
    response_step = None
    try:
        outcome = await loop._dispatch_llm_call(
            call.system_prompt,
            turn.messages,
            round_idx,
            call.spinner,
        )
        if isinstance(outcome, AgenticResult):
            return await assemble_termination(
                loop,
                outcome,
                user_input=turn.user_input,
                round_idx=round_idx + 1,
            )
        response = outcome
        response_step = loop._current_step_snapshot
        call.step_snapshot = response_step
    except EmptyModelOutputError as exc:
        partial = await loop._afinalize_actionable_partial_on_empty(
            exc,
            messages=turn.messages,
            user_input=turn.user_input,
            round_idx=round_idx,
        )
        if partial is None:
            raise
        return partial
    except _ContextExhaustedError as exc:
        call.spinner.stop()
        log.warning("Context exhausted: %s — attempting aggressive recovery", exc)
        recovered = await loop._aggressive_context_recovery(
            call.system_prompt,
            turn.messages,
        )
        if recovered:
            loop._notify_context_event(
                "prune",
                original_count=len(turn.messages) + recovered,
                new_count=len(turn.messages),
            )
            log.info("Aggressive recovery succeeded — continuing loop")
            return None
        return await loop._finalize_context_exhausted(
            turn.user_input,
            turn.messages,
            round_idx,
        )
    finally:
        call.spinner.stop()
        if call.ipc_writer is not None and not loop._quiet:
            call.ipc_writer.send_event("thinking_end")

    if response is not None:
        return response

    adapter_exc = getattr(loop._new_adapter, "_last_error", None)
    from core.llm.errors import _ERROR_CLASSIFICATION

    error_type, severity, hint = _ERROR_CLASSIFICATION["unknown"]
    if adapter_exc is not None:
        from core.llm.errors import classify_llm_error

        error_type, severity, hint = classify_llm_error(adapter_exc)
        if error_type == "context_overflow":
            log.warning("Context overflow detected from 400 — attempting recovery")
            recovered = await loop._aggressive_context_recovery(
                call.system_prompt,
                turn.messages,
            )
            if recovered:
                loop._notify_context_event(
                    "prune",
                    original_count=len(turn.messages) + recovered,
                    new_count=len(turn.messages),
                )
                log.info("Context overflow recovery succeeded — retrying LLM call")
                return None
            return await loop._finalize_context_exhausted(
                turn.user_input,
                turn.messages,
                round_idx,
            )

        if error_type in {"auth", "bad_request"}:
            if not loop._quiet:
                from core.ui.agentic_ui import emit_llm_error

                emit_llm_error(error_type, severity, hint, loop.model, loop._provider)
            if error_type == "auth":
                loop._inject_credential_breadcrumb()
            result = loop._build_model_action_result(
                error_type=error_type,
                severity=severity,
                hint=hint,
                rounds=round_idx + 1,
                detail=loop._last_llm_error or str(adapter_exc),
            )
            return await assemble_termination(
                loop,
                result,
                user_input=turn.user_input,
                round_idx=round_idx + 1,
            )

        if not loop._quiet:
            from core.ui.agentic_ui import emit_llm_error

            emit_llm_error(
                error_type,
                severity,
                hint,
                loop.model,
                loop._provider,
                attempt=loop._consecutive_llm_failures + 1,
            )

        if loop._hooks:
            await loop._hooks.trigger_async(
                HookEvent.LLM_CALL_FAILED,
                {
                    **(asdict(response_step.correlation) if response_step is not None else {}),
                    "model": loop.model,
                    "provider": loop._provider,
                    "error_type": error_type,
                    "severity": severity,
                    "attempt": loop._consecutive_llm_failures + 1,
                },
            )

    loop._set_llm_retry_count(loop._consecutive_llm_failures + 1)
    loop._sync_messages_to_context(turn.messages)
    loop._save_checkpoint(turn.user_input, round_idx=round_idx)

    if error_type == "rate_limit":
        result = loop._build_model_action_result(
            error_type=error_type,
            severity=severity,
            hint=hint,
            rounds=round_idx + 1,
            detail=loop._last_llm_error or str(adapter_exc),
        )
        return await assemble_termination(
            loop,
            result,
            user_input=turn.user_input,
            round_idx=round_idx + 1,
        )

    if loop._consecutive_llm_failures >= 2:
        recovered = await loop._aggressive_context_recovery(
            call.system_prompt,
            turn.messages,
        )
        if recovered:
            loop._notify_context_event(
                "prune",
                original_count=len(turn.messages) + recovered,
                new_count=len(turn.messages),
            )
            log.info(
                "Context compacted after %d failures — retrying same model (%s)",
                loop._consecutive_llm_failures,
                loop.model,
            )
            loop._set_llm_retry_count(0)
            return None

    if loop._consecutive_llm_failures < loop._LLM_RETRY_CAP:
        delay = min(2**loop._consecutive_llm_failures, 30)
        log.info(
            "LLM call failed (%s) — retrying in %ds (attempt %d/%d)",
            error_type,
            delay,
            loop._consecutive_llm_failures,
            loop._LLM_RETRY_CAP,
        )
        if not loop._quiet:
            from core.ui.agentic_ui import emit_llm_retry

            emit_llm_retry(delay, loop._consecutive_llm_failures, loop._LLM_RETRY_CAP)
        if loop._hooks:
            await loop._hooks.trigger_async(
                HookEvent.LLM_CALL_RETRIED,
                {
                    **(asdict(response_step.correlation) if response_step is not None else {}),
                    "model": loop.model,
                    "provider": loop._provider,
                    "error_type": error_type,
                    "delay_s": delay,
                    "attempt": loop._consecutive_llm_failures,
                    "max_attempts": loop._LLM_RETRY_CAP,
                },
            )
        await asyncio.sleep(delay)
        return None

    result = loop._build_model_action_result(
        error_type=error_type,
        severity=severity,
        hint=hint,
        rounds=round_idx + 1,
        detail=loop._last_llm_error or "unknown error",
    )
    return await assemble_termination(
        loop,
        result,
        user_input=turn.user_input,
        round_idx=round_idx + 1,
    )


async def process_tool_calls(
    loop: AgenticLoop,
    turn: PreparedTurn,
    response: AgenticResponse,
    round_idx: int,
    *,
    is_last_round: bool,
    step_snapshot: StepSnapshot | None,
) -> list[dict[str, Any]] | AgenticResult:
    """Apply response guards and execute one tool-call batch."""
    loop._set_llm_retry_count(0)
    await loop._track_usage_async(response)

    terminal = loop._guard_cost_budget(messages=turn.messages, round_idx=round_idx)
    if terminal is None:
        terminal = await loop._guard_overthinking(
            response,
            messages=turn.messages,
            round_idx=round_idx,
        )
    if terminal is None:
        terminal = loop._guard_model_refusal(
            response,
            messages=turn.messages,
            round_idx=round_idx,
        )
    if terminal is not None:
        return await assemble_termination(
            loop,
            terminal,
            user_input=turn.user_input,
            round_idx=round_idx + 1,
        )

    if response.stop_reason != "tool_use":
        loop._op_logger.finalize()
        text = loop._extract_text(response)
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": loop._serialize_content(response.content),
        }
        if getattr(response, "codex_reasoning_items", None):
            assistant_message["codex_reasoning_items"] = response.codex_reasoning_items
        if getattr(response, "codex_output_items", None):
            assistant_message["codex_output_items"] = response.codex_output_items
        if phase := getattr(response, "assistant_phase", ""):
            assistant_message["phase"] = phase
        turn.messages.append(assistant_message)
        loop._sync_messages_to_context(turn.messages)
        await loop._record_text_only_round(round_idx, text=text)
        reason = TerminationReason.FORCED_TEXT if is_last_round else TerminationReason.NATURAL
        result = loop._terminal_result(
            reason,
            text,
            rounds=round_idx + 1,
            tool_calls=loop._tool_processor.tool_log,
        )
        return await assemble_termination(
            loop,
            result,
            user_input=turn.user_input,
            round_idx=round_idx + 1,
        )

    tool_results = await loop._run_cognitive_act_observe_cycle(
        response,
        round_idx,
        step_snapshot=step_snapshot,
    )
    if loop._yield_after_tool_round:
        turn.messages.append(loop._tool_round_assistant_message(response))
        turn.messages.append({"role": "user", "content": tool_results})
        return await loop._afinalize_tool_round_yield(
            messages=turn.messages,
            user_input=turn.user_input,
            round_idx=round_idx,
        )
    return tool_results


async def observe_and_compact(
    loop: AgenticLoop,
    turn: PreparedTurn,
    response: AgenticResponse,
    tool_results: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult | None:
    """Observe a tool batch, apply progress guards, and advance history."""
    loop._update_tool_error_tracking(tool_results)
    terminal = loop._guard_convergence(messages=turn.messages, round_idx=round_idx)
    if terminal is None:
        terminal = loop._guard_repeated_success(messages=turn.messages, round_idx=round_idx)
    if terminal is not None:
        return await assemble_termination(
            loop,
            terminal,
            user_input=turn.user_input,
            round_idx=round_idx + 1,
        )

    if loop._convergence.total_consecutive_tool_errors >= 3:
        from core.ui.agentic_ui import emit_tool_backpressure

        emit_tool_backpressure(loop._convergence.total_consecutive_tool_errors)
        await asyncio.sleep(1.0)
        tool_results.append(
            {
                "type": "text",
                "text": (
                    "[system] Multiple tools are failing consecutively. "
                    "Consider a different approach. If you cannot verify the answer through "
                    "tools, tell the user what failed and what remains unverified. "
                    "CANNOT silently answer from training data."
                ),
            }
        )

    diversity_n = 5
    this_response: list[tuple[str, str]] = []
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            signature = (
                getattr(block, "name", ""),
                tool_args_signature(getattr(block, "input", None)),
            )
            if signature not in this_response:
                this_response.append(signature)
    loop._consecutive_tool_tracker.extend(this_response)
    if len(loop._consecutive_tool_tracker) > 10:
        loop._consecutive_tool_tracker = loop._consecutive_tool_tracker[-10:]
    if len(loop._consecutive_tool_tracker) >= diversity_n:
        last_n = loop._consecutive_tool_tracker[-diversity_n:]
        if len(set(last_n)) == 1:
            repeated_tool = last_n[0][0]
            tool_results.append(
                {
                    "type": "text",
                    "text": (
                        f"[system] The tool '{repeated_tool}' has been called "
                        f"{diversity_n} times with identical arguments — repeating this exact "
                        "call is unlikely to add new evidence. Try a different approach or tool "
                        "to make progress."
                    ),
                }
            )
            loop._consecutive_tool_tracker.clear()
            from core.ui.agentic_ui import emit_tool_diversity_forced

            emit_tool_diversity_forced(repeated_tool, diversity_n)
            log.warning(
                "Diversity forcing: %s called %dx with identical args — injecting hint",
                repeated_tool,
                diversity_n,
            )

    turn.messages.append(loop._tool_round_assistant_message(response))
    turn.messages.append({"role": "user", "content": tool_results})
    turn.turn_state.round_index += 1
    return None


async def assemble_termination(
    loop: AgenticLoop,
    result: AgenticResult | None = None,
    *,
    user_input: str,
    round_idx: int,
    turn: PreparedTurn | None = None,
    guard_reason: str | None = None,
) -> AgenticResult:
    """Assemble and persist one terminal result."""
    if result is not None:
        return await loop._afinalize_and_return(result, user_input, round_idx)
    if turn is None:
        raise ValueError("guard termination requires prepared turn")

    loop._op_logger.finalize()
    elapsed = time.monotonic() - loop._loop_start_time
    if guard_reason == "time_budget":
        from core.ui.agentic_ui import emit_time_budget_expired

        emit_time_budget_expired(loop._time_budget_s, elapsed, round_idx)
    reason, text = loop._guard_exit_result(guard_reason, rounds=round_idx)
    turn.messages.append(
        {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        }
    )
    loop._sync_messages_to_context(turn.messages)
    terminal = loop._terminal_result(
        reason,
        text,
        rounds=round_idx,
        error=True,
        tool_calls=loop._tool_processor.tool_log,
    )
    return await loop._afinalize_and_return(terminal, user_input, round_idx)


__all__ = [
    "PreparedModelCall",
    "PreparedTurn",
    "assemble_termination",
    "call_provider",
    "observe_and_compact",
    "prepare_input",
    "prepare_model_call",
    "process_tool_calls",
    "tool_args_signature",
]
