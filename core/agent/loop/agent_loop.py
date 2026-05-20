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
    resolve_agentic_adapter,
)
from core.ui.agentic_ui import OperationLogger
from core.ui.status import TextSpinner

from . import _announce, _context, _decomposition, _lifecycle, _model_switching, _response

# Re-exported for backward-compat module-attribute access
# (some tests/utilities reach into ``core.agent.loop.MAX_TOOL_RESULT_TOKENS``)
from ._helpers import (
    AGENTIC_TOOLS,
    MAX_TOOL_RESULT_TOKENS,
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

    def __init__(  # noqa: PLR0913 — config knobs grow incrementally; refactor pending
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
        system_prompt_override: str | None = None,
        quiet: bool = False,
        disable_settings_drift: bool = False,
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self._parent_session_key = parent_session_key
        self._system_suffix = system_suffix
        # S2-wire (2026-05-18): when set, _build_system_prompt uses this
        # string as the entire role/instruction body, replacing the
        # default ``_build_system_prompt(model=loop.model)`` output.
        # Skill context + agentic suffix still appended (tool calling
        # contract preserved). Used by AgentDefinition-driven sub-agents
        # (``.claude/agents/seed_*.md``) so the seed_generator role's
        # full contract — not GEODE's generic system prompt — drives
        # the spawned worker.
        self._system_prompt_override = system_prompt_override
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
        # When True, ``sync_model_from_settings`` becomes a no-op so the
        # caller's chosen ``model`` is sticky for the lifetime of the
        # loop. Used by the petri_audit runner so a user-selected
        # ``--target`` is not silently replaced by the user's GEODE
        # ``settings.model`` between rounds.
        self._disable_settings_drift = disable_settings_drift
        # v0.52.5 — set by update_model_async() when model changes; consumed by
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

        # LLM-call retry budget. v0.90.0 — auto-escalation removed; once
        # the cap is hit the loop exits with ``model_action_required`` so
        # the user picks a different model via ``/model``.
        self._consecutive_llm_failures: int = 0
        self._LLM_RETRY_CAP: int = 5  # max retries before giving up

        # Context window management (extracted — SRP)
        from core.agent.context_manager import ContextWindowManager

        self._ctx_mgr = ContextWindowManager(hooks=hooks, quiet=quiet)

        # Convergence detection + tool error tracking (extracted — SRP).
        # v0.90.0 — ConvergenceDetector no longer takes an escalation_fn;
        # 3 identical errors break the loop and the caller surfaces a
        # ``model_action_required`` diagnostic.
        from core.agent.convergence import ConvergenceDetector

        self._convergence = ConvergenceDetector()

        # Feature 8: Diversity forcing — prevent same tool 5x consecutively
        self._consecutive_tool_tracker: list[str] = []

        # C3 checkpoint: full message persistence for /resume (Claude Code pattern)
        self._checkpoint: Any | None = None
        try:
            from core.runtime_state.session_checkpoint import SessionCheckpoint

            self._checkpoint = SessionCheckpoint()
        except Exception:
            log.warning("SessionCheckpoint init failed", exc_info=True)

        # PR-2 C-1 — explicit cognitive state container. ``goal`` is set on
        # the first ``arun()`` call (user input becomes the session goal);
        # ``round_count`` / ``last_action`` / ``last_observation`` /
        # ``observations`` are updated at each round end. Hypotheses +
        # confidence are PR-3 territory (the reflection node will populate
        # them). See ``core/agent/cognitive_state.py`` for the rationale.
        from core.agent.cognitive_state import CognitiveState

        self.cognitive_state = CognitiveState()

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

    async def _afinalize_and_return(
        self,
        result: AgenticResult,
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Delegates to :func:`_lifecycle.finalize_and_return_async`."""
        return await _lifecycle.finalize_and_return_async(self, result, user_input, round_idx)

    def _build_reasoning_metrics(self, result: AgenticResult) -> Any:
        """Delegates to :func:`_lifecycle.build_reasoning_metrics`."""
        return _lifecycle.build_reasoning_metrics(self, result)

    def _emit_quota_panel(self, exc: BillingError) -> None:
        """Delegates to :func:`_lifecycle.emit_quota_panel`."""
        return _lifecycle.emit_quota_panel(self, exc)

    def _inject_credential_breadcrumb(self) -> None:
        """Delegates to :func:`_lifecycle.inject_credential_breadcrumb`."""
        return _lifecycle.inject_credential_breadcrumb(self)

    async def _emit_cognitive(self, event: HookEvent, **payload: Any) -> None:
        """PR-2 C-6 — emit a cognitive-cycle event with the state
        snapshot attached.

        Centralises the (a) hook-system None-guard, (b) session_id
        injection, (c) ``cognitive_state`` snapshot embedding so each
        call site stays a one-liner and ``arun`` doesn't balloon past
        the ruff complexity gates.
        """
        if not self._hooks:
            return
        await self._hooks.trigger_async(
            event,
            {
                "session_id": self._session_id,
                "cognitive_state": self.cognitive_state.to_snapshot(),
                **payload,
            },
        )

    async def _record_text_only_round(self, round_idx: int, *, text: str) -> None:
        """PR-2 C-6 — record round end + emit REFLECT/UPDATE_MEMORY for
        text-only completions (``stop_reason != "tool_use"``).

        Codex MCP review #1 catch — without this, ``record_round`` only
        ran on tool-use rounds, violating the conditional-read-parity
        rule. ACT/OBSERVE are intentionally NOT emitted here: the loop
        took no action and observed no tool result this round, so the
        cognitive cycle on a text-only turn is PERCEIVE → PLAN →
        REFLECT (the LLM "thought aloud" then ended the turn).
        ``last_action`` is recorded as ``"text-only"`` and
        ``last_observation`` as a 80-char head of the emitted text so
        downstream readers can distinguish *no-action* turns from
        *failed-tool* turns.
        """
        head = text.strip().replace("\n", " ")
        if len(head) > 80:
            head = head[:80] + "…"
        self.cognitive_state.record_round(
            action="text-only",
            observation=head or "(empty text)",
        )
        await self._emit_cognitive(HookEvent.COGNITIVE_REFLECT, round=round_idx + 1)
        await self._emit_cognitive(
            HookEvent.COGNITIVE_UPDATE_MEMORY, round=round_idx + 1
        )

    async def _run_cognitive_act_observe_cycle(
        self, response: Any, round_idx: int
    ) -> list[dict[str, Any]]:
        """PR-2 C-6 — emit ACT before the tool batch, run the batch,
        emit OBSERVE after, update :attr:`cognitive_state` round-end
        fields, emit REFLECT + UPDATE_MEMORY.

        Extracted from ``arun`` to keep the run-loop within the ruff
        complexity gates while preserving the cognitive-cycle event
        ordering (PERCEIVE -> PLAN -> ACT -> OBSERVE -> REFLECT ->
        UPDATE_MEMORY).
        """
        tool_names: list[str] = []
        for block in getattr(response, "content", None) or []:
            if getattr(block, "type", None) == "tool_use":
                tool_names.append(getattr(block, "name", "unknown"))

        await self._emit_cognitive(
            HookEvent.COGNITIVE_ACT,
            round=round_idx + 1,
            tool_names=tool_names,
        )

        tool_results = await self._tool_processor.process(response)

        await self._emit_cognitive(
            HookEvent.COGNITIVE_OBSERVE,
            round=round_idx + 1,
            tool_names=tool_names,
            result_count=len(tool_results),
        )

        # Deterministic round-end state update. Action = tool names (or
        # "text-only"); observation = result-count summary. PR-3
        # replaces the deterministic summary with an LLM-derived
        # belief update from the reflection node.
        self.cognitive_state.record_round(
            action=("tools: " + ", ".join(tool_names)) if tool_names else "text-only",
            observation=f"{len(tool_results)} tool result(s)",
        )

        await self._emit_cognitive(HookEvent.COGNITIVE_REFLECT, round=round_idx + 1)
        await self._emit_cognitive(
            HookEvent.COGNITIVE_UPDATE_MEMORY, round=round_idx + 1
        )

        return tool_results

    def _overthinking_token_threshold(self) -> int:
        """Per-round output-token threshold for the overthinking signal.

        Context-proportional (1% of context window, floor 1024). Replaces
        the legacy absolute 2000-token magic number so the threshold
        scales with the model: 200K → 2000 (parity), 1M → 10000, 64K → 1024.
        Mirrors the wrap-up (0.5%) and overthinking-budget (2%) ratios
        used elsewhere in this file.

        Defensive: if the token-tracker module is mocked or the lookup
        otherwise fails (some tests stub ``sys.modules`` for a different
        purpose), fall back to the legacy 2000-token threshold so the
        loop still makes a deterministic decision.
        """
        try:
            from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

            ctx_window = MODEL_CONTEXT_WINDOW.get(self.model, 200_000)
            return max(1024, int(ctx_window) // 100)
        except (TypeError, ValueError, AttributeError):
            return 2000

    def _build_model_action_result(
        self,
        *,
        error_type: str,
        severity: str,
        hint: str,
        rounds: int,
        detail: str | None = None,
    ) -> AgenticResult:
        """Build an ``AgenticResult`` carrying a user-facing diagnostic.

        Used when an LLM error survives the retry budget (or convergence
        breaks). Replaces the prior auto-escalation path: rather than
        silently swap to the next model, surface enough context for the
        user to pick one with ``/model``.
        """
        from core.llm.errors import build_model_action_message

        cost: float | None = None
        try:
            from core.llm.token_tracker import get_tracker

            cost = float(get_tracker().accumulator.total_cost_usd)
        except Exception:
            cost = None
        text = build_model_action_message(
            error_type=error_type,
            severity=severity,
            hint=hint,
            model=self.model,
            provider=self._provider,
            attempts=self._consecutive_llm_failures,
            cost_so_far_usd=cost,
            suggested_models=self._fallback_chain_suggestions() or None,
            detail=detail,
        )
        return AgenticResult(
            text=text,
            tool_calls=self._tool_processor.tool_log,
            rounds=rounds,
            error="model_action_required",
            termination_reason="model_action_required",
        )

    # ------------------------------------------------------------------
    # Tool list refresh — delegate to ``_response``
    # ------------------------------------------------------------------

    def refresh_tools(self) -> int:
        """Delegates to :func:`_response.refresh_tools`."""
        return _response.refresh_tools(self)

    # ------------------------------------------------------------------
    # Model switching / escalation — delegate to ``_model_switching``
    # ------------------------------------------------------------------

    async def _sync_model_from_settings_async(self) -> bool:
        """Async drift sync used by ``arun``."""
        return await _model_switching.sync_model_from_settings_async(self)

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

    async def update_model_async(
        self,
        model: str,
        provider: str | None = None,
        reason: str = "user_switch",
    ) -> None:
        """Delegates to :func:`_model_switching.update_model_async`."""
        return await _model_switching.update_model_async(self, model, provider, reason)

    def _purge_stale_model_switch_acks(self) -> None:
        """Delegates to :func:`_model_switching.purge_stale_model_switch_acks`."""
        return _model_switching.purge_stale_model_switch_acks(self)

    def _adapt_context_for_model(self, target_model: str) -> None:
        """Delegates to :func:`_model_switching.adapt_context_for_model`."""
        return _model_switching.adapt_context_for_model(self, target_model)

    def _fallback_chain_suggestions(self) -> list[str]:
        """Remaining models in the current adapter's chain — for diagnostics."""
        return _model_switching.fallback_chain_suggestions(self)

    # ------------------------------------------------------------------
    # Run loop entry points
    # ------------------------------------------------------------------

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
            intercept = await self._hooks.trigger_interceptor_async(
                HookEvent.USER_INPUT_RECEIVED,
                {"user_input": user_input, "session_id": self._session_id},
            )
            if intercept.blocked:
                return AgenticResult(
                    text=intercept.reason, rounds=0, termination_reason="input_blocked"
                )

        # PR-2 C-1 + C-6 — set the cognitive-state goal to the user input
        # of the first arun() call (subsequent calls in the same session
        # keep the original goal so observations accumulate against it).
        # Then fire PERCEIVE with the state snapshot so a downstream
        # viewer can segment the session by cognitive cycle step.
        if not self.cognitive_state.goal:
            self.cognitive_state.goal = user_input
        await self._emit_cognitive(
            HookEvent.COGNITIVE_PERCEIVE,
            user_input=user_input,
        )

        # Add user message to conversation context
        self.context.add_user_message(user_input)

        # Transcript: session start + user message
        if self._transcript is not None:
            self._transcript.record_session_start(model=self.model, provider=self._provider)
            self._transcript.record_user_message(user_input)

        # Hook: SESSION_START
        if self._hooks:
            await self._hooks.trigger_async(
                HookEvent.SESSION_STARTED,
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
        # Defect A F-A1 — capture tracker snapshot at the loop entry so
        # ``finalize_and_return`` can compute a per-arun usage delta
        # without double-counting calls from sibling loops sharing the
        # same ``ContextVar``-scoped tracker. See ``AgenticResult.usage``.
        from core.llm.token_tracker import get_tracker as _get_tracker

        self._usage_snapshot = _get_tracker().snapshot()
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
            # v0.52.5 — _prompt_dirty catches any direct ``update_model`` call
            # that bypasses the drift sync; without it the system_prompt model
            # card would stay pinned to the previous model after a switch.
            # v0.90.0 — auto-escalation paths were removed; the only such
            # callers now are user-initiated /model switches.
            if await self._sync_model_from_settings_async() or self._prompt_dirty:
                system_prompt = self._build_system_prompt()
                if decomposition_hint:
                    system_prompt += "\n\n" + decomposition_hint
                self._prompt_dirty = False

            # Poll for sub-agent announced results (OpenClaw Spawn+Announce)
            self._check_announced_results(messages)

            # Pre-call context check — proactive compress/prune (prevents 400)
            try:
                await self._check_context_overflow(system_prompt, messages)
            except _ContextExhaustedError:
                log.warning("Pre-call context exhausted — attempting aggressive recovery")
                recovered = await self._aggressive_context_recovery(system_prompt, messages)
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
                    return await self._afinalize_and_return(result, user_input, round_idx + 1)

            # PR-2 C-6 — pre-LLM-call PLAN event. See ``_emit_cognitive``.
            await self._emit_cognitive(
                HookEvent.COGNITIVE_PLAN,
                round=round_idx + 1,
                model=self.model,
            )

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
                recovered = await self._aggressive_context_recovery(system_prompt, messages)
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
                return await self._afinalize_and_return(
                    result,
                    user_input,
                    round_idx + 1,
                )
            finally:
                _spinner.stop()
                if _ipc_writer is not None and not self._quiet:
                    _ipc_writer.send_event("thinking_end")

            if response is None:
                # Classify error for type-specific retry strategy.
                # Defaults cover the case where the adapter swallowed the
                # original exception (None response without a trailing
                # ``last_error``); the diagnostic builder still needs
                # ``_sev`` / ``_hint`` populated.
                adapter_exc = getattr(self._adapter, "last_error", None)
                from core.llm.errors import _ERROR_CLASSIFICATION

                _et, _sev, _hint = _ERROR_CLASSIFICATION["unknown"]
                if adapter_exc is not None:
                    from core.llm.errors import classify_llm_error

                    _et, _sev, _hint = classify_llm_error(adapter_exc)

                    # Context overflow from 400 → attempt recovery + retry
                    if _et == "context_overflow":
                        log.warning("Context overflow detected from 400 — attempting recovery")
                        recovered = await self._aggressive_context_recovery(system_prompt, messages)
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
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)

                    # Auth errors → surface to user; auto-swap was removed
                    # in v0.90.0 (cross-provider stub already in place since
                    # v0.53.0). Credentials are user-owned, so let the user
                    # refresh keys or pick a different provider via /model.
                    if _et == "auth":
                        if not self._quiet:
                            from core.ui.agentic_ui import emit_llm_error

                            emit_llm_error(_et, _sev, _hint, self.model, self._provider)
                        # v0.51.0: inject LLM-readable credential breadcrumb so
                        # the next round sees structured eligibility verdicts
                        # (Claude Code createModelSwitchBreadcrumbs pattern).
                        self._inject_credential_breadcrumb()
                        result = self._build_model_action_result(
                            error_type=_et,
                            severity=_sev,
                            hint=_hint,
                            rounds=round_idx + 1,
                            detail=self._last_llm_error or str(adapter_exc),
                        )
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)

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
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)

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
                        await self._hooks.trigger_async(
                            HookEvent.LLM_CALL_FAILED,
                            {
                                "model": self.model,
                                "provider": self._provider,
                                "error_type": _et,
                                "severity": _sev,
                                "attempt": self._consecutive_llm_failures + 1,
                            },
                        )

                # Auto-checkpoint before retry so user can resume after a
                # model switch. v0.90.0 — auto-escalation removed; the loop
                # only ever retries the same model now.
                self._sync_messages_to_context(messages)
                self._save_checkpoint(user_input, round_idx=round_idx)

                self._consecutive_llm_failures += 1

                # Rate limit → surface to user. We no longer auto-swap to a
                # different model on rate_limit (silent provider/model
                # change masks cost surprise). Wait, switch model via
                # /model, or pick a different provider — the diagnostic
                # carries the suggested fallback chain.
                if _et == "rate_limit":
                    result = self._build_model_action_result(
                        error_type=_et,
                        severity=_sev,
                        hint=_hint,
                        rounds=round_idx + 1,
                        detail=self._last_llm_error or str(adapter_exc),
                    )
                    return await self._afinalize_and_return(result, user_input, round_idx + 1)

                # Non-rate-limit errors: try aggressive context recovery
                # before retrying the same model. If recovery helps, reset
                # the failure counter and continue. Otherwise keep retrying
                # the same model; once we hit ``_LLM_RETRY_CAP`` the
                # bottom-of-loop branch surfaces a model_action_required
                # diagnostic.
                if self._consecutive_llm_failures >= 2:
                    recovered = await self._aggressive_context_recovery(system_prompt, messages)
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
                        await self._hooks.trigger_async(
                            HookEvent.LLM_CALL_RETRIED,
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

                # All retries exhausted — surface as model_action_required.
                # The diagnostic carries provider/model/attempts/cost +
                # suggested fallback so the user can switch via /model
                # and resume (conversation context is preserved).
                detail = self._last_llm_error or "unknown error"
                result = self._build_model_action_result(
                    error_type=_et,
                    severity=_sev,
                    hint=_hint,
                    rounds=round_idx + 1,
                    detail=detail,
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

            # Successful LLM response — reset failure counter
            self._consecutive_llm_failures = 0

            # Track usage + Claude Code-style token display
            await self._track_usage_async(response)

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
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)
                except Exception:
                    log.debug("Cost budget check failed", exc_info=True)

            # Adaptive compute: overthinking detection (DTR insight).
            # Consecutive rounds with long text but no tool calls = the
            # model is talking to itself. v0.90.0 — when the threshold is
            # crossed we no longer just log a warning and downgrade
            # silently; we stop the loop and ask the user to narrow the
            # request (``user_clarification_needed``).
            #
            # Threshold is context-window proportional (1%, floor 1024)
            # — matches the 0.5% wrap-up budget / 2% overthinking-budget
            # ratios used elsewhere in this file. Replaces the prior
            # absolute 2000-token magic number, which mis-calibrated for
            # both small-context (64K) and 1M-context models.
            if response.stop_reason != "tool_use":
                out_tok = getattr(response.usage, "output_tokens", 0) if response.usage else 0
                threshold = self._overthinking_token_threshold()
                if out_tok > threshold:
                    self._consecutive_text_only_rounds += 1
                else:
                    self._consecutive_text_only_rounds = 0
                if self._consecutive_text_only_rounds >= 2:
                    # Count this round once (the running consec is reported in the warning).
                    # Previous code added the running counter every round, inflating the total
                    # quadratically (consec=2,3,4 → +2+3+4=9 instead of 3 actual flagged rounds).
                    self._total_empty_rounds += 1
                    log.warning(
                        "Overthinking detected: %d consecutive text-only rounds "
                        "(>%d tok each) — surfacing user_clarification_needed",
                        self._consecutive_text_only_rounds,
                        threshold,
                    )
                    self._op_logger.finalize()
                    self._sync_messages_to_context(messages)
                    last_text = self._extract_text(response).strip()
                    summary = last_text[:400] + ("…" if len(last_text) > 400 else "")
                    clarification = (
                        f"~ I've spent {self._consecutive_text_only_rounds} consecutive "
                        f"rounds reasoning without taking any action "
                        f"(>{threshold} output tokens each). "
                        "Could you narrow the request — point at a specific file, "
                        "behaviour, or step you want me to focus on next?\n\n"
                        f"Most recent reasoning (truncated):\n{summary}"
                    )
                    await self._record_text_only_round(round_idx, text=last_text)
                    result = AgenticResult(
                        text=clarification,
                        tool_calls=self._tool_processor.tool_log,
                        rounds=round_idx + 1,
                        termination_reason="user_clarification_needed",
                    )
                    return await self._afinalize_and_return(result, user_input, round_idx + 1)
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
                await self._record_text_only_round(round_idx, text=text)
                reason = "forced_text" if is_last_round else "natural"
                result = AgenticResult(
                    text=text,
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    termination_reason=reason,
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

            tool_results = await self._run_cognitive_act_observe_cycle(
                response, round_idx
            )

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
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

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
        return await self._afinalize_and_return(result, user_input, round_idx)

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

    async def _check_context_overflow(self, system: str, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.check_context_overflow`."""
        return await _context.check_context_overflow(self, system, messages)

    async def _aggressive_context_recovery(
        self, system: str, messages: list[dict[str, Any]]
    ) -> int:
        """Delegates to :func:`_context.aggressive_context_recovery`."""
        return await _context.aggressive_context_recovery(self, system, messages)

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
        await self._check_context_overflow(system, messages)

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

        # Adaptive compute allocation (DTR insight: match budget to round purpose).
        # Context-proportional caps derived from model's context window.
        # v0.90.0 — the prior overthinking effort-downgrade branch is gone:
        # the post-response check now exits the loop on the same condition,
        # so the only remaining adaptive case is wrap-up.
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        ctx_window = MODEL_CONTEXT_WINDOW.get(self.model, 200_000)

        adaptive_max_tokens = self.max_tokens
        adaptive_thinking = self._thinking_budget
        adaptive_effort = self._effort
        if force_text:
            # Wrap-up: minimal budget — summarize, don't reason
            # Context-proportional: 0.5% of window, floor 4096
            adaptive_max_tokens = max(4096, min(self.max_tokens, ctx_window // 200))
            adaptive_thinking = 0
            adaptive_effort = "low"

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

    async def _track_usage_async(self, response: Any) -> None:
        """Delegates to :func:`_response.track_usage_async`."""
        return await _response.track_usage_async(self, response)

    def _update_tool_error_tracking(self, tool_results: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_response.update_tool_error_tracking`."""
        return _response.update_tool_error_tracking(self, tool_results)

    def _check_convergence_break(self) -> bool:
        """Delegates to :func:`_response.check_convergence_break`."""
        return _response.check_convergence_break(self)


# ---------------------------------------------------------------------------
# Re-exports for direct ``core.agent.loop.agent_loop`` imports.
# ---------------------------------------------------------------------------

__all__ = [
    "AGENTIC_TOOLS",
    "MAX_TOOL_RESULT_TOKENS",
    "TOOL_LAZY_LOAD_THRESHOLD",
    "AgenticLoop",
    "AgenticResult",
    "_ContextExhaustedError",
    "_context_exhausted_message",
    "get_agentic_tools",
]
