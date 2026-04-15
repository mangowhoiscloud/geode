"""LLM commentary generation for tool call results.

After a tool call (analyze, search, list, compare) produces structured output,
this module generates a brief natural-language commentary that highlights
key insights and suggests next actions.

Graceful degradation: all exceptions are caught and return None so that
commentary failures never break the main pipeline output.
"""

from __future__ import annotations

import logging
from typing import Any

from core.llm.prompts import COMMENTARY_SYSTEM, COMMENTARY_USER
from core.llm.router import call_llm

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Commentary generation
# ---------------------------------------------------------------------------


def _format_context(context: dict[str, Any]) -> str:
    """Format context dict into a readable summary string for the prompt."""
    lines: list[str] = []
    for key, value in context.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def generate_commentary(
    user_query: str,
    action: str,
    context: dict[str, Any],
    *,
    model: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.4,
) -> str | None:
    """Generate a brief LLM commentary for tool call results.

    Returns the commentary text, or None if generation fails for any reason.
    """
    try:
        context_summary = _format_context(context)
        user_prompt = COMMENTARY_USER.format(
            user_query=user_query,
            action=action,
            context_summary=context_summary,
        )
        text = call_llm(
            COMMENTARY_SYSTEM,
            user_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        stripped = text.strip() if text else ""
        return stripped or None
    except Exception:
        log.debug("Commentary generation failed", exc_info=True)
        return None
