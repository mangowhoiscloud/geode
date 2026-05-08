"""``call_llm_streaming`` — streaming LLM call with retry + failover."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from core.llm.providers.anthropic import (
    FALLBACK_MODELS,
    get_anthropic_client,
)
from core.llm.providers.anthropic import (
    system_with_cache as _system_with_cache,
)

# v0.88.0 — RETRYABLE_ERRORS resolves through providers/anthropic
# ``__getattr__`` (lazy SDK load).  Defer to function scope so the
# cold-start path does not pull anthropic at module import.
from core.llm.router._hooks import _fire_hook
from core.llm.router._usage import _record_response_usage

from ._route import _route_provider

log = logging.getLogger(__name__)


def call_llm_streaming(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> Iterator[str]:
    """Streaming Claude call with failover. Yields text deltas."""
    from core.config import settings
    from core.llm.fallback import MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY
    from core.llm.providers.anthropic import (
        RETRYABLE_ERRORS as _RETRYABLE_ERRORS,
    )
    from core.llm.providers.anthropic import get_circuit_breaker

    client = get_anthropic_client()
    target_model = model or settings.model
    provider = _route_provider(target_model)
    circuit_breaker = get_circuit_breaker()

    # Hook: LLM_CALL_START
    _fire_hook(
        "llm_call_start",
        {"model": target_model, "provider": provider, "function": "call_llm_streaming"},
    )
    t0 = time.monotonic()

    def _do_stream(*, model: str) -> Iterator[str]:
        system_cached = _system_with_cache(system)
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            yield from stream.text_stream

            # Record success AFTER stream completes
            circuit_breaker.record_success()

            # Capture token usage from the stream's final response
            final = stream.get_final_message()
            if final:
                _record_response_usage(final, model, label="stream")

    def _hooked_stream(inner: Iterator[str]) -> Iterator[str]:
        """Wrapper that fires LLM_CALL_END after stream exhaustion or error."""
        try:
            yield from inner
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _fire_hook(
                "llm_call_end",
                {
                    "model": target_model,
                    "provider": provider,
                    "function": "call_llm_streaming",
                    "latency_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise
        else:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _fire_hook(
                "llm_call_end",
                {
                    "model": target_model,
                    "provider": provider,
                    "function": "call_llm_streaming",
                    "latency_ms": elapsed_ms,
                    "error": None,
                },
            )

    # Circuit breaker check
    if not circuit_breaker.can_execute():
        raise RuntimeError(
            "Circuit breaker is open — LLM API calls are temporarily blocked. "
            "Too many consecutive failures detected."
        )

    # For streaming, retry at connection level only
    models_to_try = [target_model] + [m for m in FALLBACK_MODELS if m != target_model]
    last_error: Exception | None = None

    for current_model in models_to_try:
        for attempt in range(MAX_RETRIES):
            try:
                result = _do_stream(model=current_model)
                return _hooked_stream(result)
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
                time.sleep(delay)

    if last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    circuit_breaker.record_failure()
    raise last_error


__all__ = ["call_llm_streaming"]
