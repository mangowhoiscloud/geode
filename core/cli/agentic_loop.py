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
from core.llm.client import _maybe_traceable, track_token_usage
from core.llm.prompts import AGENTIC_SUFFIX
from core.ui.agentic_ui import render_tool_call, render_tool_result

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


class AgenticLoop:
    """Claude Code-style agentic execution loop.

    while stop_reason == "tool_use":
        execute tools → feed results back → continue
    """

    DEFAULT_MAX_ROUNDS = 10
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        context: ConversationContext,
        tool_executor: ToolExecutor,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str | None = None,
        tool_registry: ToolRegistry | None = None,
        offline_mode: bool = False,
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.model = model or ANTHROPIC_PRIMARY
        self._tools = get_agentic_tools(tool_registry)
        self._offline = offline_mode
        self._tool_log: list[dict[str, Any]] = []
        self._client: anthropic.Anthropic | None = None

    @_maybe_traceable(run_type="chain", name="AgenticLoop.run")  # type: ignore[untyped-decorator]
    def run(self, user_input: str) -> AgenticResult:
        """Run the agentic loop until LLM emits end_turn or max rounds."""
        self._tool_log = []

        if self._offline:
            return self._run_offline(user_input)  # type: ignore[no-any-return]

        # Add user message to conversation context
        self.context.add_user_message(user_input)
        messages = self.context.get_messages()

        system_prompt = self._build_system_prompt()

        for round_idx in range(self.max_rounds):
            response = self._call_llm(system_prompt, messages)
            if response is None:
                return AgenticResult(
                    text="LLM call failed. Try again or use /help.",
                    rounds=round_idx + 1,
                    error="llm_call_failed",
                )

            # Track usage + Claude Code-style token display
            self._track_usage(response)

            if response.stop_reason != "tool_use":
                # end_turn or max_tokens → extract text, done
                text = self._extract_text(response)
                self.context.add_assistant_message(response.content)
                return AgenticResult(
                    text=text,
                    tool_calls=self._tool_log,
                    rounds=round_idx + 1,
                )

            # Process tool calls (possibly multiple in one response)
            tool_results = self._process_tool_calls(response)

            # Accumulate messages for next round
            # Convert content blocks to serializable format
            assistant_content = self._serialize_content(response.content)
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

        # Max rounds reached — persist what we have
        self.context.add_assistant_message(
            [{"type": "text", "text": "Max agentic rounds reached."}]
        )
        return AgenticResult(
            text="Max agentic rounds reached. Please try a more specific request.",
            tool_calls=self._tool_log,
            rounds=self.max_rounds,
            error="max_rounds",
        )

    @_maybe_traceable(run_type="chain", name="AgenticLoop._run_offline")  # type: ignore[untyped-decorator]
    def _run_offline(self, user_input: str) -> AgenticResult:
        """Regex-based tool selection without LLM (1 deterministic round)."""
        from core.cli.nl_router import _offline_fallback

        intent = _offline_fallback(user_input)
        if intent.action == "help":
            return AgenticResult(
                text="Offline mode: use /help for supported commands.",
                rounds=1,
            )

        result = self.executor.execute(intent.action, intent.args or {})
        self._tool_log.append({"tool": intent.action, "input": intent.args or {}, "result": result})
        return AgenticResult(
            text=str(result),
            tool_calls=self._tool_log,
            rounds=1,
        )

    def _build_system_prompt(self) -> str:
        """Build the system prompt with agentic suffix."""
        base = _build_system_prompt()
        return base + "\n" + AGENTIC_SUFFIX

    @_maybe_traceable(run_type="llm", name="AgenticLoop._call_llm")  # type: ignore[untyped-decorator]
    def _call_llm(
        self, system: str, messages: list[dict[str, Any]]
    ) -> anthropic.types.Message | None:
        """Call the Anthropic API with tools.  Retries on rate-limit (3×)."""
        api_key = settings.anthropic_api_key
        if not api_key:
            log.warning("No Anthropic API key for agentic loop")
            return None

        if self._client is None:
            self._client = anthropic.Anthropic(api_key=api_key)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self._client.messages.create(  # type: ignore[call-overload]
                    model=self.model,
                    system=system,
                    messages=messages,
                    tools=self._tools,
                    tool_choice={"type": "auto"},
                    max_tokens=self.max_tokens,
                    temperature=0.0,
                    timeout=30.0,
                )
                track_token_usage(
                    self.model,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                return response  # type: ignore[no-any-return]

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
                log.warning("Anthropic BadRequest in agentic loop: %s", exc)
                return None
            except Exception:
                log.warning("Agentic LLM call failed", exc_info=True)
                return None
        return None

    def _process_tool_calls(self, response: anthropic.types.Message) -> list[dict[str, Any]]:
        """Execute all tool_use blocks and return tool_result messages."""
        tool_results: list[dict[str, Any]] = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input: dict[str, Any] = block.input

            log.info("AgenticLoop: tool_use %s(%s)", tool_name, tool_input)

            # Claude Code-style: show tool call before execution
            render_tool_call(tool_name, tool_input)

            # Execute via ToolExecutor (handles HITL for dangerous tools)
            result = self.executor.execute(tool_name, tool_input)

            # Claude Code-style: show tool result summary
            if isinstance(result, dict):
                render_tool_result(tool_name, result)

            self._tool_log.append(
                {
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                }
            )

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
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
            from core.llm.client import (
                LLMUsage,
                calculate_cost,
                get_usage_accumulator,
                track_token_usage,
            )

            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            cost = calculate_cost(self.model, in_tok, out_tok)
            get_usage_accumulator().record(
                LLMUsage(
                    model=self.model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                )
            )
            track_token_usage(self.model, in_tok, out_tok)
            log.debug(
                "AgenticLoop: model=%s in=%d out=%d cost=$%.6f",
                self.model,
                in_tok,
                out_tok,
                cost,
            )
        except Exception:
            log.debug("Failed to track usage", exc_info=True)
