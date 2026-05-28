"""ZhipuAI GLM provider — OpenAI-compatible API with custom base_url.

Separate provider for GLM models (glm-5.1, glm-5, glm-5-turbo,
glm-5v-turbo, glm-4.7-flash).  Uses OpenAI SDK but managed as an
independent provider with its own client lifecycle and failover chain.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.config import GLM_BASE_URL, GLM_FALLBACK_CHAIN, GLM_PRIMARY

log = logging.getLogger(__name__)

# Default GLM model — from config.py single source of truth
DEFAULT_GLM_MODEL = GLM_PRIMARY

# GLM fallback chain — from config.py single source of truth
GLM_FALLBACK_MODELS = GLM_FALLBACK_CHAIN

_glm_client: Any = None  # openai.OpenAI | None — GLM via OpenAI-compatible API
_glm_lock = threading.Lock()
_async_glm_client: Any = None  # openai.AsyncOpenAI | None — GLM via OpenAI-compatible API
_async_glm_lock = threading.Lock()


def _resolve_glm_endpoint() -> tuple[str, str]:
    """Pick (api_key, base_url) for GLM, preferring a Plan-bound profile.

    When the user registered a `glm-coding-*` Plan via /login, that Plan's
    base_url + bound API key are used (so a Coding Plan key actually
    calls the coding endpoint). Falls back to settings.zai_api_key +
    GLM_BASE_URL for legacy .env-only setups.
    """
    from core.config import settings

    try:
        from core.llm.strategies.plan_registry import resolve_routing

        target = resolve_routing("glm-5.1")
        if target is not None and target.profile.key:
            return target.profile.key, target.base_url
    except Exception:
        log.debug("GLM Plan-aware endpoint resolution failed", exc_info=True)
    return settings.zai_api_key, GLM_BASE_URL


def _get_glm_client() -> Any:
    """Lazy import and return cached GLM client (OpenAI-compatible, thread-safe).

    Uses double-checked locking pattern consistent with _get_openai_client().
    """
    global _glm_client
    if _glm_client is None:
        with _glm_lock:
            if _glm_client is None:
                import openai

                api_key, base_url = _resolve_glm_endpoint()
                _glm_client = openai.OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
                )
    return _glm_client


def _get_async_glm_client() -> Any:
    """Lazy import and return cached async GLM client (OpenAI-compatible)."""
    global _async_glm_client
    if _async_glm_client is None:
        with _async_glm_lock:
            if _async_glm_client is None:
                import openai

                api_key, base_url = _resolve_glm_endpoint()
                _async_glm_client = openai.AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
                )
    return _async_glm_client


def reset_glm_client() -> None:
    """Reset cached GLM client (e.g. after /key glm changes)."""
    global _async_glm_client, _glm_client
    with _glm_lock:
        _glm_client = None
    with _async_glm_lock:
        _async_glm_client = None
