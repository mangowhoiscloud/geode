"""Context Compactor — LLM-based conversation summarization.

GAP 7: When context reaches 80% (WARNING), older messages are compressed
into a summary using a budget LLM (Haiku by default). The summary replaces
the compressed messages as a single ``[context_summary]`` system message.

If compaction fails (LLM error, timeout), falls back to the existing
``prune_oldest_messages()`` mechanical pruning.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_COMPACTION_SYSTEM = """\
You are a conversation summarizer. Given a sequence of conversation messages,
produce a concise summary that preserves:
1. Key decisions and conclusions
2. Important facts and data mentioned
3. Tool call results and their outcomes
4. The user's original intent and progress toward it

Output ONLY the summary text. Do not include any preamble or formatting."""

_COMPACTION_USER = """\
Summarize the following conversation messages into a concise context summary.
Preserve all important information needed to continue the conversation.

Messages:
{messages_text}"""


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """Result of a context compaction operation."""

    original_count: int
    compacted_count: int
    summary_text: str
    tokens_saved_estimate: int


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Convert messages to a readable text format for summarization."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            lines.append(f"[{role}]: {content[:500]}")
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(block.get("text", "")[:300])
                    elif btype == "tool_use":
                        parts.append(f"<tool_use name={block.get('name', '?')}>")
                    elif btype == "tool_result":
                        result_text = block.get("content", "")
                        if isinstance(result_text, str):
                            parts.append(f"<tool_result>{result_text[:200]}</tool_result>")
                elif isinstance(block, str):
                    parts.append(block[:300])
            lines.append(f"[{role}]: {' '.join(parts)}")
    return "\n".join(lines)


def compact_context(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = 10,
    model: str | None = None,
    max_summary_tokens: int = 2048,
) -> CompactionResult:
    """Compact older messages into an LLM-generated summary.

    Replaces messages[1:-keep_recent] with a single summary message.
    The first message (initial user context) and the most recent messages
    are always preserved.

    Mutates ``messages`` in-place.

    Args:
        messages: Conversation messages to compact.
        keep_recent: Number of recent messages to preserve.
        model: LLM model for summarization (default: ANTHROPIC_BUDGET).
        max_summary_tokens: Max tokens for the summary response.

    Returns:
        CompactionResult with before/after counts and summary text.
    """
    from core.config import ANTHROPIC_BUDGET

    original_count = len(messages)

    if original_count <= keep_recent + 2:
        # Not enough messages to compact
        return CompactionResult(
            original_count=original_count,
            compacted_count=original_count,
            summary_text="",
            tokens_saved_estimate=0,
        )

    # Split: first message + middle (to compress) + recent
    first_msg = messages[0]
    to_compress = messages[1:-keep_recent]
    recent = messages[-keep_recent:]

    if not to_compress:
        return CompactionResult(
            original_count=original_count,
            compacted_count=original_count,
            summary_text="",
            tokens_saved_estimate=0,
        )

    # Build summary prompt
    messages_text = _messages_to_text(to_compress)
    user_prompt = _COMPACTION_USER.format(messages_text=messages_text)

    # Estimate tokens being compressed (for reporting)
    from core.orchestration.context_monitor import CHARS_PER_TOKEN

    compressed_chars = sum(len(json.dumps(m, default=str)) for m in to_compress)
    tokens_compressed = compressed_chars // CHARS_PER_TOKEN

    # Call LLM for summarization
    summary_model = model or ANTHROPIC_BUDGET
    try:
        from core.llm.client import call_llm

        summary_text = call_llm(
            _COMPACTION_SYSTEM,
            user_prompt,
            model=summary_model,
            max_tokens=max_summary_tokens,
            temperature=0.1,
        )
    except Exception as exc:
        log.warning("Context compaction LLM call failed: %s — skipping", exc)
        return CompactionResult(
            original_count=original_count,
            compacted_count=original_count,
            summary_text="",
            tokens_saved_estimate=0,
        )

    # Build the summary message
    summary_msg: dict[str, Any] = {
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": (
                    f"[Context Summary — {len(to_compress)} messages compressed]\n\n{summary_text}"
                ),
            }
        ],
    }

    # Estimate tokens saved
    summary_chars = len(json.dumps(summary_msg, default=str))
    tokens_saved = max(0, tokens_compressed - (summary_chars // CHARS_PER_TOKEN))

    # Mutate messages in-place
    messages.clear()
    messages.extend([first_msg, summary_msg, *recent])

    log.info(
        "Context compacted: %d → %d messages (~%d tokens saved)",
        original_count,
        len(messages),
        tokens_saved,
    )

    return CompactionResult(
        original_count=original_count,
        compacted_count=len(messages),
        summary_text=summary_text,
        tokens_saved_estimate=tokens_saved,
    )
