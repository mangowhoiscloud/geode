"""Provider dispatch — per-provider configuration and failover helpers.

Extracted from router.py to reduce module size. Contains the provider
dispatch table and retry helpers.
"""

from __future__ import annotations

import logging
from typing import Any

from core.config import is_model_allowed
from core.llm.fallback import retry_with_backoff_generic


def __getattr__(name: str) -> Any:
    """PEP 562 lazy ``settings`` alias for legacy patch sites."""
    if name == "settings":
        from core.config import settings as _settings

        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# v0.88.0 — anthropic SDK is module-level lazy.  ``import anthropic`` and
# the cross-module ``RETRYABLE_ERRORS`` / ``get_anthropic_client`` pulls
# happen lazily inside the dispatch table lambdas / helper functions
# below, mirroring the existing ``_openai_retryable`` /
# ``_openai_bad_request`` pattern.  Cold-start path no longer pulls the
# 248 ms anthropic graph through this module.

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider dispatch — single source of truth for per-provider configurations.
# Replaces 6 individual _get_provider_*() functions (Kent Beck DRY).
# ---------------------------------------------------------------------------


def _openai_retryable() -> tuple[type[Exception], ...]:
    import openai

    return (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)


def _openai_bad_request() -> type[Exception]:
    import openai

    return openai.BadRequestError


def _anthropic_retryable() -> tuple[type[Exception], ...]:
    """v0.88.0 — defer anthropic SDK + provider module load until first call.

    Mirrors ``_openai_retryable``.  The lambda-only previous shape
    captured ``_RETRYABLE_ERRORS`` from ``core.llm.providers.anthropic``
    at module load, eagerly pulling 248 ms of anthropic.* into the
    cold-start path even when no Anthropic call ever runs.
    """
    from core.llm.providers.anthropic import RETRYABLE_ERRORS

    return RETRYABLE_ERRORS


def _anthropic_bad_request() -> type[Exception]:
    """v0.88.0 — lazy counterpart to ``_openai_bad_request``."""
    import anthropic

    return anthropic.BadRequestError


def _anthropic_get_client() -> Any:
    """v0.88.0 — defer ``get_anthropic_client`` import until first call."""
    from core.llm.providers.anthropic import get_anthropic_client

    return get_anthropic_client()


# Lazy dispatch table — callables to avoid import-time side effects
_PROVIDER_DISPATCH: dict[str, dict[str, Any]] = {
    "anthropic": {
        "get_client": _anthropic_get_client,
        "retryable_errors": _anthropic_retryable,
        "bad_request_error": _anthropic_bad_request,
    },
    "openai": {
        "get_client": lambda: __import__(
            "core.llm.providers.openai", fromlist=["_get_openai_client"]
        )._get_openai_client(),
        "retryable_errors": _openai_retryable,
        "bad_request_error": _openai_bad_request,
    },
    "glm": {
        "get_client": lambda: __import__(
            "core.llm.providers.glm", fromlist=["_get_glm_client"]
        )._get_glm_client(),
        "retryable_errors": _openai_retryable,  # GLM uses openai SDK
        "bad_request_error": _openai_bad_request,
    },
    "openai-codex": {
        "get_client": lambda: __import__(
            "core.llm.providers.codex", fromlist=["_get_codex_client"]
        )._get_codex_client(),
        "retryable_errors": _openai_retryable,
        "bad_request_error": _openai_bad_request,
    },
}


def _get_provider_config(provider: str, key: str) -> Any:
    """Lookup a provider-specific configuration by key.

    Valid keys: get_client, retryable_errors, bad_request_error.
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


def _get_provider_retryable_errors(provider: str) -> tuple[type[Exception], ...]:
    result: tuple[type[Exception], ...] = _get_provider_config(provider, "retryable_errors")
    return result


def _get_provider_bad_request_error(provider: str) -> type[Exception] | None:
    result: type[Exception] | None = _get_provider_config(provider, "bad_request_error")
    return result


def _retry_provider_aware(
    fn: Any,
    *,
    model: str,
    provider: str,
) -> Any:
    """Execute fn with retry + backoff, provider-aware.

    There is no silent cross-model auto-fallback (PR-DRIFT-CUT, 2026-05-24):
    a failure is isolated to its actual provider/model. Operators wanting an
    alternative model invoke ``/model <id>`` explicitly.
    """
    if not is_model_allowed(model):
        raise RuntimeError(f"Model blocked by policy: {model}")

    return retry_with_backoff_generic(
        fn,
        model=model,
        fallback_models=[],
        retryable_errors=_get_provider_retryable_errors(provider),
        bad_request_error=_get_provider_bad_request_error(provider),
        billing_message=f"{provider} API billing/credit error.",
        provider_label=provider.upper(),
    )
