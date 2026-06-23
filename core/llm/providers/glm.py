"""ZhipuAI GLM provider — OpenAI-compatible API with custom base_url.

Separate provider for GLM models (glm-5.2, glm-5.1, glm-5, glm-5-turbo,
glm-5v-turbo, glm-4.7-flash).  Uses OpenAI SDK but managed as an
independent provider with its own client lifecycle and failover chain.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.config import GLM_BASE_URL
from core.llm.loop_affinity import LoopAffineClientCache

log = logging.getLogger(__name__)

# Valid z.ai ``reasoning_effort`` values for GLM-5.2 (official chat-completion
# API reference, docs.z.ai/api-reference/llm/chat-completion). reasoning_effort
# is GLM-5.2-only; the server default is ``max``.
_GLM_REASONING_EFFORTS = frozenset({"max", "xhigh", "high", "medium", "low", "minimal", "none"})


def build_glm_reasoning_extra_body(model: str) -> dict[str, Any] | None:
    """Build the ``extra_body`` for GLM-5.2 reasoning control, or ``None``.

    Returns ``None`` (send nothing → server default) UNLESS
    ``settings.glm_reasoning_effort`` is set to a valid z.ai value AND the model
    is glm-5.2. When active, returns
    ``{"reasoning_effort": <val>, "thinking": {"type": "enabled"|"disabled"}}``
    (``none`` → thinking disabled). An invalid setting value is dropped with a
    WARNING (graceful) rather than sent (which would 400).

    **Doc-grounded but live-unverified**: the official z.ai API reference
    documents both ``reasoning_effort`` (GLM-5.2-only enum) and ``thinking``
    ({"type": enabled|disabled}); the GLM backend's acceptance of them through
    the OpenAI-compatible endpoint's ``extra_body`` is not live-confirmed (the
    GLM account balance is 0). A funded round-trip is the pending gate
    (PR-NO-FALLBACK rule) — hence this is gated OFF by default so the GLM-5.2
    hot path is unchanged until verified.
    ref: https://docs.z.ai/api-reference/llm/chat-completion
    """
    from core.config import settings

    effort = (getattr(settings, "glm_reasoning_effort", "") or "").strip().lower()
    if not effort or not model.startswith("glm-5.2"):
        return None
    if effort not in _GLM_REASONING_EFFORTS:
        log.warning(
            "glm_reasoning_effort=%r is not a valid z.ai value %s — ignoring",
            effort,
            sorted(_GLM_REASONING_EFFORTS),
        )
        return None
    return {
        "reasoning_effort": effort,
        "thinking": {"type": "disabled" if effort == "none" else "enabled"},
    }


# H11-tail: the former DEFAULT_GLM_MODEL / GLM_FALLBACK_MODELS module aliases
# (boot-frozen copies of GLM_PRIMARY / GLM_FALLBACK_CHAIN) were dead — no
# consumer read them. Removed; any live value comes from ``core.config`` via a
# function-local import so a routing.toml reload is seen without restart.

_glm_client: Any = None  # openai.OpenAI | None — GLM via OpenAI-compatible API
_glm_lock = threading.Lock()
# PR-LOOP-POLLUTION-FIX (2026-06-12) — async client is per-event-loop, not
# process-global (see core/llm/loop_affinity.py).
_async_glm_clients = LoopAffineClientCache("glm-provider")


def _resolve_glm_endpoint() -> tuple[str, str]:
    """Pick (api_key, base_url) for GLM, preferring a Plan-bound profile.

    When the user registered a `glm-coding-*` Plan via /login, that Plan's
    base_url + bound API key are used (so a Coding Plan key actually
    calls the coding endpoint). Falls back to settings.zai_api_key +
    GLM_BASE_URL for legacy .env-only setups.
    """
    from core.config import GLM_PRIMARY, settings

    try:
        from core.llm.strategies.plan_registry import resolve_routing

        # Probe the live GLM default's routing (glm-5.2 now) so a Plan route
        # pinned to the current default is honoured — was hardcoded glm-5.1.
        target = resolve_routing(GLM_PRIMARY)
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
    """Return the async GLM client bound to the CURRENT event loop
    (OpenAI-compatible). See core/llm/loop_affinity.py for the per-loop
    cache rationale."""

    def _build() -> Any:
        import openai

        api_key, base_url = _resolve_glm_endpoint()
        return openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
        )

    return _async_glm_clients.get(_build)


def reset_glm_client() -> None:
    """Reset cached GLM client (e.g. after /key glm changes)."""
    global _glm_client
    with _glm_lock:
        _glm_client = None
    _async_glm_clients.invalidate()
