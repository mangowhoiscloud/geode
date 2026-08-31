"""AgenticLoop — while(tool_use) agentic execution loop.

Claude Code-style agentic loop that continues until the LLM
emits end_turn (no more tool calls). All free-text user input
is routed directly here.

Supports:
- Multi-intent: "분석하고 비교해줘" → sequential tool calls
- Multi-turn: context preserved across interactions
- Self-correction: LLM can retry or adjust based on tool results
- Advisory plans: explicit structure, revised only from observed evidence
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Set
from typing import TYPE_CHECKING, Any

from core.agent.conversation import ConversationContext
from core.agent.tool_executor import (
    ToolCallProcessor,
    ToolExecutor,
)
from core.config.policy_source import EMPTY_POLICY_SOURCES, PolicySourceBundle
from core.hooks import (
    HookCorrelation,
    HookEvent,
    HookRegistry,
    HookSystem,
    MiddlewareRegistry,
)
from core.llm.agentic_response import AgenticResponse
from core.llm.errors import BillingError, UserCancelledError
from core.tools.personal_data import (
    requires_durable_redaction,
)
from core.ui.status import TextSpinner

from . import (
    _bootstrap,
    _context,
    _goal,
    _guards,
    _lifecycle,
    _model_switching,
    _phases,
    _provider_call,
    _response,
)
from ._tool_factory import (
    AGENTIC_TOOLS,
    MAX_TOOL_RESULT_TOKENS,
    TOOL_LAZY_LOAD_THRESHOLD,
    get_agentic_tools,
)
from .models import (
    AgenticResult,
    StepSnapshot,
    TerminationReason,
    TurnState,
    _context_exhausted_message,
    _ContextExhaustedError,
)

# Confidence-adaptive compute allocation — the reflection node's
# ``CognitiveState.confidence`` (0..1) steers how much extra LLM compute
# the loop spends on itself. High stable confidence stretches the
# reflection cadence (fewer belief-update calls); low confidence forces
# a reflection every round and edge-triggers a replan. Thresholds are
# deliberately module constants, not settings knobs — one adaptive
# on/off knob exists (``cognitive_reflection_adaptive``).
REFLECTION_STRETCH_CONFIDENCE = 0.8  # confidence >= → interval doubled
REFLECTION_FORCE_CONFIDENCE = 0.4  # confidence < → reflect every round

if TYPE_CHECKING:
    from core.observability.run_event import RunEventSinkProvider
    from core.tools.plan import BoundToolPlan
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


_acomplete_with_fail_fast_pre_execution_retry = (
    _provider_call._acomplete_with_fail_fast_pre_execution_retry
)


def _tool_args_signature(tool_input: Any) -> str:
    """Compatibility alias for the observation phase's stable signature."""
    return _phases.tool_args_signature(tool_input)


def _set_conversation_context(context: ConversationContext) -> None:
    """Publish the active conversation to slash-command guards."""
    from core.agent.conversation import set_conversation_context

    set_conversation_context(context)


class AgenticLoop:
    """Claude Code-style agentic execution loop.

    while stop_reason == "tool_use":
        execute tools → feed results back → continue
    """

    DEFAULT_MAX_ROUNDS = 0  # 0 = unlimited (time-based control via time_budget_s)
    DEFAULT_MAX_TOKENS = 32768
    WRAP_UP_HEADROOM = 2  # force text response N rounds before max
    _WRAP_UP_TIME_HEADROOM_S = 30.0  # force text 30s before time budget expires

    _source: str
    _allowed_tool_names: set[str] | None
    _force_include_allowed_tools: bool
    _tools: list[dict[str, Any]]
    _transient_tools: tuple[dict[str, Any], ...]
    _transient_deferred_tool_names: tuple[str, ...]
    _capability_graph: Any | None
    _task_preflight: Any | None
    _preflight_hint: str
    _usage_snapshot: Any | None
    _capability_graph_digest: str
    _last_llm_error: str | None
    _response_schema: dict[str, Any] | None
    _new_adapter: Any
    _op_logger: Any
    _error_recovery: Any
    _timeline: Any | None
    _session_id: str
    _goal_store: Any | None
    _control_state_renderers: dict[str, Any]
    _session_metrics: Any
    _evidence_ledger: Any | None
    _tool_processor: ToolCallProcessor
    _pre_execution_retry_errors: list[str]
    _LLM_RETRY_CAP: int
    _ctx_mgr: Any
    _convergence: Any
    _consecutive_tool_tracker: list[tuple[str, str]]
    _budget_warned: bool
    _checkpoint: Any | None
    cognitive_state: Any

    def __init__(
        self,
        context: ConversationContext,
        tool_executor: ToolExecutor,
        *,
        config: _bootstrap.AgenticLoopConfig | None = None,
        model: str | None = None,
        provider: str = "anthropic",
        quiet: bool = False,
        tool_registry: ToolRegistry | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        hooks: HookSystem | None = None,
        activity_sink_provider: RunEventSinkProvider | None = None,
        policy_sources: PolicySourceBundle | None = None,
        **legacy_config: Any,
    ) -> None:
        if legacy_config:
            if config is not None:
                raise TypeError("config cannot be combined with legacy policy keywords")
            config = _bootstrap.AgenticLoopConfig(**legacy_config)
        else:
            config = config or _bootstrap.AgenticLoopConfig()
        max_rounds = config.max_rounds
        max_tokens = config.max_tokens
        thinking_budget = config.thinking_budget
        effort = config.effort
        time_budget_s = config.time_budget_s
        cost_budget = config.cost_budget
        parent_session_key = config.parent_session_key
        parent_session_id = config.parent_session_id
        system_suffix = config.system_suffix
        system_prompt_override = config.system_prompt_override
        disable_settings_drift = config.disable_settings_drift
        allowed_tool_names = config.allowed_tool_names
        allow_actionable_partial_on_empty = config.allow_actionable_partial_on_empty
        yield_after_tool_round = config.yield_after_tool_round
        self.context = context
        self.executor = tool_executor
        self._parent_session_key = parent_session_key
        self._parent_session_id = parent_session_id
        self._system_suffix = system_suffix
        # When set, replaces the default role/instruction body (skill
        # context + agentic suffix still appended). Drives AgentDefinition
        # sub-agents off their own role contract.
        self._system_prompt_override = system_prompt_override
        self._quiet = quiet  # suppress spinner (sub-agent, headless)
        # Evaluator-owned simulators can preserve tool actions from a completed
        # round when the following model continuation is irrecoverably empty.
        # Ordinary agents retain the strict exception boundary by default.
        self._allow_actionable_partial_on_empty = allow_actionable_partial_on_empty
        # External half-duplex orchestrators can own the next model turn. The
        # default AgenticLoop contract remains while(tool_use); opted-in callers
        # yield only after one completed tool batch has been recorded.
        self._yield_after_tool_round = yield_after_tool_round
        self._activity_sink_provider = activity_sink_provider
        self._policy_sources = policy_sources or EMPTY_POLICY_SOURCES
        self._user_profile = config.user_profile
        from core.tools.plan import BoundToolPlan as _BoundToolPlan

        executor_plan = getattr(tool_executor, "_bound_tool_plan", None)
        bound_tool_plan = executor_plan if isinstance(executor_plan, _BoundToolPlan) else None
        if (
            bound_tool_plan is not None
            and allowed_tool_names is not None
            and not set(bound_tool_plan.tool_names) <= allowed_tool_names
        ):
            raise ValueError("bound_tool_plan must be filtered before applying an allowlist")
        self._bound_tool_plan = bound_tool_plan
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self._thinking_budget = thinking_budget
        self._effort = effort
        self._time_budget_s = time_budget_s
        # Adaptive compute: track consecutive text-only rounds for overthinking detection
        self._consecutive_text_only_rounds = 0
        self._total_empty_rounds = 0
        # Low-confidence replan is edge-triggered: fires once when
        # confidence drops below REPLAN_LOW_CONFIDENCE, re-arms only
        # after confidence recovers — prevents a replan storm while
        # confidence stays low.
        self._low_confidence_replan_armed = True
        # No positive cost_budget → fall back to settings.cost_limit_usd so
        # the config knob (`cost.limit_usd`) reaches the enforced guard 3
        # (80% warn / 100% hard stop), not just the COST_WARNING /
        # COST_LIMIT_EXCEEDED hook events. A positive caller value (e.g.
        # supervised services' monthly-budget wiring) always wins; there is
        # deliberately no "explicit 0 disables the settings knob" escape.
        # Snapshot at construction is intentional (session-bound budget);
        # the hook path in _response.py live-reads the knob instead.
        if cost_budget <= 0.0:
            try:
                from core.config import settings as _settings

                limit_raw = getattr(_settings, "cost_limit_usd", 0.0)
                # isinstance filters MagicMock auto-attrs in fixtures
                if isinstance(limit_raw, int | float) and limit_raw > 0:
                    cost_budget = float(limit_raw)
            except Exception:
                log.debug("settings.cost_limit_usd read failed", exc_info=True)
        self._cost_budget = cost_budget
        self._loop_start_time: float = 0.0
        # No explicit model → prefer settings.act_model (Plan/Act split),
        # else ANTHROPIC_PRIMARY.
        if model is None:
            try:
                from core.config import settings

                # isinstance(str) filters MagicMock auto-attrs in fixtures
                act_raw = getattr(settings, "act_model", "")
                act_model = act_raw.strip() if isinstance(act_raw, str) else ""
            except Exception:
                log.debug("settings.act_model read failed", exc_info=True)
                act_model = ""
            # live read — config change takes effect without restart
            from core.config import ANTHROPIC_PRIMARY

            self.model = act_model or ANTHROPIC_PRIMARY
        else:
            self.model = model
        self._provider = provider  # "anthropic", "openai", or "glm"
        # When True, sync_model_from_settings is a no-op — caller's model
        # stays sticky for the loop's lifetime.
        self._disable_settings_drift = disable_settings_drift
        # set by update_model_async on model change; the run-loop rebuilds
        # system_prompt before the next LLM call.
        self._prompt_dirty: bool = False
        self._last_plan_hint: str = ""
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._hooks = hooks
        executor_hooks = getattr(tool_executor, "hook_registry", None)
        executor_middleware = getattr(tool_executor, "middleware_registry", None)
        self._hook_registry = (
            executor_hooks
            if isinstance(executor_hooks, HookRegistry)
            else HookRegistry(events=hooks)
        )
        self._middleware_registry = (
            executor_middleware
            if isinstance(executor_middleware, MiddlewareRegistry)
            else MiddlewareRegistry(events=hooks)
        )
        self._turn_id = ""
        self._turn_state: TurnState | None = None
        self._current_step_snapshot: StepSnapshot | None = None
        self._verify_root_turn_id = ""
        self._verify_root_user_input = ""
        self._verify_attempt = 0
        self._verify_attempt_results: list[AgenticResult] = []
        self._verification_evidence_refs: list[dict[str, Any]] = []
        self._pending_verification: dict[str, Any] = {}
        self._verify_continuation_budget = 2
        self._session_generation = 1
        self._public_session_started = False
        self._public_session_ended = False
        from core.llm.adapters.registry import registry_snapshot

        self._adapter_registry_snapshot = registry_snapshot()
        _bootstrap.initialize_runtime(self, tool_executor, hooks, config, quiet=quiet)

    # ------------------------------------------------------------------
    # Lifecycle / metrics — delegate to ``_lifecycle``
    # ------------------------------------------------------------------

    @property
    def pre_execution_retry_errors(self) -> tuple[str, ...]:
        """Connection/empty-output retries observed in the current arun."""

        return tuple(self._pre_execution_retry_errors)

    def _save_checkpoint(self, user_input: str, round_idx: int = 0) -> bool:
        """Delegates to :func:`_lifecycle.save_checkpoint`."""
        return _lifecycle.save_checkpoint(self, user_input, round_idx)

    def mark_session_paused(self) -> None:
        """Delegates to :func:`_lifecycle.mark_session_paused`."""
        return _lifecycle.mark_session_paused(self)

    async def amark_session_completed(self) -> None:
        """Durably complete and emit the public SessionEnd boundary."""
        await _lifecycle.mark_session_completed_async(self)

    async def amark_session_paused(self) -> None:
        """Durably pause while keeping the public session lifetime open."""
        await _lifecycle.mark_session_paused_async(self)

    async def amark_session_error(self) -> None:
        """Durably error and emit the public SessionEnd boundary."""
        await _lifecycle.mark_session_error_async(self)

    def restore_from_checkpoint(self, state: Any) -> None:
        """Delegates to :func:`_lifecycle.restore_loop_state` — the single
        resume surgery (session id + cognitive state + guard counters)."""
        return _lifecycle.restore_loop_state(self, state)

    async def _afinalize_and_return(
        self,
        result: AgenticResult,
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Delegates to :func:`_lifecycle.finalize_and_return_async`."""
        return await _lifecycle.finalize_and_return_async(self, result, user_input, round_idx)

    def _emit_quota_panel(self, exc: BillingError) -> None:
        """Delegates to :func:`_lifecycle.emit_quota_panel`."""
        return _lifecycle.emit_quota_panel(self, exc)

    async def _emit_cognitive(self, event: HookEvent, **payload: Any) -> None:
        """Emit a cognitive-cycle event with the state snapshot attached.

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
        """Record round end + emit REFLECT/UPDATE_MEMORY for text-only
        completions (``stop_reason != "tool_use"``).

        Contract: ACT/OBSERVE are NOT emitted (no action taken). If
        ``cognitive_reflection_enabled`` is on, the reflection node still
        gets one final chance to update beliefs from the terminal text
        snapshot before REFLECT/UPDATE_MEMORY fire. ``last_action`` =
        ``"text-only"``, ``last_observation`` = 80-char head of the text
        (distinguishes no-action from failed-tool turns).
        """
        head = text.strip().replace("\n", " ")
        if len(head) > 80:
            head = head[:80] + "…"
        self.cognitive_state.record_round(
            action="text-only",
            observation=head or "(empty text)",
        )
        await self._maybe_reflect([])
        await self._emit_cognitive(HookEvent.COGNITIVE_REFLECT, round=round_idx + 1)
        await self._emit_cognitive(HookEvent.COGNITIVE_UPDATE_MEMORY, round=round_idx + 1)

    async def _run_cognitive_act_observe_cycle(
        self,
        response: Any,
        round_idx: int,
        *,
        step_snapshot: StepSnapshot | None = None,
        defer_reflection: bool = False,
    ) -> list[dict[str, Any]]:
        """Run ACT/OBSERVE and optionally defer reflection until checkpointed.

        Preserves the cognitive-cycle event ordering (PERCEIVE -> PLAN ->
        ACT -> OBSERVE -> REFLECT -> UPDATE_MEMORY).
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

        if step_snapshot is not None:
            self._tool_processor.bind_step(step_snapshot)
        tool_results = await self._tool_processor.process(response)

        await self._emit_cognitive(
            HookEvent.COGNITIVE_OBSERVE,
            round=round_idx + 1,
            tool_names=tool_names,
            result_count=len(tool_results),
        )

        # deterministic round-end update — reflection node overwrites below
        self.cognitive_state.record_round(
            action=("tools: " + ", ".join(tool_names)) if tool_names else "text-only",
            observation=f"{len(tool_results)} tool result(s)",
        )
        if not defer_reflection:
            await AgenticLoop._finish_cognitive_tool_round(self, response, tool_results, round_idx)
        return tool_results

    async def _finish_cognitive_tool_round(
        self,
        response: Any,
        tool_results: list[dict[str, Any]],
        round_idx: int,
    ) -> None:
        """Reflect only after the owning phase checkpoints tool results."""
        tool_names = [
            getattr(block, "name", "unknown")
            for block in getattr(response, "content", None) or []
            if getattr(block, "type", None) == "tool_use"
        ]

        # Raw personal Workspace results stay in the active model turn only.
        # Reflection can use a separately configured provider and persists its
        # hypotheses, so skip that secondary processing for the whole batch if
        # any personal-data tool ran.  The deterministic count/tool-name
        # snapshot above remains available to cognitive listeners.
        personal_tools = sorted(
            name for name in set(tool_names) if requires_durable_redaction(name)
        )
        batch_requires_redaction = bool(
            getattr(
                self._tool_processor,
                "last_batch_requires_redaction",
                False,
            )
        ) or bool(personal_tools)
        if batch_requires_redaction:
            log.info(
                "reflection skipped for personal-data tool batch: tools=%s",
                ",".join(personal_tools) or "effective-request",
            )
        else:
            # reflection runs before the REFLECT hook so listeners see the
            # LLM-derived belief update, not the deterministic snapshot
            await self._maybe_reflect(tool_results)

        await self._emit_cognitive(HookEvent.COGNITIVE_REFLECT, round=round_idx + 1)
        await self._emit_cognitive(HookEvent.COGNITIVE_UPDATE_MEMORY, round=round_idx + 1)

    async def _maybe_reflect(self, tool_results: list[dict[str, Any]]) -> None:
        """Call the reflection node if enabled.

        Reads ``settings.cognitive_reflection_enabled`` lazily (toggle
        takes effect next round, no restart). ``reflection_interval=N``
        thins the cadence; the first round always reflects. Errors are
        swallowed inside ``reflect_async`` (loop stays robust to a flaky
        reflection model).
        """
        from core.config import settings

        if not settings.cognitive_reflection_enabled:
            return
        interval = max(1, int(settings.cognitive_reflection_interval))
        # Confidence-adaptive cadence: high stable confidence buys fewer
        # belief-update calls (interval doubled), low confidence forces a
        # reflection every round. Reads the LAST reflection's confidence —
        # staleness during a stretch is the accepted trade (verify still
        # watches every turn). None (no reflection yet) → base interval.
        confidence = self.cognitive_state.confidence
        if getattr(settings, "cognitive_reflection_adaptive", True) and isinstance(
            confidence, int | float
        ):
            if confidence >= REFLECTION_STRETCH_CONFIDENCE:
                interval *= 2
            elif confidence < REFLECTION_FORCE_CONFIDENCE:
                interval = 1
        # round_count is 1-based (record_round ran just before this);
        # (round_count - 1) % interval == 0 → rounds 1, 1+N, 1+2N, ...
        round_count = self.cognitive_state.round_count
        if interval > 1 and (round_count - 1) % interval != 0:
            log.debug(
                "reflection skipped: round=%d interval=%d (next at round %d)",
                round_count,
                interval,
                round_count + (interval - (round_count - 1) % interval),
            )
            return
        from core.agent.loop._reflection import reflect_async

        raw_model = settings.cognitive_reflection_model
        configured_model = raw_model.strip() if isinstance(raw_model, str) else ""
        inherit_loop_model = not configured_model
        reflection_model = configured_model or self.model
        reflection_provider = self._provider if inherit_loop_model else None
        reflection_source = (
            getattr(self._new_adapter, "source", self._source) if inherit_loop_model else None
        )

        reflection_kwargs: dict[str, Any] = {}
        active_middleware = getattr(self, "_middleware_registry", None)
        if active_middleware is not None:
            reflection_kwargs["middleware_registry"] = active_middleware
        await reflect_async(
            self.cognitive_state,
            tool_results,
            model=reflection_model,
            max_tokens=settings.cognitive_reflection_max_tokens,
            provider=reflection_provider,
            source=reflection_source,
            policy_sources=self._policy_sources,
            **reflection_kwargs,
        )

    async def _emit_session_start_signals(self, user_input: str) -> AgenticResult | None:
        """Emit the turn-start signals. Owns the USER_INPUT_RECEIVED
        observation, cognitive-state goal init + ContextVar bind,
        COGNITIVE_PERCEIVE emit, conversation-context append, SessionTimeline
        ``record_session_start`` / ``record_user_message``, and the
        SESSION_STARTED hook.

        Returns ``None`` on the happy path. Returns an
        :class:`AgenticResult` (with ``termination_reason="input_blocked"``)
        The public UserPromptSubmit decision runs at the start of ``arun``
        before preflight or decomposition.
        """
        # Internal observation only; public control belongs to HookRegistry.
        if self._hooks:
            await self._hooks.trigger_async(
                HookEvent.USER_INPUT_RECEIVED,
                {
                    "user_input": user_input,
                    "session_id": self._session_id,
                    "turn_id": self._turn_id,
                },
            )

        # goal = first arun()'s input (later calls keep it so observations
        # accumulate against one goal)
        if not self.cognitive_state.goal:
            self.cognitive_state.goal = user_input
        # Bind CognitiveState/session ids to ContextVars so tool-executor
        # hooks read the live state without coupling to AgenticLoop. Binding
        # is asyncio-task-scoped; the next arun overwrites idempotently.
        from core.agent.cognitive_state_ctx import (
            set_cognitive_state,
            set_parent_session_id,
            set_parent_session_key,
            set_session_id,
            set_turn_id,
        )

        set_cognitive_state(self.cognitive_state)
        set_session_id(self._session_id)
        set_turn_id(getattr(self, "_turn_id", ""))
        # Sub-agent lineage → Episode rows (empty for top-level loops)
        set_parent_session_key(self._parent_session_key)
        set_parent_session_id(self._parent_session_id)
        await self._emit_cognitive(
            HookEvent.COGNITIVE_PERCEIVE,
            user_input=user_input,
        )

        # Add user message to conversation context
        self.context.add_user_message(user_input)

        # Durable history: session generation + this turn's user message.
        if self._timeline is not None:
            self._timeline.record_session_start(model=self.model, provider=self._provider)
            self._timeline.record_user_message(user_input)

        # fresh per-session adapter usage counter → SESSION_ENDED adapter_usage
        from core.llm.adapters.dispatch import begin_session_adapter_tracking

        begin_session_adapter_tracking()

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

        return None

    async def _dispatch_llm_call(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        round_idx: int,
        spinner: TextSpinner,
    ) -> AgenticResponse | AgenticResult | None:
        """Dispatch the LLM call and handle the simple exceptions.

        Returns:
          * ``AgenticResponse`` on a successful call (caller proceeds
            with response processing).
          * ``AgenticResult`` on ``BillingError`` or
            ``UserCancelledError`` (caller ``return``s this verbatim).
          * ``None`` when ``_call_llm`` returns ``None`` (caller's
            existing error-classification path handles it).

        ``_ContextExhaustedError`` is NOT caught — propagates so the
        caller's aggressive-recovery path runs intact. Stops ``spinner``
        before emitting quota/cancel output (caller's finally also stops it).
        """
        try:
            return await self._call_llm(system_prompt, messages, round_idx=round_idx)
        except BillingError as exc:
            spinner.stop()
            self._emit_quota_panel(exc)
            return _guards._terminal_result(
                self,
                TerminationReason.BILLING_ERROR,
                exc.user_message(),
                rounds=round_idx + 1,
            )
        except UserCancelledError:
            spinner.stop()
            log.info("LLM call interrupted by user")
            return _guards._terminal_result(
                self,
                TerminationReason.USER_CANCELLED,
                "Interrupted.",
                rounds=round_idx + 1,
            )

    def _open_step_snapshot(
        self,
        *,
        round_idx: int,
        model: str,
        allow_tools: bool,
    ) -> StepSnapshot:
        """Freeze the exact runtime inputs for one model sampling request."""
        turn = self._turn_state
        if turn is None or turn.turn_id != self._turn_id:
            turn = TurnState(turn_id=self._turn_id)
            self._turn_state = turn
        step_index = turn.next_step_index()
        step_id = f"{self._turn_id or 'unbound'}:step-{step_index}"
        adapter = self._new_adapter
        snapshot = StepSnapshot(
            step_id=step_id,
            step_index=step_index,
            round_index=round_idx,
            model=model,
            provider=str(getattr(adapter, "provider", self._provider)),
            source=str(getattr(adapter, "source", self._source)),
            adapter_name=str(getattr(adapter, "name", "")),
            bound_tool_plan=(self._bound_tool_plan if allow_tools else None),
            time_budget_s=self._time_budget_s,
            cost_budget_usd=self._cost_budget,
            cancellation=turn.cancellation,
            correlation=HookCorrelation(
                session_id=self._session_id,
                turn_id=self._turn_id,
                step_id=step_id,
                session_generation=self._session_generation,
                verify_attempt=self._verify_attempt,
            ),
        )
        self._current_step_snapshot = snapshot
        self._tool_processor.bind_step(snapshot)
        return snapshot

    def _set_turn_termination(self, reason: TerminationReason) -> None:
        turn = getattr(self, "_turn_state", None)
        if turn is None or turn.turn_id != self._turn_id:
            return
        turn.termination_reason = reason
        if reason is TerminationReason.USER_CANCELLED:
            turn.cancellation.set()

    def _bind_turn_messages(self, messages: list[dict[str, Any]]) -> TurnState:
        turn = self._turn_state
        if turn is None:
            raise RuntimeError("agent turn state was not initialized")
        turn.messages = messages
        return turn

    def _set_llm_retry_count(self, count: int) -> None:
        self._consecutive_llm_failures = count
        if self._turn_state is not None:
            self._turn_state.retry_count = count

    async def _sync_model_and_rebuild_prompt(
        self,
        system_prompt: str,
        reflection_hint: str | None = None,
        verification_hint: str | None = None,
    ) -> str:
        """Sync model drift + rebuild the system prompt.

        Rebuilds when the model drifted (``settings.model`` changed),
        ``_prompt_dirty`` is set (direct ``update_model_async``), or advisory
        plan progress changed. On rebuild, re-applies the preflight /
        reflection / verification / plan hints inside the dynamic envelope so
        a mid-arun change does not drop them. Returns the (possibly-rebuilt)
        prompt; clears ``_prompt_dirty``.
        """
        drift_detected = await _model_switching.sync_model_from_settings_async(self)
        prompt_dirty = self._prompt_dirty
        raw_plan_hint = _guards._consume_plan_hint(self)
        plan_hint = raw_plan_hint if isinstance(raw_plan_hint, str) else ""
        last_plan_hint = getattr(self, "_last_plan_hint", "")
        if not isinstance(last_plan_hint, str):
            last_plan_hint = plan_hint
        plan_changed = plan_hint != last_plan_hint
        if drift_detected or prompt_dirty or plan_changed:
            from core.agent.loop._context import inject_runtime_hints

            system_prompt = inject_runtime_hints(
                self._build_system_prompt(),
                getattr(self, "_preflight_hint", ""),
                reflection_hint,
                verification_hint,
                plan_hint if isinstance(plan_hint, str) else "",
                _context.render_control_state_hints(self),
            )
            self._prompt_dirty = False
            self._last_plan_hint = plan_hint
            # Fire PROMPT_ASSEMBLED on each per-round rebuild (no-op if no hooks)
            hooks = getattr(self, "_hooks", None)
            if hooks:
                from core.hooks import HookEvent

                reason = (
                    "model_drift"
                    if drift_detected
                    else ("prompt_dirty" if prompt_dirty else "plan_progress")
                )
                await hooks.trigger_async(
                    HookEvent.PROMPT_ASSEMBLED,
                    {
                        "model": self.model,
                        "provider": self._provider,
                        "reason": reason,
                        "x2_injected": True,  # identity line always present
                        "prompt_len": len(system_prompt),
                    },
                )
        if (turn := getattr(self, "_turn_state", None)) is not None:
            turn.plan_hint = self._last_plan_hint
        return system_prompt

    # ------------------------------------------------------------------
    # Tool list refresh — delegate to ``_response``
    # ------------------------------------------------------------------

    def refresh_tools(self) -> int:
        """Delegates to :func:`_response.refresh_tools`."""
        return _response.refresh_tools(self)

    def _transient_tool_names(
        self,
        mcp_tools: list[dict[str, Any]] | None,
    ) -> frozenset[str]:
        names = {tool["name"] for tool in (mcp_tools or ()) if isinstance(tool.get("name"), str)}
        if self._tool_registry is not None:
            names.update(
                tool["name"]
                for tool in self._tool_registry.to_anthropic_tools()
                if isinstance(tool.get("name"), str)
            )
        return frozenset(names)

    def _apply_bound_tool_plan(
        self,
        runtime_tools: list[dict[str, Any]],
        *,
        transient_tool_names: Set[str] = frozenset(),
    ) -> None:
        """Project plan-owned schemas plus explicit transient runtime overlays."""
        from core.tools.plan import thaw_tool_schema

        bound = self._bound_tool_plan
        if bound is None:
            self._tools = runtime_tools
            self._transient_tools = ()
            self._transient_deferred_tool_names = ()
            return
        from core.llm.tool_defer import default_deferred_tool_names

        plan_names = {item.spec.name for item in bound.plan.registrations}
        transient = tuple(
            tool
            for tool in runtime_tools
            if tool.get("name") in transient_tool_names
            and tool.get("name") not in plan_names
            and tool.get("name") not in self.executor._denied_tools
        )
        plan_tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": thaw_tool_schema(spec.input_schema),
            }
            for spec in bound.ordered_specs
        ]
        self._transient_tools = transient
        deferred = default_deferred_tool_names(
            tool["name"] for tool in transient if isinstance(tool.get("name"), str)
        )
        self._transient_deferred_tool_names = tuple(
            tool["name"] for tool in transient if tool.get("name") in deferred
        )
        self.executor._replace_bound_tool_scope(
            frozenset(tool["name"] for tool in transient if isinstance(tool.get("name"), str))
        )
        self._tools = [*plan_tools, *transient]

    def _reproject_bound_tool_plan(self) -> None:
        """Rebuild one effective Bound snapshot after a provider/source switch."""
        current = self._bound_tool_plan
        if current is None:
            return
        from core.agent.loop._tool_factory import project_bound_tool_plan

        projected = project_bound_tool_plan(
            current.base,
            provider=self._provider,
            source=self._source,
            policy_sources=self._policy_sources,
            force_include=(self._allowed_tool_names if self._force_include_allowed_tools else None),
        )
        from core.tools.policy import apply_profile_policy

        projected = apply_profile_policy(projected).filtered(
            allowed_tool_names=(
                frozenset(self._allowed_tool_names)
                if self._allowed_tool_names is not None
                else None
            ),
            denied_tool_names=self.executor._denied_tools,
        )
        if projected.content_hash == current.content_hash:
            return
        projected = projected.at_generation(current.generation + 1)
        self.executor._replace_bound_tool_plan(projected)
        self._bound_tool_plan = projected

    def bound_tool_plan_snapshot(self) -> tuple[BoundToolPlan, Mapping[str, Any]]:
        """Return the current immutable catalog for an isolated child run."""
        if self._bound_tool_plan is None:
            raise RuntimeError("active AgenticLoop has no bound tool plan")
        transient_handlers = getattr(self.executor, "_transient_handlers", None)
        if not isinstance(transient_handlers, Mapping):
            raise RuntimeError("active ToolExecutor has no transient handler snapshot")
        return self._bound_tool_plan, transient_handlers

    # ------------------------------------------------------------------
    # Model switching / escalation — delegate to ``_model_switching``
    # ------------------------------------------------------------------

    async def update_model_async(
        self,
        model: str,
        provider: str | None = None,
        reason: str = "user_switch",
    ) -> None:
        """Delegates to :func:`_model_switching.update_model_async`."""
        return await _model_switching.update_model_async(self, model, provider, reason)

    # ------------------------------------------------------------------
    # Run loop entry points
    # ------------------------------------------------------------------

    def _prepare_task_preflight(self, user_input: str) -> str:
        """Run capability-aware preflight and return a system-prompt hint."""
        try:
            from core.agent.capability_graph import graph_summary
            from core.agent.task_preflight import plan_task_preflight, render_preflight_hint

            capability_graph = self._capability_graph
            if capability_graph is None:
                raise RuntimeError("capability graph is unavailable")
            self._task_preflight = plan_task_preflight(user_input, capability_graph)
            preflight_hint = render_preflight_hint(self._task_preflight)
            if self._evidence_ledger is not None:
                self._evidence_ledger.append_preflight(
                    capability_graph=graph_summary(capability_graph),
                    preflight=self._task_preflight,
                )
            if self._timeline is not None:
                summary = graph_summary(capability_graph)
                digest = hashlib.sha256(
                    json.dumps(summary, sort_keys=True, ensure_ascii=False, default=str).encode()
                ).hexdigest()
                # The graph is invariant across a run while preflight varies per
                # turn, so re-serialising it every turn cost 43.4 MB across only
                # 19 distinct values. Emit it once, then reference the digest;
                # readers resolve a digest against the last full emission.
                payload: dict[str, Any] = {
                    "capability_graph_sha256": digest,
                    "preflight": self._task_preflight,
                }
                if self._bound_tool_plan is not None:
                    payload["tool_plan"] = {
                        "generation": self._bound_tool_plan.generation,
                        "content_hash": self._bound_tool_plan.content_hash,
                        "tool_count": len(self._bound_tool_plan.tool_names),
                        "eager_count": len(self._bound_tool_plan.eager_tool_names),
                        "deferred_count": len(self._bound_tool_plan.deferred_tool_names),
                    }
                if digest != self._capability_graph_digest:
                    payload["capability_graph"] = summary
                    self._capability_graph_digest = digest
                self._timeline.record_lifecycle_event(
                    event="task_preflight",
                    component="agentic_loop",
                    level="info",
                    payload=payload,
                    action="agent.preflight",
                    entity_type="session",
                    entity_id=self._session_id,
                )
            return preflight_hint
        except Exception:
            log.debug("Task preflight failed", exc_info=True)
            return ""

    async def arun(
        self,
        user_input: str,
        *,
        _verify_continuation: HookCorrelation | None = None,
    ) -> AgenticResult:
        """Run one user turn plus any explicitly activated goal continuations."""
        from core.llm.adapters.registry import use_registry_snapshot

        with use_registry_snapshot(self._adapter_registry_snapshot):
            return await _goal.run(
                self,
                user_input,
                verify_continuation=_verify_continuation,
            )

    async def acontinue_goal(
        self,
        *,
        trigger: str = "serve_idle",
    ) -> AgenticResult | None:
        """Continue this session's active Goal through the normal turn loop."""
        from core.llm.adapters.registry import use_registry_snapshot

        with use_registry_snapshot(self._adapter_registry_snapshot):
            return await _goal.continue_active(self, trigger=trigger)

    async def _arun_once(
        self,
        user_input: str,
        *,
        _verify_continuation: HookCorrelation | None = None,
        _goal_continuation: Any | None = None,
        _goal_continuation_trigger: str = "active_goal",
    ) -> AgenticResult:
        """Run one physical agent turn through the six explicit phases."""
        prepared = await _phases.prepare_input(
            self,
            user_input,
            verify_continuation=_verify_continuation,
            goal_continuation=_goal_continuation,
            goal_continuation_trigger=_goal_continuation_trigger,
        )
        if isinstance(prepared, AgenticResult):
            return prepared

        guard_reason: str | None = None
        round_idx = prepared.turn_state.round_index
        while True:
            round_idx = prepared.turn_state.round_index
            guard_reason = _guards._check_round_guards(self, round_idx)
            if guard_reason is not None:
                break
            is_last_round = self.max_rounds > 0 and round_idx == self.max_rounds - 1

            model_call = await _phases.prepare_model_call(self, prepared, round_idx)
            if isinstance(model_call, AgenticResult):
                return model_call

            provider_result = await _phases.call_provider(
                self,
                prepared,
                model_call,
                round_idx,
            )
            if provider_result is None:
                continue
            if isinstance(provider_result, AgenticResult):
                return provider_result

            tool_result = await _phases.process_tool_calls(
                self,
                prepared,
                provider_result,
                round_idx,
                is_last_round=is_last_round,
                step_snapshot=model_call.step_snapshot,
            )
            if isinstance(tool_result, AgenticResult):
                return tool_result

            terminal = await _phases.observe_and_compact(
                self,
                prepared,
                provider_result,
                tool_result,
                round_idx,
            )
            if terminal is not None:
                return terminal

        return await _phases.assemble_termination(
            self,
            user_input=prepared.user_input,
            round_idx=round_idx,
            turn=prepared,
            guard_reason=guard_reason,
        )

    # ------------------------------------------------------------------
    # Context window — delegate to ``_context``
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Delegates to :func:`_context.build_system_prompt`."""
        return _context.build_system_prompt(self)

    # ------------------------------------------------------------------
    # Durable child mailbox — delegate to ``_collaboration_mailbox``
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # LLM call (stays in this file — tightly coupled to ``arun`` body)
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        round_idx: int = 0,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        allow_tools: bool = True,
    ) -> AgenticResponse | None:
        """Assemble and dispatch one provider request."""
        return await _provider_call.call_llm(
            self,
            system,
            messages,
            round_idx=round_idx,
            model=model,
            response_schema=response_schema,
            allow_tools=allow_tools,
        )

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
