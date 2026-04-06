"""LLM-based learning extraction — Claude Code extractMemories pattern.

Runs on TURN_COMPLETE (low priority, after auto_learn regex detectors).
Sends recent conversation context to a budget model (Haiku/GLM-flash)
to extract learning items that regex detectors would miss.

Fires at most once per 5 turns to control cost.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from core.hooks.system import HookEvent

log = logging.getLogger(__name__)

_TURN_INTERVAL = 5  # extract every N turns
_MAX_CONTEXT_CHARS = 3000  # recent conversation to send to LLM
_MAX_PER_SESSION = 5  # LLM extractions per session

_EXTRACT_PROMPT = """\
You are a learning extraction agent. Analyze the recent conversation
and identify what should be remembered for future sessions.

Extract ONLY items that are:
- User corrections ("don't do X", "that's wrong")
- User validations ("yes exactly", "good approach", accepting without pushback)
- Stated preferences (tools, style, workflow)
- Domain knowledge learned during this exchange

For each item, output ONE LINE in this format:
[category] pattern text. Why: reason

Categories: correction, validation, preference, domain

Rules:
- Max 3 items per extraction
- Skip obvious/trivial items
- Include "Why:" with specific context
- If nothing noteworthy, output: NONE

Recent conversation:
---
{context}
---

Extract learning items:"""


def _build_context(data: dict[str, Any]) -> str:
    """Build recent conversation context from turn data."""
    parts: list[str] = []
    user_input = data.get("user_input", "")
    assistant_text = data.get("text", "")
    tool_calls = data.get("tool_calls", [])

    if user_input:
        parts.append(f"User: {user_input[:500]}")
    if tool_calls:
        parts.append(f"Tools used: {', '.join(tool_calls[:5])}")
    if assistant_text:
        parts.append(f"Assistant: {assistant_text[:1500]}")

    return "\n".join(parts)[:_MAX_CONTEXT_CHARS]


def _call_budget_llm(prompt: str) -> str | None:
    """Call a budget model for extraction. Returns text or None on failure."""
    try:
        from core.config import settings

        # Try GLM-flash first (free), then Haiku
        if settings.zai_api_key:
            return _call_glm_flash(prompt, settings.zai_api_key)
        if settings.anthropic_api_key:
            return _call_haiku(prompt, settings.anthropic_api_key)
        return None
    except Exception:
        log.debug("LLM extract call failed", exc_info=True)
        return None


def _call_glm_flash(prompt: str, api_key: str) -> str | None:
    """Call GLM-4.7-flash (free tier)."""
    import openai

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )
    resp = client.chat.completions.create(
        model="glm-4.7-flash",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.0,
        timeout=10.0,
    )
    return resp.choices[0].message.content if resp.choices else None


def _call_haiku(prompt: str, api_key: str) -> str | None:
    """Call Claude Haiku (budget tier)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
        timeout=10.0,
    )
    return resp.content[0].text if resp.content else None


def _parse_extractions(text: str) -> list[tuple[str, str]]:
    """Parse LLM output into (pattern_text, category) pairs."""
    if not text or "NONE" in text.upper():
        return []

    results: list[tuple[str, str]] = []
    valid_categories = {"correction", "validation", "preference", "domain"}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Parse: [category] pattern text. Why: reason
        if line.startswith("["):
            bracket_end = line.find("]")
            if bracket_end > 0:
                category = line[1:bracket_end].strip().lower()
                pattern = line[bracket_end + 1 :].strip()
                if category in valid_categories and len(pattern) > 10:
                    results.append((pattern, category))

    return results[:3]  # max 3 per extraction


def make_llm_extract_handler() -> tuple[str, Callable[..., None]]:
    """Create TURN_COMPLETE handler for LLM-based learning extraction."""
    turn_count = 0
    session_extractions = 0
    last_extract_ts = 0.0

    def _on_turn_complete(event: HookEvent, data: dict[str, Any]) -> None:
        nonlocal turn_count, session_extractions, last_extract_ts

        turn_count += 1

        # Fire every N turns
        if turn_count % _TURN_INTERVAL != 0:
            return

        if session_extractions >= _MAX_PER_SESSION:
            return

        # 60s cooldown
        now = time.monotonic()
        if now - last_extract_ts < 60.0:
            return

        from core.tools.profile_tools import get_user_profile

        profile = get_user_profile()
        if profile is None:
            return

        context = _build_context(data)
        if len(context) < 50:
            return

        prompt = _EXTRACT_PROMPT.format(context=context)
        llm_output = _call_budget_llm(prompt)
        if not llm_output:
            return

        extractions = _parse_extractions(llm_output)
        for pattern_text, category in extractions:
            try:
                saved = profile.add_learned_pattern(pattern_text, category)
                if saved:
                    session_extractions += 1
                    last_extract_ts = now
                    log.info(
                        "LLM extract: [%s] %s",
                        category,
                        pattern_text[:80],
                    )
            except Exception:
                log.debug("LLM extract save failed", exc_info=True)

    return ("turn_llm_extract", _on_turn_complete)
