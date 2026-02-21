"""LLM client wrapper for Anthropic and OpenAI."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import anthropic

from geode.config import settings


def get_anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def call_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Synchronous Claude call. Returns text content."""
    client = get_anthropic_client()
    model = model or settings.model
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    block = response.content[0]
    assert hasattr(block, "text"), f"Expected TextBlock, got {type(block)}"
    return block.text  # type: ignore[return-value]


def call_llm_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> dict[str, Any]:
    """Claude call that parses JSON from the response."""
    raw = call_llm(system, user, model=model, max_tokens=max_tokens, temperature=temperature)
    # Strip markdown code fences if present (handles ```json, ``` with trailing spaces, etc.)
    text = raw.strip()
    text = re.sub(r"^```\w*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    result: dict[str, Any] = json.loads(text)
    return result


def call_llm_streaming(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> Iterator[str]:
    """Streaming Claude call. Yields text deltas."""
    client = get_anthropic_client()
    model = model or settings.model
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        yield from stream.text_stream
