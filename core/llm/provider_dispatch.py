"""Provider dispatch — per-provider configuration and cross-provider fallback.

Extracted from router.py to reduce module size. Contains circuit breaker
singletons, provider dispatch table, retry helpers, and cross-provider
dispatch logic.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import anthropic

from core.config import (
    ANTHROPIC_FALLBACK_CHAIN,
    GLM_FALLBACK_CHAIN,
    OPENAI_FALLBACK_CHAIN,
    is_model_allowed,
    settings,
)
from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic
from core.llm.providers.anthropic import (
    RETRYABLE_ERRORS as _RETRYABLE_ERRORS,
)
from core.llm.providers.anthropic import (
    get_anthropic_client,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hook system — local _fire_hook to avoid circular import with router
# ---------------------------------------------------------------------------

_hooks_ctx: Any = None  # HookSystem | None — set via set_dispatch_hooks()


def set_dispatch_hooks(hooks: Any) -> None:
    """Wire HookSystem into provider_dispatch for cross-provider hook events."""
    global _hooks_ctx
    _hooks_ctx = hooks


def _fire_hook(event_name: str, data: dict[str, Any]) -> None:
    """Fire a hook event if HookSystem is available. Graceful degradation on failure."""
    hooks = _hooks_ctx
    if hooks is None:
        return
    try:
        from core.hooks import HookEvent

        event = HookEvent(event_name)
        hooks.trigger(event, data)
    except Exception:
        log.debug("Hook trigger failed for %s", event_name, exc_info=True)


# ---------------------------------------------------------------------------
# Provider dispatch — single source of truth for per-provider configurations.
# Replaces 6 individual _get_provider_*() functions (Kent Beck DRY).
# ---------------------------------------------------------------------------

# Per-provider circuit breakers (must be module-level singletons)
_openai_cb = CircuitBreaker()
_glm_cb = CircuitBreaker()


def _openai_retryable() -> tuple[type[Exception], ...]:
    import openai

    return (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)


def _openai_bad_request() -> type[Exception]:
    import openai

    return openai.BadRequestError


# Lazy dispatch table — callables to avoid import-time side effects
_PROVIDER_DISPATCH: dict[str, dict[str, Any]] = {
    "anthropic": {
        "get_client": lambda: get_anthropic_client(),
        "fallback_chain": lambda: list(ANTHROPIC_FALLBACK_CHAIN),
        "retryable_errors": lambda: _RETRYABLE_ERRORS,
        "bad_request_error": lambda: anthropic.BadRequestError,
        "circuit_breaker": lambda: __import__(
            "core.llm.providers.anthropic", fromlist=["get_circuit_breaker"]
        ).get_circuit_breaker(),
    },
    "openai": {
        "get_client": lambda: __import__(
            "core.llm.providers.openai", fromlist=["_get_openai_client"]
        )._get_openai_client(),
        "fallback_chain": lambda: list(OPENAI_FALLBACK_CHAIN),
        "retryable_errors": _openai_retryable,
        "bad_request_error": _openai_bad_request,
        "circuit_breaker": lambda: _openai_cb,
    },
    "glm": {
        "get_client": lambda: __import__(
            "core.llm.providers.glm", fromlist=["_get_glm_client"]
        )._get_glm_client(),
        "fallback_chain": lambda: list(GLM_FALLBACK_CHAIN),
        "retryable_errors": _openai_retryable,  # GLM uses openai SDK
        "bad_request_error": _openai_bad_request,
        "circuit_breaker": lambda: _glm_cb,
    },
    "codex": {
        "get_client": lambda: __import__(
            "core.llm.providers.codex", fromlist=["_get_codex_client"]
        )._get_codex_client(),
        "fallback_chain": lambda: list(
            __import__("core.config", fromlist=["CODEX_FALLBACK_CHAIN"]).CODEX_FALLBACK_CHAIN
        ),
        "retryable_errors": _openai_retryable,
        "bad_request_error": _openai_bad_request,
        "circuit_breaker": lambda: __import__(
            "core.llm.providers.codex", fromlist=["get_circuit_breaker"]
        ).get_circuit_breaker(),
    },
}


def _get_provider_config(provider: str, key: str) -> Any:
    """Lookup a provider-specific configuration by key.

    Valid keys: get_client, fallback_chain, retryable_errors,
    bad_request_error, circuit_breaker.
    """
    dispatch = _PROVIDER_DISPATCH.get(provider)
    if dispatch is None:
        raise ValueError(f"Unsupported provider: {provider}")
    factory = dispatch.get(key)
    if factory is None:
        raise KeyError(f"Unknown config key '{key}' for provider '{provider}'")
    return factory()


# Convenience wrappers (preserve existing call sites)
def _get_provider_client(provider: str) -> Any:
    return _get_provider_config(provider, "get_client")


def _get_fallback_chain(provider: str) -> list[str]:
    result: list[str] = _get_provider_config(provider, "fallback_chain")
    return result


def _get_provider_retryable_errors(provider: str) -> tuple[type[Exception], ...]:
    result: tuple[type[Exception], ...] = _get_provider_config(provider, "retryable_errors")
    return result


def _get_provider_bad_request_error(provider: str) -> type[Exception] | None:
    result: type[Exception] | None = _get_provider_config(provider, "bad_request_error")
    return result


def _get_provider_circuit_breaker(provider: str) -> CircuitBreaker:
    result: CircuitBreaker = _get_provider_config(provider, "circuit_breaker")
    return result


def _retry_provider_aware(
    fn: Any,
    *,
    model: str,
    provider: str,
) -> Any:
    """Execute fn with retry + backoff + fallback, provider-aware."""
    fallback = _get_fallback_chain(provider)
    candidates = [model] + [m for m in fallback if m != model]
    models_to_try = [m for m in candidates if is_model_allowed(m)]
    if not models_to_try:
        raise RuntimeError(f"All models blocked by policy: {candidates}")

    return retry_with_backoff_generic(
        fn,
        model=models_to_try[0],
        fallback_models=models_to_try[1:],
        circuit_breaker=_get_provider_circuit_breaker(provider),
        retryable_errors=_get_provider_retryable_errors(provider),
        bad_request_error=_get_provider_bad_request_error(provider),
        billing_message=f"{provider} API billing/credit error.",
        provider_label=provider.upper(),
    )


T_Result = TypeVar("T_Result")


def _cross_provider_dispatch(  # noqa: UP047 — PEP695 syntax requires Python 3.12+
    primary_provider: str,
    primary_model: str,
    dispatch_fn: Callable[[str, str], T_Result],
    function_name: str,
) -> T_Result:
    """Execute dispatch_fn(provider, model) with opt-in cross-provider fallback.

    When ``settings.llm_cross_provider_failover`` is True and the primary
    provider chain is exhausted, iterates through ``llm_cross_provider_order``
    trying each remaining provider's primary model.
    """
    providers: list[tuple[str, str]] = [(primary_provider, primary_model)]
    if settings.llm_cross_provider_failover:
        for p in settings.llm_cross_provider_order:
            if p != primary_provider:
                chain = _get_fallback_chain(p)
                if chain:
                    providers.append((p, chain[0]))

    last_exc: Exception | None = None
    t0 = time.perf_counter()
    for idx, (provider, model) in enumerate(providers):
        try:
            return dispatch_fn(provider, model)
        except Exception as exc:
            last_exc = exc
            if idx < len(providers) - 1:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                next_p, next_m = providers[idx + 1]
                log.warning(
                    "Cross-provider fallback: %s(%s) -> %s(%s) [%s] after %.0fms",
                    provider,
                    model,
                    next_p,
                    next_m,
                    function_name,
                    elapsed_ms,
                )
                _fire_hook(
                    "fallback_cross_provider",
                    {
                        "from_provider": provider,
                        "to_provider": next_p,
                        "from_model": model,
                        "to_model": next_m,
                        "function": function_name,
                        "error": str(exc),
                        "elapsed_ms": round(elapsed_ms, 1),
                        "attempt": idx,
                    },
                )
                continue
            raise

    # Unreachable when providers is non-empty; satisfies type checker
    assert last_exc is not None
    raise last_exc
