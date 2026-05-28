"""Shared capability implementations — web_search + complete_text.

PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28). Concrete capability methods that
multiple adapters share. Each adapter inlines a tiny wrapper that:

- delegates to one of these helpers for the actual SDK call
- declares the appropriate ``supports_*`` class attribute

Helpers raise on failure (no silent return None) so the dispatch wrapper in
``core/llm/adapters/dispatch.py`` can distinguish billing-fatal vs transient
via :func:`core.llm.errors.is_billing_fatal`.
"""

from __future__ import annotations

import logging
from typing import Any

from core.llm.adapters.base import (
    TextCompletionResult,
    UsageSummary,
    WebSearchResult,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anthropic — used by AnthropicPaygAdapter + AnthropicOAuthAdapter
# ---------------------------------------------------------------------------


async def anthropic_web_search(
    client: Any, *, query: str, max_results: int, model: str, adapter_name: str
) -> WebSearchResult:
    """Anthropic native ``web_search_20260209`` tool — same shape on PAYG and
    OAuth subscription endpoints."""
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Search the web for: {query}. Return up to {max_results} relevant "
                    "results with titles, URLs, and brief summaries."
                ),
            }
        ],
        timeout=60.0,
    )
    text_parts: list[str] = []
    source_urls: list[str] = []
    for block in getattr(response, "content", []) or []:
        if hasattr(block, "text"):
            text_parts.append(block.text)
        if getattr(block, "type", "") == "web_search_tool_result":
            for entry in getattr(block, "content", []) or []:
                url = getattr(entry, "url", None)
                if url:
                    source_urls.append(url)
    return WebSearchResult(
        query=query,
        text="\n".join(text_parts),
        source_urls=tuple(source_urls),
        adapter_name=adapter_name,
    )


async def anthropic_complete_text(
    client: Any,
    *,
    prompt: str,
    system: str,
    model: str,
    max_tokens: int,
) -> TextCompletionResult:
    """Single-turn Anthropic ``messages.create`` — used by compaction / extraction."""
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": 60.0,
    }
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if hasattr(block, "text"):
            text_parts.append(block.text)
    usage = getattr(response, "usage", None)
    return TextCompletionResult(
        text="".join(text_parts),
        usage=UsageSummary(
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
        ),
    )


# ---------------------------------------------------------------------------
# OpenAI Responses API — used by OpenAIPaygAdapter (web_search)
# ---------------------------------------------------------------------------


async def openai_web_search(
    client: Any, *, query: str, max_results: int, model: str, adapter_name: str
) -> WebSearchResult:
    """OpenAI Responses API ``web_search`` hosted tool. PAYG only — the Codex
    backend subscription endpoint does not advertise web_search support
    (frontier audit 2026-05-28)."""
    response = await client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        input=(
            f"Search the web for: {query}. Return up to {max_results} relevant "
            "results with titles, URLs, and brief summaries."
        ),
    )
    text_parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") == "message":
            for sub in getattr(item, "content", []) or []:
                if getattr(sub, "type", "") == "output_text":
                    text = getattr(sub, "text", "")
                    if text:
                        text_parts.append(text)
    if not text_parts:
        raise RuntimeError("openai_web_search: empty output_text in response")
    return WebSearchResult(
        query=query,
        text="\n".join(text_parts),
        adapter_name=adapter_name,
    )


# ---------------------------------------------------------------------------
# OpenAI Responses API — preferred path for OpenAI text completion
# ---------------------------------------------------------------------------


async def openai_responses_complete_text(
    client: Any,
    *,
    prompt: str,
    system: str,
    model: str,
    max_tokens: int,
) -> TextCompletionResult:
    """Single-turn OpenAI Responses API call — preferred over Chat
    Completions for OpenAI PAYG (and Codex backend if/when it supports
    text_completion). Responses API is the forward-going surface
    (per developers.openai.com/api/docs) — Chat Completions stays for
    GLM-family endpoints (z.ai PAYG / Coding Plan) which don't expose
    Responses API.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "input": prompt,
        "max_output_tokens": max_tokens,
    }
    if system:
        kwargs["instructions"] = system
    response = await client.responses.create(**kwargs)
    text_parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") == "message":
            for sub in getattr(item, "content", []) or []:
                if getattr(sub, "type", "") == "output_text":
                    sub_text = getattr(sub, "text", "")
                    if sub_text:
                        text_parts.append(sub_text)
    usage = getattr(response, "usage", None)
    return TextCompletionResult(
        text="".join(text_parts),
        usage=UsageSummary(
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        ),
    )


# ---------------------------------------------------------------------------
# OpenAI Chat Completions — kept ONLY for GLM-family endpoints (z.ai PAYG /
# Coding Plan) which don't expose Responses API. OpenAI proper uses the
# Responses helper above.
# ---------------------------------------------------------------------------


async def openai_chat_complete_text(
    client: Any,
    *,
    prompt: str,
    system: str,
    model: str,
    max_tokens: int,
) -> TextCompletionResult:
    """Single-turn Chat Completions call — used by GLM adapters
    (``glm-payg`` / ``glm-coding-plan``) whose z.ai endpoint speaks the
    Chat Completions wire shape only. OpenAI adapters should call
    :func:`openai_responses_complete_text` instead.
    """
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        timeout=60.0,
    )
    choice = response.choices[0] if response.choices else None
    text = (choice.message.content or "") if choice else ""
    usage = getattr(response, "usage", None)
    return TextCompletionResult(
        text=text,
        usage=UsageSummary(
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        ),
    )


# ---------------------------------------------------------------------------
# GLM — Chat Completions with z.ai native web_search tool
# ---------------------------------------------------------------------------


async def glm_web_search(
    client: Any, *, query: str, max_results: int, model: str, adapter_name: str
) -> WebSearchResult:
    """GLM (zhipuai/z.ai) native ``web_search`` Chat Completions tool. PAYG
    endpoint confirmed; Coding Plan subscription endpoint untested (audit
    2026-05-28)."""
    response = await client.chat.completions.create(
        model=model,
        tools=[{"type": "web_search", "web_search": {"enable": True}}],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Search the web for: {query}. Return up to {max_results} relevant "
                    "results with titles, URLs, and brief summaries."
                ),
            }
        ],
        timeout=30.0,
    )
    choice = response.choices[0] if response.choices else None
    text = (choice.message.content or "") if choice else ""
    if not text:
        raise RuntimeError("glm_web_search: empty content in response")
    return WebSearchResult(query=query, text=text, adapter_name=adapter_name)


__all__ = [
    "anthropic_complete_text",
    "anthropic_web_search",
    "glm_web_search",
    "openai_chat_complete_text",
    "openai_responses_complete_text",
    "openai_web_search",
]
