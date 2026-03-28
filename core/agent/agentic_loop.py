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
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.agent.conversation import ConversationContext
from core.agent.error_recovery import ErrorRecoveryStrategy
from core.agent.sub_agent import SubAgentResult, drain_announced_results
from core.agent.system_prompt import build_system_prompt as _build_system_prompt
from core.agent.tool_executor import (
    ToolCallProcessor,
    ToolExecutor,
)
from core.cli.agentic_response import AgenticResponse
from core.cli.ui.agentic_ui import OperationLogger
from core.cli.ui.status import TextSpinner
from core.config import (
    ANTHROPIC_PRIMARY,
    _resolve_provider,
)
from core.hooks import HookEvent, HookSystem
from core.llm.errors import BillingError, UserCancelledError
from core.llm.prompts import AGENTIC_SUFFIX
from core.llm.router import (
    CROSS_PROVIDER_FALLBACK,
    maybe_traceable,
    resolve_agentic_adapter,
)

if TYPE_CHECKING:
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Load base tool definitions from centralized JSON
_TOOLS_JSON_PATH = Path(__file__).resolve().parent.parent / "tools" / "definitions.json"
_BASE_TOOLS: list[dict[str, Any]] = json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8"))

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
    if registry:
        existing_names = {t["name"] for t in tools}
        for tool_def in registry.to_anthropic_tools():
            if tool_def["name"] not in existing_names:
                tools.append(tool_def)
    # Merge MCP tools into the unified list
    if mcp_tools:
        existing_names = {t["name"] for t in tools}
        for mcp_tool in mcp_tools:
            if mcp_tool.get("name") not in existing_names:
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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


class AgenticLoop:
    """Claude Code-style agentic execution loop.

    while stop_reason == "tool_use":
        execute tools → feed results back → continue
    """

    DEFAULT_MAX_ROUNDS = 50
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
        self._time_budget_s = time_budget_s
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

        # Feature 5: Backpressure on consecutive tool failures
        self._total_consecutive_tool_errors: int = 0

        # Feature 6: Convergence detection (stuck loop)
        self._recent_errors: list[str] = []
        self._convergence_escalated: bool = False

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
            self._transcript.record_session_end(rounds=rounds)
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
        self._record_transcript_end(result)
        self._save_checkpoint(user_input, round_idx=round_idx)
        if self._hooks:
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
        return result

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

    def update_model(self, model: str, provider: str | None = None) -> None:
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

        # Fire MODEL_SWITCHED hook for observability
        if self._hooks and old_model != model:
            from core.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.MODEL_SWITCHED,
                {
                    "from_model": old_model,
                    "to_model": model,
                    "reason": "user_switch",
                },
            )

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

        # Add user message to conversation context
        self.context.add_user_message(user_input)

        # Transcript: session start + user message
        if self._transcript is not None:
            self._transcript.record_session_start(model=self.model, provider=self._provider)
            self._transcript.record_user_message(user_input)
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

            # Poll for sub-agent announced results (OpenClaw Spawn+Announce)
            self._check_announced_results(messages)

            # Show spinner while waiting for LLM response
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
                log.warning("Context exhausted: %s", exc)
                self._notify_context_event(
                    "exhausted",
                    original_count=len(messages),
                    new_count=len(messages),
                )
                self._sync_messages_to_context(messages)
                result = AgenticResult(
                    text=(
                        "Context window exhausted after pruning. "
                        "Your conversation is preserved — start a new request "
                        "or use /compact to manually reduce context."
                    ),
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

            if response is None:
                # Feature 3/4: Model escalation on consecutive LLM failures
                self._consecutive_llm_failures += 1
                if self._consecutive_llm_failures >= self._ESCALATION_THRESHOLD:
                    escalated = self._try_model_escalation()
                    if escalated:
                        # Retry with escalated model — continue to next round iteration
                        log.info(
                            "Model escalated after %d consecutive failures, retrying",
                            self._consecutive_llm_failures,
                        )
                        self._consecutive_llm_failures = 0
                        continue

                # Persist intermediate tool-use messages so next turn sees them
                self._sync_messages_to_context(messages)
                detail = self._last_llm_error or "unknown error"
                text = (
                    f"LLM call failed ({detail}). "
                    "Your conversation context is preserved — try again."
                )
                result = AgenticResult(
                    text=text,
                    rounds=round_idx + 1,
                    error="llm_call_failed",
                    termination_reason="llm_error",
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
                    if _session_cost >= self._cost_budget:
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

            if self._total_consecutive_tool_errors >= 3:
                # Backpressure: inject a cooldown hint
                await asyncio.sleep(1.0)
                backpressure_hint = {
                    "type": "text",
                    "text": (
                        "[system] Multiple tools are failing consecutively. "
                        "Consider a different approach."
                    ),
                }
                tool_results.append(backpressure_hint)

            # Feature 8: Diversity forcing — prevent same tool 5x consecutively
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    self._consecutive_tool_tracker.append(getattr(block, "name", ""))
            if len(self._consecutive_tool_tracker) > 10:
                self._consecutive_tool_tracker = self._consecutive_tool_tracker[-10:]
            if len(self._consecutive_tool_tracker) >= 5:
                _last_5 = self._consecutive_tool_tracker[-5:]
                if len(set(_last_5)) == 1:
                    _repeated_tool = _last_5[0]
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

    def _maybe_prune_messages(self, messages: list[dict[str, Any]]) -> None:
        """Prune old messages when conversation exceeds 5 rounds (10 msgs).

        Keeps first user message + bridge + recent messages for context budget.
        Ensures:
        1. user/assistant alternation is preserved
        2. No orphaned tool_result messages (each tool_result must follow
           an assistant message containing the matching tool_use block)
        """
        if len(messages) <= 30:
            return
        first = messages[0]
        # Walk backward to find a safe cut point:
        # - Must be a "user" role message
        # - Must NOT be a tool_result message (those need a preceding tool_use)
        # Start from -4 and go back until we find a plain user text message
        safe_cut = None
        for candidate in range(-4, -(len(messages)), -1):
            idx = len(messages) + candidate
            if idx <= 0:
                break
            msg = messages[idx]
            if msg["role"] != "user":
                continue
            # Check if this is a tool_result message
            content = msg.get("content")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                continue  # Skip — orphaned tool_result after pruning
            safe_cut = candidate
            break

        if safe_cut is None:
            # No safe cut found — don't prune to avoid corruption
            return

        recent = messages[safe_cut:]
        bridge: dict[str, Any] = {
            "role": "assistant",
            "content": [{"type": "text", "text": "(earlier rounds omitted)"}],
        }
        messages.clear()
        messages.extend([first, bridge, *recent])
        log.debug("Pruned messages: kept first + bridge + %d recent", len(recent))

    def _check_context_overflow(self, system: str, messages: list[dict[str, Any]]) -> None:
        """Check context window usage and apply provider-aware compression.

        Strategy by provider:
        - Anthropic: server-side compaction (compact_20260112) handles 80%+ automatically.
          Client only intervenes at 95% as emergency prune safety net.
        - OpenAI/GLM: no server-side compaction. Client triggers LLM-based compaction
          at 80% and emergency prune at 95%.

        Compression strategy is delegated to the CONTEXT_OVERFLOW_ACTION hook handler.
        If no handler is registered or all fail, falls back to hardcoded defaults.
        """
        try:
            from core.config import settings
            from core.orchestration.context_monitor import check_context

            metrics = check_context(messages, self.model, system_prompt=system)

            if metrics.is_critical:
                log.warning(
                    "Context CRITICAL: %.0f%% (%d/%d tokens) — emergency action",
                    metrics.usage_pct,
                    metrics.estimated_tokens,
                    metrics.context_window,
                )
                if self._hooks:
                    self._hooks.trigger(
                        HookEvent.CONTEXT_CRITICAL,
                        {"metrics": dataclasses.asdict(metrics), "model": self.model},
                    )

                strategy = self._resolve_overflow_strategy(metrics, settings)
                self._apply_overflow_strategy(strategy, messages, settings)

                # Re-check: if still critical after pruning, context is exhausted
                post = check_context(messages, self.model, system_prompt=system)
                if post.is_critical:
                    raise _ContextExhaustedError(
                        f"Context exhausted: {post.usage_pct:.0f}% after pruning"
                    )

            elif metrics.is_warning:
                # For non-Anthropic providers, 80% triggers client compaction
                strategy = self._resolve_overflow_strategy(metrics, settings)
                if strategy.get("strategy") == "compact":
                    self._apply_overflow_strategy(strategy, messages, settings)
                elif self._provider == "anthropic":
                    log.info(
                        "Context at %.0f%% — server-side compaction will handle cleanup",
                        metrics.usage_pct,
                    )
                else:
                    log.info(
                        "Context at %.0f%% — below compaction threshold",
                        metrics.usage_pct,
                    )
        except Exception:
            log.debug("Context monitor check failed", exc_info=True)

    def _apply_overflow_strategy(
        self,
        strategy: dict[str, Any],
        messages: list[dict[str, Any]],
        settings: Any,
    ) -> None:
        """Execute the overflow strategy (prune or compact)."""
        from core.orchestration.context_monitor import prune_oldest_messages

        action = strategy.get("strategy", "none")
        keep_recent = strategy.get("keep_recent", settings.compact_keep_recent)

        if action == "compact":
            import asyncio

            from core.orchestration.compaction import compact_conversation

            try:
                new_msgs, did_compact = asyncio.get_event_loop().run_until_complete(
                    compact_conversation(
                        messages,
                        provider=self._provider,
                        model=self.model,
                        keep_recent=keep_recent,
                    )
                )
                if did_compact:
                    original_count = len(messages)
                    messages.clear()
                    messages.extend(new_msgs)
                    self._notify_context_event(
                        "compact",
                        original_count=original_count,
                        new_count=len(new_msgs),
                    )
                    return
            except Exception:
                log.warning("Client compaction failed — falling back to prune", exc_info=True)
            # Fall through to prune on failure
            action = "prune"

        if action == "prune":
            pruned = prune_oldest_messages(messages, keep_recent=keep_recent)
            original_count = len(messages)
            if len(pruned) < original_count:
                messages.clear()
                messages.extend(pruned)
                log.info(
                    "Emergency pruned: %d → %d messages (keep_recent=%d)",
                    original_count,
                    len(pruned),
                    keep_recent,
                )
                self._notify_context_event(
                    "prune",
                    original_count=original_count,
                    new_count=len(pruned),
                )

    def _notify_context_event(
        self,
        event_type: str,
        *,
        original_count: int,
        new_count: int,
    ) -> None:
        """Notify user of automatic context compression via UI."""
        if self._quiet:
            return
        try:
            from core.cli.ui.agentic_ui import render_context_event

            render_context_event(event_type, original_count=original_count, new_count=new_count)
        except Exception:
            log.debug("Context event notification failed", exc_info=True)

    def _resolve_overflow_strategy(self, metrics: Any, settings: Any) -> dict[str, Any]:
        """Ask CONTEXT_OVERFLOW_ACTION hook for compression strategy, with fallback.

        Returns a dict with at least ``strategy`` key. If no handler responds
        or all handlers fail, returns the hardcoded default strategy.

        Provider-aware: passes self._provider so the hook can differentiate
        between Anthropic (server-side compaction) and others (client-side).
        """
        if self._hooks:
            results = self._hooks.trigger_with_result(
                HookEvent.CONTEXT_OVERFLOW_ACTION,
                {
                    "metrics": dataclasses.asdict(metrics),
                    "model": self.model,
                    "provider": self._provider,
                },
            )
            for result in results:
                if result.success and result.data.get("strategy"):
                    return result.data

        # Fallback: hardcoded default (no handler registered or all failed)
        keep_recent = settings.compact_keep_recent
        if self._provider == "anthropic":
            # Anthropic: server-side handles it, only emergency prune at 95%
            if metrics.usage_pct >= 95:
                return {"strategy": "prune", "keep_recent": keep_recent}
            return {"strategy": "none"}

        # Non-Anthropic: compact at 80%, prune at 95%
        if metrics.context_window < 200_000:
            keep_recent = min(keep_recent, 5)
        if metrics.usage_pct >= 95:
            return {"strategy": "prune", "keep_recent": keep_recent}
        elif metrics.usage_pct >= 80:
            return {"strategy": "compact", "keep_recent": keep_recent}
        return {"strategy": "none"}

    @staticmethod
    def _repair_messages(messages: list[dict[str, Any]]) -> None:
        """Remove orphaned tool_result messages that lack a preceding tool_use.

        Scans backward and removes any user message whose content is entirely
        tool_result blocks without matching tool_use in the prior assistant msg.
        Also syncs the repair back to context via mutation in place.
        """
        i = len(messages) - 1
        while i >= 1:
            msg = messages[i]
            if msg["role"] != "user":
                i -= 1
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                i -= 1
                continue
            # Check if ALL blocks are tool_result
            tr_ids = {
                b["tool_use_id"]
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result"
            }
            if not tr_ids:
                i -= 1
                continue
            # Check preceding assistant message for matching tool_use
            if i > 0 and messages[i - 1]["role"] == "assistant":
                prev_content = messages[i - 1].get("content", [])
                if isinstance(prev_content, list):
                    tu_ids = {
                        b.get("id")
                        for b in prev_content
                        if isinstance(b, dict) and b.get("type") == "tool_use"
                    }
                    if tr_ids <= tu_ids:
                        i -= 1
                        continue  # All tool_results have matching tool_use — OK
            # Orphaned — remove this tool_result message and its preceding
            # assistant message (which also lost its tool_use context)
            log.debug("Removing orphaned tool_result at index %d", i)
            messages.pop(i)
            # Also remove the preceding assistant message if it's a bridge/text
            if i > 0 and messages[i - 1]["role"] == "assistant":
                prev_c = messages[i - 1].get("content", [])
                if isinstance(prev_c, list):
                    has_tool_use = any(
                        isinstance(b, dict) and b.get("type") == "tool_use" for b in prev_c
                    )
                    if not has_tool_use:
                        messages.pop(i - 1)
                        i -= 1
            i -= 1

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

        response = await self._adapter.agentic_call(
            model=self.model,
            system=system,
            messages=messages,
            tools=self._tools,
            tool_choice=tool_choice,
            max_tokens=self.max_tokens,
            temperature=0.0,
        )

        if response is None:
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
            usage = get_tracker().record(self.model, in_tok, out_tok)
            if not self._quiet:
                render_tokens(self.model, in_tok, out_tok, cost_usd=usage.cost_usd)
            log.info(
                "LLM call: model=%s in=%d out=%d cost=$%.4f",
                self.model,
                in_tok,
                out_tok,
                usage.cost_usd,
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
                self.update_model(next_model, self._provider)
                return True

        # Current provider's chain exhausted — try cross-provider (Feature 4)
        fallbacks = CROSS_PROVIDER_FALLBACK.get(self._provider, [])
        for fallback_provider, fallback_model in fallbacks:
            if fallback_model != current:
                log.warning(
                    "Cross-provider escalation: %s(%s) -> %s(%s)",
                    current,
                    self._provider,
                    fallback_model,
                    fallback_provider,
                )
                self.update_model(fallback_model, fallback_provider)
                return True

        log.warning("Model escalation failed: no more fallback models available")
        return False

    # ---------------------------------------------------------------------------
    # Feature 5: Backpressure on tool failures
    # Feature 6: Convergence detection (stuck loop)
    # ---------------------------------------------------------------------------

    def _update_tool_error_tracking(self, tool_results: list[dict[str, Any]]) -> None:
        """Update consecutive tool error tracking and recent error history.

        Processes a batch of tool results from the current round.
        Resets the consecutive counter on any success, increments on all-error rounds.
        Appends normalized error keys to _recent_errors for convergence detection.
        """
        has_success = False
        has_error = False

        for tr in tool_results:
            # Parse content JSON to check for errors
            content = tr.get("content", "")
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    parsed = {}
            else:
                parsed = content if isinstance(content, dict) else {}

            if isinstance(parsed, dict) and parsed.get("error"):
                has_error = True
                # Feature 6: append normalized error key
                tool_use_id = tr.get("tool_use_id", "")
                error_str = str(parsed.get("error", ""))[:50]
                # Extract tool name from tool_log (most recent entries)
                tool_name = "unknown"
                for entry in reversed(self._tool_processor.tool_log):
                    if tool_use_id and entry.get("tool") and isinstance(entry.get("result"), dict):
                        tool_name = entry["tool"]
                        break
                error_key = f"{tool_name}:{error_str}"
                self._recent_errors.append(error_key)
                # Keep last 6 entries max
                if len(self._recent_errors) > 6:
                    self._recent_errors = self._recent_errors[-6:]
            else:
                has_success = True

        if has_success:
            self._total_consecutive_tool_errors = 0
        elif has_error:
            self._total_consecutive_tool_errors += 1

    def _check_convergence_break(self) -> bool:
        """Check if the loop is stuck in a repeating failure pattern.

        On first detection of 3 identical errors, attempts model escalation
        (runtime ratchet — Karpathy P4) instead of breaking immediately.
        Only breaks after escalation has been tried and errors persist.
        """
        if len(self._recent_errors) < 3:
            return False

        # Check last 3 entries for identical pattern
        last_3 = self._recent_errors[-3:]
        if last_3[0] == last_3[1] == last_3[2]:
            # Runtime ratchet: try model escalation before giving up
            if not self._convergence_escalated:
                self._convergence_escalated = True
                log.warning(
                    "Convergence detected (%s x3) — escalating model",
                    last_3[0],
                )
                escalated = self._try_model_escalation()
                if escalated:
                    self._recent_errors.clear()
                    return False  # Give escalated model a chance
                # Escalation failed (no fallback) — fall through to break check

            # Already escalated and still stuck — check for 4+ identical
            if len(self._recent_errors) >= 4:
                last_4 = self._recent_errors[-4:]
                if last_4[0] == last_4[1] == last_4[2] == last_4[3]:
                    log.warning(
                        "Convergence detected after escalation: 4+ identical errors '%s'",
                        last_4[0],
                    )
                    return True
            # 3 identical post-escalation — log warning, don't break yet
            log.warning(
                "Convergence warning (post-escalation): 3 identical errors '%s'",
                last_3[0],
            )
        return False
