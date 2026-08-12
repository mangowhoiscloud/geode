"""Session lifecycle helpers: checkpointing, session record, finalize, metrics.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``)
and reads/writes its state. The class methods on ``AgenticLoop`` are
thin one-line delegators.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from core.hooks import (
    HookAction,
    HookCorrelation,
    HookName,
    RuntimeEvent,
)
from core.llm.errors import BillingError

from .models import (
    AgenticResult,
    TerminationReason,
    is_failure_termination,
    is_successful_task_termination,
)

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def collect_guard_state(loop: AgenticLoop) -> dict[str, Any]:
    """Serialize the loop's guard counters — the machine state that the
    conversation messages do NOT carry.

    Snapshot-completeness contract: everything a resumed session needs to
    keep its guard progress (overthinking streak, retry counter, diversity
    tracker, convergence detector) lives here, so
    ``apply_guard_state(collect_guard_state(loop))`` round-trips. Pinned by
    ``tests/core/agent/test_loop_state_machine.py``.
    """
    return {
        "consecutive_text_only_rounds": loop._consecutive_text_only_rounds,
        "consecutive_llm_failures": loop._consecutive_llm_failures,
        "total_empty_rounds": loop._total_empty_rounds,
        "budget_warned": bool(getattr(loop, "_budget_warned", False)),
        "low_confidence_replan_armed": bool(getattr(loop, "_low_confidence_replan_armed", True)),
        "consecutive_tool_tracker": [list(sig) for sig in loop._consecutive_tool_tracker],
        "convergence": loop._convergence.to_snapshot(),
    }


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def apply_guard_state(loop: AgenticLoop, data: Any) -> None:
    """Inverse of :func:`collect_guard_state` — REPLACEMENT semantics.

    Missing or malformed fields reset to their fresh-loop defaults, never
    keep the live loop's values: the IPC poller reuses ONE loop across
    resumes, so a legacy checkpoint (no ``loop_guards``) must not inherit
    the previous conversation's counters. Field coercion is defensive so a
    malformed checkpoint can never leave the loop half-restored.
    """
    if not isinstance(data, dict):
        data = {}
    loop._consecutive_text_only_rounds = _as_int(data.get("consecutive_text_only_rounds"))
    loop._consecutive_llm_failures = _as_int(data.get("consecutive_llm_failures"))
    loop._total_empty_rounds = _as_int(data.get("total_empty_rounds"))
    loop._budget_warned = bool(data.get("budget_warned", False))
    loop._low_confidence_replan_armed = bool(data.get("low_confidence_replan_armed", True))
    tracker = data.get("consecutive_tool_tracker", [])
    loop._consecutive_tool_tracker = [
        (str(sig[0]), str(sig[1]))
        for sig in (tracker if isinstance(tracker, list) else [])
        if isinstance(sig, (list, tuple)) and len(sig) == 2
    ]
    convergence = data.get("convergence", {})
    loop._convergence.apply_snapshot(convergence if isinstance(convergence, dict) else {})


def restore_loop_state(loop: AgenticLoop, state: Any) -> None:
    """Restore a checkpointed session's machine identity onto *loop*.

    The single resume surgery shared by every resume path (IPC
    ``_handle_resume``, gateway ask continuation) — session id, cognitive
    state, and guard counters in one place, so no path can forget a field.
    Model restore stays with the caller (sync vs async contexts differ).
    """
    import time

    from core.agent.cognitive_state import CognitiveState
    from core.observability.session_metrics import SessionMetrics

    timeline = getattr(loop, "_timeline", None)
    loop._session_id = state.session_id
    if getattr(getattr(loop, "_session_metrics", None), "session_id", "") != state.session_id:
        loop._session_metrics = SessionMetrics(
            session_id=state.session_id,
            component="agentic_loop",
            started_at=time.time(),
        )
    loop._session_generation = (
        timeline.next_generation(state.session_id)
        if timeline is not None
        else int(getattr(loop, "_session_generation", 1)) + 1
    )
    if timeline is not None:
        timeline.rebind(
            state.session_id,
            session_generation=loop._session_generation,
        )
    loop._public_session_started = False
    loop._public_session_ended = False
    loop._pending_verification = dict(getattr(state, "pending_verification", {}) or {})
    loop.cognitive_state = CognitiveState.from_snapshot(state.cognitive_state)
    apply_guard_state(loop, getattr(state, "loop_guards", {}) or {})


def save_checkpoint(loop: AgenticLoop, user_input: str, round_idx: int = 0) -> bool:
    """Persist session checkpoint for resume (per-turn, Claude Code pattern)."""
    if loop._checkpoint is None or not loop._session_id:
        return False
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
            loop_guards=collect_guard_state(loop),
            pending_verification=dict(getattr(loop, "_pending_verification", {}) or {}),
        )
        loop._checkpoint.save(state)

        from core.ui.agentic_ui import emit_checkpoint_saved

        emit_checkpoint_saved(loop._session_id, round_idx)
        return True
    except Exception:
        log.debug("Checkpoint save failed", exc_info=True)
        return False


async def emit_public_session_start(loop: AgenticLoop) -> None:
    """Emit SessionStart once, after the active checkpoint is durable."""
    if getattr(loop, "_public_session_started", False):
        return
    await loop._hook_registry.invoke(
        HookName.SESSION_START,
        payload={
            "model": loop.model,
            "provider": loop._provider,
            "resumed": int(getattr(loop, "_session_generation", 1)) > 1,
            "status": "active",
        },
        correlation=HookCorrelation(
            session_id=loop._session_id,
            turn_id=getattr(loop, "_turn_id", ""),
            session_generation=int(getattr(loop, "_session_generation", 1)),
        ),
    )
    loop._public_session_started = True
    loop._public_session_ended = False


async def _emit_public_session_end(loop: AgenticLoop, *, reason: str) -> None:
    """Emit SessionEnd once, after a durable terminal transition."""
    if getattr(loop, "_public_session_ended", False):
        return
    await loop._hook_registry.invoke(
        HookName.SESSION_END,
        payload={"reason": reason, "status": reason},
        correlation=HookCorrelation(
            session_id=loop._session_id,
            turn_id=getattr(loop, "_turn_id", ""),
            session_generation=int(getattr(loop, "_session_generation", 1)),
        ),
    )
    loop._public_session_ended = True


def _mark_session_status(loop: AgenticLoop, *, reason: str) -> bool:
    if loop._checkpoint is None or not loop._session_id:
        return False
    try:
        transition = getattr(loop._checkpoint, f"mark_{reason}")
        transitioned = bool(transition(loop._session_id))
        current = loop._checkpoint.current_status(loop._session_id)
        return transitioned and current is not None and str(current) == reason
    except Exception:
        log.debug("Checkpoint mark_%s failed", reason, exc_info=True)
        return False


def _record_terminal_timeline(loop: AgenticLoop, *, status: str) -> None:
    """Append the durable terminal edge only after checkpoint transition."""
    timeline = getattr(loop, "_timeline", None)
    if timeline is None:
        return
    try:
        timeline.record_session_end(status=status)
    except Exception:
        log.debug("Session timeline terminal recording failed", exc_info=True)


def mark_session_paused(loop: AgenticLoop) -> None:
    """Mark the current session as paused — a one-shot surface parked it
    awaiting operator input (pending ask); the checkpoint stays resumable.
    """
    _mark_session_status(loop, reason="paused")


async def mark_session_completed_async(loop: AgenticLoop) -> None:
    """Durably complete the session, then publish its public terminal edge."""
    if _mark_session_status(loop, reason="completed"):
        _record_terminal_timeline(loop, status="completed")
        await _emit_public_session_end(loop, reason="completed")


async def mark_session_paused_async(loop: AgenticLoop) -> None:
    """Durably pause a resumable session without ending its lifetime."""
    _mark_session_status(loop, reason="paused")


async def mark_session_error_async(loop: AgenticLoop) -> None:
    """Durably mark error, then publish its public terminal edge."""
    if _mark_session_status(loop, reason="error"):
        _record_terminal_timeline(loop, status="error")
        await _emit_public_session_end(loop, reason="error")


def record_timeline_end(
    loop: AgenticLoop,
    result: Any,
    verify_payload: dict[str, Any] | None = None,
) -> None:
    """Record one completed turn without closing the durable session."""
    if loop._timeline is None:
        return
    try:
        text = getattr(result, "text", "") or ""
        termination_reason = str(getattr(result, "termination_reason", "") or "")
        synthetic_terminal = is_failure_termination(termination_reason) or (
            termination_reason
            in {
                str(TerminationReason.INPUT_BLOCKED),
                str(TerminationReason.USER_CANCELLED),
            }
        )
        if text and not synthetic_terminal:
            loop._timeline.record_assistant_message(text)
        usage = getattr(result, "usage", None)
        if usage is not None:
            loop._timeline.record_cost(
                str(getattr(usage, "model", "") or getattr(loop, "model", "")),
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
                float(getattr(usage, "cost_usd", 0.0) or 0.0),
            )
        error = str(getattr(result, "error", "") or "")
        failed = is_failure_termination(termination_reason)
        if error or failed:
            loop._timeline.record_error(
                termination_reason or "agent_error",
                error or f"terminated with {termination_reason or 'agent_error'}",
            )
        loop._timeline.record_turn_complete(
            termination_reason=termination_reason,
            rounds=int(getattr(result, "rounds", 0) or 0),
            tool_call_count=len(getattr(result, "tool_calls", []) or []),
            error=error,
            failed=failed,
            successful=not error and is_successful_task_termination(termination_reason),
            verify=verify_payload,
        )
    except Exception:
        log.debug("Session timeline end recording failed", exc_info=True)


def _prepare_final_result(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
    *,
    persist: bool = True,
) -> None:
    """Prepare result metadata, optionally committing final persistence."""
    # ToolCallProcessor owns a reusable list and clears it at the next arun.
    # A terminal result is a value snapshot, especially across bounded
    # PostVerify continuations, so detach it before any subsequent turn reset.
    result.tool_calls = [dict(tool_call) for tool_call in result.tool_calls]
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

    if persist:
        _persist_final_result(loop, result, user_input, round_idx)


def _persist_final_result(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
    verify_payload: dict[str, Any] | None = None,
) -> None:
    """Commit timeline, evidence, and checkpoint after stop is final."""
    loop._record_timeline_end(result, verify_payload)
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
        from core.self_improving.loop.observe.run_timeline import current_run_timeline

        run_timeline = current_run_timeline()
        if run_timeline is not None:
            component = run_timeline.component
    except Exception:
        # RunTimeline module is optional in tests / REPL — falls back to the
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
        "turn_id": getattr(loop, "_turn_id", ""),
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
    """Record one verdict in metrics and SQLite, then build its payload."""
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


def _finalization_correlation(loop: AgenticLoop) -> HookCorrelation:
    """Correlate all verify attempts back to the originating user turn."""
    return HookCorrelation(
        session_id=getattr(loop, "_session_id", ""),
        turn_id=(getattr(loop, "_verify_root_turn_id", "") or getattr(loop, "_turn_id", "")),
        run_id=getattr(loop, "run_id", ""),
        session_generation=int(getattr(loop, "_session_generation", 1)),
        verify_attempt=int(getattr(loop, "_verify_attempt", 0)),
    )


async def _run_public_finalization_async(
    loop: AgenticLoop,
    result: AgenticResult,
) -> tuple[dict[str, Any] | None, str, bool, HookCorrelation]:
    """Run PreVerify -> verifier -> PostVerify -> Stop monotonically.

    Returns ``(verify_payload, follow_up, escalated, correlation)``.
    ``follow_up`` is non-empty only when a bounded replay-free continuation
    was accepted.
    """
    from core.agent.verify import VerifyMode, verify_turn_async

    correlation = _finalization_correlation(loop)
    candidate = {
        "termination_reason": result.termination_reason,
        "rounds": result.rounds,
        "tool_call_count": len(result.tool_calls),
        "candidate_summary": (result.text or "")[:500],
    }
    pre = await loop._hook_registry.invoke(
        HookName.PRE_VERIFY,
        payload=candidate,
        correlation=correlation,
    )
    additional_misses = tuple(
        miss
        for decision in pre.decisions
        if decision.action is HookAction.STRENGTHEN
        for miss in decision.additional_misses
    )
    requirements = tuple(
        decision.instruction
        for decision in pre.decisions
        if decision.action is HookAction.STRENGTHEN and decision.instruction
    )

    vr = await verify_turn_async(result, loop=loop)
    if additional_misses:
        misses = tuple(dict.fromkeys((*vr.rubric_misses, *additional_misses)))
        hint_parts = [vr.reflection_hint, *requirements]
        vr = replace(
            vr,
            passed=False,
            rubric_misses=misses,
            reflection_hint="\n".join(part for part in hint_parts if part),
            should_retry=True,
        )

    verify_payload = (
        None
        if vr.mode is VerifyMode.OFF and not additional_misses
        else _finalize_verify_outcome(loop, result, vr)
    )
    public_verify_payload = {
        "passed": vr.passed,
        "mode": vr.mode.value,
        "effective_mode": vr.effective_mode.value,
        "score": round(vr.score, 4),
        "rubric_misses": list(vr.rubric_misses),
        "should_retry": vr.should_retry,
        **candidate,
    }

    post = await loop._hook_registry.invoke(
        HookName.POST_VERIFY,
        payload=public_verify_payload,
        correlation=correlation,
    )
    pre_post_evidence_refs = tuple(
        dict.fromkeys(
            ref
            for outcome in (pre, post)
            for decision in outcome.decisions
            for ref in decision.evidence_refs
        )
    )
    actions = {decision.action for decision in post.decisions}
    fallback_action = ""
    fallback_instruction = ""
    invalid_accept = not vr.passed and HookAction.ACCEPT in actions
    escalated = HookAction.ESCALATE in actions or invalid_accept
    follow_up = ""
    if not post.decisions:
        if vr.passed:
            fallback_action = policy_action = "accept"
        elif vr.should_retry:
            fallback_action = policy_action = "revise"
            miss_summary = ", ".join(vr.rubric_misses[:8]) or "unspecified"
            follow_up = (
                "Verification: retry required.\n"
                f"Rubric misses: {miss_summary}.\n"
                "Required action: repair the candidate, re-check relevant evidence, "
                "and return a corrected result."
            )
            fallback_instruction = follow_up
        else:
            fallback_action = policy_action = "escalate"
            escalated = True
    else:
        policy_action = "escalate" if escalated else ("accept" if vr.passed else "built_in_fail")
        if HookAction.REVISE in actions and not escalated:
            policy_action = "revise"
            follow_up = next(
                (
                    decision.instruction
                    for decision in post.decisions
                    if decision.action is HookAction.REVISE and decision.instruction
                ),
                "",
            )

    stop = await loop._hook_registry.invoke(
        HookName.STOP,
        payload={
            **public_verify_payload,
            "policy_action": policy_action,
            "evidence_refs": [reference.as_dict() for reference in pre_post_evidence_refs],
        },
        correlation=correlation,
    )
    if not escalated:
        stop_follow_up = next(
            (
                decision.instruction
                for decision in stop.decisions
                if decision.action is HookAction.CONTINUE and decision.instruction
            ),
            "",
        )
        if stop_follow_up:
            policy_action = "continue"
            follow_up = stop_follow_up

    evidence_ref_objects = tuple(
        dict.fromkeys(
            [
                *pre_post_evidence_refs,
                *(reference for decision in stop.decisions for reference in decision.evidence_refs),
            ]
        )
    )
    evidence_refs = tuple(reference.as_dict() for reference in evidence_ref_objects)

    budget = int(getattr(loop, "_verify_continuation_budget", 0))
    if follow_up and correlation.verify_attempt >= budget:
        log.warning(
            "Verification continuation budget exhausted (%d/%d)",
            correlation.verify_attempt,
            budget,
        )
        follow_up = ""
        escalated = True
        policy_action = "escalate_budget_exhausted"

    decision_records: list[dict[str, Any]] = []
    if fallback_action:
        instruction_bytes = fallback_instruction.encode("utf-8")
        decision_records.append(
            {
                "surface": HookName.POST_VERIFY.value,
                "handler": "runtime_default",
                "action": fallback_action,
                "reason": "empty_post_verify_decision_set",
                "instruction_sha256": (
                    sha256(instruction_bytes).hexdigest() if instruction_bytes else ""
                ),
                "instruction_bytes": len(instruction_bytes),
                "evidence_refs": [],
            }
        )
    for surface, outcome in (
        (HookName.POST_VERIFY.value, post),
        (HookName.STOP.value, stop),
    ):
        for source, decision in zip(
            outcome.decision_sources,
            outcome.decisions,
            strict=True,
        ):
            instruction_bytes = decision.instruction.encode("utf-8")
            decision_records.append(
                {
                    "surface": surface,
                    "handler": source,
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "instruction_sha256": (
                        sha256(instruction_bytes).hexdigest() if instruction_bytes else ""
                    ),
                    "instruction_bytes": len(instruction_bytes),
                    "evidence_refs": [ref.as_dict() for ref in decision.evidence_refs],
                }
            )

    ledger = getattr(loop, "_evidence_ledger", None)
    if ledger is not None and (post.decisions or stop.decisions or evidence_refs):
        try:
            ledger.append(
                kind="verification_policy",
                summary=f"External verification policy resolved to {policy_action}.",
                payload={
                    "turn_id": correlation.turn_id,
                    "verify_attempt": correlation.verify_attempt,
                    "built_in_passed": vr.passed,
                    "policy_action": policy_action,
                    "rubric_misses": list(vr.rubric_misses),
                    "evidence_refs": list(evidence_refs),
                },
                turn_id=correlation.turn_id,
            )
        except Exception:
            log.debug("Verification policy evidence row failed", exc_info=True)
    timeline = getattr(loop, "_timeline", None)
    if timeline is not None:
        try:
            timeline.record_verification_decision(
                candidate=result.text or "",
                root_turn_id=correlation.turn_id,
                verify_attempt=correlation.verify_attempt,
                built_in_passed=vr.passed,
                policy_action=policy_action,
                decisions=decision_records,
            )
        except Exception:
            log.debug("Verification decision timeline row failed", exc_info=True)
    if timeline is not None and evidence_refs:
        try:
            timeline.record_verification_evidence(
                evidence_refs,
                root_turn_id=correlation.turn_id,
                verify_attempt=correlation.verify_attempt,
                policy_action=policy_action,
            )
        except Exception:
            log.debug("Verification evidence timeline row failed", exc_info=True)
    loop._verification_evidence_refs = list(evidence_refs)

    return verify_payload, follow_up, escalated, correlation


def _merge_verify_attempts(loop: AgenticLoop, result: AgenticResult) -> None:
    """Merge bounded continuation attempts before final persistence."""
    prior = list(getattr(loop, "_verify_attempt_results", ()))
    if not prior:
        return
    all_results = [*prior, result]
    result.tool_calls = [tool_call for attempt in all_results for tool_call in attempt.tool_calls]
    result.rounds = sum(attempt.rounds for attempt in all_results)
    usages = [attempt.usage for attempt in all_results if attempt.usage is not None]
    if usages:
        from core.llm.token_tracker import LLMUsage

        result.usage = LLMUsage(
            model=result.usage.model if result.usage is not None else usages[-1].model,
            input_tokens=sum(usage.input_tokens for usage in usages),
            output_tokens=sum(usage.output_tokens for usage in usages),
            thinking_tokens=sum(usage.thinking_tokens for usage in usages),
            cache_creation_tokens=sum(usage.cache_creation_tokens for usage in usages),
            cache_read_tokens=sum(usage.cache_read_tokens for usage in usages),
            cost_usd=sum(usage.cost_usd for usage in usages),
        )
    result.reasoning_metrics = loop._build_reasoning_metrics(result).to_dict()
    loop._verify_attempt_results = []


async def _close_verify_attempt(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
    verify_payload: dict[str, Any] | None,
) -> None:
    """Checkpoint a bounded verification continuation without ending the session."""
    timeline = getattr(loop, "_timeline", None)
    if timeline is not None:
        text = getattr(result, "text", "") or ""
        if text:
            timeline.record_assistant_message(text)
        record_turn_complete = getattr(timeline, "record_turn_complete", None)
        if callable(record_turn_complete):
            record_turn_complete(
                termination_reason=str(getattr(result, "termination_reason", "") or ""),
                rounds=int(getattr(result, "rounds", 0) or 0),
                tool_call_count=len(getattr(result, "tool_calls", []) or []),
                error=str(getattr(result, "error", "") or ""),
                failed=is_failure_termination(getattr(result, "termination_reason", "")),
                successful=not bool(getattr(result, "error", None))
                and is_successful_task_termination(getattr(result, "termination_reason", "")),
                verify=verify_payload,
            )
    root_input = getattr(loop, "_verify_root_user_input", "") or user_input
    loop._save_checkpoint(root_input, round_idx=round_idx)
    if loop._hooks:
        _session_ended, turn_completed, reasoning_metrics = _final_hook_payloads(
            loop,
            result,
            user_input,
            verify_payload=verify_payload,
        )
        await loop._hooks.emit_async(RuntimeEvent.TURN_COMPLETED, turn_completed)
        await loop._hooks.emit_async(RuntimeEvent.REASONING_METRICS, reasoning_metrics)


async def _emit_verify_runtime_event(
    loop: AgenticLoop,
    verify_payload: dict[str, Any] | None,
) -> None:
    if verify_payload is None or loop._hooks is None:
        return
    event = (
        RuntimeEvent.TURN_VERIFY_PASSED
        if verify_payload.get("passed")
        else RuntimeEvent.TURN_VERIFY_FAILED
    )
    await loop._hooks.emit_async(event, verify_payload)


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


def _skips_public_finalization(result: AgenticResult) -> bool:
    """Return whether a terminal has no candidate answer to verify or stop."""
    return not is_successful_task_termination(result.termination_reason)


async def _finalize_without_public_verify_async(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
) -> AgenticResult:
    """Async persistence-only terminal path for infrastructure and cancel."""
    _prepare_final_result(loop, result, user_input, round_idx, persist=False)
    _merge_verify_attempts(loop, result)
    _persist_final_result(loop, result, user_input, round_idx)
    if loop._hooks:
        session_ended, turn_completed, reasoning_metrics = _final_hook_payloads(
            loop, result, user_input
        )
        await loop._hooks.emit_async(RuntimeEvent.SESSION_ENDED, session_ended)
        await loop._hooks.emit_async(RuntimeEvent.TURN_COMPLETED, turn_completed)
        await loop._hooks.emit_async(RuntimeEvent.REASONING_METRICS, reasoning_metrics)
    return result


async def finalize_and_return_async(
    loop: AgenticLoop,
    result: AgenticResult,
    user_input: str,
    round_idx: int,
) -> AgenticResult:
    """Async finalizer for ``AgenticLoop.arun`` hook emission."""
    if _skips_public_finalization(result):
        return await _finalize_without_public_verify_async(loop, result, user_input, round_idx)
    _prepare_final_result(loop, result, user_input, round_idx, persist=False)
    verify_payload, follow_up, escalated, correlation = await _run_public_finalization_async(
        loop, result
    )
    await _emit_verify_runtime_event(loop, verify_payload)
    if follow_up:
        await _close_verify_attempt(loop, result, user_input, round_idx, verify_payload)
        loop._verify_attempt_results.append(result)
        continued = await loop._arun_once(
            follow_up,
            _verify_continuation=replace(
                correlation,
                verify_attempt=correlation.verify_attempt + 1,
            ),
        )
        return continued

    if escalated:
        # PostVerify escalation is a delivery gate, not telemetry. Preserve the
        # candidate for an external owner, withhold it from ordinary response
        # surfaces, and park the durable session before returning.
        _merge_verify_attempts(loop, result)
        candidate = result.text
        evidence_refs = list(getattr(loop, "_verification_evidence_refs", ()) or ())
        result.pending_text = candidate
        result.text = ""
        result.error = str(TerminationReason.EXTERNAL_VERIFICATION_REQUIRED)
        result.termination_reason = TerminationReason.EXTERNAL_VERIFICATION_REQUIRED
        loop._pending_verification = {
            "candidate": candidate,
            "root_turn_id": correlation.turn_id,
            "verify_attempt": correlation.verify_attempt,
            "evidence_refs": evidence_refs,
        }
        timeline = getattr(loop, "_timeline", None)
        if timeline is not None:
            try:
                timeline.record_verification_pending(
                    candidate=candidate,
                    root_turn_id=correlation.turn_id,
                    verify_attempt=correlation.verify_attempt,
                    references=evidence_refs,
                )
            except Exception:
                log.debug("Verification pending timeline row failed", exc_info=True)
        root_input = getattr(loop, "_verify_root_user_input", "") or user_input
        save_checkpoint = getattr(loop, "_save_checkpoint", None)
        if callable(save_checkpoint):
            save_checkpoint(root_input, round_idx=round_idx)
        _mark_session_status(loop, reason="paused")
        return result

    _merge_verify_attempts(loop, result)
    root_input = getattr(loop, "_verify_root_user_input", "") or user_input
    _persist_final_result(
        loop,
        result,
        root_input,
        round_idx,
        verify_payload=verify_payload,
    )
    if loop._hooks:
        session_ended, turn_completed, reasoning_metrics = _final_hook_payloads(
            loop, result, root_input, verify_payload=verify_payload
        )
        await loop._hooks.emit_async(RuntimeEvent.SESSION_ENDED, session_ended)
        await loop._hooks.emit_async(RuntimeEvent.TURN_COMPLETED, turn_completed)
        await loop._hooks.emit_async(RuntimeEvent.REASONING_METRICS, reasoning_metrics)
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
