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
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

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


def _resolve_anthropic_key() -> str:
    """Resolve Anthropic API key from ProfileRotator (OAuth preferred) or settings."""
    from core.llm.credentials import resolve_provider_key

    return resolve_provider_key("anthropic", settings.anthropic_api_key)


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
                api_key=_resolve_anthropic_key(),
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
            key = api_key or _resolve_anthropic_key()
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


# ---------------------------------------------------------------------------
# ClaudeAgenticAdapter — Anthropic LLM adapter for agentic loop
# ---------------------------------------------------------------------------

_API_ALLOWED_KEYS = frozenset({"name", "description", "input_schema", "cache_control", "type"})

# Models that support server-side context management + compaction beta.
# Haiku 4.5 (2025-10-01) predates compact-2026-01-12 and rejects the beta
# header with a 400 whose message contains "context" — misclassified as
# context_overflow.  Only 1M-context models are known to support it.
_CONTEXT_MGMT_MODELS: frozenset[str] = frozenset(
    {
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
    }
)

_ANTHROPIC_NATIVE_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]},
    {"type": "web_fetch_20260209", "name": "web_fetch", "allowed_callers": ["direct"]},
]

# Computer-use tool (injected when enabled via settings)
_COMPUTER_USE_TOOL: dict[str, Any] = {
    "type": "computer_20251124",
    "name": "computer",
    "display_width_px": 1280,
    "display_height_px": 800,
}


def is_computer_use_enabled() -> bool:
    """Check if computer-use is enabled (requires pyautogui + opt-in)."""
    if not getattr(settings, "computer_use_enabled", False):
        return False
    try:
        import pyautogui  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        log.debug("computer-use disabled: pyautogui not installed")
        return False


class ClaudeAgenticAdapter:
    """Anthropic agentic adapter (P1 Gateway pattern).

    Features:
    - Context management beta (clear_tool_uses)
    - Tool schema key filtering (_API_ALLOWED_KEYS)
    - BadRequest -> repair_messages -> retry
    - KeyboardInterrupt -> UserCancelledError
    """

    def __init__(self) -> None:
        self._client: Any | None = None
        self.last_error: Exception | None = None

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def fallback_chain(self) -> list[str]:
        return list(ANTHROPIC_FALLBACK_CHAIN)

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
        from core.llm.agentic_response import normalize_anthropic
        from core.llm.errors import LLMBadRequestError, UserCancelledError
        from core.llm.router import call_with_failover

        api_key = settings.anthropic_api_key
        if not api_key:
            self.last_error = ValueError("ANTHROPIC_API_KEY not configured")
            log.warning("No Anthropic API key for agentic loop")
            return None

        if self._client is None:
            self._client = get_async_anthropic_client(api_key)

        # Anthropic tool_choice is always a dict
        if isinstance(tool_choice, str):
            tool_choice = {"type": tool_choice}

        api_tools = [{k: v for k, v in t.items() if k in _API_ALLOWED_KEYS} for t in tools]

        # Inject Anthropic native tools (web_search, web_fetch) with dedup
        existing_names = {t.get("name") for t in api_tools}
        for native in _ANTHROPIC_NATIVE_TOOLS:
            if native["name"] not in existing_names:
                api_tools.append(native)

        # Inject computer-use tool if enabled
        if is_computer_use_enabled() and "computer" not in existing_names:
            api_tools.append(_COMPUTER_USE_TOOL)

        failover_models = [model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != model]

        async def _do_call(m: str) -> Any:
            # Server-side context management only for models that support it.
            # Haiku 4.5 rejects the compact beta → 400 misclassified as overflow.
            extra_h: dict[str, str] = {}
            extra_b: dict[str, Any] = {}
            if m in _CONTEXT_MGMT_MODELS:
                m_window = MODEL_CONTEXT_WINDOW.get(m, 200_000)
                m_trigger = max(50_000, int(m_window * 0.8))
                extra_h["anthropic-beta"] = "context-management-2025-06-27,compact-2026-01-12"
                extra_b["context_management"] = {
                    "edits": [
                        {
                            "type": "clear_tool_uses_20250919",
                            "keep": {"type": "tool_uses", "value": 5},
                        },
                        {
                            "type": "compact_20260112",
                            "trigger": {
                                "type": "input_tokens",
                                "value": m_trigger,
                            },
                        },
                    ]
                }

            # Thinking mode: adaptive (4.6+) or legacy budget (older models)
            _ADAPTIVE_MODELS = {"claude-opus-4-6", "claude-sonnet-4-6"}
            call_temperature = temperature
            call_max_tokens = max_tokens
            thinking_param: dict[str, Any] | None = None
            output_config: dict[str, str] | None = None

            if m in _ADAPTIVE_MODELS:
                # Adaptive thinking (recommended for 4.6+): effort controls depth
                thinking_param = {"type": "adaptive"}
                output_config = {"effort": effort}
                # Anthropic API requires temperature=1 with thinking
                call_temperature = 1.0
            elif thinking_budget > 0:
                # Legacy: manual budget_tokens for older models
                thinking_param = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
                call_temperature = 1.0
                call_max_tokens = max(max_tokens, thinking_budget + max_tokens)

            # Prompt caching split: static content before boundary gets
            # cache_control for reuse across turns; dynamic content after
            # boundary is ephemeral.  (Claude Code STATIC/DYNAMIC pattern)
            from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY

            if PROMPT_CACHE_BOUNDARY in system:
                static_part, dynamic_part = system.split(PROMPT_CACHE_BOUNDARY, 1)
                sys_blocks: list[dict[str, Any]] = [
                    {
                        "type": "text",
                        "text": static_part.rstrip(),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": dynamic_part.lstrip()},
                ]
            else:
                sys_blocks = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

            create_kwargs: dict[str, Any] = {
                "model": m,
                "system": sys_blocks,
                "messages": messages,
                "tools": api_tools,
                "tool_choice": tool_choice,
                "max_tokens": call_max_tokens,
                "temperature": call_temperature,
            }
            if thinking_param is not None:
                create_kwargs["thinking"] = thinking_param
            if output_config is not None:
                create_kwargs["output_config"] = output_config
            if extra_h:
                create_kwargs["extra_headers"] = extra_h
            if extra_b:
                create_kwargs["extra_body"] = extra_b

            return await self._client.messages.create(**create_kwargs)  # type: ignore[union-attr]

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except LLMBadRequestError as exc:
            self.last_error = exc
            msg = str(exc)
            # Billing/credit errors — propagate as BillingError for clean UI
            if "credit balance" in msg.lower() or "billing" in msg.lower():
                from core.llm.errors import BillingError

                raise BillingError(
                    "Anthropic API credit balance too low. "
                    "Visit https://console.anthropic.com/settings/billing to add credits."
                ) from exc
            log.warning("Anthropic BadRequest in agentic loop: %s", msg)
            if "tool_use_id" in msg or "tool_result" in msg:
                from core.agent.agentic_loop import AgenticLoop

                AgenticLoop._repair_messages(messages)
                log.info("Repaired orphaned tool_result in conversation history")
                try:
                    response = await _do_call(model)
                    return normalize_anthropic(response)
                except Exception:
                    log.warning("Retry after repair failed", exc_info=True)
                    return None
            if "input_schema" in msg:
                log.error(
                    "Tool schema error — likely an MCP tool missing input_schema. tools=%d",
                    len(tools),
                )
            return None
        except Exception as exc:
            self.last_error = exc
            log.warning("Agentic LLM call failed", exc_info=True)
            return None

        if response is None:
            return None

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        return normalize_anthropic(response)

    def reset_client(self) -> None:
        self._client = None
