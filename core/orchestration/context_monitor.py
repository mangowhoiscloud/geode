"""Context Overflow Detection — proactive token budget monitoring.

Monitors conversation context size against model context window limits.
Emits CONTEXT_CRITICAL (>=95%) hook events
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

# Absolute token ceiling — prevents rate limit pool separation on large-context models.
# Anthropic (and others) assign requests >200K tokens to a separate, more restrictive
# rate limit pool. This guard triggers compression before crossing that boundary,
# even when the percentage-based thresholds (80%/95%) are far away (e.g. 200K/1M = 20%).
ABSOLUTE_TOKEN_CEILING = 200_000

# Approximate chars per token (conservative estimate)
CHARS_PER_TOKEN = 4

# Default overhead for system prompt + tool definitions (measured: ~10K tokens).
# System prompt ~2.7K + 56 base tools ~7.3K = ~10K.
_DEFAULT_TOOLS_OVERHEAD = 10_000


@dataclass(frozen=True, slots=True)
class ContextMetrics:
    """Snapshot of context window usage."""

    estimated_tokens: int
    context_window: int
    usage_pct: float
    remaining_tokens: int
    is_warning: bool
    is_critical: bool
    is_ceiling_exceeded: bool = False


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
    tools_tokens: int = 0,
) -> ContextMetrics:
    """Check context window health for the given conversation.

    Args:
        tools_tokens: Estimated tokens for tool definitions sent to the API.
            Defaults to _DEFAULT_TOOLS_OVERHEAD (~10K) when 0.

    Returns a ContextMetrics snapshot with usage percentage and thresholds.
    """
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

    context_window = MODEL_CONTEXT_WINDOW.get(model, 200_000)

    system_tokens = len(system_prompt) // CHARS_PER_TOKEN if system_prompt else 0
    message_tokens = estimate_message_tokens(messages)
    overhead = tools_tokens if tools_tokens > 0 else _DEFAULT_TOOLS_OVERHEAD
    estimated = system_tokens + message_tokens + overhead

    usage_pct = estimated / context_window * 100
    remaining = max(context_window - estimated, 0)

    # Ceiling exceeded: only relevant for large-context models where percentage
    # thresholds are too distant (e.g. 200K/1M = 20%, but 80% threshold = 800K).
    ceiling_exceeded = (
        estimated > ABSOLUTE_TOKEN_CEILING and context_window > ABSOLUTE_TOKEN_CEILING
    )

    return ContextMetrics(
        estimated_tokens=estimated,
        context_window=context_window,
        usage_pct=usage_pct,
        remaining_tokens=remaining,
        is_warning=usage_pct >= WARNING_THRESHOLD,
        is_critical=usage_pct >= CRITICAL_THRESHOLD,
        is_ceiling_exceeded=ceiling_exceeded,
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


def summarize_tool_results(
    messages: list[dict[str, Any]],
    target_window: int,
) -> tuple[int, int, int]:
    """Replace large tool_result content with compact summaries.

    Mutates messages in-place.
    Returns (summarized_count, tokens_before, tokens_after).
    Only targets tool_result blocks exceeding 2% of the target context window.
    """
    tokens_before = estimate_message_tokens(messages)
    threshold = target_window // 50  # 2% of context window (~20K for 1M)
    summarized = 0

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content", "")
            if isinstance(inner, str) and len(inner) < 200:
                continue  # already small
            estimated = len(json.dumps(block, default=str)) // CHARS_PER_TOKEN
            if estimated > threshold:
                block["content"] = f"[summarized: {estimated:,} tokens truncated]"
                summarized += 1

    tokens_after = estimate_message_tokens(messages)
    if summarized:
        log.info(
            "Summarized %d tool results: %d → %d tokens (-%d)",
            summarized,
            tokens_before,
            tokens_after,
            tokens_before - tokens_after,
        )
    return summarized, tokens_before, tokens_after


def adaptive_prune(
    messages: list[dict[str, Any]],
    target_tokens: int,
) -> list[dict[str, Any]]:
    """Token-aware pruning: build result from newest messages within budget.

    Strategy:
    1. Always keep the first message (initial context)
    2. Always keep the last 2 messages (most recent exchange)
    3. Add middle messages from newest to oldest until budget is reached
    4. Budget = target_tokens * 0.7 (30% headroom for system prompt + response)
    """
    if len(messages) <= 3:
        return list(messages)

    budget = int(target_tokens * 0.7)
    first = messages[0]
    recent = messages[-2:]
    middle = messages[1:-2]

    base_tokens = estimate_message_tokens([first]) + estimate_message_tokens(recent)
    if base_tokens >= budget:
        # Even first + recent exceeds budget — return minimal
        return [first, *recent]

    remaining_budget = budget - base_tokens
    kept_middle: list[dict[str, Any]] = []

    # Add from newest to oldest
    for msg in reversed(middle):
        msg_tokens = estimate_message_tokens([msg])
        if remaining_budget - msg_tokens >= 0:
            kept_middle.append(msg)
            remaining_budget -= msg_tokens
        # Skip messages that don't fit

    kept_middle.reverse()  # restore chronological order
    result = [first, *kept_middle, *recent]
    tokens_before = estimate_message_tokens(messages)
    tokens_after = estimate_message_tokens(result)
    log.info(
        "Adaptive prune: %d → %d messages, %d → %d tokens (-%d)",
        len(messages),
        len(result),
        tokens_before,
        tokens_after,
        tokens_before - tokens_after,
    )
    return result
