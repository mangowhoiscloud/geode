"""LLM-based learning extraction — Claude Code extractMemories pattern.

Runs on TURN_COMPLETE (low priority, after auto_learn regex detectors).
Sends recent conversation context to a budget model (Haiku/GLM-flash)
to extract learning items that regex detectors would miss.

Cursor-based incremental extraction: only processes messages since the
last extraction, skipping already-seen content.  Mutual exclusion skips
extraction if the main agent already wrote to memory this turn.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from core.hooks.system import HookEvent

log = logging.getLogger(__name__)

_TURN_INTERVAL = 1  # extract every N turns (cursor-based, so safe at 1)
_MAX_CONTEXT_CHARS = 3000  # recent conversation to send to LLM
_MAX_PER_SESSION = 10  # LLM extractions per session (raised from 5)

_EXTRACT_PROMPT = """\
Task: learning extraction. Analyze the recent conversation and identify
what should be remembered for future sessions.

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


async def _call_budget_llm(prompt: str) -> str | None:
    """Call a budget model for extraction. Returns text or None on failure.

    PR-EXTRACT-LEARNING-MODELS-ADAPTER (2026-05-28) — dispatches through
    :func:`core.llm.adapters.dispatch.complete_text_via_adapters` so the
    full operator credential surface (PAYG + Subscription + local-CLI)
    drives extraction with one switch. The legacy provider-direct
    ``_call_glm_flash`` / ``_call_haiku`` helpers — each instantiating a
    fresh sync SDK client + raising bare ``Exception`` to ``log.debug``
    — are replaced by the central dispatch chain's billing-fatal /
    transient handling. Returns ``None`` (graceful) when every capable
    adapter fails so the caller treats extraction as a soft hint.

    The extraction model determines the provider route. Dispatch no
    longer scans a provider order, so an unavailable extraction adapter
    degrades cleanly instead of trying unrelated credentials.
    """
    from core.config import _resolve_provider, settings
    from core.llm.adapters._source_inference import infer_source
    from core.llm.adapters.dispatch import (
        AdapterDispatchError,
        AdapterUnavailableError,
        complete_text_via_adapters,
    )
    from core.llm.adapters.registry import normalize_registry_provider
    from core.llm.errors import BillingError

    provider = normalize_registry_provider(_resolve_provider(settings.learning_extract_model))
    source = infer_source(provider)
    # Strict single-adapter dispatch tries exactly the extraction model's
    # route and never silently widens. Returning ``None`` on any failure
    # keeps the extraction hook a soft hint — the loop's main path is
    # unaffected.
    try:
        result = await complete_text_via_adapters(
            prompt,
            model=settings.learning_extract_model,
            max_tokens=300,
            prefer_provider=provider,
            prefer_source=source,
            model_by_provider={"glm": settings.learning_extract_model},
        )
    except BillingError:
        log.debug("LLM extract: adapter credit exhausted")
        return None
    except AdapterUnavailableError:
        log.debug("LLM extract: no capable adapter registered")
        return None
    except AdapterDispatchError:
        log.debug("LLM extract: single attempt transient failure")
        return None
    except Exception:
        # Expected degrade (no key / quota / offline) — extraction is an
        # optional enrichment, so debug is the right level; the save path
        # below warns because losing an EXTRACTED pattern is data loss.
        log.debug("LLM extract call failed", exc_info=True)
        return None
    return result.text or None


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


def make_llm_extract_handler() -> tuple[str, Callable[..., Awaitable[None]]]:
    """Create TURN_COMPLETE handler for LLM-based learning extraction.

    Claude Code extractMemories pattern: cursor-based incremental extraction
    with mutual exclusion (skip if main agent wrote to memory this turn).
    """
    turn_count = 0
    session_extractions = 0
    # ``float("-inf")`` so the first call always passes the cooldown gate.
    # Mirrors the auto_learn fix — fresh xdist worker processes have small
    # ``time.monotonic()`` values that would otherwise trip the cooldown.
    last_extract_ts: float = float("-inf")
    _seen_inputs: set[int] = set()  # hash of already-extracted user inputs

    async def _on_turn_complete(event: HookEvent, data: dict[str, Any]) -> None:
        nonlocal turn_count, session_extractions, last_extract_ts

        turn_count += 1

        # Fire every N turns
        if turn_count % _TURN_INTERVAL != 0:
            return

        if session_extractions >= _MAX_PER_SESSION:
            return

        # 30s cooldown (reduced from 60s for cursor-based extraction)
        now = time.monotonic()
        if now - last_extract_ts < 30.0:
            return

        # Mutual exclusion: skip if main agent already wrote to memory this turn
        # (Claude Code pattern — avoid duplicate extraction)
        tool_calls = data.get("tool_calls", [])
        _MEMORY_TOOLS = {"memory_save", "note_save", "profile_learn", "manage_rule"}
        if _MEMORY_TOOLS & set(tool_calls):
            log.debug("LLM extract: skipping — main agent wrote to memory")
            return

        # Cursor-based: skip if we already extracted from this user input
        user_input = data.get("user_input", "")
        input_hash = hash(user_input)
        if input_hash in _seen_inputs:
            log.debug("LLM extract: skipping — already extracted from this input")
            return

        from core.tools.profile_tools import get_user_profile

        profile = get_user_profile()
        if profile is None:
            return

        context = _build_context(data)
        if len(context) < 50:
            return

        prompt = _EXTRACT_PROMPT.format(context=context)
        llm_output = await _call_budget_llm(prompt)
        if not llm_output:
            return

        # Mark as seen regardless of extraction result
        _seen_inputs.add(input_hash)

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
                # PR-OBS-CONTRACT — extracted-but-unsaved is silent data
                # loss; surface at WARNING.
                log.warning("LLM extract save failed", exc_info=True)

    return ("turn_llm_extract", _on_turn_complete)
