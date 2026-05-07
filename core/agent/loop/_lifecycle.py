"""Session lifecycle helpers: checkpointing, transcript end, finalize, metrics.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``)
and reads/writes its state. The class methods on ``AgenticLoop`` are
thin one-line delegators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.hooks import HookEvent
from core.llm.errors import BillingError

from .models import AgenticResult

if TYPE_CHECKING:
    from .loop import AgenticLoop

log = logging.getLogger(__name__)


def save_checkpoint(loop: AgenticLoop, user_input: str, round_idx: int = 0) -> None:
    """Persist session checkpoint for resume (per-turn, Claude Code pattern)."""
    if loop._checkpoint is None or not loop._session_id:
        return
    try:
        from core.runtime_state.session_checkpoint import SessionState

        state = SessionState(
            session_id=loop._session_id,
            round_idx=round_idx,
            model=loop.model,
            provider=loop._provider,
            status="active",
            messages=loop.context.messages,
            tool_log=loop._tool_processor.tool_log,
            user_input=user_input,
        )
        loop._checkpoint.save(state)

        from core.ui.agentic_ui import emit_checkpoint_saved

        emit_checkpoint_saved(loop._session_id, round_idx)
    except Exception:
        log.debug("Checkpoint save failed", exc_info=True)


def mark_session_completed(loop: AgenticLoop) -> None:
    """Mark the current session as completed (called on clean REPL exit)."""
    # Clean up announce queue to prevent orphan accumulation
    if loop._parent_session_key:
        from core.agent.sub_agent import cleanup_announce_queue

        cleanup_announce_queue(loop._parent_session_key)
    if loop._checkpoint is None or not loop._session_id:
        return
    try:
        loop._checkpoint.mark_completed(loop._session_id)
    except Exception:
        log.debug("Checkpoint mark_completed failed", exc_info=True)


def record_transcript_end(loop: AgenticLoop, result: Any) -> None:
    """Record session end + assistant message to transcript."""
    if loop._transcript is None:
        return
    try:
        text = getattr(result, "text", "") or ""
        if text:
            loop._transcript.record_assistant_message(text)
        rounds = getattr(result, "rounds", 0)

        # Read accumulated cost from TokenTracker (was missing → always $0)
        total_cost = 0.0
        try:
            from core.llm.token_tracker import get_tracker

            total_cost = get_tracker().accumulator.total_cost_usd
        except Exception:
            log.debug("Could not read session cost from TokenTracker")

        loop._transcript.record_session_end(rounds=rounds, total_cost=total_cost)
    except Exception:
        log.debug("Transcript end recording failed", exc_info=True)


def finalize_and_return(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
) -> AgenticResult:
    """Log result, record transcript end, save checkpoint, and return (DRY)."""
    log.info(
        "AgenticLoop: reason=%s rounds=%d/%d tools=%d",
        result.termination_reason,
        result.rounds,
        loop.max_rounds,
        len(result.tool_calls),
    )

    # Reasoning metrics (DTR-inspired observability)
    metrics = loop._build_reasoning_metrics(result)
    result.reasoning_metrics = metrics.to_dict()

    loop._record_transcript_end(result)
    loop._save_checkpoint(user_input, round_idx=round_idx)
    if loop._hooks:
        loop._hooks.trigger(
            HookEvent.SESSION_END,
            {
                "model": loop.model,
                "provider": loop._provider,
                "session_id": loop._session_id,
                "termination_reason": result.termination_reason,
                "rounds": result.rounds,
                "tool_count": len(result.tool_calls),
                "error": result.error,
            },
        )
        loop._hooks.trigger(
            HookEvent.TURN_COMPLETE,
            {
                "user_input": user_input,
                "text": result.text[:500] if result.text else "",
                "rounds": result.rounds,
                "tool_calls": [tc.get("name", "") for tc in result.tool_calls],
                "termination_reason": result.termination_reason,
            },
        )
        loop._hooks.trigger(
            HookEvent.REASONING_METRICS,
            result.reasoning_metrics,
        )
    return result


def build_reasoning_metrics(loop: AgenticLoop, result: AgenticResult) -> Any:
    """Collect reasoning efficiency metrics for this turn."""
    from core.agent.reasoning_metrics import ReasoningMetrics

    try:
        from core.llm.token_tracker import get_tracker

        tracker = get_tracker()
        acc = tracker.accumulator
        thinking_tok = int(acc.total_thinking_tokens)
        output_tok = int(acc.total_output_tokens)
        cost = float(acc.total_cost_usd)
    except Exception:
        thinking_tok = 0
        output_tok = 0
        cost = 0.0

    metrics = ReasoningMetrics(
        total_rounds=result.rounds,
        thinking_tokens=thinking_tok,
        output_tokens=output_tok,
        tool_calls_total=len(result.tool_calls),
        empty_rounds=loop._total_empty_rounds,
        cost_usd=cost,
        overthinking_detected=loop._consecutive_text_only_rounds >= 2,
    )
    metrics.compute_derived()
    return metrics


def emit_quota_panel(loop: AgenticLoop, exc: BillingError) -> None:
    """v0.53.0 — emit structured quota_exhausted IPC event with Plan
    context, falling back to legacy billing_error if context absent.

    Pre-v0.53.0 BillingError surfaced as a single-line message and
    cross-provider auto-failover masked the issue by silently
    swapping providers (cost surprise + behavior drift). The new
    flow stops the loop and renders a multi-line panel
    (header + reset-time + 3 actionable options).
    """
    from core.ui.agentic_ui import emit_billing_error, emit_quota_exhausted

    if exc.provider:
        emit_quota_exhausted(
            provider=exc.provider,
            plan_id=exc.plan_id,
            plan_display_name=exc.plan_display_name,
            upgrade_url=exc.upgrade_url,
            resets_in_seconds=exc.resets_in_seconds,
            message=str(exc),
        )
    else:
        emit_billing_error(str(exc))


def inject_credential_breadcrumb(loop: AgenticLoop) -> None:
    """Append an LLM-readable credential note after auth failure (v0.51.0).

    The next agentic round sees a structured rejection breakdown so
    the model can self-recover (call ``manage_login``) or surface a
    meaningful message to the user instead of a generic 'LLM call
    failed' line.
    """
    try:
        from core.auth.credential_breadcrumb import format as fmt_breadcrumb
        from core.auth.rotation import get_last_eligibility_verdicts

        verdicts = get_last_eligibility_verdicts(loop._provider)
        note = fmt_breadcrumb(
            verdicts,
            attempted_provider=loop._provider,
            attempted_model=loop.model,
        )
        if note and not loop.context.is_empty:
            loop.context.add_user_message(note)
    except Exception:
        log.debug("credential breadcrumb injection failed", exc_info=True)
