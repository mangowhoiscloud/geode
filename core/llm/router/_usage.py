"""Token usage recording helpers shared by all router call functions.

Anthropic vs OpenAI/GLM responses expose usage tokens under different
attribute names; these helpers normalize the recording call into
``token_tracker.get_tracker().record(...)`` so the dispatch loops in
``calls.py`` stay focused on transport.
"""

from __future__ import annotations

import logging
from typing import Any

from core.llm.token_tracker import LLMUsage, get_tracker

log = logging.getLogger(__name__)


def _record_response_usage(
    response: Any,
    model: str,
    *,
    label: str = "",
) -> LLMUsage | None:
    """Record token usage from an Anthropic response. Returns usage or None."""
    if not (hasattr(response, "usage") and response.usage):
        return None
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    cache_create = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    usage = get_tracker().record(
        model,
        in_tok,
        out_tok,
        cache_creation_tokens=cache_create,
        cache_read_tokens=cache_read,
    )
    suffix = f" ({label})" if label else ""
    log.info(
        "LLM call%s: model=%s in=%d out=%d cost=$%.4f",
        suffix,
        model,
        in_tok,
        out_tok,
        usage.cost_usd,
    )
    if cache_create or cache_read:
        log.debug("Cache: create=%d read=%d", cache_create, cache_read)
    return usage


def _record_openai_usage(
    response: Any,
    model: str,
    *,
    label: str = "",
) -> LLMUsage | None:
    """Record token usage from an OpenAI-format response. Returns usage or None."""
    if not (hasattr(response, "usage") and response.usage):
        return None
    in_tok = response.usage.prompt_tokens or 0
    out_tok = response.usage.completion_tokens or 0
    usage = get_tracker().record(model, in_tok, out_tok)
    suffix = f" ({label})" if label else ""
    log.info(
        "LLM call%s: model=%s in=%d out=%d cost=$%.4f",
        suffix,
        model,
        in_tok,
        out_tok,
        usage.cost_usd,
    )
    return usage
