"""System injection — XML-tagged context reinforcement for multi-turn conversations.

Inspired by Claude Code's ``<system-reminder>`` pattern: a reminder block is
attached adjacent to the **latest** user message (appended as the final
message) before each LLM call, keeping the injected content explicitly
XML-delimited.

Why: In long multi-turn conversations, instructions in the system prompt drift
out of the model's attention window. The system reminder reinforces critical
context (date, active rules, key constraints) at a position closer to the
latest user message, improving instruction following.

Cache contract (PR-CACHE-REMINDER, 2026-06-10): prompt caching is a prefix
match and messages render after the system blocks. The previous design
inserted the reminder at ``messages[0]`` and rewrote it per round
("Current round: N"), which re-keyed the entire history prefix on every
round — none of the rolling message cache breakpoints
(core/llm/providers/anthropic.py, ADR-013 T5) could ever hit. The reminder
therefore MUST stay append-only and MUST stay out of the stored
ConversationContext:

  - ``append_system_reminder`` returns a NEW list; the caller's history list
    is never modified, so ``_sync_messages_to_context`` cannot persist the
    reminder into history as stale mid-prefix bytes.
  - Per-round variance (round index, date) lands after the last stable
    history block, so only the reminder itself is uncached each round.

Guard: ``tests/core/agent/test_system_injection.py::TestCacheContract``.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Tag format for system-injected messages (mirrors Claude Code's <system-reminder>)
_REMINDER_TAG = "system-reminder"

# Max chars for the reminder to stay within a reasonable token budget
_MAX_REMINDER_CHARS = 800


def build_system_reminder(
    *,
    model: str = "",
    round_idx: int = 0,
    extra_context: dict[str, str] | None = None,
) -> str:
    """Build a system reminder string for end-adjacent injection.

    Assembles a concise context block containing:
      - Current date/time (prevents year hallucination in tool calls)
      - Active analysis rules (from ProjectMemory, if any)
      - Round index (helps the model track progress)
      - Extra context (caller-provided key-value pairs)

    Returns empty string if nothing meaningful to inject.
    """
    parts: list[str] = []

    # 1. Date context (shared helper — prevents stale year in searches)
    from core.agent.system_prompt import format_current_date

    parts.append(f"Current date: {format_current_date()}")

    # 2. Round awareness
    if round_idx > 0:
        parts.append(f"Current round: {round_idx + 1}")

    # 3. Active analysis rules (shared helper — names only)
    from core.agent.system_prompt import get_active_rule_names

    rule_names = get_active_rule_names()
    if rule_names:
        parts.append(f"Active rules: {', '.join(rule_names)}")

    # 4. Extra context from caller
    if extra_context:
        for key, value in extra_context.items():
            parts.append(f"{key}: {value}")

    if not parts:
        return ""

    body = "\n".join(parts)

    # Enforce budget
    if len(body) > _MAX_REMINDER_CHARS:
        body = body[:_MAX_REMINDER_CHARS] + "..."
        log.warning("System reminder truncated to %d chars", _MAX_REMINDER_CHARS)

    return body


def append_system_reminder(
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    round_idx: int = 0,
    extra_context: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return a new messages list with a system reminder appended last.

    The input list is NOT modified — the reminder exists only in the
    per-request copy, never in the stored conversation history (see module
    docstring for the prompt-cache contract this protects).

    A legacy reminder persisted at position 0 by the pre-2026-06-10 prepend
    design is stripped, so long-lived sessions converge to a stable prefix
    after one call.

    Args:
        messages: Conversation history (left untouched).
        model: Current model name (for context).
        round_idx: Current round index in the agentic loop.
        extra_context: Additional key-value pairs to include.

    Returns:
        A new list ``[*history, reminder]`` — or the input list unchanged
        when there is nothing to inject.
    """
    base = messages
    if base and _is_system_reminder(base[0]):
        base = base[1:]

    reminder = build_system_reminder(
        model=model,
        round_idx=round_idx,
        extra_context=extra_context,
    )

    if not reminder:
        return base

    reminder_message: dict[str, Any] = {
        "role": "user",
        "content": f"<{_REMINDER_TAG}>\n{reminder}\n</{_REMINDER_TAG}>",
    }

    return [*base, reminder_message]


def _is_system_reminder(message: dict[str, Any]) -> bool:
    """Check if a message is a system reminder (for legacy-prefix strip)."""
    if message.get("role") != "user":
        return False
    content = message.get("content", "")
    if isinstance(content, str):
        return content.startswith(f"<{_REMINDER_TAG}>")
    return False
