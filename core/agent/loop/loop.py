"""AgenticLoop — while(tool_use) agentic execution loop.

Claude Code-style agentic loop that continues until the LLM
emits end_turn (no more tool calls). All free-text user input
is routed directly here.

Supports:
- Multi-intent: "분석하고 비교해줘" → sequential tool calls
- Multi-turn: context preserved across interactions
- Self-correction: LLM can retry or adjust based on tool results
- Goal decomposition: compound requests auto-decomposed into sub-goal DAGs
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.agent.conversation import ConversationContext
from core.agent.error_recovery import ErrorRecoveryStrategy
from core.agent.tool_executor import (
    ToolCallProcessor,
    ToolExecutor,
)
from core.config import (
    ANTHROPIC_PRIMARY,
)
from core.hooks import HookEvent, HookSystem
from core.llm.agentic_response import AgenticResponse
from core.llm.errors import BillingError, UserCancelledError
from core.llm.router import (
    maybe_traceable,
    resolve_agentic_adapter,
)
from core.ui.agentic_ui import OperationLogger
from core.ui.status import TextSpinner

from . import _announce, _context, _decomposition, _lifecycle, _model_switching, _response

# Re-exported for backward-compat module-attribute access
# (some tests/utilities reach into ``core.agent.loop.MAX_TOOL_RESULT_TOKENS``)
from ._helpers import (
    AGENTIC_TOOLS,
    MAX_TOOL_RESULT_TOKENS,  # noqa: F401
    TOOL_LAZY_LOAD_THRESHOLD,
    get_agentic_tools,
)
from .models import AgenticResult, _context_exhausted_message, _ContextExhaustedError

if TYPE_CHECKING:
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


class AgenticLoop:
    """Claude Code-style agentic execution loop.

    while stop_reason == "tool_use":
        execute tools → feed results back → continue
    """

    DEFAULT_MAX_ROUNDS = 0  # 0 = unlimited (time-based control via time_budget_s)
    DEFAULT_MAX_TOKENS = 32768
    WRAP_UP_HEADROOM = 2  # force text response N rounds before max
    _WRAP_UP_TIME_HEADROOM_S = 30.0  # force text 30s before time budget expires

    def __init__(
        self,
        context: ConversationContext,
        tool_executor: ToolExecutor,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        thinking_budget: int = 0,  # 0 = disabled; >0 = Extended Thinking tokens (legacy)
        effort: str = "high",  # "low" | "medium" | "high" | "max" (adaptive thinking)
        time_budget_s: float = 0.0,  # 0 = no time limit (OpenClaw pattern)
        cost_budget: float = 0.0,  # 0 = no cost limit (Karpathy P3)
        model: str | None = None,
        provider: str = "anthropic",
        tool_registry: ToolRegistry | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        hooks: HookSystem | None = None,
        enable_goal_decomposition: bool = True,
        parent_session_key: str = "",
        system_suffix: str = "",
        quiet: bool = False,
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self._parent_session_key = parent_session_key
        self._system_suffix = system_suffix
        self._quiet = quiet  # suppress spinner (sub-agent, headless)
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self._thinking_budget = thinking_budget
        self._effort = effort
        self._time_budget_s = time_budget_s
        # Adaptive compute: track consecutive text-only rounds for overthinking detection
        self._consecutive_text_only_rounds = 0
        self._total_empty_rounds = 0
        self._cost_budget = cost_budget
        self._loop_start_time: float = 0.0
        self.model = model or ANTHROPIC_PRIMARY
        self._provider = provider  # "anthropic", "openai", or "glm"
        # v0.52.5 — set by update_model() when model changes; consumed by
        # the run-loop to rebuild system_prompt before the next LLM call.
        self._prompt_dirty: bool = False
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._hooks = hooks
        # Unified tool assembly: merge native + MCP tools together
        mcp_tool_list = mcp_manager.get_all_tools() if mcp_manager is not None else None
        self._tools = get_agentic_tools(tool_registry, mcp_tools=mcp_tool_list)
        self._last_llm_error: str | None = None  # last error type for user message
        self._adapter = resolve_agentic_adapter(self._provider)
        self._op_logger = OperationLogger(quiet=self._quiet)
        self._error_recovery = ErrorRecoveryStrategy(tool_executor)

        # Tier 1 transcript: append-only JSONL event stream (snapshot-redesign)
        self._transcript: Any | None = None
        self._session_id: str = ""
        try:
            import uuid as _uuid

            from core.runtime_state.transcript import SessionTranscript

            self._session_id = f"s-{_uuid.uuid4().hex[:12]}"
            self._transcript = SessionTranscript(self._session_id)
        except Exception:
            log.warning("Transcript init failed", exc_info=True)

        # ToolCallProcessor: orchestrates tool_use block execution
        self._tool_processor = ToolCallProcessor(
            executor=tool_executor,
            op_logger=self._op_logger,
            error_recovery=self._error_recovery,
            hooks=hooks,
            mcp_manager=mcp_manager,
            transcript=self._transcript,
            model=self.model,
        )

        # Goal decomposition: auto-decompose compound requests into sub-goal DAGs
        self._enable_goal_decomposition = enable_goal_decomposition
        self._goal_decomposer: Any | None = None  # lazy init

        # Feature 3: Model escalation on consecutive LLM failures
        self._consecutive_llm_failures: int = 0
        self._ESCALATION_THRESHOLD: int = 2
        self._LLM_RETRY_CAP: int = 5  # max retries before giving up

        # Context window management (extracted — SRP)
        from core.agent.context_manager import ContextWindowManager

        self._ctx_mgr = ContextWindowManager(hooks=hooks, quiet=quiet)

        # Convergence detection + tool error tracking (extracted — SRP)
        from core.agent.convergence import ConvergenceDetector

        # Late-binding lambda so test patches on _try_model_escalation propagate
        self._convergence = ConvergenceDetector(escalation_fn=lambda: self._try_model_escalation())

        # Feature 8: Diversity forcing — prevent same tool 5x consecutively
        self._consecutive_tool_tracker: list[str] = []

        # C3 checkpoint: full message persistence for /resume (Claude Code pattern)
        self._checkpoint: Any | None = None
        try:
            from core.runtime_state.session_checkpoint import SessionCheckpoint

            self._checkpoint = SessionCheckpoint()
        except Exception:
            log.warning("SessionCheckpoint init failed", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle / metrics — delegate to ``_lifecycle``
    # ------------------------------------------------------------------

    def _save_checkpoint(self, user_input: str, round_idx: int = 0) -> None:
        """Delegates to :func:`_lifecycle.save_checkpoint`."""
        return _lifecycle.save_checkpoint(self, user_input, round_idx)

    def mark_session_completed(self) -> None:
        """Delegates to :func:`_lifecycle.mark_session_completed`."""
        return _lifecycle.mark_session_completed(self)

    def _record_transcript_end(self, result: Any) -> None:
        """Delegates to :func:`_lifecycle.record_transcript_end`."""
        return _lifecycle.record_transcript_end(self, result)

    def _finalize_and_return(
        self,
        result: AgenticResult,
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Delegates to :func:`_lifecycle.finalize_and_return`."""
        return _lifecycle.finalize_and_return(self, result, user_input, round_idx)

    def _build_reasoning_metrics(self, result: AgenticResult) -> Any:
        """Delegates to :func:`_lifecycle.build_reasoning_metrics`."""
        return _lifecycle.build_reasoning_metrics(self, result)

    def _emit_quota_panel(self, exc: BillingError) -> None:
        """Delegates to :func:`_lifecycle.emit_quota_panel`."""
        return _lifecycle.emit_quota_panel(self, exc)

    def _inject_credential_breadcrumb(self) -> None:
        """Delegates to :func:`_lifecycle.inject_credential_breadcrumb`."""
        return _lifecycle.inject_credential_breadcrumb(self)

    # ------------------------------------------------------------------
    # Tool list refresh — delegate to ``_response``
    # ------------------------------------------------------------------

    def refresh_tools(self) -> int:
        """Delegates to :func:`_response.refresh_tools`."""
        return _response.refresh_tools(self)

    # ------------------------------------------------------------------
    # Model switching / escalation — delegate to ``_model_switching``
    # ------------------------------------------------------------------

    def _sync_model_from_settings(self) -> bool:
        """Drift sync: consult ``_drift_target_is_healthy`` before ``self.update_model``.

        v0.52.2 contract — when ``settings.model`` diverges from
        ``loop.model``, the helper first verifies the target provider has
        an eligible profile (via ``_drift_target_is_healthy``) and only
        then calls ``self.update_model``. Refusing unhealthy targets
        prevents the v0.51-incident regression where stale settings
        silently overwrote the loop's chosen model.
        Delegates to :func:`_model_switching.sync_model_from_settings`.
        """
        return _model_switching.sync_model_from_settings(self)

    def _drift_target_is_healthy(self, target_model: str) -> bool:
        """Health check: ``_resolve_provider`` → ``rotator.resolve`` lookup.

        Resolves ``target_model`` to its provider via ``_resolve_provider``
        and asks ``ProfileRotator.resolve`` whether any eligible profile
        could serve the next call. The query mirrors the actual selection
        path used by the LLM call so the answer matches what the next
        call would pick. Delegates to
        :func:`_model_switching.drift_target_is_healthy`.
        """
        return _model_switching.drift_target_is_healthy(self, target_model)

    def update_model(
        self,
        model: str,
        provider: str | None = None,
        reason: str = "user_switch",
    ) -> None:
        """Delegates to :func:`_model_switching.update_model`."""
        return _model_switching.update_model(self, model, provider, reason)

    def _purge_stale_model_switch_acks(self) -> None:
        """Delegates to :func:`_model_switching.purge_stale_model_switch_acks`."""
        return _model_switching.purge_stale_model_switch_acks(self)

    def _adapt_context_for_model(self, target_model: str) -> None:
        """Delegates to :func:`_model_switching.adapt_context_for_model`."""
        return _model_switching.adapt_context_for_model(self, target_model)

    def _try_model_escalation(self) -> bool:
        """Same-provider escalation only (v0.53.0 — no cross-provider auto-swap).

        Once the current adapter's chain exhausts, the loop surfaces the
        quota exhaustion to user via the ``BillingError`` panel; callers
        must not reintroduce cross-provider iteration through fallbacks.
        Delegates to :func:`_model_switching.try_model_escalation`.
        """
        return _model_switching.try_model_escalation(self)

    @staticmethod
    def _persist_escalated_model(model: str) -> None:
        """Delegates to :func:`_model_switching.persist_escalated_model`."""
        return _model_switching.persist_escalated_model(model)

    def _try_cross_provider_escalation(self) -> bool:
        """Disabled in v0.53.0 — early ``return False`` (no auto-swap).

        Cross-provider auto-failover was removed in v0.53.0 because it
        masked quota exhaustion with cost surprise and behaviour drift.
        Delegates to :func:`_model_switching.try_cross_provider_escalation`,
        which is a no-op that returns ``False``.
        """
        return _model_switching.try_cross_provider_escalation(self)

    # ------------------------------------------------------------------
    # Run loop entry points
    # ------------------------------------------------------------------

    def run(self, user_input: str) -> AgenticResult:
        """Sync wrapper — delegates to ``arun()`` via ``asyncio.run()``."""
        result: AgenticResult = asyncio.run(self.arun(user_input))
        return result

    @maybe_traceable(run_type="chain", name="AgenticLoop.run")  # type: ignore[untyped-decorator]
    async def arun(self, user_input: str) -> AgenticResult:
        """Run the agentic loop until LLM emits end_turn or max rounds."""
        self._tool_processor.reset()
        self._op_logger.reset()

        # Wire conversation context so /model command guard can check size
        from core.cli.commands import set_conversation_context

        set_conversation_context(self.context)

        # Lazy MCP tool refresh: if tools were empty at init (MCP not yet connected),
        # try to load them now. This handles the startup timing gap.
        if self._mcp_manager is not None and len(self._tools) < TOOL_LAZY_LOAD_THRESHOLD:
            added = self.refresh_tools()
            if added > 0:
                log.info("MCP tools lazy-loaded: +%d tools (total %d)", added, len(self._tools))

        # Goal decomposition: try to break compound requests into sub-goal DAGs.
        # Returns a hint string appended to the system prompt, or None if not compound.
        try:
            decomposition_hint = self._try_decompose(user_input)
        except BillingError as exc:
            self._emit_quota_panel(exc)
            return AgenticResult(
                text=exc.user_message(),
                rounds=0,
                termination_reason="billing_error",
            )

        # Hook: USER_INPUT_RECEIVED (interceptor — can block input)
        if self._hooks:
            intercept = self._hooks.trigger_interceptor(
                HookEvent.USER_INPUT_RECEIVED,
                {"user_input": user_input, "session_id": self._session_id},
            )
            if intercept.blocked:
                return AgenticResult(
                    text=intercept.reason, rounds=0, termination_reason="input_blocked"
                )

        # Add user message to conversation context
        self.context.add_user_message(user_input)

        # Transcript: session start + user message
        if self._transcript is not None:
            self._transcript.record_session_start(model=self.model, provider=self._provider)
            self._transcript.record_user_message(user_input)

        # Hook: SESSION_START
        if self._hooks:
            self._hooks.trigger(
                HookEvent.SESSION_START,
                {
                    "model": self.model,
                    "provider": self._provider,
                    "session_id": self._session_id,
                    "resumed": len(self.context.messages) > 1,
                },
            )

        messages = self.context.get_messages()

        system_prompt = self._build_system_prompt()
        if decomposition_hint:
            system_prompt += "\n\n" + decomposition_hint

        # Prune old messages to stay within context budget (Karpathy P6)
        self._maybe_prune_messages(messages)

        import time as _time

        self._loop_start_time = _time.monotonic()
        round_idx = 0
        while True:
            # Guard 1: Round limit (max_rounds > 0 enforces; 0 = unlimited)
            if self.max_rounds > 0 and round_idx >= self.max_rounds:
                break
            # Guard 2: Time budget (Karpathy P3)
            if self._time_budget_s > 0:
                elapsed = _time.monotonic() - self._loop_start_time
                if elapsed >= self._time_budget_s:
                    break

            is_last_round = (self.max_rounds > 0) and (round_idx == self.max_rounds - 1)
            self._op_logger.begin_round("AgenticLoop")

            # Model drift check: settings may have changed via switch_model tool
            # or /model command between rounds. Apply safely before next LLM call.
            #
            # v0.52.5 — _prompt_dirty also catches escalation paths
            # (`_try_model_escalation`, `_try_cross_provider_escalation`)
            # which call update_model() without going through the drift sync.
            # Without this, the system_prompt model card stays pinned to the
            # previous model after escalation.
            if self._sync_model_from_settings() or self._prompt_dirty:
                system_prompt = self._build_system_prompt()
                if decomposition_hint:
                    system_prompt += "\n\n" + decomposition_hint
                self._prompt_dirty = False

            # Poll for sub-agent announced results (OpenClaw Spawn+Announce)
            self._check_announced_results(messages)

            # Pre-call context check — proactive compress/prune (prevents 400)
            try:
                self._check_context_overflow(system_prompt, messages)
            except _ContextExhaustedError:
                log.warning("Pre-call context exhausted — attempting aggressive recovery")
                recovered = self._aggressive_context_recovery(system_prompt, messages)
                if recovered:
                    self._notify_context_event(
                        "prune",
                        original_count=len(messages) + recovered,
                        new_count=len(messages),
                    )
                    log.info("Pre-call recovery succeeded — proceeding with pruned context")
                else:
                    self._notify_context_event(
                        "exhausted",
                        original_count=len(messages),
                        new_count=len(messages),
                    )
                    self._sync_messages_to_context(messages)
                    result = AgenticResult(
                        text=_context_exhausted_message(user_input),
                        tool_calls=self._tool_processor.tool_log,
                        rounds=round_idx + 1,
                        error="context_exhausted",
                        termination_reason="context_exhausted",
                    )
                    return self._finalize_and_return(result, user_input, round_idx + 1)

            # Show spinner while waiting for LLM response
            # IPC mode: send structured event; direct mode: TextSpinner
            from core.ui.agentic_ui import _ipc_writer_local

            _ipc_writer = getattr(_ipc_writer_local, "writer", None)
            if _ipc_writer is not None and not self._quiet:
                _ipc_writer.send_event("thinking_start", model=self.model, round=round_idx + 1)
                _spinner = TextSpinner("", quiet=True)  # no-op spinner
            else:
                label = "Thinking..." if round_idx == 0 else f"Thinking... (round {round_idx + 1})"
                _spinner = TextSpinner(f"✢ {label}", quiet=self._quiet)
            _spinner.start()
            try:
                response = await self._call_llm(system_prompt, messages, round_idx=round_idx)
            except BillingError as exc:
                _spinner.stop()
                self._emit_quota_panel(exc)
                return AgenticResult(
                    text=exc.user_message(),
                    rounds=round_idx + 1,
                    termination_reason="billing_error",
                )
            except UserCancelledError:
                _spinner.stop()
                log.info("LLM call interrupted by user")
                return AgenticResult(
                    text="Interrupted.",
                    rounds=round_idx + 1,
                    termination_reason="user_cancelled",
                )
            except _ContextExhaustedError as exc:
                _spinner.stop()
                log.warning("Context exhausted: %s — attempting aggressive recovery", exc)

                # Aggressive recovery: prune harder + summarize tool results
                recovered = self._aggressive_context_recovery(system_prompt, messages)
                if recovered:
                    self._notify_context_event(
                        "prune",
                        original_count=len(messages) + recovered,
                        new_count=len(messages),
                    )
                    log.info("Aggressive recovery succeeded — continuing loop")
                    continue  # retry LLM call with pruned context

                # Recovery failed — break loop
                self._notify_context_event(
                    "exhausted",
                    original_count=len(messages),
                    new_count=len(messages),
                )
                self._sync_messages_to_context(messages)
                result = AgenticResult(
                    text=_context_exhausted_message(user_input),
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    error="context_exhausted",
                    termination_reason="context_exhausted",
                )
                return self._finalize_and_return(
                    result,
                    user_input,
                    round_idx + 1,
                )
            finally:
                _spinner.stop()
                if _ipc_writer is not None and not self._quiet:
                    _ipc_writer.send_event("thinking_end")

            if response is None:
                # Classify error for type-specific retry strategy
                adapter_exc = getattr(self._adapter, "last_error", None)
                _et = "unknown"
                if adapter_exc is not None:
                    from core.llm.errors import classify_llm_error

                    _et, _sev, _hint = classify_llm_error(adapter_exc)

                    # Context overflow from 400 → attempt recovery + retry
                    if _et == "context_overflow":
                        log.warning("Context overflow detected from 400 — attempting recovery")
                        recovered = self._aggressive_context_recovery(system_prompt, messages)
                        if recovered:
                            self._notify_context_event(
                                "prune",
                                original_count=len(messages) + recovered,
                                new_count=len(messages),
                            )
                            log.info("Context overflow recovery succeeded — retrying LLM call")
                            continue  # retry with pruned context
                        # Recovery failed — context is unrecoverably large
                        self._notify_context_event(
                            "exhausted",
                            original_count=len(messages),
                            new_count=len(messages),
                        )
                        self._sync_messages_to_context(messages)
                        result = AgenticResult(
                            text=_context_exhausted_message(user_input),
                            tool_calls=self._tool_processor.tool_log,
                            rounds=round_idx + 1,
                            error="context_exhausted",
                            termination_reason="context_exhausted",
                        )
                        return self._finalize_and_return(result, user_input, round_idx + 1)

                    # Auth errors → try cross-provider escalation before giving up.
                    # Expired keys affect all models in the same provider chain,
                    # so skip intra-provider fallback and go straight to cross-provider.
                    if _et == "auth":
                        if not self._quiet:
                            from core.ui.agentic_ui import emit_llm_error

                            emit_llm_error(_et, _sev, _hint, self.model, self._provider)
                        # v0.51.0: inject LLM-readable credential breadcrumb so
                        # the next round sees structured eligibility verdicts
                        # (Claude Code createModelSwitchBreadcrumbs pattern).
                        self._inject_credential_breadcrumb()
                        old_model = self.model
                        escalated = self._try_cross_provider_escalation()
                        if escalated:
                            from core.ui.agentic_ui import emit_model_escalation

                            emit_model_escalation(
                                old_model, self.model, self._consecutive_llm_failures
                            )
                            self._consecutive_llm_failures = 0
                            messages[:] = self.context.messages
                            continue
                        # No cross-provider fallback available — exit
                        detail = self._last_llm_error or str(adapter_exc)
                        result = AgenticResult(
                            text=f"LLM call failed ({detail}).",
                            rounds=round_idx + 1,
                            error="llm_call_failed",
                            termination_reason="llm_error",
                        )
                        return self._finalize_and_return(result, user_input, round_idx + 1)

                    # Non-retryable errors → immediate exit (no retry budget waste)
                    if _et == "bad_request":
                        if not self._quiet:
                            from core.ui.agentic_ui import emit_llm_error

                            emit_llm_error(_et, _sev, _hint, self.model, self._provider)
                        detail = self._last_llm_error or str(adapter_exc)
                        result = AgenticResult(
                            text=f"LLM call failed ({detail}).",
                            rounds=round_idx + 1,
                            error="llm_call_failed",
                            termination_reason="llm_error",
                        )
                        return self._finalize_and_return(result, user_input, round_idx + 1)

                    if not self._quiet:
                        from core.ui.agentic_ui import emit_llm_error

                        emit_llm_error(
                            _et,
                            _sev,
                            _hint,
                            self.model,
                            self._provider,
                            attempt=self._consecutive_llm_failures + 1,
                        )

                    if self._hooks:
                        self._hooks.trigger(
                            HookEvent.LLM_CALL_FAILED,
                            {
                                "model": self.model,
                                "provider": self._provider,
                                "error_type": _et,
                                "severity": _sev,
                                "attempt": self._consecutive_llm_failures + 1,
                            },
                        )

                # Auto-checkpoint before escalation/retry so user can resume
                self._sync_messages_to_context(messages)
                self._save_checkpoint(user_input, round_idx=round_idx)

                self._consecutive_llm_failures += 1

                # Rate limit → immediate model escalation (different model = different quota)
                if _et == "rate_limit":
                    old_model = self.model
                    escalated = self._try_model_escalation()
                    if escalated:
                        from core.ui.agentic_ui import emit_model_escalation

                        emit_model_escalation(old_model, self.model, self._consecutive_llm_failures)
                        self._consecutive_llm_failures = 0
                        messages[:] = self.context.messages  # re-sync adapted context
                        continue

                # Non-rate-limit errors: compact context + same model retry first,
                # model switch only as last resort (downgrade loses quality).
                if self._consecutive_llm_failures >= self._ESCALATION_THRESHOLD:
                    recovered = self._aggressive_context_recovery(system_prompt, messages)
                    if recovered:
                        self._notify_context_event(
                            "prune",
                            original_count=len(messages) + recovered,
                            new_count=len(messages),
                        )
                        log.info(
                            "Context compacted after %d failures — retrying same model (%s)",
                            self._consecutive_llm_failures,
                            self.model,
                        )
                        self._consecutive_llm_failures = 0
                        continue

                    # Context compaction failed — model switch as last resort
                    old_model = self.model
                    escalated = self._try_model_escalation()
                    if escalated:
                        from core.ui.agentic_ui import emit_model_escalation

                        emit_model_escalation(old_model, self.model, self._consecutive_llm_failures)
                        log.info(
                            "Context compaction insufficient, model escalated: %s → %s",
                            old_model,
                            self.model,
                        )
                        self._consecutive_llm_failures = 0
                        messages[:] = self.context.messages  # re-sync adapted context
                        continue

                # Below retry cap: backoff and retry (don't break the loop)
                if self._consecutive_llm_failures < self._LLM_RETRY_CAP:
                    import asyncio as _asyncio

                    delay = min(2**self._consecutive_llm_failures, 30)
                    log.info(
                        "LLM call failed (%s) — retrying in %ds (attempt %d/%d)",
                        _et,
                        delay,
                        self._consecutive_llm_failures,
                        self._LLM_RETRY_CAP,
                    )
                    if not self._quiet:
                        from core.ui.agentic_ui import emit_llm_retry

                        emit_llm_retry(
                            delay,
                            self._consecutive_llm_failures,
                            self._LLM_RETRY_CAP,
                        )
                    if self._hooks:
                        self._hooks.trigger(
                            HookEvent.LLM_CALL_RETRY,
                            {
                                "model": self.model,
                                "provider": self._provider,
                                "error_type": _et,
                                "delay_s": delay,
                                "attempt": self._consecutive_llm_failures,
                                "max_attempts": self._LLM_RETRY_CAP,
                            },
                        )
                    await _asyncio.sleep(delay)
                    continue  # retry without incrementing round_idx

                # All retries exhausted — surface error
                detail = self._last_llm_error or "unknown error"
                text = (
                    f"LLM call failed ({detail}). "
                    "Your conversation context is preserved — try again."
                )
                result = AgenticResult(
                    text=text,
                    rounds=round_idx + 1,
                    error="llm_call_failed",
                    termination_reason="retry_exhausted",
                )
                return self._finalize_and_return(result, user_input, round_idx + 1)

            # Successful LLM response — reset failure counter
            self._consecutive_llm_failures = 0

            # Track usage + Claude Code-style token display
            self._track_usage(response)

            # Guard 3: Cost budget (Karpathy P3 — resource budget)
            if self._cost_budget > 0:
                try:
                    from core.llm.token_tracker import get_tracker as _get_cost_tracker

                    _cost_tracker = _get_cost_tracker()
                    _session_cost = _cost_tracker.accumulator.total_cost_usd

                    # Proactive warning at 80% of budget (once per session)
                    _warn_threshold = self._cost_budget * 0.8
                    if (
                        _session_cost >= _warn_threshold
                        and _session_cost < self._cost_budget
                        and not getattr(self, "_budget_warned", False)
                    ):
                        self._budget_warned = True
                        if not self._quiet:
                            from core.ui.agentic_ui import emit_budget_warning

                            emit_budget_warning(
                                self._cost_budget,
                                _session_cost,
                                pct=_session_cost / self._cost_budget * 100,
                            )

                    if _session_cost >= self._cost_budget:
                        from core.ui.agentic_ui import emit_cost_budget_exceeded

                        emit_cost_budget_exceeded(self._cost_budget, _session_cost)
                        self._op_logger.finalize()
                        self._sync_messages_to_context(messages)
                        text = (
                            f"Cost budget (${self._cost_budget:.2f}) exceeded. "
                            f"Session cost: ${_session_cost:.2f}"
                        )
                        log.warning(text)
                        result = AgenticResult(
                            text=text,
                            tool_calls=self._tool_processor.tool_log,
                            rounds=round_idx + 1,
                            error="cost_budget_exceeded",
                            termination_reason="cost_budget_exceeded",
                        )
                        return self._finalize_and_return(result, user_input, round_idx + 1)
                except Exception:
                    log.debug("Cost budget check failed", exc_info=True)

            # Adaptive compute: overthinking detection (DTR insight)
            # Consecutive rounds with long text but no tool calls = overthinking signal
            if response.stop_reason != "tool_use":
                out_tok = getattr(response.usage, "output_tokens", 0) if response.usage else 0
                if out_tok > 2000:
                    self._consecutive_text_only_rounds += 1
                else:
                    self._consecutive_text_only_rounds = 0
                if self._consecutive_text_only_rounds >= 2:
                    # Count this round once (the running consec is reported in the warning).
                    # Previous code added the running counter every round, inflating the total
                    # quadratically (consec=2,3,4 → +2+3+4=9 instead of 3 actual flagged rounds).
                    self._total_empty_rounds += 1
                    log.warning(
                        "Overthinking detected: %d consecutive text-only rounds (>2000 tok each)",
                        self._consecutive_text_only_rounds,
                    )
            else:
                self._consecutive_text_only_rounds = 0

            if response.stop_reason != "tool_use":
                # end_turn or max_tokens → extract text, done
                self._op_logger.finalize()
                text = self._extract_text(response)
                # Sync all intermediate tool-use messages + final response to context
                assistant_content = self._serialize_content(response.content)
                _assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_content,
                }
                # v0.55.0 — Codex Plus encrypted reasoning passthrough.
                # Sidecar stays on the assistant message and is consumed
                # by ``_convert_messages_to_responses`` (Codex adapter)
                # to echo the reasoning items back into the next-turn
                # ``input`` array. Other adapters ignore the field.
                if getattr(response, "codex_reasoning_items", None):
                    _assistant_msg["codex_reasoning_items"] = response.codex_reasoning_items
                messages.append(_assistant_msg)
                self._sync_messages_to_context(messages)
                reason = "forced_text" if is_last_round else "natural"
                result = AgenticResult(
                    text=text,
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    termination_reason=reason,
                )
                return self._finalize_and_return(result, user_input, round_idx + 1)

            tool_results = await self._tool_processor.process(response)

            # Feature 5: Backpressure on consecutive tool failures
            # Feature 6: Convergence detection (stuck loop)
            self._update_tool_error_tracking(tool_results)

            if self._check_convergence_break():
                from core.ui.agentic_ui import emit_convergence_detected

                last_err = (
                    self._convergence.recent_errors[-1]
                    if self._convergence.recent_errors
                    else "unknown"
                )
                emit_convergence_detected(last_err, round_idx + 1)
                self._op_logger.finalize()
                self._sync_messages_to_context(messages)
                result = AgenticResult(
                    text=(
                        "Detected repeating failure pattern. Breaking loop to avoid infinite retry."
                    ),
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    error="convergence_detected",
                    termination_reason="convergence_detected",
                )
                return self._finalize_and_return(result, user_input, round_idx + 1)

            if self._convergence.total_consecutive_tool_errors >= 3:
                # Backpressure: inject a cooldown hint
                from core.ui.agentic_ui import emit_tool_backpressure

                emit_tool_backpressure(self._convergence.total_consecutive_tool_errors)
                await asyncio.sleep(1.0)
                backpressure_hint = {
                    "type": "text",
                    "text": (
                        "[system] Multiple tools are failing consecutively. "
                        "Consider a different approach. "
                        "If you cannot verify the answer through tools, "
                        "tell the user what failed and what remains unverified. "
                        "Do NOT silently answer from training data."
                    ),
                }
                tool_results.append(backpressure_hint)

            # Feature 8: Diversity forcing — prevent same tool 5x consecutively
            # Read/search tools are naturally repetitive — exempt from diversity forcing
            _DIVERSITY_EXEMPT: frozenset[str] = frozenset(
                {
                    "read_file",
                    "read_text_file",
                    "search_files",
                    "list_directory",
                    "memory_search",
                    "note_read",
                    "web_search",
                    "general_web_search",
                    "sequentialthinking",
                }
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    self._consecutive_tool_tracker.append(getattr(block, "name", ""))
            if len(self._consecutive_tool_tracker) > 10:
                self._consecutive_tool_tracker = self._consecutive_tool_tracker[-10:]
            if len(self._consecutive_tool_tracker) >= 5:
                _last_5 = self._consecutive_tool_tracker[-5:]
                if len(set(_last_5)) == 1:
                    _repeated_tool = _last_5[0]
                    if _repeated_tool in _DIVERSITY_EXEMPT:
                        self._consecutive_tool_tracker.clear()
                    else:
                        diversity_hint = {
                            "type": "text",
                            "text": (
                                f"[system] The tool '{_repeated_tool}' has been called 5 times "
                                "consecutively with similar results. "
                                "Try a different approach or tool to make progress."
                            ),
                        }
                        tool_results.append(diversity_hint)
                        self._consecutive_tool_tracker.clear()

                        from core.ui.agentic_ui import emit_tool_diversity_forced

                        emit_tool_diversity_forced(_repeated_tool, 5)
                        log.warning(
                            "Diversity forcing: %s called 5x — injecting hint",
                            _repeated_tool,
                        )

            # Accumulate messages for next round
            # Convert content blocks to serializable format
            assistant_content = self._serialize_content(response.content)
            _assistant_msg = {"role": "assistant", "content": assistant_content}
            # v0.55.0 — Codex reasoning passthrough (see end_turn branch
            # above for the rationale; same shape on tool-use rounds).
            if getattr(response, "codex_reasoning_items", None):
                _assistant_msg["codex_reasoning_items"] = response.codex_reasoning_items
            messages.append(_assistant_msg)
            messages.append({"role": "user", "content": tool_results})
            round_idx += 1

        # Loop exited via guard — determine reason
        self._op_logger.finalize()
        elapsed = _time.monotonic() - self._loop_start_time
        if self._time_budget_s > 0 and elapsed >= self._time_budget_s:
            from core.ui.agentic_ui import emit_time_budget_expired

            emit_time_budget_expired(self._time_budget_s, elapsed, round_idx)
            reason = "time_budget_expired"
            text = f"Time budget ({self._time_budget_s:.0f}s) expired after {round_idx} rounds."
        else:
            reason = "max_rounds"
            text = "Max agentic rounds reached. Please try a more specific request."
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            }
        )
        self._sync_messages_to_context(messages)
        result = AgenticResult(
            text=text,
            tool_calls=self._tool_processor.tool_log,
            rounds=round_idx,
            error=reason,
            termination_reason=reason,
        )
        return self._finalize_and_return(result, user_input, round_idx)

    # ------------------------------------------------------------------
    # Context window — delegate to ``_context``
    # ------------------------------------------------------------------

    def _sync_messages_to_context(self, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.sync_messages_to_context`."""
        return _context.sync_messages_to_context(self, messages)

    def _notify_context_event(
        self, event_type: str, *, original_count: int, new_count: int
    ) -> None:
        """Delegates to :func:`_context.notify_context_event`."""
        return _context.notify_context_event(
            self, event_type, original_count=original_count, new_count=new_count
        )

    def _maybe_prune_messages(self, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.maybe_prune_messages`."""
        return _context.maybe_prune_messages(self, messages)

    def _check_context_overflow(self, system: str, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.check_context_overflow`."""
        return _context.check_context_overflow(self, system, messages)

    def _aggressive_context_recovery(self, system: str, messages: list[dict[str, Any]]) -> int:
        """Delegates to :func:`_context.aggressive_context_recovery`."""
        return _context.aggressive_context_recovery(self, system, messages)

    @staticmethod
    def _repair_messages(messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.repair_messages`."""
        return _context.repair_messages(messages)

    def _build_system_prompt(self) -> str:
        """Delegates to :func:`_context.build_system_prompt`."""
        return _context.build_system_prompt(self)

    # ------------------------------------------------------------------
    # Goal decomposition — delegate to ``_decomposition``
    # ------------------------------------------------------------------

    def _try_decompose(self, user_input: str) -> str | None:
        """Delegates to :func:`_decomposition.try_decompose`."""
        return _decomposition.try_decompose(self, user_input)

    # ------------------------------------------------------------------
    # Sub-agent announce queue — delegate to ``_announce``
    # ------------------------------------------------------------------

    def _check_announced_results(self, messages: list[dict[str, Any]]) -> int:
        """Delegates to :func:`_announce.check_announced_results`."""
        return _announce.check_announced_results(self, messages)

    # ------------------------------------------------------------------
    # LLM call (stays in this file — tightly coupled to ``arun`` body)
    # ------------------------------------------------------------------

    @maybe_traceable(run_type="llm", name="AgenticLoop._call_llm")  # type: ignore[untyped-decorator]
    async def _call_llm(
        self, system: str, messages: list[dict[str, Any]], *, round_idx: int = 0
    ) -> AgenticResponse | None:
        """Multi-provider LLM call via adapter (P1 Gateway pattern).

        Delegates to ``self._adapter.agentic_call()`` which handles
        provider-specific message/tool conversion, retry, and failover.
        Returns a normalized ``AgenticResponse`` or None on failure.
        Raises ``UserCancelledError`` on Ctrl+C (caught by ``arun()``).
        """
        # Sandwich injection: prepend system reminder to messages (Claude Code pattern)
        from core.agent.system_injection import prepend_system_reminder

        prepend_system_reminder(messages, model=self.model, round_idx=round_idx)

        # Context overflow detection (Karpathy P6 Context Budget)
        self._check_context_overflow(system, messages)

        # WRAP_UP: force text-only when approaching limits
        force_text = False
        if self.max_rounds > 0:
            remaining = self.max_rounds - round_idx
            force_text = remaining <= self.WRAP_UP_HEADROOM
        if not force_text and self._time_budget_s > 0:
            import time as _time

            remaining_time = self._time_budget_s - (_time.monotonic() - self._loop_start_time)
            force_text = remaining_time <= self._WRAP_UP_TIME_HEADROOM_S
        tool_choice: dict[str, str] = {"type": "none"} if force_text else {"type": "auto"}

        # Adaptive compute allocation (DTR insight: match budget to round purpose)
        # Context-proportional caps derived from model's context window
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        ctx_window = MODEL_CONTEXT_WINDOW.get(self.model, 200_000)
        # v0.56.0 R4-mini — ``xhigh`` added (Opus 4.7-only level per
        # platform.claude.com/docs/en/build-with-claude/effort).
        # Adapter version-gates: ``xhigh`` downgrades to ``"max"`` on
        # models that reject it (4.6 / Sonnet 4.6).
        _EFFORT_LEVELS = ["low", "medium", "high", "max", "xhigh"]

        adaptive_max_tokens = self.max_tokens
        adaptive_thinking = self._thinking_budget
        adaptive_effort = self._effort
        if force_text:
            # Wrap-up: minimal budget — summarize, don't reason
            # Context-proportional: 0.5% of window, floor 4096
            adaptive_max_tokens = max(4096, min(self.max_tokens, ctx_window // 200))
            adaptive_thinking = 0
            adaptive_effort = "low"
        elif self._consecutive_text_only_rounds >= 2:
            # Overthinking: reduce budget — curb verbose non-actionable output
            # Context-proportional: 2% of window, floor 8192
            adaptive_max_tokens = max(8192, min(self.max_tokens, ctx_window // 50))
            adaptive_thinking = max(0, adaptive_thinking // 2)
            # Downgrade effort by one level
            idx = _EFFORT_LEVELS.index(adaptive_effort) if adaptive_effort in _EFFORT_LEVELS else 2
            adaptive_effort = _EFFORT_LEVELS[max(0, idx - 1)]

        response = await self._adapter.agentic_call(
            model=self.model,
            system=system,
            messages=messages,
            tools=self._tools,
            tool_choice=tool_choice,
            max_tokens=adaptive_max_tokens,
            temperature=0.0,
            thinking_budget=adaptive_thinking,
            effort=adaptive_effort,
        )

        if response is None:
            adapter_err = getattr(self._adapter, "last_error", None)
            if adapter_err:
                self._last_llm_error = str(adapter_err)
            else:
                self._last_llm_error = f"All {self._provider} models exhausted"

        # v0.57.0 R6 — surface reasoning summaries to AgenticUI. Per-item
        # granularity (the sidecar collects one entry per finished
        # reasoning item / thinking block) — see ``emit_reasoning_summary``
        # for the rationale on not streaming per-delta.
        if response is not None and not self._quiet:
            summaries = getattr(response, "reasoning_summaries", None) or []
            for summary in summaries:
                if not summary:
                    continue
                from core.ui.agentic_ui import emit_reasoning_summary

                emit_reasoning_summary(self._provider, self.model, summary)

        return response

    # ------------------------------------------------------------------
    # Response handling — delegate to ``_response``
    # ------------------------------------------------------------------

    def _extract_text(self, response: Any) -> str:
        """Delegates to :func:`_response.extract_text`."""
        return _response.extract_text(self, response)

    def _serialize_content(self, content: list[Any]) -> list[dict[str, Any]]:
        """Delegates to :func:`_response.serialize_content`."""
        return _response.serialize_content(self, content)

    def _track_usage(self, response: Any) -> None:
        """Delegates to :func:`_response.track_usage`."""
        return _response.track_usage(self, response)

    def _update_tool_error_tracking(self, tool_results: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_response.update_tool_error_tracking`."""
        return _response.update_tool_error_tracking(self, tool_results)

    def _check_convergence_break(self) -> bool:
        """Delegates to :func:`_response.check_convergence_break`."""
        return _response.check_convergence_break(self)


# ---------------------------------------------------------------------------
# Re-exports for ``from core.agent.loop.loop import …`` backward compat
# ---------------------------------------------------------------------------

__all__ = [
    "AGENTIC_TOOLS",
    "AgenticLoop",
    "AgenticResult",
    "_ContextExhaustedError",
    "_context_exhausted_message",
    "get_agentic_tools",
]
