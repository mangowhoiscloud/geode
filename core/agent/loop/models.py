"""Result dataclass + context-exhausted exception/helpers for AgenticLoop.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7).
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class _ContextExhaustedError(Exception):
    """Raised when context remains critical after pruning — unrecoverable."""


_EXHAUSTED_FALLBACK = (
    "Context window exhausted. "
    "This conversation has been automatically reset — "
    "please start a new thread or send a new message to continue."
)

_EXHAUSTED_SYSTEM = (
    "The conversation context has been exhausted and automatically reset. "
    "Reply ONLY with a short notice (1-2 sentences) in the SAME language as the user's message. "
    "Tell them the conversation was reset and they should start a new thread or send a new message."
)


def _context_exhausted_message(user_input: str) -> str:
    """Generate context-exhausted message in the user's language via lightweight LLM call."""
    try:
        import anthropic

        from core.config import ANTHROPIC_BUDGET, settings

        if not settings.anthropic_api_key:
            return _EXHAUSTED_FALLBACK

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=ANTHROPIC_BUDGET,
            max_tokens=150,
            system=_EXHAUSTED_SYSTEM,
            messages=[{"role": "user", "content": user_input[:200]}],
        )
        block = resp.content[0] if resp.content else None
        text = block.text if block and hasattr(block, "text") else ""
        return text or _EXHAUSTED_FALLBACK
    except Exception:
        log.debug("Exhausted message LLM call failed, using fallback", exc_info=True)
        return _EXHAUSTED_FALLBACK


@dataclass
class AgenticResult:
    """Result of an agentic loop execution."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    error: str | None = None
    # "natural" | "forced_text" | "max_rounds" | "time_budget_expired"
    # | "llm_error" | "context_exhausted" | "cost_budget_exceeded"
    termination_reason: str = "unknown"
    summary: str = ""  # Tier 1 compact action summary (auto-generated)
    reasoning_metrics: dict[str, object] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}
