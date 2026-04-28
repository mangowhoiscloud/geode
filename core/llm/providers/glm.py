"""ZhipuAI GLM provider — OpenAI-compatible API with custom base_url.

Separate provider for GLM models (glm-5.1, glm-5, glm-5-turbo,
glm-5v-turbo, glm-4.7-flash).  Uses OpenAI SDK but managed as an
independent provider with its own client lifecycle, circuit breaker,
and failover chain.
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


def _resolve_glm_endpoint() -> tuple[str, str]:
    """Pick (api_key, base_url) for GLM, preferring a Plan-bound profile.

    When the user registered a `glm-coding-*` Plan via /login, that Plan's
    base_url + bound API key are used (so a Coding Plan key actually
    calls the coding endpoint). Falls back to settings.zai_api_key +
    GLM_BASE_URL for legacy .env-only setups.
    """
    try:
        from core.auth.plan_registry import resolve_routing

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


# ---------------------------------------------------------------------------
# GlmAgenticAdapter — ZhipuAI GLM adapter for agentic loop
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

from core.llm.errors import UserCancelledError  # noqa: E402
from core.llm.providers.openai import (  # noqa: E402
    OpenAIAgenticAdapter,
    _convert_messages_to_openai,
    _tools_to_chat_completions,
)
from core.llm.router import call_with_failover  # noqa: E402

# GLM-5 native web_search configuration.
# Injected alongside function tools for free built-in web search.
_GLM_NATIVE_WEB_SEARCH: dict[str, Any] = {
    "type": "web_search",
    "web_search": {
        "enable": True,
    },
}

# v0.58.0 R2 — GLM ``thinking`` parameter (docs.z.ai/api-reference/llm/
# chat-completion + docs.z.ai/guides/capabilities/thinking-mode).
# Spec re-verified 2026-04-28:
#   - Field shape: ``{"type": "enabled"|"disabled", "clear_thinking": bool}``
#   - GLM-4.5+ honours the flag (hybrid models — opt in/out)
#   - GLM-5.x / GLM-5V / GLM-4.7 / GLM-4.5V will think *compulsorily*
#     (sending ``"disabled"`` is silently ignored — but harmless)
#   - Pre-GLM-4.5 models reject the field; we omit it for them
#   - openai-python doesn't know ``thinking`` — must go via ``extra_body``
# Models that accept the ``thinking`` field. Anything not listed gets the
# field omitted entirely so the request shape stays compatible with the
# legacy GLM-4.x endpoints.
_GLM_THINKING_MODELS: frozenset[str] = frozenset(
    {
        # GLM-5 family — thinking always-on, but the field is accepted
        "glm-5.1",
        "glm-5",
        "glm-5-turbo",
        "glm-5v-turbo",
        # GLM-4.7 family — thinking always-on
        "glm-4.7",
        "glm-4.7-flash",
        "glm-4.7-flashx",
        # GLM-4.6 family — hybrid (honors enabled/disabled)
        "glm-4.6",
        "glm-4.6v",
        # GLM-4.5 family — hybrid
        "glm-4.5",
        "glm-4.5v",
        "glm-4.5-air",
        "glm-4.5-flash",
    }
)


def _glm_thinking_supported(model: str) -> bool:
    """Return True if the GLM model accepts the ``thinking`` field."""
    return model in _GLM_THINKING_MODELS


class GlmAgenticAdapter(OpenAIAgenticAdapter):
    """ZhipuAI GLM adapter (glm-5.1, glm-5, glm-5-turbo, glm-5v-turbo, glm-4.7-flash).

    Injects GLM native web_search tool alongside function tools.
    """

    @property
    def provider_name(self) -> str:
        return "glm"

    @property
    def fallback_chain(self) -> list[str]:
        return list(GLM_FALLBACK_CHAIN)

    def _resolve_config(self, model: str) -> tuple[str, str | None]:
        return _resolve_glm_endpoint()

    async def agentic_call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, str] | str,
        max_tokens: int,
        temperature: float,
        thinking_budget: int = 0,
        effort: str = "high",
    ) -> Any | None:
        """GLM agentic call with native web_search injection."""
        client = self._ensure_client(model)
        if client is None:
            self.last_error = ValueError(f"{self.provider_name} API key not configured")
            log.warning("No API key for %s agentic loop", self.provider_name)
            return None

        if not self._circuit_breaker.can_execute():
            self.last_error = RuntimeError(f"{self.provider_name} circuit breaker is OPEN")
            log.warning("%s circuit breaker is OPEN, skipping call", self.provider_name)
            return None

        tc_val = tool_choice.get("type", "auto") if isinstance(tool_choice, dict) else tool_choice

        oai_tools = _tools_to_chat_completions(tools)
        oai_tools.append(_GLM_NATIVE_WEB_SEARCH)

        oai_messages = _convert_messages_to_openai(system, messages)
        failover_models = [model] + [m for m in self.fallback_chain if m != model]

        async def _do_call(m: str) -> Any:
            # v0.58.0 R2 — GLM ``thinking`` field (passed via ``extra_body``
            # because openai-python's ``ChatCompletion.create`` doesn't know
            # about it). Default ``clear_thinking=False`` — keep prior-turn
            # ``reasoning_content`` in context across rounds (matches the
            # multi-turn-reasoning-preservation goal of R1 on Codex Plus).
            # Per-failover-model gate: drop the field on pre-GLM-4.5
            # models so the request is accepted.
            local_extra: dict[str, Any] = {}
            if _glm_thinking_supported(m):
                local_extra["thinking"] = {"type": "enabled", "clear_thinking": False}
            return await asyncio.to_thread(
                client.chat.completions.create,
                model=m,
                messages=oai_messages,
                tools=oai_tools if oai_tools else None,
                tool_choice=tc_val if oai_tools else None,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                extra_body=local_extra or None,
                timeout=120.0,
            )

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except Exception as exc:
            # v0.53.2 — preserve BillingError so the loop fires
            # quota_exhausted IPC panel (parity with Anthropic +
            # post-v0.53.2 OpenAI / Codex). GLM 1113 ("Insufficient
            # balance") is the v0.52.3 incident shape.
            from core.llm.errors import BillingError

            if isinstance(exc, BillingError):
                self._circuit_breaker.record_failure()
                raise
            self.last_error = exc
            log.warning("%s agentic LLM call failed", self.provider_name, exc_info=True)
            self._circuit_breaker.record_failure()
            return None

        if response is None:
            self._circuit_breaker.record_failure()
            return None

        self._circuit_breaker.record_success()

        # Track token usage/cost (was missing — GLM calls were $0.00)
        if hasattr(response, "usage") and response.usage:
            from core.llm.token_tracker import get_tracker

            actual_model = used_model or model
            in_tok = response.usage.prompt_tokens or 0
            out_tok = response.usage.completion_tokens or 0
            get_tracker().record(actual_model, in_tok, out_tok)

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        from core.llm.agentic_response import normalize_openai

        return normalize_openai(response)
