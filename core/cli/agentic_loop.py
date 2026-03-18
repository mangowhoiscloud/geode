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

from core.cli.agentic_response import (
    AgenticResponse,
    normalize_anthropic,
    normalize_openai,
)
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
from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY, settings
from core.llm.client import (
    LLMBadRequestError,
    call_with_failover,
    get_async_anthropic_client,
    maybe_traceable,
)
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

# Anthropic API tool schema allowed keys — fields outside this set cause
# 400 "Extra inputs are not permitted" errors. Defined at module level
# to avoid re-creating the frozenset on every LLM call.
_API_ALLOWED_KEYS = frozenset({"name", "description", "input_schema", "cache_control", "type"})

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
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self._parent_session_key = parent_session_key
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.model = model or ANTHROPIC_PRIMARY
        self._provider = provider  # "anthropic" or "openai"
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
        self._client: Any | None = None
        self._op_logger = OperationLogger()
        self._error_recovery = ErrorRecoveryStrategy(tool_executor)

        # Goal decomposition: auto-decompose compound requests into sub-goal DAGs
        self._enable_goal_decomposition = enable_goal_decomposition
        self._goal_decomposer: Any | None = None  # lazy init

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
            finally:
                _spinner.stop()

            if response is None:
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
                return result

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
                return result

            tool_results = await self._process_tool_calls(response)

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
        """Check context window usage and emit hooks if near limits."""
        try:
            from core.orchestration.context_monitor import (
                check_context,
                prune_oldest_messages,
            )

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
                # Emergency prune: keep first + last 10 messages
                pruned = prune_oldest_messages(messages, keep_recent=10)
                if len(pruned) < len(messages):
                    messages.clear()
                    messages.extend(pruned)
                    log.info(
                        "Pruned conversation: %d → %d messages",
                        len(messages) + (len(messages) - len(pruned)),
                        len(pruned),
                    )
            elif metrics.is_warning:
                log.info(
                    "Context WARNING: %.0f%% (%d/%d tokens)",
                    metrics.usage_pct,
                    metrics.estimated_tokens,
                    metrics.context_window,
                )
                if self._hooks:
                    self._hooks.trigger(
                        HookEvent.CONTEXT_WARNING,
                        {"metrics": dataclasses.asdict(metrics), "model": self.model},
                    )
        except Exception:
            log.debug("Context monitor check failed", exc_info=True)

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
        base = _build_system_prompt()
        # Inject skill context into placeholder
        skill_ctx = ""
        if self._skill_registry is not None:
            skill_ctx = self._skill_registry.get_context_block()
        base = base.replace("{skill_context}", skill_ctx or "No skills loaded.")
        return base + "\n" + AGENTIC_SUFFIX

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
        """Multi-provider LLM call with tools + automatic model failover.

        Dispatches to Anthropic or OpenAI based on ``self._provider``.
        Returns a normalized ``AgenticResponse`` with provider-agnostic
        content blocks (.type, .text, .name, .input, .id).
        """
        # Context overflow detection (Karpathy P6 Context Budget)
        self._check_context_overflow(system, messages)

        if self._provider == "openai":
            return await self._call_llm_openai(system, messages, round_idx=round_idx)
        return await self._call_llm_anthropic(system, messages, round_idx=round_idx)

    async def _call_llm_anthropic(
        self, system: str, messages: list[dict[str, Any]], *, round_idx: int = 0
    ) -> AgenticResponse | None:
        """Anthropic-specific LLM call with context management beta."""
        api_key = settings.anthropic_api_key
        if not api_key:
            log.warning("No Anthropic API key for agentic loop")
            return None

        if self._client is None:
            self._client = get_async_anthropic_client(api_key)

        remaining = self.max_rounds - round_idx
        force_text = remaining <= self.WRAP_UP_HEADROOM
        tool_choice: dict[str, str] = {"type": "none"} if force_text else {"type": "auto"}

        api_tools = [{k: v for k, v in t.items() if k in _API_ALLOWED_KEYS} for t in self._tools]
        failover_models = [self.model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != self.model]

        async def _do_call(model: str) -> Any:
            return await self._client.messages.create(  # type: ignore[union-attr]
                model=model,
                system=system,
                messages=messages,
                tools=api_tools,
                tool_choice=tool_choice,
                max_tokens=self.max_tokens,
                temperature=0.0,
                extra_headers={
                    "anthropic-beta": "context-management-2025-06-27",
                },
                extra_body={
                    "context_management": {
                        "edits": [
                            {
                                "type": "clear_tool_uses_20250919",
                                "keep": {"type": "tool_uses", "value": 5},
                            }
                        ]
                    }
                },
            )

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            log.info("LLM call interrupted by user")
            return None
        except LLMBadRequestError as exc:
            msg = str(exc)
            log.warning("Anthropic BadRequest in agentic loop: %s", msg)
            if "tool_use_id" in msg or "tool_result" in msg:
                self._repair_messages(messages)
                log.info("Repaired orphaned tool_result in conversation history")
                try:
                    response = await _do_call(self.model)
                    return normalize_anthropic(response)
                except Exception:
                    log.warning("Retry after repair failed", exc_info=True)
                    return None
            if "input_schema" in msg:
                log.error(
                    "Tool schema error — likely an MCP tool missing input_schema. tools count=%d",
                    len(self._tools),
                )
            return None
        except Exception:
            log.warning("Agentic LLM call failed", exc_info=True)
            return None

        if response is None:
            self._last_llm_error = "All models in failover chain exhausted"
            return None

        if used_model and used_model != self.model:
            log.warning("Model failover: %s -> %s", self.model, used_model)

        return normalize_anthropic(response)

    async def _call_llm_openai(
        self, system: str, messages: list[dict[str, Any]], *, round_idx: int = 0
    ) -> AgenticResponse | None:
        """OpenAI-specific LLM call with tool-use support."""
        if not settings.openai_api_key:
            log.warning("No OpenAI API key for agentic loop")
            return None

        try:
            from core.infrastructure.adapters.llm.openai_adapter import (
                _get_openai_client,
            )
        except ImportError:
            log.error("OpenAI adapter not available")
            return None

        if self._client is None:
            self._client = _get_openai_client()

        remaining = self.max_rounds - round_idx
        force_text = remaining <= self.WRAP_UP_HEADROOM
        tool_choice_val = "none" if force_text else "auto"

        # Convert Anthropic tool format to OpenAI function format
        oai_tools = self._convert_tools_to_openai()

        # Build messages with system prompt for OpenAI
        oai_messages = [{"role": "system", "content": system}, *messages]

        from core.config import OPENAI_FALLBACK_CHAIN

        failover_models = [self.model] + [m for m in OPENAI_FALLBACK_CHAIN if m != self.model]

        async def _do_call(model: str) -> Any:
            import asyncio as _aio

            client = self._client
            return await _aio.to_thread(
                client.chat.completions.create,  # type: ignore[union-attr]
                model=model,
                messages=oai_messages,
                tools=oai_tools if oai_tools else None,
                tool_choice=tool_choice_val if oai_tools else None,
                max_completion_tokens=self.max_tokens,
                temperature=0.0,
                timeout=90.0,
            )

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            log.info("LLM call interrupted by user")
            return None
        except Exception:
            log.warning("OpenAI agentic LLM call failed", exc_info=True)
            return None

        if response is None:
            self._last_llm_error = "All OpenAI models exhausted"
            return None

        if used_model and used_model != self.model:
            log.warning("Model failover: %s -> %s", self.model, used_model)

        return normalize_openai(response)

    def _convert_tools_to_openai(self) -> list[dict[str, Any]]:
        """Convert Anthropic-format tool definitions to OpenAI function calling format."""
        oai_tools: list[dict[str, Any]] = []
        for tool in self._tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            if not name:
                continue
            oai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc,
                        "parameters": schema,
                    },
                }
            )
        return oai_tools

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
