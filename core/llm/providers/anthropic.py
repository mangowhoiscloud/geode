"""Anthropic provider — singleton clients + retry wrapper.

Owns sync/async Anthropic clients with configured httpx connection pool.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

from core.config import ANTHROPIC_FALLBACK_CHAIN, is_model_allowed
from core.llm.fallback import (
    CircuitBreaker,
    retry_with_backoff_generic,
    retry_with_backoff_generic_async,
)
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

if TYPE_CHECKING:
    import anthropic
    import httpx
    from anthropic.types import TextBlockParam

    # v0.88.0 — declare the lazy module-level tuples so mypy / IDEs see a
    # concrete type for ``except RETRYABLE_ERRORS:`` etc.  Runtime values
    # come from ``__getattr__`` below.  Use ``Exception`` (not
    # ``BaseException``) to match the ``retry_with_backoff_generic``
    # signature + ``except`` blocks in failover/streaming.
    RETRYABLE_ERRORS: tuple[type[Exception], ...]
    NON_RETRYABLE_ERRORS: tuple[type[Exception], ...]

# v0.88.0 — anthropic SDK is module-level lazy.  Eager top-level
# ``import anthropic`` + ``from anthropic.types import TextBlockParam``
# pulled 248 ms of SDK graph at startup even when no Anthropic call ever
# fired (cold-start path: ``geode about`` / ``doctor``).  Module-level
# tuples ``RETRYABLE_ERRORS`` / ``NON_RETRYABLE_ERRORS`` and any direct
# ``anthropic.X`` references inside function bodies now resolve through
# the PEP 562 ``__getattr__`` hook below; type annotations use the
# ``TYPE_CHECKING`` block above so mypy still sees them.
_ANTHROPIC_LAZY_TUPLES: dict[str, tuple[str, ...]] = {
    "RETRYABLE_ERRORS": ("RateLimitError", "APIConnectionError", "InternalServerError"),
    "NON_RETRYABLE_ERRORS": ("AuthenticationError", "BadRequestError"),
}


def __getattr__(name: str) -> Any:
    """PEP 562 module attribute hook — resolve anthropic-derived names lazily."""
    if name in _ANTHROPIC_LAZY_TUPLES:
        import anthropic

        value = tuple(getattr(anthropic, n) for n in _ANTHROPIC_LAZY_TUPLES[name])
        globals()[name] = value
        return value
    if name == "TextBlockParam":
        from anthropic.types import TextBlockParam

        globals()[name] = TextBlockParam
        return TextBlockParam
    if name == "settings":
        # Preserve legacy patch surface (tests monkeypatch
        # ``core.llm.providers.anthropic.settings``) without paying the
        # pydantic_settings cost at module import.
        from core.config import settings as _settings

        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# httpx connection pool — configured for long-lived REPL sessions
# ---------------------------------------------------------------------------


def _build_httpx_timeout() -> httpx.Timeout:
    """Build httpx Timeout from settings."""
    import httpx

    from core.config import settings

    return httpx.Timeout(
        connect=settings.llm_connect_timeout,
        read=settings.llm_read_timeout,
        write=settings.llm_write_timeout,
        pool=settings.llm_pool_timeout,
    )


def _build_httpx_limits() -> httpx.Limits:
    """Build httpx connection pool Limits from settings."""
    import httpx

    from core.config import settings

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

# v0.88.0 — RETRYABLE_ERRORS / NON_RETRYABLE_ERRORS resolve through the
# module-level ``__getattr__`` hook (defined above) on first use.  Their
# concrete tuples used to live here as eager module-level expressions
# (``RETRYABLE_ERRORS = (anthropic.RateLimitError, …)``), which forced
# the anthropic SDK import at module load.

# Fallback models
FALLBACK_MODELS = ANTHROPIC_FALLBACK_CHAIN


def _resolve_anthropic_key() -> str:
    """Resolve Anthropic API key from ProfileRotator (OAuth preferred) or settings."""
    from core.config import settings
    from core.llm.credentials import resolve_provider_key

    return resolve_provider_key("anthropic", settings.anthropic_api_key)


def get_anthropic_client() -> anthropic.Anthropic:
    """Return a singleton sync Anthropic client with configured connection pool.

    Thread-safe. The client is created once and reused for all sync LLM calls,
    ensuring httpx connection pooling works effectively across calls.
    SDK-level retries are disabled (max_retries=0) to avoid conflict with
    app-level retry logic in ``_retry_with_backoff()``.
    """
    import anthropic
    import httpx

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
    import anthropic
    import httpx

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


async def areset_clients() -> None:
    """Close and reset singleton clients. Used in tests and on API key change."""
    global _sync_client, _async_client
    with _sync_client_lock:
        if _sync_client is not None:
            with contextlib.suppress(Exception):
                _sync_client.close()
            _sync_client = None
    with _async_client_lock:
        client = _async_client
        _async_client = None
    if client is not None:
        with contextlib.suppress(Exception):
            await client.close()


def system_with_cache(system: str) -> list[TextBlockParam]:
    """Convert a system prompt string to content block format with cache_control.

    Enables Anthropic Prompt Caching so that repeated calls sharing the same
    system prompt (e.g., 4 analysts or 3 evaluators) get cache hits and
    reduced latency/cost.
    """
    from anthropic.types import TextBlockParam as _TextBlockParam

    return [
        _TextBlockParam(
            type="text",
            text=system,
            cache_control={"type": "ephemeral"},
        )
    ]


# Anthropic allows up to 4 cache_control breakpoints per request.  The agentic
# adapter already uses 1-2 on the system block (STATIC/DYNAMIC split).  Keep 3
# slots for the messages array — Hermes "system_and_3" strategy.
MAX_MESSAGE_CACHE_BREAKPOINTS = 3


def apply_messages_cache_control(
    messages: list[dict[str, Any]],
    *,
    n_breakpoints: int = MAX_MESSAGE_CACHE_BREAKPOINTS,
) -> list[dict[str, Any]]:
    """Return a copy of *messages* with ephemeral cache_control on the last
    *n_breakpoints* non-system messages' final content block.

    Mirrors Hermes ``apply_anthropic_cache_control`` (system_and_3) and
    OpenClaw ``applyAnthropicCacheControlToMessages``.  Used by the agentic
    adapter to extend prompt caching from the system block to the rolling
    history window, reducing cost in long multi-turn loops.

    The function is non-mutating: returns a new list with shallow copies of
    the targeted messages and their last block.  String-content messages are
    materialised into a single text block before the marker is attached.

    Args:
        messages: Anthropic-format messages list (role + content).
        n_breakpoints: Max number of trailing non-system messages to mark.
            Default 3 (Anthropic's 4-breakpoint cap minus 1 for system).

    Returns:
        New messages list ready for ``messages.create``.
    """
    if not messages or n_breakpoints <= 0:
        return list(messages)

    out: list[dict[str, Any]] = list(messages)
    targets = [i for i, m in enumerate(out) if m.get("role") != "system"][-n_breakpoints:]

    for i in targets:
        msg = dict(out[i])
        content = msg.get("content")
        if isinstance(content, str):
            # Defect B-1 upper-layer fix (2026-05-11, F-A4 live evidence)
            # — anthropic 400s on ``messages.N.content.0.text:
            # cache_control cannot be set for empty text blocks``.
            # Skip cache_control whenever the message body is empty;
            # there is nothing useful to cache anyway and attaching the
            # breakpoint here turns a free-and-empty entry into a hard
            # API failure that bubbles up as ``error='llm_call_failed'``
            # in AgenticResult.
            if not content:
                continue
            msg["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and content:
            new_content = list(content)
            last_block = dict(new_content[-1])
            # Same empty-text guard for list-content messages — the API
            # rejects ``{"type":"text","text":"","cache_control":...}``
            # whether the block is the only one or the last of many.
            if last_block.get("type") == "text" and not last_block.get("text"):
                continue
            last_block["cache_control"] = {"type": "ephemeral"}
            new_content[-1] = last_block
            msg["content"] = new_content
        else:
            # Empty or unexpected content — skip silently.
            continue
        out[i] = msg

    return out


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
    import anthropic

    from core.llm.fallback import MAX_RETRIES as _DEFAULT_MAX_RETRIES

    _max_retries = max_retries if max_retries is not None else _DEFAULT_MAX_RETRIES

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    models_to_try = [m for m in candidates if is_model_allowed(m)]
    if not models_to_try:
        raise RuntimeError(f"All models blocked by policy: {candidates}")

    # v0.88.0 — same-module ``__getattr__`` is bypassed for unqualified
    # references, so we resolve ``RETRYABLE_ERRORS`` via direct attribute
    # lookup on the module object (which DOES go through ``__getattr__``).
    import sys

    _retryable_errors = sys.modules[__name__].RETRYABLE_ERRORS

    return retry_with_backoff_generic(
        fn,
        model=models_to_try[0],
        fallback_models=models_to_try[1:],
        circuit_breaker=_circuit_breaker,
        retryable_errors=_retryable_errors,
        bad_request_error=anthropic.BadRequestError,
        billing_message=(
            "Anthropic API credit balance too low. "
            "Visit https://console.anthropic.com/settings/billing to add credits, "
            "or use --dry-run mode."
        ),
        max_retries=_max_retries,
        provider_label="LLM",
    )


async def retry_with_backoff_async(
    fn: Any,
    *,
    model: str,
    max_retries: int | None = None,
) -> Any:
    """Execute async fn with retry + exponential backoff + model fallback."""
    import anthropic

    from core.llm.fallback import MAX_RETRIES as _DEFAULT_MAX_RETRIES

    _max_retries = max_retries if max_retries is not None else _DEFAULT_MAX_RETRIES

    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    models_to_try = [m for m in candidates if is_model_allowed(m)]
    if not models_to_try:
        raise RuntimeError(f"All models blocked by policy: {candidates}")

    import sys

    _retryable_errors = sys.modules[__name__].RETRYABLE_ERRORS

    return await retry_with_backoff_generic_async(
        fn,
        model=models_to_try[0],
        fallback_models=models_to_try[1:],
        circuit_breaker=_circuit_breaker,
        retryable_errors=_retryable_errors,
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
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
    }
)

# Adaptive thinking models (Opus 4.6+).  Sampling parameters
# (temperature/top_p/top_k) are rejected with 400 starting from Opus 4.7
# (https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
# #sampling-parameters-removed) and are also rejected by Opus 4.6 when
# adaptive thinking is on.  Omit them entirely on these models.
_ADAPTIVE_MODELS: frozenset[str] = frozenset(
    {
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    }
)

# v0.56.0 R4-mini — Opus 4.7 supports the new ``xhigh`` effort level (one
# step above ``high``); 4.6 / Sonnet 4.6 reject it with 400. Mirrors
# Hermes ``anthropic_adapter.py:49-53`` substring-based gate. Anthropic
# explicitly recommends ``xhigh`` as the starting effort for Opus 4.7
# coding/agentic workloads (platform.claude.com/docs/en/build-with-claude/
# effort) — but only the GEODE caller can opt in by setting
# ``agentic.effort = "xhigh"``; we never auto-upgrade ``high → xhigh``.
_XHIGH_EFFORT_MODELS: frozenset[str] = frozenset({"claude-opus-4-7"})


def _supports_xhigh_effort(model: str) -> bool:
    """Return True if the model accepts ``output_config.effort = "xhigh"``."""
    return model in _XHIGH_EFFORT_MODELS


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
    from core.config import settings

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
        from core.config import settings
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

        # GAP-T1 — normalize cross-provider tool_choice into the Anthropic
        # dict shape ({"type": "auto"|"any"|"tool"|"none", "name"?: ...}).
        from core.llm.tool_choice import normalize as _normalize_tool_choice

        tool_choice = _normalize_tool_choice("anthropic", tool_choice) or {"type": "auto"}

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
            # ``self._client`` is initialised right before this nested
            # function in the outer scope (line 448-449); the assert
            # localises the invariant for mypy across the closure.
            assert self._client is not None

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
            call_temperature: float | None = temperature
            call_max_tokens = max_tokens
            thinking_param: dict[str, Any] | None = None
            output_config: dict[str, str] | None = None

            if m in _ADAPTIVE_MODELS:
                # Adaptive thinking (Opus 4.6+ and Sonnet 4.6): effort controls depth.
                # Sampling parameters (temperature/top_p/top_k) are rejected — omit.
                #
                # v0.56.0 R4-mini — explicit ``display: "summarized"``. Opus 4.7
                # changed the default to ``"omitted"`` (whats-new-claude-4-7) which
                # makes thinking blocks arrive empty; without summaries the
                # GEODE activity feed has no reasoning trace to render. Hermes
                # forces this same value (``anthropic_adapter.py:1440``) for the
                # same reason: *"explicit override preserves UX."*
                thinking_param = {"type": "adaptive", "display": "summarized"}
                # v0.56.0 R4-mini — version-gate ``xhigh``. Opus 4.7 accepts it
                # (Anthropic recommends as starting effort for coding/agentic);
                # 4.6 / Sonnet 4.6 reject with 400. Downgrade to ``"max"`` on
                # the older models. Mirrors Hermes ``_supports_xhigh_effort``.
                effective_effort = effort
                if effort == "xhigh" and not _supports_xhigh_effort(m):
                    effective_effort = "max"
                output_config = {"effort": effective_effort}
                call_temperature = None
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
                static_text = static_part.rstrip()
                dynamic_text = dynamic_part.lstrip()
                # G-A2 (2026-05-12) — audit-mode (G3 strip) leaves
                # ``static_part`` empty when GEODE identity + memory layers are
                # all stripped; the boundary marker becomes the very first
                # character of ``system``. Attaching ``cache_control`` to an
                # empty text block trips
                # ``system.0: cache_control cannot be set for empty text
                # blocks`` (Anthropic 400). Promote the dynamic side to the
                # single cacheable block when ``static_text`` is empty so the
                # boundary still applies somewhere useful.
                if static_text and dynamic_text:
                    sys_blocks: list[dict[str, Any]] = [
                        {
                            "type": "text",
                            "text": static_text,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": dynamic_text},
                    ]
                elif dynamic_text:
                    sys_blocks = [
                        {
                            "type": "text",
                            "text": dynamic_text,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                elif static_text:
                    sys_blocks = [
                        {
                            "type": "text",
                            "text": static_text,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                else:
                    # Both halves empty — drop the system block entirely.
                    sys_blocks = []
            else:
                sys_blocks = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

            # Rolling messages-level cache breakpoints (Hermes system_and_3).
            # Combined with the system block above, this fills up to 4 of
            # Anthropic's cache_control slots and caches the long history
            # window in multi-turn agentic loops.
            cached_messages = apply_messages_cache_control(messages)

            create_kwargs: dict[str, Any] = {
                "model": m,
                "system": sys_blocks,
                "messages": cached_messages,
                "tools": api_tools,
                "tool_choice": tool_choice,
                "max_tokens": call_max_tokens,
            }
            if call_temperature is not None:
                create_kwargs["temperature"] = call_temperature
            if thinking_param is not None:
                create_kwargs["thinking"] = thinking_param
            if output_config is not None:
                create_kwargs["output_config"] = output_config
            if extra_h:
                create_kwargs["extra_headers"] = extra_h
            if extra_b:
                create_kwargs["extra_body"] = extra_b

            # GAP-S1 — stream API 로 TTFB 단축 + chunk-level 수신.
            # ``get_final_message()`` 가 stream 을 완전 소비 한 뒤
            # ``anthropic.types.Message`` 를 반환 — ``messages.create`` 와
            # 동일 schema 이므로 ``normalize_anthropic`` / 회계 path 가
            # 변경 없이 작동. agentic 소비자 interface 불변.
            async with self._client.messages.stream(**create_kwargs) as _stream:
                return await _stream.get_final_message()

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except LLMBadRequestError as exc:
            self.last_error = exc
            msg = str(exc)
            # Billing/credit errors — propagate as BillingError for clean UI.
            # v0.53.2 — carry plan context so AgenticLoop renders the
            # quota_exhausted IPC panel (parity with OpenAI/Codex/GLM).
            if "credit balance" in msg.lower() or "billing" in msg.lower():
                from core.llm.errors import BillingError

                _circuit_breaker.record_failure()
                plan_meta = _resolve_plan_meta(model)
                raise BillingError(
                    "Anthropic API credit balance too low. "
                    "Visit https://console.anthropic.com/settings/billing to add credits.",
                    provider=plan_meta.get("provider", "anthropic"),
                    plan_id=plan_meta.get("plan_id", ""),
                    plan_display_name=plan_meta.get("plan_display_name", ""),
                    upgrade_url=plan_meta.get(
                        "upgrade_url", "https://console.anthropic.com/settings/billing"
                    ),
                ) from exc
            log.warning("Anthropic BadRequest in agentic loop: %s", msg)
            # Booster E (2026-05-12) — surface the failure in
            # ``~/.geode/diagnostics/`` so an inspect_ai subprocess crash
            # leaves a trail outside the (subprocess-local) Python logger.
            if os.environ.get("GEODE_AUDIT_UNRESTRICTED") == "1":
                from core.audit.diagnostics import diag

                diag("petri.anthropic", f"BadRequest model={model}: {msg[:200]}")
            if "tool_use_id" in msg or "tool_result" in msg:
                from core.agent.loop import AgenticLoop

                AgenticLoop._repair_messages(messages)
                log.info("Repaired orphaned tool_result in conversation history")
                try:
                    response = await _do_call(model)
                    _circuit_breaker.record_success()
                    return normalize_anthropic(response)
                except Exception:
                    log.warning("Retry after repair failed", exc_info=True)
                    _circuit_breaker.record_failure()
                    return None
            if "input_schema" in msg:
                log.error(
                    "Tool schema error — likely an MCP tool missing input_schema. tools=%d",
                    len(tools),
                )
            _circuit_breaker.record_failure()
            return None
        except Exception as exc:
            # v0.53.2 — preserve BillingError propagation (mirror of the
            # OpenAI/Codex/GLM fix). Without the early re-raise the loop
            # treats quota exhaustion as a generic failure → no
            # quota_exhausted IPC event fires.
            from core.llm.errors import BillingError

            if isinstance(exc, BillingError):
                _circuit_breaker.record_failure()
                raise
            self.last_error = exc
            log.warning("Agentic LLM call failed", exc_info=True)
            # Booster E — same rationale as the BadRequest branch above.
            if os.environ.get("GEODE_AUDIT_UNRESTRICTED") == "1":
                from core.audit.diagnostics import diag

                diag("petri.anthropic", f"call_failed model={model}: {exc!r}")
            _circuit_breaker.record_failure()
            return None

        if response is None:
            _circuit_breaker.record_failure()
            return None

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        _circuit_breaker.record_success()
        return normalize_anthropic(response)

    async def areset_client(self) -> None:
        self._client = None


def _resolve_plan_meta(model: str) -> dict[str, str]:
    """v0.53.2 — resolve Plan metadata for BillingError context.

    Mirrors ``core/llm/fallback.py:_resolve_plan_for_billing_error``;
    duplicated here because the Anthropic adapter uses the async router
    path (``call_with_failover``) instead of ``retry_with_backoff_generic``.
    """
    try:
        from core.auth.plan_registry import resolve_routing

        target = resolve_routing(model)
        if target is None:
            return {}
        plan = target.plan
        return {
            "provider": plan.provider,
            "plan_id": plan.id,
            "plan_display_name": plan.display_name,
            "upgrade_url": plan.upgrade_url or "",
        }
    except Exception:
        log.debug("Plan resolution for Anthropic billing error failed", exc_info=True)
        return {}
