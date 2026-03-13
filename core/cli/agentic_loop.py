"""AgenticLoop — while(tool_use) agentic execution loop.

Replaces the single-shot NLRouter classify() → action dispatch pattern
with a Claude Code-style agentic loop that continues until the LLM
emits end_turn (no more tool calls).

Supports:
- Multi-intent: "분석하고 비교해줘" → sequential tool calls
- Multi-turn: context preserved across interactions
- Self-correction: LLM can retry or adjust based on tool results
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anthropic

from core.cli.conversation import ConversationContext
from core.cli.nl_router import _build_system_prompt
from core.cli.tool_executor import ToolExecutor
from core.config import ANTHROPIC_PRIMARY, settings
from core.llm.client import _maybe_traceable
from core.llm.prompts import AGENTIC_SUFFIX
from core.ui.agentic_ui import OperationLogger
from core.ui.console import console

if TYPE_CHECKING:
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Load base tool definitions from centralized JSON
_TOOLS_JSON_PATH = Path(__file__).resolve().parent.parent / "tools" / "definitions.json"
_BASE_TOOLS: list[dict[str, Any]] = json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8"))

# Backward-compatible alias
AGENTIC_TOOLS: list[dict[str, Any]] = _BASE_TOOLS


def get_agentic_tools(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    """Return tool definitions, merging ToolRegistry extras if provided."""
    tools = list(_BASE_TOOLS)
    if registry:
        existing_names = {t["name"] for t in tools}
        for tool_def in registry.to_anthropic_tools():
            if tool_def["name"] not in existing_names:
                tools.append(tool_def)
    return tools


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
    DEFAULT_MAX_TOKENS = 8192
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
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.model = model or ANTHROPIC_PRIMARY
        self._tools = get_agentic_tools(tool_registry)
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        # Merge MCP tools if available
        if mcp_manager is not None:
            existing_names = {t["name"] for t in self._tools}
            for mcp_tool in mcp_manager.get_all_tools():
                if mcp_tool.get("name") not in existing_names:
                    self._tools.append(mcp_tool)
        self._tool_log: list[dict[str, Any]] = []
        self._consecutive_failures: dict[str, int] = {}
        self._client: anthropic.Anthropic | None = None
        self._op_logger = OperationLogger()

    def refresh_tools(self) -> int:
        """Reload MCP tools into the tool list without reconstructing the loop.

        Called after install_mcp_server to make new tools available immediately.
        Returns number of newly added tools.
        """
        if self._mcp_manager is None:
            return 0
        existing = {t["name"] for t in self._tools}
        added = 0
        for tool in self._mcp_manager.get_all_tools():
            if tool.get("name") not in existing:
                self._tools.append(tool)
                existing.add(tool["name"])
                added += 1
        return added

    @_maybe_traceable(run_type="chain", name="AgenticLoop.run")  # type: ignore[untyped-decorator]
    def run(self, user_input: str) -> AgenticResult:
        """Run the agentic loop until LLM emits end_turn or max rounds."""
        self._tool_log = []
        self._clarification_count = 0
        self._consecutive_failures.clear()
        self._op_logger.reset()

        # Add user message to conversation context
        self.context.add_user_message(user_input)
        messages = self.context.get_messages()

        system_prompt = self._build_system_prompt()

        # Prune old messages to stay within context budget (Karpathy P6)
        self._maybe_prune_messages(messages)

        for round_idx in range(self.max_rounds):
            is_last_round = round_idx == self.max_rounds - 1
            self._op_logger.begin_round("AgenticLoop")

            # Claude Code-style: spinner during LLM API call
            with console.status(
                "  [cyan]Thinking...[/cyan]",
                spinner="dots",
                spinner_style="cyan",
            ):
                response = self._call_llm(system_prompt, messages, round_idx=round_idx)

            if response is None:
                # Persist intermediate tool-use messages so next turn sees them
                self._sync_messages_to_context(messages)
                result = AgenticResult(
                    text="LLM call failed. Try again or use /help.",
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

            # Process tool calls (possibly multiple in one response)
            tool_results = self._process_tool_calls(response)

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

    @_maybe_traceable(run_type="llm", name="AgenticLoop._call_llm")  # type: ignore[untyped-decorator]
    def _call_llm(
        self, system: str, messages: list[dict[str, Any]], *, round_idx: int = 0
    ) -> anthropic.types.Message | None:
        """Call the Anthropic API with tools.  Retries on rate-limit (3×).

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
            self._client = anthropic.Anthropic(api_key=api_key, max_retries=0)

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
                response = self._client.messages.create(  # type: ignore[call-overload]
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
                    time.sleep(wait)
                else:
                    log.error("%s exhausted after %d retries", exc_type, max_retries)
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
                    time.sleep(wait)
                else:
                    log.error("Rate limit exhausted after %d retries", max_retries)
                    return None
            except anthropic.AuthenticationError:
                log.warning("Anthropic API key is invalid in agentic loop")
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

    def _process_tool_calls(self, response: anthropic.types.Message) -> list[dict[str, Any]]:
        """Execute all tool_use blocks and return tool_result messages.

        Tracks consecutive failures per tool name.  After _MAX_CONSECUTIVE_FAILURES
        for the same tool, returns a synthetic "skip" result so the LLM stops retrying
        a broken tool and moves on.
        """
        tool_results: list[dict[str, Any]] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input: dict[str, Any] = block.input

            log.info("AgenticLoop: tool_use %s(%s)", tool_name, tool_input)

            # Auto-skip: if this tool has failed too many times consecutively
            fail_count = self._consecutive_failures.get(tool_name, 0)
            if fail_count >= self._MAX_CONSECUTIVE_FAILURES:
                result: dict[str, Any] = {
                    "error": (
                        f"Tool '{tool_name}' failed {fail_count} times consecutively. "
                        "Skipping — please use a different approach."
                    ),
                    "skipped": True,
                }
                visible = self._op_logger.log_tool_call(tool_name, tool_input)
                self._op_logger.log_tool_result(tool_name, result, visible=visible)
            else:
                # Progressive log: show tool call before execution
                visible = self._op_logger.log_tool_call(tool_name, tool_input)

                # Execute via ToolExecutor with spinner (handles HITL for dangerous tools)
                with console.status(
                    f"  [cyan]Running {tool_name}...[/cyan]",
                    spinner="dots",
                    spinner_style="cyan",
                ):
                    result = self.executor.execute(tool_name, tool_input)

            # Track consecutive failures
            if isinstance(result, dict) and result.get("error"):
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

            # Progressive log: show tool result summary
            if isinstance(result, dict):
                self._op_logger.log_tool_result(tool_name, result, visible=visible)

            self._tool_log.append(
                {
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                }
            )

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
