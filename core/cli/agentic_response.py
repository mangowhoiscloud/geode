"""Provider-agnostic agentic response normalization.

Normalizes LLM provider responses (Anthropic, OpenAI) into a common
format that AgenticLoop can process without provider-specific code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolUseBlock:
    """A single tool-use request from the LLM."""

    id: str
    type: str = "tool_use"
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TextBlock:
    """A text content block from the LLM."""

    type: str = "text"
    text: str = ""


@dataclass(slots=True)
class ResponseUsage:
    """Token usage from an LLM response."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AgenticResponse:
    """Provider-agnostic LLM response for the agentic loop.

    Normalizes Anthropic and OpenAI responses into a common format.
    The content list contains TextBlock and ToolUseBlock objects
    with the same attribute names (.type, .text, .name, .input, .id).
    """

    content: list[TextBlock | ToolUseBlock] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" or "tool_use"
    usage: ResponseUsage = field(default_factory=ResponseUsage)


def normalize_anthropic(response: Any) -> AgenticResponse:
    """Normalize an Anthropic SDK response to AgenticResponse."""
    blocks: list[TextBlock | ToolUseBlock] = []
    for block in response.content:
        if block.type == "text":
            blocks.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            blocks.append(
                ToolUseBlock(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                )
            )

    usage = ResponseUsage()
    if response.usage:
        usage = ResponseUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    return AgenticResponse(
        content=blocks,
        stop_reason=response.stop_reason,
        usage=usage,
    )


def normalize_openai(response: Any) -> AgenticResponse:
    """Normalize an OpenAI SDK response to AgenticResponse."""
    choice = response.choices[0] if response.choices else None
    if choice is None:
        return AgenticResponse()

    blocks: list[TextBlock | ToolUseBlock] = []

    # Text content
    if choice.message.content:
        blocks.append(TextBlock(text=choice.message.content))

    # Tool calls
    has_tools = False
    if choice.message.tool_calls:
        has_tools = True
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            blocks.append(
                ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                )
            )

    # Map finish_reason to Anthropic-style stop_reason
    stop_reason = "end_turn"
    if has_tools and choice.finish_reason == "tool_calls":
        stop_reason = "tool_use"

    usage = ResponseUsage()
    if response.usage:
        usage = ResponseUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
        )

    return AgenticResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=usage,
    )
