"""ZhipuAI GLM provider — OpenAI-compatible API with custom base_url.

Separate provider for GLM models (glm-5.1, glm-5, glm-5-turbo,
glm-5v-turbo, glm-4.7-flash).  Uses OpenAI SDK but managed as an
independent provider with its own client lifecycle and failover chain.
"""

from __future__ import annotations

import inspect
import logging
import threading
from types import SimpleNamespace
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
                )
    return _async_glm_client


def reset_glm_client() -> None:
    """Reset cached GLM client (e.g. after /key glm changes)."""
    global _async_glm_client, _glm_client
    with _glm_lock:
        _glm_client = None
    with _async_glm_lock:
        _async_glm_client = None


# ---------------------------------------------------------------------------
# GlmAgenticAdapter — ZhipuAI GLM adapter for agentic loop
# ---------------------------------------------------------------------------

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
        # GLM-5 series (zhipuai provider) — thinking always-on, but the field is accepted
        "glm-5.1",
        "glm-5",
        "glm-5-turbo",
        "glm-5v-turbo",
        # GLM-4.7 series (zhipuai provider) — thinking always-on
        "glm-4.7",
        "glm-4.7-flash",
        "glm-4.7-flashx",
        # GLM-4.6 series (zhipuai provider) — hybrid (honors enabled/disabled)
        "glm-4.6",
        "glm-4.6v",
        # GLM-4.5 series (zhipuai provider) — hybrid
        "glm-4.5",
        "glm-4.5v",
        "glm-4.5-air",
        "glm-4.5-flash",
    }
)


def _glm_thinking_supported(model: str) -> bool:
    """Return True if the GLM model accepts the ``thinking`` field."""
    return model in _GLM_THINKING_MODELS


async def _consume_glm_chat_stream(stream_obj: Any) -> Any:
    """Convert Chat Completions delta chunks into a normalizable response."""
    if inspect.isawaitable(stream_obj):
        stream_obj = await stream_obj

    if not hasattr(stream_obj, "__aiter__") and not hasattr(stream_obj, "__iter__"):
        return stream_obj

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, str]] = {}
    finish_reason = "stop"
    usage: Any = None

    async def _handle_chunk(chunk: Any) -> None:
        nonlocal finish_reason, usage
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage = chunk_usage
        for choice in getattr(chunk, "choices", None) or []:
            choice_finish = getattr(choice, "finish_reason", None)
            if choice_finish:
                finish_reason = choice_finish
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                content_parts.append(content)
            reasoning = getattr(delta, "reasoning_content", None)
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
            for call in getattr(delta, "tool_calls", None) or []:
                index = getattr(call, "index", None)
                if not isinstance(index, int):
                    index = len(tool_calls_by_index)
                acc = tool_calls_by_index.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )
                call_id = getattr(call, "id", None)
                if isinstance(call_id, str) and call_id:
                    acc["id"] = call_id
                function = getattr(call, "function", None)
                if function is not None:
                    name = getattr(function, "name", None)
                    if isinstance(name, str) and name:
                        acc["name"] += name
                    arguments = getattr(function, "arguments", None)
                    if isinstance(arguments, str) and arguments:
                        acc["arguments"] += arguments

    if hasattr(stream_obj, "__aiter__"):
        async for chunk in stream_obj:
            await _handle_chunk(chunk)
    else:
        for chunk in stream_obj:
            await _handle_chunk(chunk)

    tool_calls = [
        SimpleNamespace(
            id=call["id"],
            function=SimpleNamespace(
                name=call["name"],
                arguments=call["arguments"] or "{}",
            ),
        )
        for _, call in sorted(tool_calls_by_index.items())
    ]
    message = SimpleNamespace(
        content="".join(content_parts),
        reasoning_content="".join(reasoning_parts),
        tool_calls=tool_calls,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage,
    )


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

        # GAP-T1 — normalize cross-provider tool_choice into the Chat Completions
        # nested shape (string or {"type": "function", "function": {"name": "..."}}).
        from core.llm.tool_choice import normalize as _normalize_tool_choice

        tc_val = _normalize_tool_choice("glm", tool_choice)

        oai_tools = _tools_to_chat_completions(tools)
        oai_tools.append(_GLM_NATIVE_WEB_SEARCH)

        oai_messages = _convert_messages_to_openai(system, messages)
        failover_models = [model] + [m for m in self.fallback_chain if m != model]

        # GAP-R1 — effort=off / none explicitly disables GLM ``thinking``.
        # GLM-5.x / 4.7 ignore the ``disabled`` value (thinking is compulsory
        # per the upstream contract — harmless), but GLM-4.5 / 4.6 hybrid
        # models honour it and recover the (typically large) reasoning-token
        # cost when the caller asks for cheap non-thinking output.  Any other
        # effort value keeps the v0.58.0 enabled-with-context-preserve shape.
        _thinking_off = effort in ("off", "none")
        _thinking_type = "disabled" if _thinking_off else "enabled"

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
                local_extra["thinking"] = {
                    "type": _thinking_type,
                    "clear_thinking": False,
                }
            # Z.AI Chat Completions does not document OpenAI Responses'
            # ``prompt_cache_key`` routing knob; context caching is automatic
            # server-side and reports read hits via
            # ``usage.prompt_tokens_details.cached_tokens``. ``stream_options``
            # is also absent from the Z.AI streaming guide, whose examples show
            # final-chunk usage without it, so keep the request shape to the
            # documented fields only.
            # https://docs.z.ai/api-reference/llm/chat-completion
            # https://docs.z.ai/guides/capabilities/cache
            # https://docs.z.ai/guides/capabilities/streaming
            create_kwargs: dict[str, Any] = {
                "model": m,
                "messages": oai_messages,
                "tools": oai_tools if oai_tools else None,
                "tool_choice": tc_val if oai_tools else None,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
                # Passed to the SDK call as extra_body= via **create_kwargs.
                "extra_body": local_extra or None,
                "timeout": 120.0,
                "stream": True,
            }
            response = client.chat.completions.create(**create_kwargs)
            return await _consume_glm_chat_stream(response)

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
                raise
            self.last_error = exc
            log.warning("%s agentic LLM call failed", self.provider_name, exc_info=True)
            return None

        if response is None:
            return None

        # Token usage is recorded once by the agentic loop's ``_track_usage``
        # on the normalized AgenticResponse below — recording here as well
        # would double-count every GLM call into ``~/.geode/usage/*.jsonl``
        # (matches the codex.py fix; agent loop reads the same
        # ``response.usage`` so the numbers match without a second persist).

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        from core.llm.agentic_response import normalize_openai

        return normalize_openai(response)
