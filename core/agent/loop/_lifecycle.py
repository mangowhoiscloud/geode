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
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def save_checkpoint(loop: AgenticLoop, user_input: str, round_idx: int = 0) -> None:
    """Persist session checkpoint for resume (per-turn, Claude Code pattern)."""
    if loop._checkpoint is None or not loop._session_id:
        return
    try:
        from core.memory.session_checkpoint import SessionState

        state = SessionState(
            session_id=loop._session_id,
            round_idx=round_idx,
            model=loop.model,
            provider=loop._provider,
            status="active",
            messages=loop.context.messages,
            tool_log=loop._tool_processor.tool_log,
            cognitive_state=loop.cognitive_state.to_snapshot(),
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

        # Read accumulated cost + tokens from TokenTracker (was missing →
        # always $0 / 0 tokens). PR-SEEDGEN-TOKENS (2026-05-30) adds the
        # token reads so the session_end event carries prompt/completion
        # tokens for the seed-generation per-phase cost grid. payg and
        # claude-cli calls populate real numbers (PR-CLI-USAGE-CAPTURE,
        # 2026-07-13); codex-cli remains 0 (plain-text stdout carries no
        # usage block). Never fabricated.
        total_cost = 0.0
        prompt_tokens = 0
        completion_tokens = 0
        try:
            from core.llm.token_tracker import get_tracker

            accumulator = get_tracker().accumulator
            total_cost = accumulator.total_cost_usd
            prompt_tokens = accumulator.total_input_tokens
            completion_tokens = accumulator.total_output_tokens
        except Exception:
            log.debug("Could not read session cost/tokens from TokenTracker")

        loop._transcript.record_session_end(
            rounds=rounds,
            total_cost=total_cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception:
        log.debug("Transcript end recording failed", exc_info=True)


def _prepare_final_result(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
) -> None:
    """Apply shared finalization side effects before hook emission."""
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

    # Defect A F-A1 (2026-05-11) — aggregate per-arun usage via tracker
    # snapshot delta. Inspect_ai's role_usage aggregation reads this off
    # the ModelEvent.output.usage that ``GeodeModelAPI.generate`` emits,
    # so if ``result.usage`` is None the petri audit's target column
    # silently disappears from log.stats.role_usage. The snapshot anchor
    # is captured at the top of ``arun`` (see ``loop.py:429``); reading
    # the accumulator directly here would over-count sibling loops on
    # the same ContextVar tracker (e.g. compaction sub-LLM calls).
    snap = getattr(loop, "_usage_snapshot", None)
    if snap is not None:
        try:
            from core.llm.token_tracker import LLMUsage as _LLMUsage
            from core.llm.token_tracker import get_tracker as _get_tracker

            delta = _get_tracker().delta_since(snap)
            if delta.call_count > 0:
                result.usage = _LLMUsage(
                    model=loop.model,
                    input_tokens=delta.total_input_tokens,
                    output_tokens=delta.total_output_tokens,
                    thinking_tokens=delta.total_thinking_tokens,
                    cache_creation_tokens=delta.total_cache_creation_tokens,
                    cache_read_tokens=delta.total_cache_read_tokens,
                    cost_usd=delta.total_cost_usd,
                )
        except Exception:
            log.debug("usage delta snapshot failed", exc_info=True)

    loop._record_transcript_end(result)
    ledger = getattr(loop, "_evidence_ledger", None)
    if ledger is not None:
        try:
            ledger.append_final(result=result)
        except Exception:
            log.debug("Evidence final row failed", exc_info=True)
        # Trajectory audit 2026-07-03 — close the declared → recorded →
        # verified chain. ``_prepare_task_preflight`` appended the
        # ``required_evidence`` declaration at session start; the row
        # writers appended evidence as the run progressed; this gate
        # compares the two and appends a ``kind="evidence_check"`` row
        # with the present / missing lists. Runs AFTER ``append_final``
        # so the ``final_answer`` requirement can match the just-written
        # ``final_result`` row. Never raises — the check is telemetry,
        # not a hard failure path.
        preflight = getattr(loop, "_task_preflight", None)
        required = list(preflight.get("required_evidence", [])) if preflight else []
        if required:
            try:
                ledger.append_evidence_check(required_evidence=required)
            except Exception:
                log.debug("Evidence check row failed", exc_info=True)
    loop._save_checkpoint(user_input, round_idx=round_idx)


def _final_hook_payloads(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    verify_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build final lifecycle hook payloads once for sync and async callers.

    PR-COMM-3b (2026-05-24) enriches SESSION_ENDED with four columns the
    SQLite ``agent_runtime_state`` writer needs: ``agent_kind`` (process
    origin), ``component`` (GEODE subsystem), ``adapter_type`` (adapter
    name), and ``claude_cli_session_id`` (the resumable session captured
    by the loop's PR-V persistence helper). Falls back to safe defaults
    when the loop is bare (REPL without orchestrator, tests).
    """
    agent_kind = "subagent" if getattr(loop, "_parent_session_id", "") else "repl"
    component = "agentic_loop"
    try:
        from core.self_improving.loop.observe.run_transcript import current_run_transcript

        run_transcript = current_run_transcript()
        if run_transcript is not None:
            component = run_transcript.component
    except Exception:
        # RunTranscript module is optional in tests / REPL — falls back to the
        # default already assigned above.
        component = "agentic_loop"
    adapter_type = ""
    new_adapter = getattr(loop, "_new_adapter", None)
    if new_adapter is not None:
        adapter_type = str(getattr(new_adapter, "name", ""))

    # PR-DISPATCH-OBS-EXT (2026-05-28) — read the per-session adapter
    # usage counter (populated by dispatch._fire_attempt across the
    # session's lifetime) and emit it inline. Operators see "this session
    # routed N calls through codex-oauth (3 success, 1 transient) +
    # 2 calls through glm-payg (2 success)" without having to parse the
    # ADAPTER_DISPATCH_ATTEMPT event stream.
    #
    # Caveat — captures attempts up to SESSION_ENDED emission. TURN_COMPLETED
    # hooks (e.g. ``turn_llm_extract`` calling complete_text_via_adapters)
    # fire AFTER this payload is built, so their dispatch attempts are NOT
    # in this aggregate. Acceptable: post-turn extraction belongs to
    # ``turn_complete`` accounting, not session_end. Codex MCP audit
    # 2026-05-28 — limitation documented.
    #
    # Reset to ``None`` after read so any leaked post-finalization
    # dispatch (background async hook) doesn't mutate a stale counter.
    from core.llm.adapters.dispatch import (
        end_session_adapter_tracking,
        get_session_adapter_usage,
    )

    adapter_usage = get_session_adapter_usage()
    end_session_adapter_tracking()

    session_ended = {
        "model": loop.model,
        "provider": loop._provider,
        "session_id": loop._session_id,
        "termination_reason": result.termination_reason,
        "rounds": result.rounds,
        "tool_count": len(result.tool_calls),
        "error": result.error,
        # PR-COMM-3b additions for the agent_runtime_state writer:
        "agent_kind": agent_kind,
        "component": component,
        "adapter_type": adapter_type,
        "claude_cli_session_id": getattr(loop, "_last_emitted_session_id", ""),
        # PR-DISPATCH-OBS-EXT (2026-05-28) — per-session aggregate.
        "adapter_usage": adapter_usage,
    }
    turn_completed = {
        "session_id": loop._session_id,
        "model": loop.model,
        "provider": loop._provider,
        "user_input": user_input,
        "text": result.text[:500] if result.text else "",
        "rounds": result.rounds,
        "tool_calls": [tc.get("name", "") for tc in result.tool_calls],
        "termination_reason": result.termination_reason,
    }
    if verify_payload is not None:
        session_ended["turn_verify"] = verify_payload
        turn_completed["turn_verify"] = verify_payload
    return session_ended, turn_completed, result.reasoning_metrics or {}


def _finalize_verify_outcome(
    loop: AgenticLoop, result: AgenticResult, vr: Any
) -> dict[str, Any] | None:
    """Shared SessionMetrics record + DB persist + payload-build path.

    Called by both the sync and async ``_run_turn_verify*`` wrappers so
    the bookkeeping stays identical regardless of how the verify outcome
    was produced. ``None`` mirrors the "skip the hook" semantics for
    OFF mode.
    """
    from core.agent.verify import VerifyMode
    from core.observability.session_metrics import current_session_metrics

    if vr.mode is VerifyMode.OFF:
        return None
    metrics = current_session_metrics()
    metrics.record_verify(
        passed=vr.passed,
        mode=vr.mode.value,
        effective_mode=vr.effective_mode.value,
        rubric_misses=vr.rubric_misses,
        reflection_hint=vr.reflection_hint,
        should_retry=vr.should_retry,
    )
    _persist_verify_state(loop, metrics, vr.should_retry)
    payload: dict[str, Any] = vr.to_payload()
    payload["session_id"] = getattr(loop, "_session_id", "")
    payload["rounds"] = int(getattr(result, "rounds", 0) or 0)
    payload["termination_reason"] = getattr(result, "termination_reason", "") or ""
    payload["tool_call_count"] = len(getattr(result, "tool_calls", []) or [])
    return payload


def _run_turn_verify(loop: AgenticLoop, result: AgenticResult) -> dict[str, Any] | None:
    """PR-CL-A3 (2026-05-23) — sync per-turn verify dispatch.

    Sync variant used by ``finalize_and_return`` (legacy sync path) and
    test fixtures. The async finalizer uses :func:`_run_turn_verify_async`
    so the LLM-judge call can ``await`` cleanly (Codex MCP HIGH #2 fix,
    PR-CL-A6).
    """
    try:
        from core.agent.verify import verify_turn

        vr = verify_turn(result, loop=loop)
        return _finalize_verify_outcome(loop, result, vr)
    except Exception:
        log.warning("turn verify dispatch crashed; skipping", exc_info=True)
        return None


async def _run_turn_verify_async(loop: AgenticLoop, result: AgenticResult) -> dict[str, Any] | None:
    """Async per-turn verify dispatch (PR-CL-A6 — Codex MCP HIGH #2 fix).

    Used by ``finalize_and_return_async`` so an LLM-judge mode call can
    await ``loop._call_llm`` under the same event loop without the
    cross-loop thread-pool hop the sync wrapper has to use.
    """
    try:
        from core.agent.verify import verify_turn_async

        vr = await verify_turn_async(result, loop=loop)
        return _finalize_verify_outcome(loop, result, vr)
    except Exception:
        log.warning("turn verify (async) dispatch crashed; skipping", exc_info=True)
        return None


def _persist_verify_state(loop: AgenticLoop, metrics: Any, should_retry: bool) -> None:
    """Mirror SessionMetrics verify telemetry into the SessionManager DB row.

    Failures NEVER raise (observability hygiene). Skipped silently when no
    session_id is set or no SessionManager singleton exists.
    """
    session_id = getattr(loop, "_session_id", "")
    if not session_id:
        return
    mgr = None
    try:
        from core.memory.session_manager import SessionManager

        mgr = SessionManager()
        mgr.upsert_verify_state(
            session_id,
            verify_pass_count=metrics.verify_pass_count,
            verify_fail_count=metrics.verify_fail_count,
            last_verify_passed=metrics.last_verify_passed,
            last_verify_mode=metrics.last_verify_mode,
            last_verify_effective_mode=metrics.last_verify_effective_mode,
            last_verify_rubric_misses=metrics.last_verify_rubric_misses,
            last_verify_should_retry=should_retry,
        )
    except Exception:
        log.debug("verify state persistence skipped", exc_info=True)
    finally:
        # Close to avoid leaked SQLite handles (Codex MCP follow-up 2026-05-23).
        if mgr is not None:
            try:
                mgr.close()
            except Exception:
                log.debug("verify SessionManager close failed", exc_info=True)


def finalize_and_return(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
) -> AgenticResult:
    """Log result, record transcript end, save checkpoint, and return (DRY)."""
    _prepare_final_result(loop, result, user_input, round_idx)
    # Verify/reflection belongs to the task-completion boundary. Run it
    # before SESSION_ENDED/TURN_COMPLETED hooks so lifecycle consumers can
    # read the final self-evaluation from the same terminal payload.
    verify_payload = _run_turn_verify(loop, result)
    if loop._hooks:
        session_ended, turn_completed, reasoning_metrics = _final_hook_payloads(
            loop, result, user_input, verify_payload=verify_payload
        )
        loop._hooks.trigger(
            HookEvent.SESSION_ENDED,
            session_ended,
        )
        loop._hooks.trigger(
            HookEvent.TURN_COMPLETED,
            turn_completed,
        )
        loop._hooks.trigger(
            HookEvent.REASONING_METRICS,
            reasoning_metrics,
        )
    if verify_payload is not None and loop._hooks:
        event = (
            HookEvent.TURN_VERIFY_PASSED
            if verify_payload.get("passed")
            else HookEvent.TURN_VERIFY_FAILED
        )
        loop._hooks.trigger(event, verify_payload)
    return result


async def finalize_and_return_async(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
) -> AgenticResult:
    """Async finalizer for ``AgenticLoop.arun`` hook emission."""
    _prepare_final_result(loop, result, user_input, round_idx)
    # Verify/reflection belongs to the task-completion boundary. Run it
    # before SESSION_ENDED/TURN_COMPLETED hooks so lifecycle consumers can
    # read the final self-evaluation from the same terminal payload.
    verify_payload = await _run_turn_verify_async(loop, result)
    if loop._hooks:
        session_ended, turn_completed, reasoning_metrics = _final_hook_payloads(
            loop, result, user_input, verify_payload=verify_payload
        )
        await loop._hooks.trigger_async(HookEvent.SESSION_ENDED, session_ended)
        await loop._hooks.trigger_async(HookEvent.TURN_COMPLETED, turn_completed)
        await loop._hooks.trigger_async(HookEvent.REASONING_METRICS, reasoning_metrics)
    if verify_payload is not None and loop._hooks:
        event = (
            HookEvent.TURN_VERIFY_PASSED
            if verify_payload.get("passed")
            else HookEvent.TURN_VERIFY_FAILED
        )
        await loop._hooks.trigger_async(event, verify_payload)
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
        log.debug("reasoning metrics tracker read failed — zeroing", exc_info=True)
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
