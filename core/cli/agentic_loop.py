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

from core.cli.agentic_response import AgenticResponse
from core.cli.conversation import ConversationContext
from core.cli.error_recovery import ErrorRecoveryStrategy
from core.cli.sub_agent import SubAgentResult, drain_announced_results
from core.cli.system_prompt import build_system_prompt as _build_system_prompt
from core.cli.tool_executor import (
    AUTO_APPROVED_MCP_SERVERS,
    DANGEROUS_TOOLS,
    EXPENSIVE_TOOLS,
    SAFE_TOOLS,
    WRITE_TOOLS,
    ToolExecutor,
)
from core.config import (
    ANTHROPIC_PRIMARY,
    _resolve_provider,
    settings,
)
from core.infrastructure.adapters.llm.agentic_registry import (
    CROSS_PROVIDER_FALLBACK,
    resolve_agentic_adapter,
)
from core.infrastructure.ports.agentic_llm_port import UserCancelledError
from core.llm.client import maybe_traceable
from core.llm.prompts import AGENTIC_SUFFIX
from core.orchestration.hooks import HookEvent, HookSystem
from core.ui.agentic_ui import OperationLogger
from core.ui.status import TextSpinner

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


def _guard_tool_result(
    result: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Truncate oversized tool results while preserving summary.

    When *max_tokens* is 0 (default), no truncation is performed.
    """
    if max_tokens is None:
        max_tokens = settings.max_tool_result_tokens
    if max_tokens <= 0:
        return result
    try:
        serialized = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return result
    estimated_tokens = len(serialized) // 4
    if estimated_tokens <= max_tokens:
        return result
    # Preserve summary if present (SubAgentResult always has one)
    if "summary" in result:
        guarded: dict[str, Any] = {
            "summary": result["summary"],
            "_truncated": True,
            "_original_tokens": estimated_tokens,
        }
        # Keep lightweight fields
        for key in ("task_id", "task_type", "status", "error_message", "tier"):
            if key in result:
                guarded[key] = result[key]
        return guarded
    # No summary — return preview
    return {
        "_truncated": True,
        "_original_tokens": estimated_tokens,
        "preview": serialized[: max_tokens * 4],
    }


@dataclass
class AgenticResult:
    """Result of an agentic loop execution."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    error: str | None = None
    termination_reason: str = "unknown"  # "natural" | "forced_text" | "max_rounds" | "llm_error"

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
    MAX_CLARIFICATION_ROUNDS = 3
    WRAP_UP_HEADROOM = 2  # force text response N rounds before max

    def __init__(
        self,
        context: ConversationContext,
        tool_executor: ToolExecutor,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str | None = None,
        provider: str = "anthropic",
        tool_registry: ToolRegistry | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        hooks: HookSystem | None = None,
        enable_goal_decomposition: bool = True,
        parent_session_key: str = "",
        system_suffix: str = "",
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self._parent_session_key = parent_session_key
        self._system_suffix = system_suffix
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.model = model or ANTHROPIC_PRIMARY
        self._provider = provider  # "anthropic", "openai", or "glm"
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._hooks = hooks
        # Unified tool assembly: merge native + MCP tools together
        mcp_tool_list = mcp_manager.get_all_tools() if mcp_manager is not None else None
        self._tools = get_agentic_tools(tool_registry, mcp_tools=mcp_tool_list)
        self._tool_log: list[dict[str, Any]] = []
        self._consecutive_failures: dict[str, int] = {}
        self._last_llm_error: str | None = None  # last error type for user message
        self._adapter = resolve_agentic_adapter(self._provider)
        self._op_logger = OperationLogger()
        self._error_recovery = ErrorRecoveryStrategy(tool_executor)

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

        # Tier 1 transcript: append-only JSONL event stream (snapshot-redesign)
        self._transcript: Any | None = None
        self._session_id: str = ""
        try:
            import uuid as _uuid

            from core.cli.transcript import SessionTranscript

            self._session_id = f"s-{_uuid.uuid4().hex[:12]}"
            self._transcript = SessionTranscript(self._session_id)
        except Exception:
            log.debug("Transcript init failed", exc_info=True)

        # C3 checkpoint: full message persistence for /resume (Claude Code pattern)
        self._checkpoint: Any | None = None
        try:
            from core.cli.session_checkpoint import SessionCheckpoint

            self._checkpoint = SessionCheckpoint()
        except Exception:
            log.debug("SessionCheckpoint init failed", exc_info=True)

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
                tool_log=self._tool_log,
                user_input=user_input,
            )
            self._checkpoint.save(state)
        except Exception:
            log.debug("Checkpoint save failed", exc_info=True)

    def mark_session_completed(self) -> None:
        """Mark the current session as completed (called on clean REPL exit)."""
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
        new_provider = provider or _resolve_provider(model)
        if new_provider != self._provider:
            self._provider = new_provider
            self._adapter = resolve_agentic_adapter(new_provider)
        self.model = model

        # Sync SessionMeter so "Worked for" status line shows the correct model
        from core.ui.agentic_ui import update_session_model

        update_session_model(model)
        log.info("AgenticLoop model updated: %s (provider=%s)", model, self._provider)

    def run(self, user_input: str) -> AgenticResult:
        """Sync wrapper — delegates to ``arun()`` via ``asyncio.run()``."""
        result: AgenticResult = asyncio.run(self.arun(user_input))
        return result

    @maybe_traceable(run_type="chain", name="AgenticLoop.run")  # type: ignore[untyped-decorator]
    async def arun(self, user_input: str) -> AgenticResult:
        """Run the agentic loop until LLM emits end_turn or max rounds."""
        self._tool_log = []
        self._clarification_count = 0
        self._consecutive_failures.clear()
        self._op_logger.reset()

        # Goal decomposition: try to decompose compound requests into sub-goal DAGs.
        # If successful, inject the decomposition plan into the system prompt so the
        # LLM executes sub-goals in the correct dependency order.
        decomposition_hint = self._try_decompose(user_input)

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

        for round_idx in range(self.max_rounds):
            is_last_round = round_idx == self.max_rounds - 1
            self._op_logger.begin_round("AgenticLoop")

            # Poll for sub-agent announced results (OpenClaw Spawn+Announce)
            self._check_announced_results(messages)

            # Show spinner while waiting for LLM response
            label = "Thinking..." if round_idx == 0 else f"Thinking... (round {round_idx + 1})"
            _spinner = TextSpinner(f"✢ {label}")
            _spinner.start()
            try:
                response = await self._call_llm(system_prompt, messages, round_idx=round_idx)
            except UserCancelledError:
                _spinner.stop()
                log.info("LLM call interrupted by user")
                return AgenticResult(
                    text="Interrupted.",
                    rounds=round_idx + 1,
                    termination_reason="user_cancelled",
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
                log.info(
                    "AgenticLoop: reason=%s rounds=%d/%d tools=%d",
                    result.termination_reason,
                    result.rounds,
                    self.max_rounds,
                    len(result.tool_calls),
                )
                self._record_transcript_end(result)
                self._save_checkpoint(user_input, round_idx=round_idx + 1)
                return result

            # Successful LLM response — reset failure counter
            self._consecutive_llm_failures = 0

            # Track usage + Claude Code-style token display
            self._track_usage(response)

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
                    tool_calls=self._tool_log,
                    rounds=round_idx + 1,
                    termination_reason=reason,
                )
                log.info(
                    "AgenticLoop: reason=%s rounds=%d/%d tools=%d",
                    result.termination_reason,
                    result.rounds,
                    self.max_rounds,
                    len(result.tool_calls),
                )
                self._record_transcript_end(result)
                self._save_checkpoint(user_input, round_idx=round_idx + 1)
                return result

            tool_results = await self._process_tool_calls(response)

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
                    tool_calls=self._tool_log,
                    rounds=round_idx + 1,
                    error="convergence_detected",
                    termination_reason="convergence_detected",
                )
                log.info(
                    "AgenticLoop: reason=%s rounds=%d/%d tools=%d",
                    result.termination_reason,
                    result.rounds,
                    self.max_rounds,
                    len(result.tool_calls),
                )
                self._record_transcript_end(result)
                self._save_checkpoint(user_input, round_idx=round_idx + 1)
                return result

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

            # Accumulate messages for next round
            # Convert content blocks to serializable format
            assistant_content = self._serialize_content(response.content)
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

        # Max rounds reached — persist what we have
        self._op_logger.finalize()
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Max agentic rounds reached."}],
            }
        )
        self._sync_messages_to_context(messages)
        result = AgenticResult(
            text="Max agentic rounds reached. Please try a more specific request.",
            tool_calls=self._tool_log,
            rounds=self.max_rounds,
            error="max_rounds",
            termination_reason="max_rounds",
        )
        log.info(
            "AgenticLoop: reason=%s rounds=%d/%d tools=%d",
            result.termination_reason,
            result.rounds,
            self.max_rounds,
            len(result.tool_calls),
        )
        self._record_transcript_end(result)
        self._save_checkpoint(user_input, round_idx=self.max_rounds)
        return result

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
        """Check context window usage and emit hooks if near limits.

        GAP 7 strategy:
        - WARNING (80%): LLM-based compaction (summarize older messages)
        - CRITICAL (95%): Emergency mechanical prune + tool_result truncation
        """
        try:
            from core.config import settings
            from core.orchestration.context_monitor import (
                check_context,
                prune_oldest_messages,
            )

            keep_recent = settings.compact_keep_recent
            metrics = check_context(messages, self.model, system_prompt=system)

            if metrics.is_critical:
                log.warning(
                    "Context CRITICAL: %.0f%% (%d/%d tokens)",
                    metrics.usage_pct,
                    metrics.estimated_tokens,
                    metrics.context_window,
                )
                if self._hooks:
                    self._hooks.trigger(
                        HookEvent.CONTEXT_CRITICAL,
                        {"metrics": dataclasses.asdict(metrics), "model": self.model},
                    )
                # Emergency: truncate large tool_result content in remaining messages
                self._truncate_tool_results(messages, max_chars=2000)
                # Emergency prune: keep first + last N messages
                pruned = prune_oldest_messages(messages, keep_recent=keep_recent)
                original_count = len(messages)
                if len(pruned) < original_count:
                    messages.clear()
                    messages.extend(pruned)
                    log.info(
                        "Emergency pruned conversation: %d → %d messages",
                        original_count,
                        len(pruned),
                    )
            elif metrics.is_warning:
                log.info(
                    "Context WARNING: %.0f%% (%d/%d tokens) — attempting compaction",
                    metrics.usage_pct,
                    metrics.estimated_tokens,
                    metrics.context_window,
                )
                if self._hooks:
                    self._hooks.trigger(
                        HookEvent.CONTEXT_WARNING,
                        {"metrics": dataclasses.asdict(metrics), "model": self.model},
                    )
                # GAP 7: LLM-based context compaction
                try:
                    from core.orchestration.context_compactor import compact_context

                    result = compact_context(messages, keep_recent=keep_recent)
                    if result.tokens_saved_estimate > 0:
                        log.info(
                            "Compaction saved ~%d tokens (%d→%d messages)",
                            result.tokens_saved_estimate,
                            result.original_count,
                            result.compacted_count,
                        )
                except Exception:
                    log.debug("Context compaction failed, falling back to prune", exc_info=True)
                    pruned = prune_oldest_messages(messages, keep_recent=keep_recent)
                    if len(pruned) < len(messages):
                        messages.clear()
                        messages.extend(pruned)
        except Exception:
            log.debug("Context monitor check failed", exc_info=True)

    @staticmethod
    def _truncate_tool_results(messages: list[dict[str, Any]], *, max_chars: int = 2000) -> None:
        """Truncate large tool_result content blocks to free context space.

        Extractive pattern: preserves first max_chars of text content,
        appends [truncated] marker. Only modifies tool_result blocks.
        """
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if isinstance(inner, str) and len(inner) > max_chars:
                    block["content"] = inner[:max_chars] + "\n[truncated]"
                elif isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            text = sub.get("text", "")
                            if len(text) > max_chars:
                                sub["text"] = text[:max_chars] + "\n[truncated]"

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

        remaining = self.max_rounds - round_idx
        force_text = remaining <= self.WRAP_UP_HEADROOM
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

    _MAX_CONSECUTIVE_FAILURES = 2  # auto-skip after N consecutive failures per tool

    async def _process_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        """Execute tool_use blocks — parallel when multiple, sequential when single.

        When the LLM returns 2+ tool_use blocks in one response, executes them
        concurrently via ``asyncio.gather`` (frontier pattern: runtime handles
        parallelism, LLM just calls tools).  Single tool_use falls through to
        the sequential path for zero-overhead backward compatibility.

        Tracks consecutive failures per tool name.  After _MAX_CONSECUTIVE_FAILURES
        for the same tool, triggers the adaptive error recovery chain:
        retry → alternative tool → cheaper fallback → escalate.
        """
        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        if len(tool_blocks) <= 1:
            return await self._execute_tools_sequential(tool_blocks)

        # Multiple tools: parallel execution via asyncio.gather
        return await self._execute_tools_parallel(tool_blocks)

    async def _execute_single_tool(self, block: Any) -> dict[str, Any]:
        """Execute a single tool_use block and return its processed result dict.

        Handles consecutive failure tracking, recovery, clarification guards,
        logging, tool_log bookkeeping, and token guard — the same per-tool
        logic shared by both sequential and parallel paths.

        Returns a dict ready to be used as a tool_result content block
        (with ``type``, ``tool_use_id``, ``content`` keys).
        """
        tool_name = block.name
        tool_input: dict[str, Any] = block.input

        log.info("AgenticLoop: tool_use %s(%s)", tool_name, tool_input)

        # Check consecutive failure count
        fail_count = self._consecutive_failures.get(tool_name, 0)

        if fail_count >= self._MAX_CONSECUTIVE_FAILURES:
            # Adaptive recovery: try recovery chain instead of auto-skip
            result = await self._attempt_recovery(tool_name, tool_input, fail_count)
            visible = self._op_logger.log_tool_call(tool_name, tool_input)
            self._op_logger.log_tool_result(tool_name, result, visible=visible)
        else:
            # Progressive log: show tool call before execution
            visible = self._op_logger.log_tool_call(tool_name, tool_input)

            # Execute via ToolExecutor (sync handlers wrapped in to_thread)
            result = await asyncio.to_thread(self.executor.execute, tool_name, tool_input)

        # Track consecutive failures
        if isinstance(result, dict) and result.get("error"):
            # Don't increment if recovery was attempted (already handled)
            if not result.get("recovery_attempted"):
                self._consecutive_failures[tool_name] = fail_count + 1
        else:
            self._consecutive_failures[tool_name] = 0

        # Track clarification rounds to prevent infinite loops
        if isinstance(result, dict) and result.get("clarification_needed"):
            self._clarification_count += 1
            if self._clarification_count > self.MAX_CLARIFICATION_ROUNDS:
                result = {
                    "error": (
                        "Too many clarification attempts. Please provide all required parameters."
                    ),
                    "max_clarifications_exceeded": True,
                }

        # Progressive log: show tool result summary (skip if already logged)
        skip_log = result.get("skipped") or result.get("recovery_attempted")
        if isinstance(result, dict) and not skip_log:
            self._op_logger.log_tool_result(tool_name, result, visible=visible)

        # Transcript: tool_call + tool_result events
        if self._transcript is not None:
            self._transcript.record_tool_call(tool_name, tool_input)
            status = "error" if isinstance(result, dict) and result.get("error") else "ok"
            summary = ""
            if isinstance(result, dict):
                summary = str(result.get("summary", result.get("error", "")))
            self._transcript.record_tool_result(tool_name, status, summary)

        self._tool_log.append(
            {
                "tool": tool_name,
                "input": tool_input,
                "result": result,
            }
        )

        # Token guard: truncate oversized results to prevent context explosion
        if isinstance(result, dict):
            result = _guard_tool_result(result)

        # Serialize result as JSON for LLM (not Python repr)
        try:
            content = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(result)

        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }

    async def _execute_tools_sequential(self, tool_blocks: list[Any]) -> list[dict[str, Any]]:
        """Execute tool blocks one by one (single-tool fast path)."""
        tool_results: list[dict[str, Any]] = []
        for block in tool_blocks:
            tool_result = await self._execute_single_tool(block)
            tool_results.append(tool_result)
        return tool_results

    # -- Tier classification for parallel execution --------------------------

    @staticmethod
    def _classify_tool_tier(tool_name: str, mcp_manager: Any | None = None) -> int:
        """Classify a tool into a safety tier for parallel execution.

        TIER 0: SAFE tools — auto-execute, no gate
        TIER 1: MCP auto-approved — auto-execute, logged
        TIER 2: EXPENSIVE tools — batch cost confirmation, then parallel
        TIER 3: WRITE tools — individual approval, sequential
        TIER 4: DANGEROUS tools — individual approval, sequential
        Unclassified (STANDARD) tools default to TIER 0 (parallel-safe).
        """
        if tool_name in DANGEROUS_TOOLS:
            return 4
        if tool_name in WRITE_TOOLS:
            return 3
        if tool_name in EXPENSIVE_TOOLS:
            return 2
        # Check if this is an MCP tool from an auto-approved server
        if mcp_manager is not None:
            server = mcp_manager.find_server_for_tool(tool_name)
            if server is not None:
                if server in AUTO_APPROVED_MCP_SERVERS:
                    return 1
                # Non-auto-approved MCP tools need per-server approval —
                # treat as sequential (tier 3) to avoid parallel prompts
                return 3
        if tool_name in SAFE_TOOLS:
            return 0
        # STANDARD tools (analyze_ip without expensive, delegate, etc.)
        # are parallel-safe — no HITL gate.
        return 0

    async def _execute_tools_parallel(self, tool_blocks: list[Any]) -> list[dict[str, Any]]:
        """Execute 2+ tool blocks with tiered batch approval.

        Tier classification:
          TIER 0-1 (SAFE/MCP auto-approved): start immediately in parallel
          TIER 2 (EXPENSIVE): batch cost confirmation → parallel execution
          TIER 3-4 (WRITE/DANGEROUS): individual approval → sequential

        Results are returned in the same order as the input tool_use blocks
        to satisfy the Anthropic API ordering requirement.
        """
        log.info(
            "AgenticLoop: parallel execution of %d tools: %s",
            len(tool_blocks),
            [b.name for b in tool_blocks],
        )

        # Step 1: Classify blocks into tiers
        tiered: dict[int, list[tuple[int, Any]]] = {0: [], 1: [], 2: [], 3: [], 4: []}
        for idx, block in enumerate(tool_blocks):
            tier = self._classify_tool_tier(block.name, self._mcp_manager)
            tiered[tier].append((idx, block))
            log.debug("Tool %s → tier %d", block.name, tier)

        # Pre-allocate result slots in original order
        results: list[dict[str, Any] | None] = [None] * len(tool_blocks)

        # Step 2: Batch cost approval for TIER 2 (EXPENSIVE) tools
        tier2_approved = True
        if tiered[2]:
            tier2_approved = await self._batch_cost_approval([block for _, block in tiered[2]])

        # Step 3: Build parallel tasks for TIER 0 + TIER 1 + approved TIER 2
        parallel_items: list[tuple[int, Any]] = []
        parallel_items.extend(tiered[0])
        parallel_items.extend(tiered[1])

        if tier2_approved:
            # Temporarily flag executor to skip per-tool cost confirmation
            # since we already got batch approval
            parallel_items.extend(tiered[2])
        else:
            # User denied batch cost — return denial for all TIER 2 tools
            for idx, block in tiered[2]:
                results[idx] = self._make_denial_result(block, "User denied batch cost approval")

        # Step 4: Execute parallel pool
        if parallel_items:
            # For TIER 2 tools, temporarily set auto_approve to bypass
            # the per-tool cost confirmation (batch approval already done)
            old_auto_approve = self.executor._auto_approve
            if tier2_approved and tiered[2]:
                self.executor._auto_approve = True

            try:
                gathered = await asyncio.gather(
                    *[self._safe_execute_single(block) for _, block in parallel_items]
                )
            finally:
                # Restore original auto_approve state
                if tier2_approved and tiered[2]:
                    self.executor._auto_approve = old_auto_approve

            for (idx, _block), result in zip(parallel_items, gathered, strict=True):
                results[idx] = result

        # Step 5: Execute TIER 3-4 (WRITE/DANGEROUS) sequentially
        # These require individual user approval — ToolExecutor handles HITL
        sequential_items = list(tiered[3]) + list(tiered[4])
        for idx, block in sequential_items:
            results[idx] = await self._execute_single_tool(block)

        # All slots should be filled
        return [r for r in results if r is not None]

    async def _safe_execute_single(self, block: Any) -> dict[str, Any]:
        """Wrapper that catches unexpected exceptions per tool."""
        try:
            return await self._execute_single_tool(block)
        except Exception as exc:
            log.error(
                "Parallel tool %s raised unexpected error: %s",
                block.name,
                exc,
                exc_info=True,
            )
            return self._make_error_result(block, exc)

    async def _batch_cost_approval(self, blocks: list[Any]) -> bool:
        """Show a single cost confirmation prompt for all EXPENSIVE tools.

        Returns True if user approves, False if denied.
        """
        from core.ui.console import console

        items: list[tuple[str, dict[str, Any], float]] = []
        for block in blocks:
            cost = EXPENSIVE_TOOLS.get(block.name, 0.0)
            items.append((block.name, block.input, cost))

        total_cost = sum(c for _, _, c in items)

        def _prompt() -> bool:
            try:
                from core.cli import _restore_terminal

                _restore_terminal()
            except Exception:
                log.debug("_restore_terminal() unavailable in batch approval")

            console.print()
            console.print("  [warning]$ Cost confirmation[/warning]")
            count = len(items)
            plural = "s" if count > 1 else ""
            verb = "s" if count == 1 else ""
            console.print(f"  {count} tool{plural} require{verb} approval:")
            for name, inp, cost in items:
                args_preview = ", ".join(f"{k}={v!r}" for k, v in inp.items())
                console.print(f"    [dim]--[/dim] {name}({args_preview}) -- ~${cost:.2f}")
            console.print(f"  [dim]Total estimated cost:[/dim] ~${total_cost:.2f}")
            console.print()
            try:
                response = console.input("  [header]Proceed? [Y/n][/header] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                console.print()
                return False
            return response in ("", "y", "yes")

        return await asyncio.to_thread(_prompt)

    @staticmethod
    def _make_denial_result(block: Any, reason: str) -> dict[str, Any]:
        """Build a tool_result for a denied tool execution."""
        error_result = {"error": reason, "denied": True}
        try:
            content = json.dumps(error_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(error_result)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }

    @staticmethod
    def _make_error_result(block: Any, exc: Exception) -> dict[str, Any]:
        """Build a tool_result for an unexpected exception."""
        error_result = {"error": str(exc)}
        try:
            content = json.dumps(error_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(error_result)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }

    async def _attempt_recovery(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        fail_count: int,
    ) -> dict[str, Any]:
        """Attempt adaptive error recovery for a repeatedly failing tool.

        Runs the recovery chain in a background thread (sync executor calls)
        and emits hook events for observability.
        """
        self._emit_hook(
            HookEvent.TOOL_RECOVERY_ATTEMPTED,
            {
                "tool_name": tool_name,
                "fail_count": fail_count,
                "source": "agentic_loop",
            },
        )

        recovery_result = await asyncio.to_thread(
            self._error_recovery.recover,
            tool_name,
            tool_input,
            fail_count,
        )

        if recovery_result.recovered:
            # Reset consecutive failure counter on recovery success
            self._consecutive_failures[tool_name] = 0
            self._emit_hook(
                HookEvent.TOOL_RECOVERY_SUCCEEDED,
                {
                    "tool_name": tool_name,
                    "strategy": recovery_result.strategy_used.value
                    if recovery_result.strategy_used
                    else "unknown",
                    "attempts": len(recovery_result.attempts),
                    "source": "agentic_loop",
                },
            )
            result = dict(recovery_result.final_result)
            result["recovery_summary"] = recovery_result.to_summary()
            result["recovery_attempted"] = True
            return result

        # Recovery failed
        self._emit_hook(
            HookEvent.TOOL_RECOVERY_FAILED,
            {
                "tool_name": tool_name,
                "attempts": len(recovery_result.attempts),
                "strategies_tried": [a.strategy.value for a in recovery_result.attempts],
                "source": "agentic_loop",
            },
        )
        result = dict(recovery_result.final_result)
        result["recovery_summary"] = recovery_result.to_summary()
        result["recovery_attempted"] = True
        result["skipped"] = True
        return result

    def _emit_hook(self, event: HookEvent, data: dict[str, Any]) -> None:
        """Emit a hook event if HookSystem is configured."""
        if self._hooks is None:
            return
        try:
            self._hooks.trigger(event, data)
        except Exception:
            log.debug("Hook trigger failed for %s", event.value, exc_info=True)

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
            from core.llm.token_tracker import get_tracker
            from core.ui.agentic_ui import render_tokens

            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            usage = get_tracker().record(self.model, in_tok, out_tok)
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
                for entry in reversed(self._tool_log):
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

        Returns True if 4+ of the last entries are identical errors,
        indicating the loop should break.
        Injects a warning into messages if 3 identical errors are detected.
        """
        if len(self._recent_errors) < 3:
            return False

        # Check last 3 entries for identical pattern
        last_3 = self._recent_errors[-3:]
        if last_3[0] == last_3[1] == last_3[2]:
            if len(self._recent_errors) >= 4:
                last_4 = self._recent_errors[-4:]
                if last_4[0] == last_4[1] == last_4[2] == last_4[3]:
                    log.warning(
                        "Convergence detected: 4+ identical errors '%s'",
                        last_4[0],
                    )
                    return True
            # 3 identical — log warning (convergence warning injected via backpressure)
            log.warning(
                "Convergence warning: 3 identical errors '%s'",
                last_3[0],
            )
        return False
