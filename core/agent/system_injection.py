"""System injection — sandwich-style context reinforcement for multi-turn conversations.

Inspired by Claude Code's ``prependUserContext()`` pattern (utils/api.ts:449-474),
this module builds a system reminder that is prepended to the messages array
before each LLM call. This creates a "sandwich" where the user's messages are
wrapped between the system prompt (above) and the system reminder (inline).

Why: In long multi-turn conversations, instructions in the system prompt drift
out of the model's attention window. The system reminder reinforces critical
context (date, active rules, key constraints) at a position closer to the
latest user message, improving instruction following.

The reminder is injected into a deep-copied messages list (never into the
stored ConversationContext), so it is ephemeral and regenerated each round.
"""

from __future__ import annotations

import logging
from datetime import datetime
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
    """Build a system reminder string for sandwich injection.

    Assembles a concise context block containing:
      - Current date/time (prevents year hallucination in tool calls)
      - Active analysis rules (from ProjectMemory, if any)
      - Round index (helps the model track progress)
      - Extra context (caller-provided key-value pairs)

    Returns empty string if nothing meaningful to inject.
    """
    parts: list[str] = []

    # 1. Date context (always useful — prevents stale year in searches)
    now = datetime.now()
    parts.append(f"Current date: {now.strftime('%Y-%m-%d (%A)')}")

    # 2. Round awareness
    if round_idx > 0:
        parts.append(f"Current round: {round_idx + 1}")

    # 3. Active analysis rules (lightweight — names only)
    rules_summary = _get_active_rules_summary()
    if rules_summary:
        parts.append(f"Active rules: {rules_summary}")

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


def prepend_system_reminder(
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    round_idx: int = 0,
    extra_context: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Prepend a system reminder to the messages list (sandwich injection).

    Creates a user message with the system reminder and inserts it at
    position 0 of the messages list. The messages list is modified
    **in-place** (caller should pass a deep copy from ``get_messages()``).

    If the first message is already a system-reminder from a previous
    injection (e.g., stale from a retry), it is replaced rather than
    stacked.

    Args:
        messages: Deep-copied message list (will be modified in-place).
        model: Current model name (for context).
        round_idx: Current round index in the agentic loop.
        extra_context: Additional key-value pairs to include.

    Returns:
        The same messages list (for chaining convenience).
    """
    reminder = build_system_reminder(
        model=model,
        round_idx=round_idx,
        extra_context=extra_context,
    )

    if not reminder:
        return messages

    reminder_message: dict[str, Any] = {
        "role": "user",
        "content": f"[{_REMINDER_TAG}]\n{reminder}\n[/{_REMINDER_TAG}]",
    }

    # Replace stale reminder if present (idempotent injection)
    if messages and _is_system_reminder(messages[0]):
        messages[0] = reminder_message
    else:
        messages.insert(0, reminder_message)

    return messages


def _is_system_reminder(message: dict[str, Any]) -> bool:
    """Check if a message is a system reminder (for dedup)."""
    if message.get("role") != "user":
        return False
    content = message.get("content", "")
    if isinstance(content, str):
        return content.startswith(f"[{_REMINDER_TAG}]")
    return False


def _get_active_rules_summary() -> str:
    """Get a one-line summary of active analysis rules from ProjectMemory.

    Returns empty string on any failure (graceful degradation).
    """
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if not mem.exists():
            return ""

        rules = mem.list_rules()
        if not rules:
            return ""

        names = [r["name"] for r in rules[:5]]
        return ", ".join(names)
    except Exception:
        log.debug("Failed to get active rules for system reminder", exc_info=True)
        return ""
