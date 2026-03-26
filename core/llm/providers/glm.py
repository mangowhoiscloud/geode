"""ZhipuAI GLM provider — OpenAI-compatible API with custom base_url.

Separate provider for GLM models (glm-5, glm-5-turbo, glm-4.7-flash).
Uses OpenAI SDK but managed as an independent provider with its own
client lifecycle, circuit breaker, and failover chain.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.config import GLM_BASE_URL, GLM_FALLBACK_CHAIN, GLM_PRIMARY, settings
from core.llm.fallback import CircuitBreaker

log = logging.getLogger(__name__)

# Default GLM model — from config.py single source of truth
DEFAULT_GLM_MODEL = GLM_PRIMARY

# GLM fallback chain — from config.py single source of truth
GLM_FALLBACK_MODELS = GLM_FALLBACK_CHAIN

_glm_client: Any = None  # openai.OpenAI | None — GLM via OpenAI-compatible API
_glm_lock = threading.Lock()

# Circuit breaker for GLM API calls
_glm_circuit_breaker = CircuitBreaker()


def _get_glm_client() -> Any:
    """Lazy import and return cached GLM client (OpenAI-compatible, thread-safe).

    Uses double-checked locking pattern consistent with _get_openai_client().
    """
    global _glm_client
    if _glm_client is None:
        with _glm_lock:
            if _glm_client is None:
                import openai

                _glm_client = openai.OpenAI(
                    api_key=settings.zai_api_key,
                    base_url=GLM_BASE_URL,
                )
    return _glm_client


def reset_glm_client() -> None:
    """Reset cached GLM client (e.g. after /key glm changes)."""
    global _glm_client
    with _glm_lock:
        _glm_client = None


def get_circuit_breaker() -> CircuitBreaker:
    """Return the module-level GLM circuit breaker."""
    return _glm_circuit_breaker
