"""Context Overflow Detection — proactive token budget monitoring.

Monitors conversation context size against model context window limits.
Emits CONTEXT_WARNING (>=80%) and CONTEXT_CRITICAL (>=95%) hook events
before the API returns a context overflow error.

Karpathy P6 Context Budget pattern: detect and compress before hitting limits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Thresholds (percentage of model context window)
WARNING_THRESHOLD = 80.0
CRITICAL_THRESHOLD = 95.0

# Approximate chars per token (conservative estimate)
CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class ContextMetrics:
    """Snapshot of context window usage."""

    estimated_tokens: int
    context_window: int
    usage_pct: float
    remaining_tokens: int
    is_warning: bool
    is_critical: bool


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages.

    Uses a conservative 4 chars/token heuristic.
    Tool-use content (JSON) tends to be slightly more tokens per char,
    so this is an approximation that slightly underestimates.
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # tool_use, tool_result, text blocks
                    text = block.get("text", "") or block.get("content", "")
                    if isinstance(text, str):
                        total_chars += len(text)
                    elif isinstance(text, list):
                        # Nested content (tool_result with list content)
                        for sub in text:
                            if isinstance(sub, dict):
                                total_chars += len(sub.get("text", ""))
                            elif isinstance(sub, str):
                                total_chars += len(sub)
                    # Add overhead for block metadata (type, id, name, etc.)
                    total_chars += len(json.dumps(block, default=str)) - len(str(text))
                elif isinstance(block, str):
                    total_chars += len(block)
    return max(total_chars // CHARS_PER_TOKEN, 1)


def check_context(
    messages: list[dict[str, Any]],
    model: str,
    *,
    system_prompt: str = "",
) -> ContextMetrics:
    """Check context window health for the given conversation.

    Returns a ContextMetrics snapshot with usage percentage and thresholds.
    """
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

    context_window = MODEL_CONTEXT_WINDOW.get(model, 200_000)

    # Estimate tokens: system prompt + messages + response overhead (~500)
    system_tokens = len(system_prompt) // CHARS_PER_TOKEN if system_prompt else 0
    message_tokens = estimate_message_tokens(messages)
    response_overhead = 500  # reserve for response + tool definitions
    estimated = system_tokens + message_tokens + response_overhead

    usage_pct = min(estimated / context_window * 100, 100.0)
    remaining = max(context_window - estimated, 0)

    return ContextMetrics(
        estimated_tokens=estimated,
        context_window=context_window,
        usage_pct=usage_pct,
        remaining_tokens=remaining,
        is_warning=usage_pct >= WARNING_THRESHOLD,
        is_critical=usage_pct >= CRITICAL_THRESHOLD,
    )


def prune_oldest_messages(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = 10,
) -> list[dict[str, Any]]:
    """Emergency pruning: keep only the most recent N message pairs.

    Preserves system message integrity by keeping the first message
    if it's from the user (initial context), plus the most recent messages.
    """
    if len(messages) <= keep_recent:
        return messages

    # Keep the first message (initial user context) + last N
    return messages[:1] + messages[-keep_recent:]
