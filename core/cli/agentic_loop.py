"""AgenticLoop — while(tool_use) agentic execution loop.

Replaces the single-shot NLRouter classify() → action dispatch pattern
with a Claude Code-style agentic loop that continues until the LLM
emits end_turn (no more tool calls).

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

import anthropic

from core.cli.conversation import ConversationContext
from core.cli.error_recovery import ErrorRecoveryStrategy
from core.cli.nl_router import _build_system_prompt
from core.cli.tool_executor import ToolExecutor
from core.config import ANTHROPIC_PRIMARY, settings
from core.llm.client import _maybe_traceable
from core.llm.prompts import AGENTIC_SUFFIX
from core.orchestration.hooks import HookEvent, HookSystem
from core.ui.agentic_ui import OperationLogger

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
# Token guard — prevent oversized tool results from exploding context (P2-A)
# ---------------------------------------------------------------------------
MAX_TOOL_RESULT_TOKENS = 4096  # ~16K chars


def _guard_tool_result(
    result: dict[str, Any],
    max_tokens: int = MAX_TOOL_RESULT_TOKENS,
) -> dict[str, Any]:
    """Truncate oversized tool results while preserving summary."""
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

    DEFAULT_MAX_ROUNDS = 15
    DEFAULT_MAX_TOKENS = 16384
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
        tool_registry: ToolRegistry | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        hooks: HookSystem | None = None,
        enable_goal_decomposition: bool = True,
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.model = model or ANTHROPIC_PRIMARY
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
        self._client: anthropic.AsyncAnthropic | None = None
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

    @_maybe_traceable(run_type="chain", name="AgenticLoop.run")  # type: ignore[untyped-decorator]
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

            response = await self._call_llm(system_prompt, messages, round_idx=round_idx)

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
        if len(messages) <= 10:
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

    @_maybe_traceable(run_type="llm", name="AgenticLoop._call_llm")  # type: ignore[untyped-decorator]
    async def _call_llm(
        self, system: str, messages: list[dict[str, Any]], *, round_idx: int = 0
    ) -> anthropic.types.Message | None:
        """Async Anthropic API call with tools.  Retries on rate-limit (3×).

        On the last round (round_idx == max_rounds - 1), forces tool_choice=none
        so the LLM must produce a text response instead of another tool call.
        """
        api_key = settings.anthropic_api_key
        if not api_key:
            log.warning("No Anthropic API key for agentic loop")
            return None

        if self._client is None:
            # Disable SDK-level retries to prevent double-retry with our own loop.
            # Default max_retries=2 causes SDK to retry timeouts 3× internally,
            # compounding with our 3 retries → 9 total attempts / 18min worst case.
            self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

        # Force text response in the last WRAP_UP_HEADROOM rounds
        # so the LLM always has a chance to summarize before max_rounds
        remaining = self.max_rounds - round_idx
        force_text = remaining <= self.WRAP_UP_HEADROOM
        tool_choice: dict[str, str] = {"type": "none"} if force_text else {"type": "auto"}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Strip internal metadata (e.g. _mcp_server) before sending to API
                api_tools = [
                    {k: v for k, v in t.items() if not k.startswith("_")} for t in self._tools
                ]
                response = await self._client.messages.create(  # type: ignore[call-overload]
                    model=self.model,
                    system=system,
                    messages=messages,
                    tools=api_tools,
                    tool_choice=tool_choice,
                    max_tokens=self.max_tokens,
                    temperature=0.0,
                    timeout=120.0,
                )
                return response  # type: ignore[no-any-return]

            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
                wait = 2**attempt * 5  # 5s, 10s, 20s
                exc_type = type(exc).__name__
                log.warning(
                    "%s (attempt %d/%d), retrying in %ds",
                    exc_type,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)
                else:
                    log.error("%s exhausted after %d retries", exc_type, max_retries)
                    self._last_llm_error = f"{exc_type} after {max_retries} retries"
                    return None
            except anthropic.RateLimitError:
                wait = 2**attempt * 10  # 10s, 20s, 40s
                log.warning(
                    "Rate limited (attempt %d/%d), retrying in %ds",
                    attempt + 1,
                    max_retries,
                    wait,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)
                else:
                    log.error("Rate limit exhausted after %d retries", max_retries)
                    self._last_llm_error = f"RateLimitError after {max_retries} retries"
                    return None
            except anthropic.AuthenticationError:
                log.warning("Anthropic API key is invalid in agentic loop")
                self._last_llm_error = "AuthenticationError — API key invalid"
                return None
            except anthropic.BadRequestError as exc:
                msg = str(exc)
                log.warning("Anthropic BadRequest in agentic loop: %s", msg)
                if "tool_use_id" in msg or "tool_result" in msg:
                    # Orphaned tool_result in conversation history — repair
                    self._repair_messages(messages)
                    log.info("Repaired orphaned tool_result in conversation history")
                    continue  # retry with cleaned messages
                if "input_schema" in msg:
                    log.error(
                        "Tool schema error — likely an MCP tool missing input_schema. "
                        "tools count=%d",
                        len(self._tools),
                    )
                return None
            except KeyboardInterrupt:
                log.info("LLM call interrupted by user")
                return None
            except Exception:
                log.warning("Agentic LLM call failed", exc_info=True)
                return None
        return None

    _MAX_CONSECUTIVE_FAILURES = 2  # auto-skip after N consecutive failures per tool

    async def _process_tool_calls(self, response: anthropic.types.Message) -> list[dict[str, Any]]:
        """Execute all tool_use blocks and return tool_result messages.

        Tracks consecutive failures per tool name.  After _MAX_CONSECUTIVE_FAILURES
        for the same tool, triggers the adaptive error recovery chain:
        retry → alternative tool → cheaper fallback → escalate.

        If recovery is not possible (safety-gated tools) or the chain is
        exhausted, returns a synthetic error result so the LLM moves on.
        """
        tool_results: list[dict[str, Any]] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

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
                            "Too many clarification attempts. "
                            "Please provide all required parameters."
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

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                }
            )

        return tool_results

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

    def _extract_text(self, response: anthropic.types.Message) -> str:
        """Extract text content from response blocks."""
        parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts).strip()

    def _serialize_content(self, content: list[Any]) -> list[dict[str, Any]]:
        """Serialize Anthropic content blocks to plain dicts for message history."""
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

    def _track_usage(self, response: anthropic.types.Message) -> None:
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
