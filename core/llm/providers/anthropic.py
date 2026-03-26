"""Anthropic provider — singleton clients + retry wrapper.

Owns sync/async Anthropic clients with configured httpx connection pool.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any

import anthropic
import httpx
from anthropic.types import TextBlockParam

from core.config import ANTHROPIC_FALLBACK_CHAIN, is_model_allowed, settings
from core.llm.fallback import (
    CircuitBreaker,
    retry_with_backoff_generic,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# httpx connection pool — configured for long-lived REPL sessions
# ---------------------------------------------------------------------------


def _build_httpx_timeout() -> httpx.Timeout:
    """Build httpx Timeout from settings."""
    return httpx.Timeout(
        connect=settings.llm_connect_timeout,
        read=settings.llm_read_timeout,
        write=settings.llm_write_timeout,
        pool=settings.llm_pool_timeout,
    )


def _build_httpx_limits() -> httpx.Limits:
    """Build httpx connection pool Limits from settings."""
    return httpx.Limits(
        max_connections=settings.llm_max_connections,
        max_keepalive_connections=settings.llm_max_keepalive_connections,
        keepalive_expiry=settings.llm_keepalive_expiry,
    )


# ---------------------------------------------------------------------------
# Singleton Anthropic clients — reuse connection pool across all calls
# ---------------------------------------------------------------------------
_sync_client: anthropic.Anthropic | None = None
_sync_client_lock = threading.Lock()

_async_client: anthropic.AsyncAnthropic | None = None
_async_client_lock = threading.Lock()

# Circuit breaker for Anthropic API calls
_circuit_breaker = CircuitBreaker()

# Retryable error types
RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)

# Non-retryable errors
NON_RETRYABLE_ERRORS = (anthropic.AuthenticationError, anthropic.BadRequestError)

# Fallback models
FALLBACK_MODELS = ANTHROPIC_FALLBACK_CHAIN


def get_anthropic_client() -> anthropic.Anthropic:
    """Return a singleton sync Anthropic client with configured connection pool.

    Thread-safe. The client is created once and reused for all sync LLM calls,
    ensuring httpx connection pooling works effectively across calls.
    SDK-level retries are disabled (max_retries=0) to avoid conflict with
    app-level retry logic in ``_retry_with_backoff()``.
    """
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    with _sync_client_lock:
        if _sync_client is None:
            http_client = httpx.Client(
                limits=_build_httpx_limits(),
                timeout=_build_httpx_timeout(),
            )
            _sync_client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key,
                max_retries=0,  # app-level retry handles this
                http_client=http_client,
            )
        return _sync_client


def get_async_anthropic_client(api_key: str | None = None) -> anthropic.AsyncAnthropic:
    """Return a singleton async Anthropic client with configured connection pool.

    Thread-safe. The client is created once and reused for all async LLM calls
    (AgenticLoop, etc.), ensuring httpx connection pooling works effectively.
    SDK-level retries are disabled (max_retries=0) to avoid conflict with
    app-level retry logic.

    Args:
        api_key: Optional API key override. If None, uses settings.
    """
    global _async_client
    if _async_client is not None:
        return _async_client
    with _async_client_lock:
        if _async_client is None:
            key = api_key or settings.anthropic_api_key
            http_client = httpx.AsyncClient(
                limits=_build_httpx_limits(),
                timeout=_build_httpx_timeout(),
            )
            _async_client = anthropic.AsyncAnthropic(
                api_key=key,
                max_retries=0,  # app-level retry handles this
                http_client=http_client,
            )
        return _async_client


def reset_clients() -> None:
    """Close and reset singleton clients. Used in tests and on API key change."""
    global _sync_client, _async_client
    with _sync_client_lock:
        if _sync_client is not None:
            with contextlib.suppress(Exception):
                _sync_client.close()
            _sync_client = None
    with _async_client_lock:
        if _async_client is not None:
            # AsyncClient.close() is a coroutine but we're in sync context
            # Just drop the reference — GC will clean up
            _async_client = None


def system_with_cache(system: str) -> list[TextBlockParam]:
    """Convert a system prompt string to content block format with cache_control.

    Enables Anthropic Prompt Caching so that repeated calls sharing the same
    system prompt (e.g., 4 analysts or 3 evaluators) get cache hits and
    reduced latency/cost.
    """
    return [
        TextBlockParam(
            type="text",
            text=system,
            cache_control={"type": "ephemeral"},
        )
    ]


def get_circuit_breaker() -> CircuitBreaker:
    """Return the module-level Anthropic circuit breaker."""
    return _circuit_breaker


def retry_with_backoff(
    fn: Any,
    *,
    model: str,
    max_retries: int | None = None,
) -> Any:
    """Execute fn with retry + exponential backoff + model fallback (Anthropic).

    Delegates to ``retry_with_backoff_generic`` with Anthropic-specific config.
    """
    from core.llm.fallback import MAX_RETRIES as _DEFAULT_MAX_RETRIES

    _max_retries = max_retries if max_retries is not None else _DEFAULT_MAX_RETRIES

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    models_to_try = [m for m in candidates if is_model_allowed(m)]
    if not models_to_try:
        raise RuntimeError(f"All models blocked by policy: {candidates}")

    return retry_with_backoff_generic(
        fn,
        model=models_to_try[0],
        fallback_models=models_to_try[1:],
        circuit_breaker=_circuit_breaker,
        retryable_errors=RETRYABLE_ERRORS,
        bad_request_error=anthropic.BadRequestError,
        billing_message=(
            "Anthropic API credit balance too low. "
            "Visit https://console.anthropic.com/settings/billing to add credits, "
            "or use --dry-run mode."
        ),
        max_retries=_max_retries,
        provider_label="LLM",
    )
