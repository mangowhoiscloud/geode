"""Router data types — tool-use loop result records.

``ToolCallRecord`` captures one tool invocation (name, input, result, latency).
``ToolUseResult`` collects every record across a multi-turn agentic loop along
with per-turn token usage and the final assistant text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.llm.token_tracker import LLMUsage


@dataclass
class ToolCallRecord:
    """Record of a single tool call within a tool-use loop."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_result: dict[str, Any]
    duration_ms: float


@dataclass
class ToolUseResult:
    """Result from a multi-turn tool-use LLM call."""

    text: str
    tool_calls: list[ToolCallRecord]
    usage: list[LLMUsage]
    rounds: int
