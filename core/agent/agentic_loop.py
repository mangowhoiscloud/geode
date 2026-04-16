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
import dataclasses
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.agent.conversation import ConversationContext
from core.agent.error_recovery import ErrorRecoveryStrategy
from core.agent.sub_agent import SubAgentResult, drain_announced_results
from core.agent.system_prompt import build_system_prompt as _build_system_prompt
from core.agent.tool_executor import (
    ToolCallProcessor,
    ToolExecutor,
)
from core.cli.ui.agentic_ui import OperationLogger
from core.cli.ui.status import TextSpinner
from core.config import (
    ANTHROPIC_PRIMARY,
    _resolve_provider,
)
from core.hooks import HookEvent, HookSystem
from core.llm.agentic_response import AgenticResponse
from core.llm.errors import BillingError, UserCancelledError
from core.llm.prompts import AGENTIC_SUFFIX
from core.llm.router import (
    CROSS_PROVIDER_FALLBACK,
    maybe_traceable,
    resolve_agentic_adapter,
)
from core.tools.base import load_all_tool_definitions

if TYPE_CHECKING:
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Load base tool definitions from centralized JSON (SOT: core/tools/base.py)
_BASE_TOOLS: list[dict[str, Any]] = load_all_tool_definitions()

# Backward-compatible alias
AGENTIC_TOOLS: list[dict[str, Any]] = _BASE_TOOLS


def get_agentic_tools(
    registry: ToolRegistry | None = None,
    *,
    mcp_tools: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return tool definitions with unified deferred loading for native + MCP tools.

    Merges base tools, registry extras, and MCP tools into a single list.
    When the combined count exceeds the defer threshold (10), deferred loading
    activates: core tools stay loaded, the rest are deferred via tool_search.

    Args:
        registry: Optional ToolRegistry with additional native tools.
        mcp_tools: Optional MCP tool definitions to include.
    """
    tools = list(_BASE_TOOLS)
    existing_names = {t["name"] for t in tools}
    if registry:
        for tool_def in registry.to_anthropic_tools():
            if tool_def["name"] not in existing_names:
                existing_names.add(tool_def["name"])
                tools.append(tool_def)
    # Merge MCP tools into the unified list (dedup across servers)
    if mcp_tools:
        existing_names = {t["name"] for t in tools}
        for mcp_tool in mcp_tools:
            name = mcp_tool.get("name")
            if name and name not in existing_names:
                existing_names.add(name)
                tools.append(mcp_tool)
    return tools


# ---------------------------------------------------------------------------
# Token guard — optional tool result truncation (P2-A)
# Default: unlimited (0). Frontier consensus: compression > hard cap.
# Server-side clear_tool_uses handles context accumulation.
# Set GEODE_MAX_TOOL_RESULT_TOKENS to a positive value to re-enable.
# ---------------------------------------------------------------------------
MAX_TOOL_RESULT_TOKENS = 0  # backward-compat alias; canonical: settings.max_tool_result_tokens
TOOL_LAZY_LOAD_THRESHOLD = 50  # Above this count, skip MCP lazy loading


class _ContextExhaustedError(Exception):
    """Raised when context remains critical after pruning — unrecoverable."""


_EXHAUSTED_FALLBACK = (
    "Context window exhausted. "
    "This conversation has been automatically reset — "
    "please start a new thread or send a new message to continue."
)

_EXHAUSTED_SYSTEM = (
    "The conversation context has been exhausted and automatically reset. "
    "Reply ONLY with a short notice (1-2 sentences) in the SAME language as the user's message. "
    "Tell them the conversation was reset and they should start a new thread or send a new message."
)


def _context_exhausted_message(user_input: str) -> str:
    """Generate context-exhausted message in the user's language via lightweight LLM call."""
    try:
        import anthropic

        from core.config import ANTHROPIC_BUDGET, settings

        if not settings.anthropic_api_key:
            return _EXHAUSTED_FALLBACK

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=ANTHROPIC_BUDGET,
            max_tokens=150,
            system=_EXHAUSTED_SYSTEM,
            messages=[{"role": "user", "content": user_input[:200]}],
        )
        block = resp.content[0] if resp.content else None
        text = block.text if block and hasattr(block, "text") else ""
        return text or _EXHAUSTED_FALLBACK
    except Exception:
        log.debug("Exhausted message LLM call failed, using fallback", exc_info=True)
        return _EXHAUSTED_FALLBACK


@dataclass
class AgenticResult:
    """Result of an agentic loop execution."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    error: str | None = None
    # "natural" | "forced_text" | "max_rounds" | "time_budget_expired"
    # | "llm_error" | "context_exhausted" | "cost_budget_exceeded"
    termination_reason: str = "unknown"
    summary: str = ""  # Tier 1 compact action summary (auto-generated)
    reasoning_metrics: dict[str, object] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


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
        self._total_thinking_tokens = 0
        self._total_empty_rounds = 0
        self._cost_budget = cost_budget
        self._loop_start_time: float = 0.0
        self.model = model or ANTHROPIC_PRIMARY
        self._provider = provider  # "anthropic", "openai", or "glm"
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

            from core.cli.transcript import SessionTranscript

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
            from core.cli.session_checkpoint import SessionCheckpoint

            self._checkpoint = SessionCheckpoint()
        except Exception:
            log.warning("SessionCheckpoint init failed", exc_info=True)

    def _save_checkpoint(self, user_input: str, round_idx: int = 0) -> None:
        """Persist session checkpoint for resume (per-turn, Claude Code pattern)."""
        if self._checkpoint is None or not self._session_id:
            return
        try:
            from core.cli.session_checkpoint import SessionState

            state = SessionState(
                session_id=self._session_id,
                round_idx=round_idx,
                model=self.model,
                provider=self._provider,
                status="active",
                messages=self.context.messages,
                tool_log=self._tool_processor.tool_log,
                user_input=user_input,
            )
            self._checkpoint.save(state)

            from core.cli.ui.agentic_ui import emit_checkpoint_saved

            emit_checkpoint_saved(self._session_id, round_idx)
        except Exception:
            log.debug("Checkpoint save failed", exc_info=True)

    def mark_session_completed(self) -> None:
        """Mark the current session as completed (called on clean REPL exit)."""
        # Clean up announce queue to prevent orphan accumulation
        if self._parent_session_key:
            from core.agent.sub_agent import cleanup_announce_queue

            cleanup_announce_queue(self._parent_session_key)
        if self._checkpoint is None or not self._session_id:
            return
        try:
            self._checkpoint.mark_completed(self._session_id)
        except Exception:
            log.debug("Checkpoint mark_completed failed", exc_info=True)

    def _record_transcript_end(self, result: Any) -> None:
        """Record session end + assistant message to transcript."""
        if self._transcript is None:
            return
        try:
            text = getattr(result, "text", "") or ""
            if text:
                self._transcript.record_assistant_message(text)
            rounds = getattr(result, "rounds", 0)

            # Read accumulated cost from TokenTracker (was missing → always $0)
            total_cost = 0.0
            try:
                from core.llm.token_tracker import get_tracker

                total_cost = get_tracker().accumulator.total_cost_usd
            except Exception:
                log.debug("Could not read session cost from TokenTracker")

            self._transcript.record_session_end(rounds=rounds, total_cost=total_cost)
        except Exception:
            log.debug("Transcript end recording failed", exc_info=True)

    def _finalize_and_return(
        self,
        result: AgenticResult,
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Log result, record transcript end, save checkpoint, and return (DRY)."""
        log.info(
            "AgenticLoop: reason=%s rounds=%d/%d tools=%d",
            result.termination_reason,
            result.rounds,
            self.max_rounds,
            len(result.tool_calls),
        )

        # Reasoning metrics (DTR-inspired observability)
        metrics = self._build_reasoning_metrics(result)
        result.reasoning_metrics = metrics.to_dict()

        self._record_transcript_end(result)
        self._save_checkpoint(user_input, round_idx=round_idx)
        if self._hooks:
            self._hooks.trigger(
                HookEvent.SESSION_END,
                {
                    "model": self.model,
                    "provider": self._provider,
                    "session_id": self._session_id,
                    "termination_reason": result.termination_reason,
                    "rounds": result.rounds,
                    "tool_count": len(result.tool_calls),
                    "error": result.error,
                },
            )
            self._hooks.trigger(
                HookEvent.TURN_COMPLETE,
                {
                    "user_input": user_input,
                    "text": result.text[:500] if result.text else "",
                    "rounds": result.rounds,
                    "tool_calls": [tc.get("name", "") for tc in result.tool_calls],
                    "termination_reason": result.termination_reason,
                },
            )
            self._hooks.trigger(
                HookEvent.REASONING_METRICS,
                result.reasoning_metrics,
            )
        return result

    def _build_reasoning_metrics(self, result: AgenticResult) -> Any:
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
            thinking_tokens=self._total_thinking_tokens + thinking_tok,
            output_tokens=output_tok,
            tool_calls_total=len(result.tool_calls),
            empty_rounds=self._total_empty_rounds,
            cost_usd=cost,
            overthinking_detected=self._consecutive_text_only_rounds >= 2,
        )
        metrics.compute_derived()
        return metrics

    def refresh_tools(self) -> int:
        """Reload MCP tools into the tool list without reconstructing the loop.

        Called after install_mcp_server to make new tools available immediately.
        Rebuilds the unified tool list with deferred loading applied.
        Returns number of newly added tools.
        """
        if self._mcp_manager is None:
            return 0
        old_count = len(self._tools)
        mcp_tool_list = self._mcp_manager.get_all_tools()
        self._tools = get_agentic_tools(self._tool_registry, mcp_tools=mcp_tool_list)
        new_count = len(self._tools)
        return max(0, new_count - old_count)

    def _sync_model_from_settings(self) -> bool:
        """Check if settings.model diverged and apply the change safely.

        Called at the top of each agentic round — between LLM calls, never
        mid-call.  This replaces the old pattern of calling update_model()
        from inside a tool handler, which swapped the adapter while the
        current round was still processing tool results.

        Returns True if the model was changed (caller should rebuild
        system_prompt), False otherwise.
        """
        try:
            from core.config import settings

            if settings.model != self.model:
                log.info(
                    "Model drift detected: loop=%s settings=%s — syncing",
                    self.model,
                    settings.model,
                )
                self.update_model(settings.model)
                return True
        except Exception:
            log.debug("Model drift check failed", exc_info=True)
        return False

    def update_model(
        self,
        model: str,
        provider: str | None = None,
        reason: str = "user_switch",
    ) -> None:
        """Update model and provider without reconstructing the loop.

        Resolves a fresh adapter when the provider changes. Within the
        same provider, the adapter is reused (it owns its own client).
        Also syncs the SessionMeter so status lines show the correct model.
        """
        old_model = self.model
        new_provider = provider or _resolve_provider(model)
        if new_provider != self._provider:
            self._provider = new_provider
            self._adapter = resolve_agentic_adapter(new_provider)
        self.model = model
        self._tool_processor._model = model

        # Sync SessionMeter so "Worked for" status line shows the correct model
        from core.cli.ui.agentic_ui import update_session_model

        update_session_model(model)
        log.info("AgenticLoop model updated: %s (provider=%s)", model, self._provider)

        # Fire MODEL_SWITCHED hook + IPC event for observability
        if old_model != model:
            from core.cli.ui.agentic_ui import emit_model_switched

            emit_model_switched(old_model, model, reason)
            if self._hooks:
                from core.hooks import HookEvent

                self._hooks.trigger(
                    HookEvent.MODEL_SWITCHED,
                    {
                        "from_model": old_model,
                        "to_model": model,
                        "reason": reason,
                    },
                )

            # Inject model-switch breadcrumb so the new model knows the switch
            # happened (Claude Code SDK pattern: createModelSwitchBreadcrumbs).
            if not self.context.is_empty:
                self.context.add_user_message(
                    f"[system] Model switched: {old_model} -> {model}. "
                    "You are now the new model. Do not reference the previous "
                    "model's responses as current state."
                )
                self.context.add_assistant_message(f"Understood. I am now {model}.")

        # Proactively adapt context for the new model's context window
        self._adapt_context_for_model(model)

    def _adapt_context_for_model(self, target_model: str) -> None:
        """Proactively adapt conversation context when switching to a smaller model.

        Hybrid approach (Research 방안 E):
        Phase 1: Summarize large tool_result blocks (most effective)
        Phase 2: Token-aware adaptive pruning
        Phase 3: Log warning if still over budget (minimal mode)
        """
        from core.orchestration.context_monitor import (
            adaptive_prune,
            check_context,
            summarize_tool_results,
        )

        if self.context.is_empty:
            return

        metrics = check_context(self.context.messages, target_model)
        if not metrics.is_warning:
            return  # Under 80% — no adaptation needed

        original_tokens = metrics.estimated_tokens
        log.info(
            "Context adaptation: %.0f%% (%d/%d tokens) for %s",
            metrics.usage_pct,
            metrics.estimated_tokens,
            metrics.context_window,
            target_model,
        )

        # Phase 1: Summarize large tool results (preserves conversation structure)
        summarize_tool_results(self.context.messages, metrics.context_window)

        # Phase 2: Token-aware pruning if still over budget
        metrics = check_context(self.context.messages, target_model)
        if metrics.is_critical:
            pruned = adaptive_prune(self.context.messages, metrics.context_window)
            self.context.messages = pruned

        # Phase 3: Final check — log result
        metrics = check_context(self.context.messages, target_model)
        log.info(
            "Context adapted: %d → %d tokens (%.0f%% of %s window)",
            original_tokens,
            metrics.estimated_tokens,
            metrics.usage_pct,
            target_model,
        )

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
            from rich.console import Console as _Con

            _Con().print(f"\n  [bold red]✗ Billing error[/bold red] — {exc}")
            return AgenticResult(
                text=str(exc),
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
            if self._sync_model_from_settings():
                # Rebuild system prompt for the new model (model card, context window)
                system_prompt = self._build_system_prompt()
                if decomposition_hint:
                    system_prompt += "\n\n" + decomposition_hint

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
            from core.cli.ui.agentic_ui import _ipc_writer_local

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
                from rich.console import Console as _Con

                _Con().print(f"\n  [bold red]✗ Billing error[/bold red] — {exc}")
                return AgenticResult(
                    text=str(exc),
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
                            from core.cli.ui.agentic_ui import emit_llm_error

                            emit_llm_error(_et, _sev, _hint, self.model, self._provider)
                        old_model = self.model
                        escalated = self._try_cross_provider_escalation()
                        if escalated:
                            from core.cli.ui.agentic_ui import emit_model_escalation

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
                            from core.cli.ui.agentic_ui import emit_llm_error

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
                        from core.cli.ui.agentic_ui import emit_llm_error

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
                        from core.cli.ui.agentic_ui import emit_model_escalation

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
                        from core.cli.ui.agentic_ui import emit_model_escalation

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
                        from core.cli.ui.agentic_ui import emit_llm_retry

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
                            from core.cli.ui.agentic_ui import emit_budget_warning

                            emit_budget_warning(
                                self._cost_budget,
                                _session_cost,
                                pct=_session_cost / self._cost_budget * 100,
                            )

                    if _session_cost >= self._cost_budget:
                        from core.cli.ui.agentic_ui import emit_cost_budget_exceeded

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
                    self._total_empty_rounds += self._consecutive_text_only_rounds
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
                messages.append({"role": "assistant", "content": assistant_content})
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
                from core.cli.ui.agentic_ui import emit_convergence_detected

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
                from core.cli.ui.agentic_ui import emit_tool_backpressure

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

                        from core.cli.ui.agentic_ui import emit_tool_diversity_forced

                        emit_tool_diversity_forced(_repeated_tool, 5)
                        log.warning(
                            "Diversity forcing: %s called 5x — injecting hint",
                            _repeated_tool,
                        )

            # Accumulate messages for next round
            # Convert content blocks to serializable format
            assistant_content = self._serialize_content(response.content)
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
            round_idx += 1

        # Loop exited via guard — determine reason
        self._op_logger.finalize()
        elapsed = _time.monotonic() - self._loop_start_time
        if self._time_budget_s > 0 and elapsed >= self._time_budget_s:
            from core.cli.ui.agentic_ui import emit_time_budget_expired

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

    def _sync_messages_to_context(self, messages: list[dict[str, Any]]) -> None:
        """Replace context messages with the full messages list.

        During the agentic loop, intermediate tool-use messages are appended
        only to the local ``messages`` list.  This method syncs them back to
        ``self.context`` so the next user turn sees the full history.
        """
        self.context.messages = list(messages)

    def _notify_context_event(
        self, event_type: str, *, original_count: int, new_count: int
    ) -> None:
        """Notify user of context compression. Delegates to ContextWindowManager."""
        self._ctx_mgr._notify_context_event(
            event_type, original_count=original_count, new_count=new_count
        )

    def _maybe_prune_messages(self, messages: list[dict[str, Any]]) -> None:
        """Prune old messages. Delegates to ContextWindowManager."""
        self._ctx_mgr.maybe_prune_messages(messages)

    def _check_context_overflow(self, system: str, messages: list[dict[str, Any]]) -> None:
        """Check context window usage. Delegates to ContextWindowManager."""
        self._ctx_mgr.check_context_overflow(system, messages, self.model, self._provider)

    def _aggressive_context_recovery(self, system: str, messages: list[dict[str, Any]]) -> int:
        """Last-resort context recovery. Delegates to ContextWindowManager."""
        return self._ctx_mgr.aggressive_context_recovery(system, messages, self.model)

    @staticmethod
    def _repair_messages(messages: list[dict[str, Any]]) -> None:
        """Remove orphaned tool_result messages. Delegates to ContextWindowManager."""
        from core.agent.context_manager import ContextWindowManager

        ContextWindowManager.repair_messages(messages)

    def _build_system_prompt(self) -> str:
        """Build the system prompt with skill context and agentic suffix."""
        base = _build_system_prompt(model=self.model)
        # Inject skill context into placeholder
        skill_ctx = ""
        if self._skill_registry is not None:
            skill_ctx = self._skill_registry.get_context_block()
        base = base.replace("{skill_context}", skill_ctx or "No skills loaded.")
        prompt = base + "\n" + AGENTIC_SUFFIX
        if self._system_suffix:
            prompt += "\n\n" + self._system_suffix
        return prompt

    def _try_decompose(self, user_input: str) -> str | None:
        """Attempt to decompose a compound user request into sub-goals.

        Returns a system prompt suffix describing the execution plan,
        or None if the request is simple (single tool call).

        Uses GoalDecomposer with ANTHROPIC_BUDGET (Haiku) for low-cost
        decomposition. Only triggered when compound indicators are present
        in the user input.
        """
        if not self._enable_goal_decomposition:
            return None

        try:
            from core.orchestration.goal_decomposer import GoalDecomposer

            if self._goal_decomposer is None:
                self._goal_decomposer = GoalDecomposer(
                    tool_definitions=self._tools,
                )

            result = self._goal_decomposer.decompose(
                user_input,
                tool_definitions=self._tools,
            )

            if result is None:
                return None

            # Build execution plan hint for the system prompt
            lines = [
                "## Goal Decomposition Plan",
                "",
                f"The user's request has been decomposed into {len(result.goals)} sub-goals.",
                "Execute them in dependency order. For each step, call the specified tool.",
                "If a step depends on a previous step's output, use the result from that step.",
                "",
            ]
            for goal in result.goals:
                deps = ""
                if goal.depends_on:
                    deps = f" (depends on: {', '.join(goal.depends_on)})"
                args_str = ""
                if goal.tool_args:
                    args_str = ", ".join(f"{k}={v!r}" for k, v in goal.tool_args.items())
                lines.append(
                    f"- **{goal.id}**: {goal.description} → `{goal.tool_name}({args_str})`{deps}"
                )

            if result.reasoning:
                lines.append("")
                lines.append(f"Reasoning: {result.reasoning}")

            plan_text = "\n".join(lines)

            # Emit structured event for thin client
            from core.cli.ui.agentic_ui import emit_goal_decomposition

            emit_goal_decomposition([g.description for g in result.goals])
            log.info(
                "GoalDecomposer: injecting %d-step plan into system prompt",
                len(result.goals),
            )
            return plan_text

        except Exception:
            log.debug("Goal decomposition skipped", exc_info=True)
            return None

    def _check_announced_results(self, messages: list[dict[str, Any]]) -> int:
        """Poll for sub-agent announced results and inject into conversation.

        Drains the announce queue for this parent session and adds each
        completed sub-agent's summary as a system event message.

        OpenClaw Spawn+Announce pattern: parent polls at each round start.
        """
        if not self._parent_session_key:
            return 0
        announced: list[SubAgentResult] = drain_announced_results(self._parent_session_key)
        if not announced:
            return 0
        for result in announced:
            status_label = "completed" if result.success else "failed"
            content = (
                f"Sub-agent {status_label}: task_id={result.task_id}, summary={result.summary}"
            )
            if result.error_message:
                content += f", error={result.error_message}"
            self.context.add_system_event("subagent_completed", content)
            messages.append({"role": "user", "content": f"[system:subagent_completed] {content}"})
            log.debug("Injected announce for task_id=%s", result.task_id)
        return len(announced)

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
        _EFFORT_LEVELS = ["low", "medium", "high", "max"]

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
            adaptive_thinking = min(adaptive_thinking, adaptive_thinking // 2)
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

        return response

    def _extract_text(self, response: Any) -> str:
        """Extract text content from response blocks."""
        parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts).strip()

    def _serialize_content(self, content: list[Any]) -> list[dict[str, Any]]:
        """Serialize content blocks to plain dicts for message history."""
        serialized: list[dict[str, Any]] = []
        for block in content:
            if block.type == "text":
                serialized.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serialized.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
        return serialized

    def _track_usage(self, response: Any) -> None:
        """Track token usage for cost monitoring."""
        if not response.usage:
            return
        try:
            from core.cli.ui.agentic_ui import render_tokens
            from core.llm.token_tracker import get_tracker

            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            think_tok = getattr(response.usage, "thinking_tokens", 0) or 0
            tracker = get_tracker()
            usage = tracker.record(
                self.model,
                in_tok,
                out_tok,
                thinking_tokens=think_tok,
            )
            if not self._quiet:
                render_tokens(self.model, in_tok, out_tok, cost_usd=usage.cost_usd)
            log.info(
                "LLM call: model=%s in=%d out=%d think=%d cost=$%.4f",
                self.model,
                in_tok,
                out_tok,
                think_tok,
                usage.cost_usd,
            )

            # Hook: COST_WARNING / COST_LIMIT_EXCEEDED
            if self._hooks:
                from core.config import settings

                cost_limit = getattr(settings, "cost_limit_usd", 0.0)
                if cost_limit > 0:
                    total_cost = tracker.accumulator.total_cost_usd
                    pct = total_cost / cost_limit
                    if pct >= 1.0:
                        self._hooks.trigger(
                            HookEvent.COST_LIMIT_EXCEEDED,
                            {"total_cost_usd": total_cost, "limit_usd": cost_limit},
                        )
                    elif pct >= 0.8:
                        self._hooks.trigger(
                            HookEvent.COST_WARNING,
                            {"total_cost_usd": total_cost, "limit_usd": cost_limit, "pct": pct},
                        )
        except Exception:
            log.debug("Failed to track usage", exc_info=True)

    # ---------------------------------------------------------------------------
    # Feature 3/4: Model escalation on consecutive LLM failures
    # ---------------------------------------------------------------------------

    def _try_model_escalation(self) -> bool:
        """Attempt to escalate to a higher/fallback model after consecutive failures.

        First tries the next model in the current adapter's fallback chain.
        If exhausted, tries cross-provider escalation via CROSS_PROVIDER_FALLBACK.
        Returns True if escalation succeeded, False if at end of all chains.

        Also syncs ``settings.model`` so that ``_sync_model_from_settings()``
        does not revert the escalation on the next round.
        """
        current = self.model
        chain = self._adapter.fallback_chain

        # Find current model in chain, try next
        if current in chain:
            idx = chain.index(current)
            if idx + 1 < len(chain):
                next_model = chain[idx + 1]
                log.warning(
                    "Model escalation: %s -> %s (same provider: %s)",
                    current,
                    next_model,
                    self._provider,
                )
                self.update_model(next_model, self._provider, reason="failure_escalation")
                self._persist_escalated_model(next_model)
                return True

        # Current provider's chain exhausted — try cross-provider (Feature 4)
        from_provider = self._provider
        fallbacks = CROSS_PROVIDER_FALLBACK.get(from_provider, [])
        for fallback_provider, fallback_model in fallbacks:
            if fallback_model != current:
                log.warning(
                    "Cross-provider escalation: %s(%s) -> %s(%s)",
                    current,
                    from_provider,
                    fallback_model,
                    fallback_provider,
                )
                self.update_model(
                    fallback_model, fallback_provider, reason="cross_provider_escalation"
                )
                self._persist_escalated_model(fallback_model)
                # Emit dedicated cross-provider hook for observability
                # (MODEL_SWITCHED is also fired by update_model, but this
                # event carries provider-level context for audit loggers)
                if self._hooks:
                    from core.hooks import HookEvent

                    self._hooks.trigger(
                        HookEvent.FALLBACK_CROSS_PROVIDER,
                        {
                            "from_model": current,
                            "to_model": fallback_model,
                            "from_provider": from_provider,
                            "to_provider": fallback_provider,
                        },
                    )
                return True

        log.warning("Model escalation failed: no more fallback models available")
        return False

    @staticmethod
    def _persist_escalated_model(model: str) -> None:
        """Sync escalated model to settings so _sync_model_from_settings() won't revert."""
        try:
            from core.config import settings

            settings.model = model
        except Exception:
            log.debug("Failed to persist escalated model to settings", exc_info=True)

    def _try_cross_provider_escalation(self) -> bool:
        """Skip intra-provider chain and go directly to cross-provider fallback.

        Used for auth errors where all models in the same provider share
        the same expired key — cycling within the chain is pointless.
        """
        from_provider = self._provider
        current = self.model
        fallbacks = CROSS_PROVIDER_FALLBACK.get(from_provider, [])
        for fallback_provider, fallback_model in fallbacks:
            if fallback_model != current:
                log.warning(
                    "Auth-triggered cross-provider escalation: %s(%s) -> %s(%s)",
                    current,
                    from_provider,
                    fallback_model,
                    fallback_provider,
                )
                self.update_model(fallback_model, fallback_provider, reason="auth_cross_provider")
                self._persist_escalated_model(fallback_model)
                if self._hooks:
                    from core.hooks import HookEvent

                    self._hooks.trigger(
                        HookEvent.FALLBACK_CROSS_PROVIDER,
                        {
                            "from_model": current,
                            "to_model": fallback_model,
                            "from_provider": from_provider,
                            "to_provider": fallback_provider,
                        },
                    )
                return True
        return False

    # ---------------------------------------------------------------------------
    # Feature 5: Backpressure on tool failures
    # Feature 6: Convergence detection (stuck loop)
    # ---------------------------------------------------------------------------

    def _update_tool_error_tracking(self, tool_results: list[dict[str, Any]]) -> None:
        """Update tool error tracking. Delegates to ConvergenceDetector."""
        self._convergence.update_tool_error_tracking(tool_results, self._tool_processor.tool_log)

    def _check_convergence_break(self) -> bool:
        """Check for stuck loop. Delegates to ConvergenceDetector."""
        return self._convergence.check_convergence_break()
