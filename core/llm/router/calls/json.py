"""``call_llm_json`` — legacy JSON-extraction wrapper around ``call_llm``.

Prefer ``call_llm_parsed`` for guaranteed structured output. Kept for
backward compatibility with code that expects ``dict[str, Any]``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .text import call_llm

log = logging.getLogger(__name__)


def call_llm_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    seed: int | None = None,
) -> dict[str, Any]:
    """Claude call that parses JSON from the response. Includes failover.

    Legacy function — prefer call_llm_parsed() for guaranteed structured output.
    Kept for backward compatibility with code that expects dict[str, Any].
    """
    raw = call_llm(
        system, user, model=model, max_tokens=max_tokens, temperature=temperature, seed=seed
    )
    # Strip markdown code fences if present (handles ```json, ``` with trailing spaces, etc.)
    text = raw.strip()
    text = re.sub(r"^```\w*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    text = text.strip()

    # Try direct JSON parse
    try:
        result: dict[str, Any] = json.loads(text)
        return result
    except json.JSONDecodeError:
        pass

    # Fallback: extract JSON object from text (handles markdown-wrapped responses)
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            result = json.loads(candidate)
            log.info("Extracted JSON from position %d-%d in LLM response", first_brace, last_brace)
            return result
        except json.JSONDecodeError:
            pass

    log.error("Failed to parse LLM JSON response. Raw text: %s", text[:500])
    raise ValueError("LLM returned invalid JSON: could not extract JSON object from response")


__all__ = ["call_llm", "call_llm_json"]
