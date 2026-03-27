"""Client-side conversation compaction — LLM summary-based context management.

For providers without server-side compaction (OpenAI, GLM), this module
provides LLM-based conversation summarization when context approaches limits.

Anthropic has server-side compaction (compact_20260112) and does not need this.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Default summarization prompt (aligned with Claude Code / Codex CLI patterns)
_COMPACTION_PROMPT = (
    "You are summarizing a conversation for continuity. Write a concise summary "
    "preserving: (1) the user's original task/goal, (2) key decisions made, "
    "(3) current state and progress, (4) important code/data references, "
    "(5) next steps. Be factual and specific. Do not add commentary."
)

# Marker injected after compaction so the LLM knows history was compressed
COMPACTION_MARKER = (
    "[This conversation was automatically compacted. "
    "Previous context has been summarized above. "
    "Some details from earlier messages may no longer be available.]"
)


async def compact_conversation(
    messages: list[dict[str, Any]],
    provider: str,
    model: str,
    *,
    keep_recent: int = 10,
) -> tuple[list[dict[str, Any]], bool]:
    """Compact conversation via LLM summarization.

    Returns (new_messages, did_compact).
    Only runs for non-Anthropic providers (Anthropic uses server-side compaction).
    """
    if provider == "anthropic":
        log.debug("Skipping client compaction — Anthropic uses server-side compaction")
        return messages, False

    if len(messages) <= keep_recent + 2:
        log.debug("Not enough messages to compact (%d <= %d)", len(messages), keep_recent + 2)
        return messages, False

    # Split: messages to summarize vs. messages to keep
    to_summarize = messages[:-keep_recent]
    to_keep = messages[-keep_recent:]

    # Build conversation text for summarization
    summary_input = _build_summary_input(to_summarize)
    if not summary_input.strip():
        return messages, False

    # Call LLM for summarization
    summary = await _call_summarize(summary_input, provider, model)
    if not summary:
        log.warning("Compaction summary generation failed — keeping original messages")
        return messages, False

    # Build new message list: summary + marker + recent messages
    new_messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"[Conversation Summary]\n{summary}"},
        {"role": "assistant", "content": "Understood. I have the summary context."},
        {"role": "user", "content": COMPACTION_MARKER},
        {"role": "assistant", "content": "Acknowledged. Continuing from where we left off."},
        *to_keep,
    ]

    log.info(
        "Compacted conversation: %d → %d messages (summarized %d, kept %d recent)",
        len(messages),
        len(new_messages),
        len(to_summarize),
        len(to_keep),
    )
    return new_messages, True


def _build_summary_input(messages: list[dict[str, Any]]) -> str:
    """Convert messages to a flat text representation for summarization."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content[:2000]  # Cap per-message length for summary input
        elif isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    t = block.get("text", "") or block.get("content", "")
                    if isinstance(t, str):
                        texts.append(t[:500])
                elif isinstance(block, str):
                    texts.append(block[:500])
            text = " ".join(texts)[:2000]
        else:
            text = str(content)[:2000]
        if text.strip():
            parts.append(f"{role}: {text}")
    return "\n".join(parts)


async def _call_summarize(conversation_text: str, provider: str, model: str) -> str | None:
    """Call the appropriate LLM provider to generate a summary."""
    try:
        if provider == "openai":
            return await _summarize_openai(conversation_text, model)
        elif provider in ("glm", "zhipuai"):
            return await _summarize_glm(conversation_text, model)
        else:
            log.warning("Unknown provider '%s' for compaction — skipping", provider)
            return None
    except Exception:
        log.exception("Compaction summarization failed for provider=%s", provider)
        return None


async def _summarize_openai(conversation_text: str, model: str) -> str | None:
    """Generate summary using OpenAI provider."""
    from core.llm.providers.openai import _get_openai_client

    client = _get_openai_client()
    if client is None:
        return None

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _COMPACTION_PROMPT},
            {"role": "user", "content": conversation_text},
        ],
        max_tokens=2048,
        temperature=0.0,
    )
    choice = response.choices[0] if response.choices else None
    if choice and choice.message and choice.message.content:
        return str(choice.message.content)
    return None


async def _summarize_glm(conversation_text: str, model: str) -> str | None:
    """Generate summary using GLM provider (OpenAI-compatible API)."""
    from core.llm.providers.glm import _get_glm_client

    client = _get_glm_client()
    if client is None:
        return None

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _COMPACTION_PROMPT},
            {"role": "user", "content": conversation_text},
        ],
        max_tokens=2048,
        temperature=0.0,
    )
    choice = response.choices[0] if response.choices else None
    if choice and choice.message and choice.message.content:
        return str(choice.message.content)
    return None
