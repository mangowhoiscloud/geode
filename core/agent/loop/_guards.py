"""Turn admission, execution guards, and terminal-result policy."""

from __future__ import annotations

import logging
from typing import Any, cast

from core.hooks import HookAction, HookCorrelation, HookEvent, HookName
from core.llm.adapters.base import EmptyModelOutputError
from core.llm.agentic_response import AgenticResponse, ToolUseBlock
from core.tools.personal_data import set_bound_tool_data_policies

from . import _context, _lifecycle, _model_switching
from ._tool_factory import TOOL_LAZY_LOAD_THRESHOLD
from .models import (
    AgenticResult,
    TerminationReason,
    TurnState,
    _context_exhausted_message,
)

REPLAN_LOW_CONFIDENCE = 0.4
log = logging.getLogger(__name__)


def _check_round_guards(loop: Any, round_idx: int) -> str | None:
    """Run the round-entry guards.

    Returns ``None`` to proceed, else a short guard-name string
    (``arun`` breaks the while-loop on a non-None response).

    Guards (Karpathy P3): ``round_limit`` (``max_rounds > 0``, 0-based
    index), ``time_budget`` (``time_budget_s > 0``, wall clock vs
    ``_loop_start_time``), and the session-wide budget/handoff check.
    """
    import time as _time

    if loop.max_rounds > 0 and round_idx >= loop.max_rounds:
        return "round_limit"
    if loop._time_budget_s > 0:
        elapsed = _time.monotonic() - loop._loop_start_time
        if elapsed >= loop._time_budget_s:
            return "time_budget"
    # session-wide cap + T-threshold handoff (getattr tolerates stub loops)
    handoff_reason = _check_session_budget_and_maybe_handoff(loop)
    if handoff_reason is not None:
        return handoff_reason
    return None


def _terminal_result(
    loop: Any,
    reason: TerminationReason,
    text: str,
    *,
    rounds: int,
    error: bool = False,
    tool_calls: list[dict[str, Any]] | None = None,
) -> AgenticResult:
    """Sole birth-place of terminal results — the loop's exit alphabet.

    Every terminal exit constructs its :class:`AgenticResult` here, so
    the reachable terminal-state space is exactly
    :class:`TerminationReason` (pinned by
    ``tests/core/agent/test_loop_state_machine.py``). ``error=True``
    mirrors *reason* into ``AgenticResult.error`` — the legacy dual
    encoding some consumers still read. ``tool_calls=None`` keeps the
    dataclass default (empty list) for pre-tool exits; pass
    ``loop._tool_processor.tool_log`` explicitly where the exit carries
    tool work.
    """
    result = AgenticResult(
        text=text,
        rounds=rounds,
        error=str(reason) if error else None,
        termination_reason=reason,
    )
    if tool_calls is not None:
        result.tool_calls = tool_calls
    loop._set_turn_termination(reason)
    return result


async def _apply_user_prompt_hook(
    loop: Any,
    user_input: str,
) -> tuple[str, AgenticResult | None]:
    """Apply the public input boundary before any planning or model work."""
    outcome = await loop._hook_registry.invoke(
        HookName.USER_PROMPT_SUBMIT,
        payload={"user_input": user_input},
        correlation=HookCorrelation(
            session_id=loop._session_id,
            turn_id=loop._turn_id,
        ),
    )
    if outcome.blocked:
        reason = next(
            (
                decision.reason
                for decision in outcome.decisions
                if decision.action is HookAction.BLOCK
            ),
            "Blocked by UserPromptSubmit hook",
        )
        return user_input, _terminal_result(
            loop,
            TerminationReason.INPUT_BLOCKED,
            reason,
            rounds=0,
        )
    effective = outcome.invocation.payload.get("user_input")
    return (effective if isinstance(effective, str) else user_input), None


async def _begin_turn(
    loop: Any,
    user_input: str,
    continuation: HookCorrelation | None,
    *,
    internal_continuation: bool = False,
) -> tuple[str, AgenticResult | None]:
    """Reset per-turn state and cross the public input boundary."""
    import uuid

    from core.observability.session_metrics import set_current_session_metrics

    set_current_session_metrics(loop._session_metrics)
    set_bound_tool_data_policies(loop._bound_tool_plan)

    loop._tool_processor.reset()
    loop._op_logger.reset()
    loop._pre_execution_retry_errors.clear()
    loop._turn_id = f"t-{uuid.uuid4().hex[:12]}"
    loop._turn_state = TurnState(turn_id=loop._turn_id)
    loop._current_step_snapshot = None
    if loop._timeline is not None:
        loop._timeline.bind_turn(
            loop._turn_id,
            session_generation=int(getattr(loop, "_session_generation", 1)),
        )
    from core.observability.session_timeline import set_current_session_timeline

    set_current_session_timeline(loop._timeline)
    if continuation is None:
        loop._verify_root_turn_id = loop._turn_id
        loop._verify_root_user_input = ""
        loop._verify_attempt = 0
        loop._verify_attempt_results = []
    else:
        loop._verify_root_turn_id = continuation.turn_id or loop._turn_id
        loop._verify_attempt = continuation.verify_attempt

    from core.agent.cognitive_state_ctx import set_session_id, set_turn_id

    set_session_id(loop._session_id)
    set_turn_id(loop._turn_id)
    if continuation is not None:
        return user_input, None
    if internal_continuation:
        from core.agent.cognitive_state_ctx import (
            set_cognitive_state,
            set_parent_session_id,
            set_parent_session_key,
        )

        set_cognitive_state(loop.cognitive_state)
        set_parent_session_key(loop._parent_session_key)
        set_parent_session_id(loop._parent_session_id)
        loop._verify_root_user_input = user_input
        return user_input, None
    effective, blocked = await _apply_user_prompt_hook(loop, user_input)
    loop._verify_root_user_input = effective
    return effective, blocked


def _refresh_mcp_tools_at_turn_start(loop: Any) -> None:
    """Refresh a lazy or stale MCP schema snapshot."""
    if loop._mcp_manager is None or (
        len(loop._tools) >= TOOL_LAZY_LOAD_THRESHOLD
        and loop._mcp_manager.connection_epoch == loop._mcp_epoch
    ):
        return
    added = loop.refresh_tools()
    loop._mcp_epoch = loop._mcp_manager.connection_epoch
    if added > 0:
        log.info("MCP tools lazy-loaded: +%d tools (total %d)", added, len(loop._tools))


async def _open_turn(
    loop: Any,
    user_input: str,
    *,
    verification_continuation: bool = False,
    goal_continuation: Any | None = None,
    goal_continuation_trigger: str = "active_goal",
) -> AgenticResult | None:
    """Publish legacy start signals, then the durable public boundary."""
    if verification_continuation:
        if loop._timeline is not None:
            loop._timeline.record_verification_continuation(
                user_input,
                root_turn_id=loop._verify_root_turn_id,
                verify_attempt=loop._verify_attempt,
            )
        root_input = loop._verify_root_user_input or user_input
        loop._save_checkpoint(root_input, round_idx=0)
        return await _admit_session_budget(loop, user_input)
    if goal_continuation is not None:
        resumed_start = (
            int(getattr(loop, "_session_generation", 1)) > 1 and not loop._public_session_started
        )
        if loop._timeline is not None:
            from core.observability.session_timeline import SessionEventKind

            if resumed_start:
                loop._timeline.record_session_start(
                    model=loop.model,
                    provider=loop._provider,
                )
            loop._timeline.record_goal_state(
                SessionEventKind.GOAL_CONTINUED,
                goal_continuation,
                trigger=goal_continuation_trigger,
            )
        if resumed_start:
            from core.llm.adapters.dispatch import begin_session_adapter_tracking

            begin_session_adapter_tracking()
            if loop._hooks:
                await loop._hooks.trigger_async(
                    HookEvent.SESSION_STARTED,
                    {
                        "model": loop.model,
                        "provider": loop._provider,
                        "session_id": loop._session_id,
                        "resumed": True,
                    },
                )
        objective = str(getattr(goal_continuation, "objective", user_input))
        if loop._save_checkpoint(objective, round_idx=0) and resumed_start:
            await _lifecycle.emit_public_session_start(loop)
        return await _admit_session_budget(loop, user_input)
    intercepted = await loop._emit_session_start_signals(user_input)
    if intercepted is not None:
        return cast(AgenticResult, intercepted)
    if loop._save_checkpoint(user_input, round_idx=0):
        await _lifecycle.emit_public_session_start(loop)
    return await _admit_session_budget(loop, user_input)


async def _finalize_blocked_turn(loop: Any, result: AgenticResult) -> AgenticResult:
    """Persist a rejected prompt attempt without storing its prompt body."""
    if loop._timeline is not None:
        loop._timeline.record_session_start(
            model=loop.model,
            provider=loop._provider,
        )
    return cast(AgenticResult, await loop._afinalize_and_return(result, "", 0))


async def _admit_session_budget(loop: Any, user_input: str) -> AgenticResult | None:
    """Stop an expired opt-in session before planner, model, or tool work."""
    _maybe_start_session_budget(loop)
    guard = _check_session_budget_and_maybe_handoff(loop)
    if guard is None:
        return None
    reason, text = _guard_exit_result(loop, guard, rounds=0)
    return cast(
        AgenticResult,
        await loop._afinalize_and_return(
            _terminal_result(loop, reason, text, rounds=0),
            user_input,
            0,
        ),
    )


# ------------------------------------------------------------------
# Guard chain — the loop's transition guards, in priority order
# ------------------------------------------------------------------
# Call order in ``arun`` IS the priority order:
#   post-response: cost_budget → overthinking → model_refusal
#   post-tool:     convergence → repeated_success_no_progress
# Each guard returns a terminal AgenticResult (born via
# ``_terminal_result``) or None to proceed. Guard counters live on
# ``self`` and are checkpointed via ``_lifecycle.collect_guard_state``
# so a resumed session keeps its guard progress.


def _guard_cost_budget(
    loop: Any,
    *,
    messages: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult | None:
    """Cost budget guard (Karpathy P3 — resource budget).

    Warns once at 80% of budget; terminates with
    ``cost_budget_exceeded`` at 100%.
    """
    if loop._cost_budget <= 0:
        return None
    try:
        from core.llm.token_tracker import get_tracker as _get_cost_tracker

        _cost_tracker = _get_cost_tracker()
        _session_cost = _cost_tracker.accumulator.total_cost_usd

        _warn_threshold = loop._cost_budget * 0.8
        if (
            _session_cost >= _warn_threshold
            and _session_cost < loop._cost_budget
            and not getattr(loop, "_budget_warned", False)
        ):
            loop._budget_warned = True
            if not loop._quiet:
                from core.ui.agentic_ui import emit_budget_warning

                emit_budget_warning(
                    loop._cost_budget,
                    _session_cost,
                    pct=_session_cost / loop._cost_budget * 100,
                )

        if _session_cost >= loop._cost_budget:
            from core.ui.agentic_ui import emit_cost_budget_exceeded

            emit_cost_budget_exceeded(loop._cost_budget, _session_cost)
            loop._op_logger.finalize()
            _context.sync_messages_to_context(loop, messages)
            text = (
                f"Cost budget (${loop._cost_budget:.2f}) exceeded. "
                f"Session cost: ${_session_cost:.2f}"
            )
            log.warning(text)
            return _terminal_result(
                loop,
                TerminationReason.COST_BUDGET_EXCEEDED,
                text,
                rounds=round_idx + 1,
                error=True,
                tool_calls=loop._tool_processor.tool_log,
            )
    except Exception:
        log.debug("Cost budget check failed", exc_info=True)
    return None


async def _guard_overthinking(
    loop: Any,
    response: Any,
    *,
    messages: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult | None:
    """Overthinking guard — N consecutive long-text/no-tool rounds stop
    the loop with ``user_clarification_needed`` (threshold is
    context-proportional, 1% / floor 1024). Owns the counter reset on
    tool-use rounds.
    """
    if response.stop_reason != "tool_use":
        out_tok = getattr(response.usage, "output_tokens", 0) if response.usage else 0
        threshold = _overthinking_token_threshold(loop)
        if out_tok > threshold:
            loop._consecutive_text_only_rounds += 1
        else:
            loop._consecutive_text_only_rounds = 0
        if loop._consecutive_text_only_rounds >= 2:
            # count this flagged round ONCE — adding the running
            # consec would inflate the total quadratically
            loop._total_empty_rounds += 1
            log.warning(
                "Overthinking detected: %d consecutive text-only rounds "
                "(>%d tok each) — surfacing user_clarification_needed",
                loop._consecutive_text_only_rounds,
                threshold,
            )
            loop._op_logger.finalize()
            _context.sync_messages_to_context(loop, messages)
            last_text = loop._extract_text(response).strip()
            summary = last_text[:400] + ("…" if len(last_text) > 400 else "")
            clarification = (
                f"~ I've spent {loop._consecutive_text_only_rounds} consecutive "
                f"rounds reasoning without taking any action "
                f"(>{threshold} output tokens each). "
                "Could you narrow the request — point at a specific file, "
                "behaviour, or step you want me to focus on next?\n\n"
                f"Most recent reasoning (truncated):\n{summary}"
            )
            await loop._record_text_only_round(round_idx, text=last_text)
            return _terminal_result(
                loop,
                TerminationReason.USER_CLARIFICATION_NEEDED,
                clarification,
                rounds=round_idx + 1,
                tool_calls=loop._tool_processor.tool_log,
            )
    else:
        loop._consecutive_text_only_rounds = 0
    return None


def _guard_model_refusal(
    loop: Any,
    response: Any,
    *,
    messages: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult | None:
    """Fable 5 safety decline (HTTP 200, often empty) — surface it
    honestly instead of a silent empty turn.

    ref: https://platform.claude.com/docs/en/about-claude/models/migration-guide
    """
    if response.stop_reason != "refusal":
        return None
    loop._op_logger.finalize()
    _context.sync_messages_to_context(loop, messages)
    stop_details = getattr(response, "stop_details", None)
    category = stop_details.get("category") if isinstance(stop_details, dict) else None
    refusal_text = loop._extract_text(response).strip() or (
        "The model declined this request"
        + (f" (safety classifier category: {category})" if category else "")
        + ". Rephrase the request or retry on another model via /model."
    )
    return _terminal_result(
        loop,
        TerminationReason.MODEL_REFUSAL,
        refusal_text,
        rounds=round_idx + 1,
        tool_calls=loop._tool_processor.tool_log,
    )


def _guard_convergence(
    loop: Any,
    *,
    messages: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult | None:
    """Convergence guard — 3 identical tool errors break the loop."""
    from . import _response

    if not _response.check_convergence_break(loop):
        return None
    from core.ui.agentic_ui import emit_convergence_detected

    last_err = loop._convergence.recent_errors[-1] if loop._convergence.recent_errors else "unknown"
    emit_convergence_detected(last_err, round_idx + 1)
    loop._op_logger.finalize()
    _context.sync_messages_to_context(loop, messages)
    return _terminal_result(
        loop,
        TerminationReason.CONVERGENCE_DETECTED,
        "Detected repeating failure pattern. Breaking loop to avoid infinite retry.",
        rounds=round_idx + 1,
        error=True,
        tool_calls=loop._tool_processor.tool_log,
    )


def _guard_repeated_success(
    loop: Any,
    *,
    messages: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult | None:
    """Repeated-success guard — identical successful results without new
    progress stop the loop (polling the same state indefinitely).
    """
    from . import _response

    if not _response.check_repeated_success_no_progress(loop):
        return None
    from core.ui.agentic_ui import emit_repeated_success_no_progress

    tool_name = loop._convergence.last_success_tool or "unknown"
    streak = loop._convergence.repeated_success_streak
    emit_repeated_success_no_progress(tool_name, streak, round_idx + 1)
    loop._op_logger.finalize()
    _context.sync_messages_to_context(loop, messages)
    return _terminal_result(
        loop,
        TerminationReason.REPEATED_SUCCESS_NO_PROGRESS,
        "Detected repeated successful tool results without new progress. "
        "Breaking loop to avoid polling the same state indefinitely.",
        rounds=round_idx + 1,
        error=True,
        tool_calls=loop._tool_processor.tool_log,
    )


def _guard_exit_result(
    loop: Any,
    guard_reason: str | None,
    *,
    rounds: int,
) -> tuple[TerminationReason, str]:
    """Map a loop-entry guard reason to a terminal result.

    The guard helper returns precise internal reasons. Preserve that
    precision here so session-wide budget handoff/expiry does not leak as
    the unrelated legacy "max rounds" fallback.
    """
    if guard_reason == "time_budget":
        return (
            TerminationReason.TIME_BUDGET_EXPIRED,
            f"Time budget ({loop._time_budget_s:.0f}s) expired after {rounds} rounds.",
        )
    if guard_reason in {"session_time_budget_handoff", "session_time_budget_expired"}:
        remaining = None
        total = None
        try:
            metrics = loop._session_metrics
            remaining = metrics.time_budget_remaining_s()
            total = metrics.time_budget_total_s
        except Exception:
            log.debug("session budget summary unavailable for guard exit", exc_info=True)

        if guard_reason == "session_time_budget_handoff":
            if remaining is not None and total is not None and total > 0:
                text = (
                    "Session time budget is in the handoff window "
                    f"({remaining:.0f}s remaining of {total:.0f}s). "
                    "Start a new GEODE session or restart GEODE to continue safely."
                )
            else:
                text = (
                    "Session time budget is in the handoff window. "
                    "Start a new GEODE session or restart GEODE to continue safely."
                )
            return TerminationReason.SESSION_TIME_BUDGET_HANDOFF, text

        if remaining is not None and total is not None and total > 0:
            text = (
                "Session time budget expired "
                f"({abs(min(remaining, 0.0)):.0f}s over the {total:.0f}s budget). "
                "Start a new GEODE session or restart GEODE to continue."
            )
        else:
            text = (
                "Session time budget expired. "
                "Start a new GEODE session or restart GEODE to continue."
            )
        return TerminationReason.SESSION_TIME_BUDGET_EXPIRED, text

    # Back-compat: an exhausted positive max_rounds cap keeps the legacy
    # result text/termination reason.
    return (
        TerminationReason.MAX_ROUNDS,
        "Max agentic rounds reached. Please try a more specific request.",
    )


def _persist_handoff_request(loop: Any) -> None:
    """Flip the ``sessions`` row to ``handoff_state='pending'`` via the
    DB CAS helper (once per session at the T-threshold crossing).

    Failures NEVER raise. No-op when no session_id is bound or the row
    isn't upserted yet.
    """
    session_id = getattr(loop, "_session_id", "")
    if not session_id:
        return
    mgr = None
    try:
        from core.agent.handoff import request_handoff
        from core.memory.session_manager import SessionManager

        mgr = SessionManager()
        request_handoff(mgr._conn, session_id=session_id, platform="agentic_loop")
    except Exception:
        log.debug("Handoff DB request skipped", exc_info=True)
    finally:
        # Close to avoid leaked SQLite handles.
        if mgr is not None:
            try:
                mgr.close()
            except Exception:
                log.debug("Handoff SessionManager close failed", exc_info=True)


async def _maybe_replan_async(loop: Any, round_idx: int, *, failure_context: str = "") -> None:
    """Per-round Dynamic Replan trigger.

    Asks :func:`core.agent.plan.should_replan`; on a trigger calls
    :func:`replan_async` (planner LLM via the active loop model) and
    installs the new :class:`Plan` via ``set_active_plan``.

    Triggers: ``verify_fail`` (fires at the first round of the *next*
    ``arun``, since verify runs at finalization) and an edge-triggered
    ``low_confidence`` signal. Failures NEVER raise; no-op when
    ``replan_enabled=False`` or no trigger fires.
    """
    try:
        from core.agent.plan import (
            _replan_max_attempts,
            replan_async,
            should_replan,
        )
        from core.observability.session_metrics import current_session_metrics

        metrics = current_session_metrics()
        # Low-confidence replan (edge-triggered; see constructor
        # comment on _low_confidence_replan_armed). Re-arm on
        # recovery, fire only on an armed drop below threshold.
        # getattr tolerates stub loops (same convention as
        # _check_round_guards' handoff check).
        raw_confidence = getattr(getattr(loop, "cognitive_state", None), "confidence", None)
        confidence: float | None = (
            float(raw_confidence) if isinstance(raw_confidence, int | float) else None
        )
        if confidence is not None and confidence >= REPLAN_LOW_CONFIDENCE:
            loop._low_confidence_replan_armed = True
        low_confidence = (
            getattr(loop, "_low_confidence_replan_armed", True)
            and confidence is not None
            and confidence < REPLAN_LOW_CONFIDENCE
        )
        trigger = should_replan(
            round_idx=round_idx,
            plan=metrics.active_plan,
            verify_failed=not metrics.last_verify_passed,
            verify_should_retry=metrics.last_verify_should_retry,
            low_confidence=low_confidence,
        )
        if trigger is None:
            return
        if trigger == "low_confidence":
            # consume the edge — no refire until confidence recovers
            loop._low_confidence_replan_armed = False
        # A verify_fail past replan_max_attempts abandons the stuck step
        # instead of calling the planner again.
        if trigger == "verify_fail" and metrics.active_plan is not None:
            metrics.record_step_attempt()
            cap = _replan_max_attempts()
            if metrics.replan_attempts_on_current_step > cap:
                abandoned_step = metrics.active_plan.current_step()
                advanced = metrics.active_plan.abandon_and_advance()
                # new step → reset the per-step counter
                metrics.set_active_plan(advanced, reset_attempts=True)
                timeline = getattr(loop, "_timeline", None)
                if timeline is not None:
                    from core.observability.session_timeline import SessionEventKind

                    timeline.record_plan_state(
                        SessionEventKind.PLAN_ABANDONED,
                        advanced,
                        trigger="retry_budget_exhausted",
                        changed_step_ids=(abandoned_step.id,) if abandoned_step is not None else (),
                    )
                loop._prompt_dirty = True
                log.info(
                    "Replan abandon: step exceeded %d attempts; advancing plan",
                    cap,
                )
                return
        # Replan against the failed candidate and verifier instruction;
        # the per-turn tool log was reset before a verify continuation.
        from types import SimpleNamespace

        recent_parts: list[str] = []
        if trigger == "verify_fail":
            attempts = getattr(loop, "_verify_attempt_results", ())
            if attempts:
                recent_parts.append(str(getattr(attempts[-1], "text", "") or ""))
            if failure_context:
                recent_parts.append(failure_context)
        if not recent_parts:
            try:
                recent_parts.append(str(loop._tool_processor.tool_log[-1].get("result", "")))
            except Exception:
                log.debug("recent tool_log read for replanner failed", exc_info=True)
        recent_text = "\n\n".join(part for part in recent_parts if part)
        stub_result = SimpleNamespace(text=str(recent_text))
        new_plan = await replan_async(
            loop, plan=metrics.active_plan, turn_result=stub_result, trigger=trigger
        )
        if new_plan is None:
            log.info("Replan trigger=%s: planner failed; keeping prior plan", trigger)
            return
        metrics.record_replan(trigger)
        metrics.set_active_plan(new_plan)
        timeline = getattr(loop, "_timeline", None)
        if timeline is not None:
            from core.observability.session_timeline import SessionEventKind

            timeline.record_plan_state(
                SessionEventKind.PLAN_REPLANNED,
                new_plan,
                trigger=trigger,
            )
        # next LLM call must see the new plan
        loop._prompt_dirty = True
        # UI replan banner
        try:
            from core.ui.agentic_ui import emit_plan_step, emit_replan

            emit_replan(
                trigger=trigger,
                step_count=len(new_plan.steps),
                revision=new_plan.revision,
            )
            first_step = new_plan.current_step()
            if first_step is not None:
                emit_plan_step(
                    current=new_plan.current + 1,
                    total=len(new_plan.steps),
                    description=first_step.description,
                    revision=new_plan.revision,
                )
        except Exception:
            log.debug("Replan UI emit failed", exc_info=True)
        log.info(
            "Replan trigger=%s: installed %d-step plan (revision %d)",
            trigger,
            len(new_plan.steps),
            new_plan.revision,
        )
    except Exception:
        log.warning("Replan dispatch crashed", exc_info=True)


def _consume_plan_hint(loop: Any) -> str:
    """Render the active :class:`Plan` as a ``<plan>...</plan>`` block.

    Read-only (no clear) — the plan persists until a replan installs a
    new revision. Empty string when no plan is active. Failures NEVER raise.
    """
    try:
        from core.agent.plan import render_plan_for_prompt
        from core.observability.session_metrics import current_session_metrics

        plan = current_session_metrics().active_plan
        if plan is None:
            return ""
        return render_plan_for_prompt(plan)
    except Exception:
        log.warning("Plan hint consume failed", exc_info=True)
        return ""


def _consume_reflection_hint(loop: Any) -> str:
    """Read+clear the failure-reflection hint left by the prior turn.

    Returns the ``<reflection>...</reflection>`` block from the prior
    turn's verify FAIL, else empty (verify passed / didn't run).
    Read+clear is asyncio-task safe (no ``await`` between); a threaded
    race only risks a duplicate prepend, not data loss. Failures NEVER
    raise.

    Contract: pre-finalize exits (BillingError / UserCancelledError)
    skip verify, so the next arun's hint slot is empty by design.
    """
    try:
        from core.observability.session_metrics import current_session_metrics

        metrics = current_session_metrics()
        hint = metrics.last_verify_reflection_hint
        if hint:
            metrics.last_verify_reflection_hint = ""
        return hint
    except Exception:
        log.warning("Reflection hint consume failed", exc_info=True)
        return ""


def _consume_reflexion_hint(loop: Any) -> str:
    """Legacy alias for :meth:`_consume_reflection_hint`."""
    return _consume_reflection_hint(loop)


def _maybe_start_session_budget(loop: Any) -> None:
    """Begin the session-wide wall-clock budget if not already started.

    Idempotent — no-op when a prior loop in the same SessionMetrics
    scope already started it (clock keeps running across nested loops).
    The cap is opt-in via ``GEODE_SESSION_TIME_BUDGET_S``; unset, invalid,
    and non-positive values leave durable sessions unbounded.
    Failures NEVER raise.
    """
    import math
    import os

    try:
        from core.agent.budget import (
            DEFAULT_HANDOFF_THRESHOLD_S,
            start_session_budget,
        )

        metrics = loop._session_metrics
        if metrics.time_budget_total_s > 0.0:
            return  # Already started in this session.
        raw = os.environ.get("GEODE_SESSION_TIME_BUDGET_S")
        if raw is None:
            return
        try:
            total = float(raw)
        except ValueError:
            log.warning("Ignoring invalid GEODE_SESSION_TIME_BUDGET_S=%r", raw)
            return
        if not math.isfinite(total) or total <= 0.0:
            log.warning("Ignoring non-positive or non-finite session time budget: %r", raw)
            return  # Explicitly disabled.
        start_session_budget(
            total_seconds=total,
            handoff_threshold_seconds=min(DEFAULT_HANDOFF_THRESHOLD_S, total / 2.0),
            metrics=metrics,
        )
    except Exception:
        log.warning("Session budget start failed", exc_info=True)


def _check_session_budget_and_maybe_handoff(loop: Any) -> str | None:
    """Check session-wide wall-clock budget. Returns a guard-string when
    the loop must break, ``None`` otherwise. Fires ``HANDOFF_TRIGGERED``
    on the first threshold crossing.

    Returns:
        * ``"session_time_budget_handoff"`` on first T-threshold crossing.
        * ``"session_time_budget_expired"`` when fully past the cap.
        * ``None`` when still within budget (or no budget set).
    """
    import time as _time

    try:
        from core.agent.budget import budget_summary, check_session_budget

        metrics = loop._session_metrics
        check = check_session_budget(metrics=metrics)
        if check.expired:
            return "session_time_budget_expired"
        if check.handoff_due:
            payload: dict[str, Any] = {
                "session_id": loop._session_id,
                "platform": "",  # adapter binding can override
                "remaining_s": check.remaining_seconds,
                "ts": _time.time(),
                **budget_summary(metrics=metrics),
            }
            if loop._hooks is not None:
                try:
                    loop._hooks.trigger(HookEvent.HANDOFF_TRIGGERED, payload)
                except Exception:
                    log.warning("HANDOFF_TRIGGERED hook failed", exc_info=True)
            if loop._timeline is not None:
                try:
                    loop._timeline.record_lifecycle_event(
                        event="handoff_triggered",
                        component="agentic_loop",
                        level="warning",
                        payload=payload,
                        action="agent.handoff_triggered",
                        entity_type="session",
                        entity_id=loop._session_id,
                    )
                except Exception:
                    log.warning("Timeline handoff_triggered record failed", exc_info=True)
            # flip the sessions row to handoff_state=PENDING (read-write
            # parity; no-op when no session row exists yet)
            _persist_handoff_request(loop)
            return "session_time_budget_handoff"
    except Exception:
        log.warning("Session budget check failed", exc_info=True)
    return None


def _overthinking_token_threshold(loop: Any) -> int:
    """Per-round output-token threshold for the overthinking signal.

    Context-proportional (1% of context window, floor 1024). Falls
    back to 2000 when the token-tracker lookup fails (mocked module).
    """
    try:
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        ctx_window = MODEL_CONTEXT_WINDOW.get(loop.model, 200_000)
        return max(1024, int(ctx_window) // 100)
    except (TypeError, ValueError, AttributeError):
        return 2000


def _build_model_action_result(
    loop: Any,
    *,
    error_type: str,
    severity: str,
    hint: str,
    rounds: int,
    detail: str | None = None,
) -> AgenticResult:
    """Build an ``AgenticResult`` carrying a user-facing diagnostic.

    Used when an LLM error survives the retry budget (or convergence
    breaks) — surfaces context for the user to pick a model via ``/model``.
    """
    from core.llm.errors import build_model_action_message, summarize_error_detail

    cost: float | None = None
    try:
        from core.llm.token_tracker import get_tracker

        cost = float(get_tracker().accumulator.total_cost_usd)
    except Exception:
        log.debug("total_cost_usd read for diagnostic failed", exc_info=True)
        cost = None
    # strip raw SDK JSON to the underlying message (no-op if unclear)
    clean_detail = summarize_error_detail(detail) if detail else None
    text = build_model_action_message(
        error_type=error_type,
        severity=severity,
        hint=hint,
        model=loop.model,
        provider=loop._provider,
        attempts=loop._consecutive_llm_failures,
        cost_so_far_usd=cost,
        suggested_models=_model_switching.fallback_chain_suggestions(loop) or None,
        detail=clean_detail,
    )
    return _terminal_result(
        loop,
        TerminationReason.MODEL_ACTION_REQUIRED,
        text,
        rounds=rounds,
        error=True,
        tool_calls=loop._tool_processor.tool_log,
    )


async def _afinalize_actionable_partial_on_empty(
    loop: Any,
    exc: EmptyModelOutputError,
    *,
    messages: list[dict[str, Any]],
    user_input: str,
    round_idx: int,
) -> AgenticResult | None:
    """Preserve prior tool work when an opted-in continuation is empty."""

    usable_tool_actions = any(
        not isinstance(entry.get("result"), dict) or not entry["result"].get("error")
        for entry in loop._tool_processor.tool_log
    )
    if not loop._allow_actionable_partial_on_empty or not usable_tool_actions:
        return None
    # The current continuation is empty, but an earlier round in this
    # same turn already emitted executable tool work. Preserve that work
    # and attest every exhausted empty attempt. Empty-before-action stays
    # a hard infrastructure failure.
    exc.mark_actionable()
    log.warning(
        "AgenticLoop: finalized actionable partial turn after empty "
        "continuation (rounds=%d tools=%d)",
        round_idx,
        len(loop._tool_processor.tool_log),
    )
    loop._op_logger.finalize()
    _context.sync_messages_to_context(loop, messages)
    result = _terminal_result(
        loop,
        TerminationReason.ACTIONABLE_PARTIAL,
        "",
        rounds=round_idx,
        tool_calls=list(loop._tool_processor.tool_log),
    )
    return cast(
        AgenticResult,
        await loop._afinalize_and_return(result, user_input, round_idx),
    )


async def _finalize_context_exhausted(
    loop: Any,
    user_input: str,
    messages: list[dict[str, Any]],
    round_idx: int,
) -> AgenticResult:
    """Build + finalize the terminal context-exhausted result.

    Shared recovery-failed tail (pre-call / post-call / 400-overflow):
    notify ``exhausted``, sync messages back to context, return the
    terminal ``context_exhausted`` result through finalize.
    """
    _context.notify_context_event(
        loop,
        "exhausted",
        original_count=len(messages),
        new_count=len(messages),
    )
    _context.sync_messages_to_context(loop, messages)
    result = _terminal_result(
        loop,
        TerminationReason.CONTEXT_EXHAUSTED,
        await _context_exhausted_message(user_input),
        rounds=round_idx + 1,
        error=True,
        tool_calls=loop._tool_processor.tool_log,
    )
    return cast(
        AgenticResult,
        await loop._afinalize_and_return(result, user_input, round_idx + 1),
    )


async def _afinalize_tool_round_yield(
    loop: Any,
    *,
    messages: list[dict[str, Any]],
    user_input: str,
    round_idx: int,
) -> AgenticResult:
    """Yield one completed tool batch to an external turn orchestrator."""

    loop._op_logger.finalize()
    _context.sync_messages_to_context(loop, messages)
    result = _terminal_result(
        loop,
        TerminationReason.TOOL_USE_YIELD,
        "",
        rounds=round_idx + 1,
        tool_calls=list(loop._tool_processor.tool_log),
    )
    return cast(
        AgenticResult,
        await loop._afinalize_and_return(result, user_input, round_idx + 1),
    )


def _tool_round_assistant_message(loop: Any, response: AgenticResponse) -> dict[str, Any]:
    """Serialize one tool-use response with provider replay sidecars."""

    message: dict[str, Any] = {
        "role": "assistant",
        "content": loop._serialize_content(response.content),
    }
    reasoning_items = getattr(response, "codex_reasoning_items", None)
    output_items = getattr(response, "codex_output_items", None)
    phase = getattr(response, "assistant_phase", "")
    if reasoning_items:
        message["codex_reasoning_items"] = reasoning_items
    if output_items:
        message["codex_output_items"] = output_items
    if phase:
        message["phase"] = phase
    processor = getattr(loop, "_tool_processor", None)
    operation_id_for = getattr(processor, "operation_id_for", None)
    step = getattr(processor, "_step_snapshot", None)
    if callable(operation_id_for):
        operations: dict[str, dict[str, str]] = {}
        for block in response.content:
            if not isinstance(block, ToolUseBlock) or not block.id:
                continue
            operation_id = operation_id_for(block.id)
            if operation_id:
                operations[block.id] = {
                    "operation_id": operation_id,
                    "step_id": getattr(step, "step_id", ""),
                }
        if operations:
            message["metadata"] = {"effect_operations": operations}
    return message
