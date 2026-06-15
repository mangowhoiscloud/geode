"""Async streaming LLM call with retry + failover."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

# v0.88.0 — RETRYABLE_ERRORS resolves through providers/anthropic
# ``__getattr__`` (lazy SDK load).  Defer to function scope so the
# cold-start path does not pull anthropic at module import.
from core.hooks.system import HookEvent
from core.llm.providers.anthropic import (
    get_async_anthropic_client,
)
from core.llm.providers.anthropic import (
    system_with_cache as _system_with_cache,
)
from core.llm.router._hooks import _fire_hook
from core.llm.router._usage import _record_response_usage

from ._route import _route_provider

log = logging.getLogger(__name__)


async def call_llm_streaming_async(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Streaming Claude call with failover. Yields text deltas."""
    from core.config import settings
    from core.llm.fallback import MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY
    from core.llm.providers.anthropic import (
        RETRYABLE_ERRORS as _RETRYABLE_ERRORS,
    )

    client = get_async_anthropic_client()
    target_model = model or settings.model
    provider = _route_provider(target_model)

    # Hook: LLM_CALL_START
    _fire_hook(
        HookEvent.LLM_CALL_STARTED,
        {"model": target_model, "provider": provider, "function": "call_llm_streaming_async"},
    )
    t0 = time.monotonic()

    async def _do_stream(*, model: str) -> AsyncIterator[str]:
        system_cached = _system_with_cache(system)
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text

            # Capture token usage from the stream's final response
            final = await stream.get_final_message()
            if final:
                _record_response_usage(final, model, label="stream")

    async def _hooked_stream(inner: AsyncIterator[str]) -> AsyncIterator[str]:
        """Wrapper that fires LLM_CALL_END after stream exhaustion or error."""
        try:
            async for item in inner:
                yield item
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _fire_hook(
                HookEvent.LLM_CALL_ENDED,
                {
                    "model": target_model,
                    "provider": provider,
                    "function": "call_llm_streaming_async",
                    "latency_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise
        else:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _fire_hook(
                HookEvent.LLM_CALL_ENDED,
                {
                    "model": target_model,
                    "provider": provider,
                    "function": "call_llm_streaming_async",
                    "latency_ms": elapsed_ms,
                    "error": None,
                },
            )

    # For streaming, retry at connection level only
    from core.config import ANTHROPIC_FALLBACK_CHAIN  # H11-tail: live read

    models_to_try = [target_model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != target_model]
    last_error: Exception | None = None

    for current_model in models_to_try:
        for attempt in range(MAX_RETRIES):
            try:
                async for token in _hooked_stream(_do_stream(model=current_model)):
                    yield token
                return
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                delay = min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)
                log.warning(
                    "Streaming call failed (model=%s, attempt=%d/%d): %s",
                    current_model,
                    attempt + 1,
                    MAX_RETRIES,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)

    if last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    raise last_error


__all__ = ["call_llm_streaming_async"]
