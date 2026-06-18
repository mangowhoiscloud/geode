"""Anthropic provider — singleton clients + retry wrapper.

Owns sync/async Anthropic clients with configured httpx connection pool.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

from core.config import is_model_allowed
from core.llm.fallback import (
    retry_with_backoff_generic,
    retry_with_backoff_generic_async,
)
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.model_capabilities import (
    ANTHROPIC_ADAPTIVE_MODELS,
    ANTHROPIC_CONTEXT_MGMT_MODELS,
    ANTHROPIC_XHIGH_MODELS,
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
    # P1a (2026-05-19) — OverloadedError (status 529) is a sibling of
    # InternalServerError under APIStatusError, NOT a subclass. The
    # original tuple omitted it, so every 529 bubbled up without retry —
    # a silent failure during Anthropic capacity dips. The audit row
    # "529 Overloaded retry 정책 미정" tracked this exact gap.
    "RETRYABLE_ERRORS": (
        "RateLimitError",
        "APIConnectionError",
        "InternalServerError",
        "OverloadedError",
    ),
    "NON_RETRYABLE_ERRORS": ("AuthenticationError", "BadRequestError"),
}


def _resolve_anthropic_exception(name: str) -> type[Exception]:
    """Resolve an anthropic SDK exception class, falling through to the
    private ``_exceptions`` namespace.

    P1a — ``OverloadedError`` (529) lives only in ``anthropic._exceptions``,
    not at the top-level ``anthropic`` namespace, so a simple
    ``getattr(anthropic, name)`` raises ``AttributeError`` for it. The
    fallthrough keeps the rest of the lazy resolution working for
    classes that DO sit at the top level (RateLimitError,
    InternalServerError, etc.).
    """
    import anthropic

    candidate: Any
    if hasattr(anthropic, name):
        candidate = getattr(anthropic, name)
    else:
        from anthropic import _exceptions as _ex

        candidate = getattr(_ex, name)
    if not (isinstance(candidate, type) and issubclass(candidate, Exception)):
        raise TypeError(
            f"anthropic attribute {name!r} resolved to {candidate!r}, expected Exception subclass"
        )
    return candidate


def __getattr__(name: str) -> Any:
    """PEP 562 module attribute hook — resolve anthropic-derived names lazily."""
    if name in _ANTHROPIC_LAZY_TUPLES:
        value = tuple(_resolve_anthropic_exception(n) for n in _ANTHROPIC_LAZY_TUPLES[name])
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

# PR-LOOP-POLLUTION-FIX (2026-06-12) — async client is per-event-loop, not
# process-global (see core/llm/loop_affinity.py).
_async_clients = LoopAffineClientCache("anthropic-provider")


# ---------------------------------------------------------------------------
# P0c — quota banner writer wiring (callback-registration pattern)
# ---------------------------------------------------------------------------
#
# httpx event hook that feeds ``SubscriptionQuotaBanner.set_state`` from
# the ``anthropic-ratelimit-tokens-*`` response headers. Runs on every
# response; values are present on subscription-OAuth routed calls and
# typically absent on PAYG calls — the hook silently skips when the
# headers are missing so PAYG users see no banner change.
#
# Architecture note: we do NOT ``from core.cli.quota_banner import …`` here
# because the import-linter contracts (``Agent stays pure``,
# ``Server may host agent but never CLI``) forbid
# ``core.llm.providers.* → core.cli.*``. Instead we expose
# :func:`register_quota_setter` and let the CLI layer push its
# ``banner.set_state`` callable in. The provider only knows about a
# generic ``Callable``; the banner module owns the import direction.
#
# Banner SoT: only this quota writer (and the trip_abort call in
# ``plugins.petri_audit.credential_source``, which is in plugins/ and
# may import core.cli) feeds the banner. Per the 2026-05-19
# observability audit §4, the banner was previously installed but never
# fed in production code — the operator never saw a quota signal.


# Type alias for the callback signature so the registration helper has a
# concrete signature without dragging the SubscriptionQuotaBanner type in.
_QuotaSetter = Any  # Callable[..., None] — kwargs: provider, used_tokens, total_tokens
_quota_setter: _QuotaSetter | None = None


def register_quota_setter(setter: _QuotaSetter | None) -> None:
    """Install (or clear) the per-call quota-banner update callback.

    Called by the CLI front-end immediately after ``install_banner`` so
    the response hook can update the banner state without
    ``core.llm.providers.anthropic`` importing ``core.cli.quota_banner``
    (which the import-linter contract forbids — the agent path must not
    depend on the CLI). Passing ``None`` clears the callback (used by
    the CLI ``uninstall_banner`` path + by tests to detach between cases).
    """
    global _quota_setter
    _quota_setter = setter


def _extract_anthropic_quota(headers: object) -> tuple[int, int] | None:
    """Parse ``(used, limit)`` from ``anthropic-ratelimit-tokens-*`` headers.

    Returns ``None`` when the headers are absent (PAYG path) or
    unparseable (defensive — never raise from the response hook). Both
    values are int tokens for the **current rate-limit window** (per-day
    on subscription OAuth; per-minute on PAYG); the banner renders them
    as a usage ratio.
    """
    try:
        limit_str = headers.get("anthropic-ratelimit-tokens-limit")  # type: ignore[attr-defined]
        remaining_str = headers.get("anthropic-ratelimit-tokens-remaining")  # type: ignore[attr-defined]
    except AttributeError:
        return None
    if not limit_str or not remaining_str:
        return None
    try:
        limit = int(limit_str)
        remaining = int(remaining_str)
    except (TypeError, ValueError):
        return None
    used = max(0, limit - remaining)
    return used, limit


def _feed_banner_from_anthropic_response(response: object) -> None:
    """Read Anthropic rate-limit headers and push to the active banner.

    No-op when no banner is installed (CLI front-end didn't start one) or
    when the response carries no rate-limit headers. Defensive: any
    exception here is swallowed because observability MUST NOT break the
    response path it observes (parity with RunTranscript.append).
    """
    try:
        headers = getattr(response, "headers", None)
        if headers is None:
            return
        parsed = _extract_anthropic_quota(headers)
        if parsed is None:
            return
        used, limit = parsed
        setter = _quota_setter
        if setter is None:
            return
        setter(provider="anthropic", used_tokens=used, total_tokens=limit)
    except Exception:  # pragma: no cover - defensive
        log.debug("anthropic quota banner feed failed", exc_info=True)


def _sync_response_hook(response: object) -> None:
    """httpx sync event hook — delegates to the banner feeder."""
    _feed_banner_from_anthropic_response(response)


async def _async_response_hook(response: object) -> None:
    """httpx async event hook — delegates to the banner feeder."""
    _feed_banner_from_anthropic_response(response)


def _on_retry_journal_emit(
    *,
    model: str,
    attempt: int,
    max_retries: int,
    delay_s: float,
    elapsed_s: float,
    error_type: str,
) -> None:
    """``on_retry`` callback — emit ``llm_retry`` event to the active journal.

    P1a — closes the silent-retry gap from the 2026-05-19 observability
    audit §4 row "529 Overloaded retry 정책 미정". The 529 → InternalServerError
    classification is already correct (Anthropic SDK maps ``status_code >= 500``
    to ``InternalServerError`` which is in ``RETRYABLE_ERRORS``), but the
    retry itself was previously silent — operators saw the final outcome
    but not the retry count or the triggering error.

    Discovered via the ContextVar set in ``run_transcript_scope``; no-op
    when not in scope (single REPL invocation outside an autoresearch /
    seed-generation run) so the helper is safe to wire unconditionally.
    """
    try:
        from core.self_improving.loop.observe.run_transcript import current_run_transcript

        journal = current_run_transcript()
        if journal is None:
            return
        # Treat overload / rate-limit / 5xx as warning level; connection
        # blips stay info because they're routine in long-running runs.
        level = (
            "warn"
            if error_type in {"InternalServerError", "RateLimitError", "OverloadedError"}
            else "info"
        )
        journal.append(
            "llm_retry",
            level=level,
            payload={
                "provider": "anthropic",
                "model": model,
                "attempt": attempt,
                "max_retries": max_retries,
                "delay_s": round(delay_s, 3),
                "elapsed_s": round(elapsed_s, 3),
                "error_type": error_type,
            },
        )
    except Exception:  # pragma: no cover - defensive
        log.debug("anthropic llm_retry journal emit failed", exc_info=True)


# v0.88.0 — RETRYABLE_ERRORS / NON_RETRYABLE_ERRORS resolve through the
# module-level ``__getattr__`` hook (defined above) on first use.  Their
# concrete tuples used to live here as eager module-level expressions
# (``RETRYABLE_ERRORS = (anthropic.RateLimitError, …)``), which forced
# the anthropic SDK import at module load.

# H11-tail: the module-level FALLBACK_MODELS alias (a boot-frozen copy of
# ANTHROPIC_FALLBACK_CHAIN, also re-exported to router/calls/streaming.py) was
# replaced by function-local ``from core.config import ANTHROPIC_FALLBACK_CHAIN``
# reads at each consumer so a routing.toml reload is seen without a restart.


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
                event_hooks={"response": [_sync_response_hook]},
            )
            _sync_client = anthropic.Anthropic(
                api_key=_resolve_anthropic_key(),
                max_retries=0,  # app-level retry handles this
                http_client=http_client,
            )
        return _sync_client


def get_async_anthropic_client(api_key: str | None = None) -> anthropic.AsyncAnthropic:
    """Return the async Anthropic client bound to the CURRENT event loop.

    PR-LOOP-POLLUTION-FIX (2026-06-12) — previously a process-global
    singleton. The serve daemon runs multiple event loops (main serve loop
    for gateway turns, CLIPoller thread loop for CLI sessions); httpx
    connection-pool primitives bind to the loop that first drives them, so
    one shared client poisoned the pool across loops (instant
    APIConnectionError / eternal hang — see ``core/llm/loop_affinity.py``).
    Now one client per owning loop; same key-resolution and pool settings.
    SDK-level retries stay disabled (max_retries=0) — app-level retry
    (AgenticLoop) and the dispatch connection-transient retry own that.

    Args:
        api_key: Optional API key override. If None, uses settings.
        Note: the override only affects the loop that triggers the build
        (same first-caller-wins semantics as the old singleton).
    """
    import anthropic
    import httpx

    def _build() -> anthropic.AsyncAnthropic:
        key = api_key or _resolve_anthropic_key()
        http_client = httpx.AsyncClient(
            limits=_build_httpx_limits(),
            timeout=_build_httpx_timeout(),
            event_hooks={"response": [_async_response_hook]},
        )
        return anthropic.AsyncAnthropic(
            api_key=key,
            max_retries=0,  # app-level retry handles this
            http_client=http_client,
        )

    client: anthropic.AsyncAnthropic = _async_clients.get(_build)
    return client


async def areset_clients() -> None:
    """Reset cached clients. Used in tests and on API key change.

    Async clients are dropped (not closed) — ``aclose()`` requires each
    client's owning event loop, which may not be the current one; GC
    finalizers reclaim the sockets (see core/llm/loop_affinity.py).
    """
    global _sync_client
    with _sync_client_lock:
        if _sync_client is not None:
            with contextlib.suppress(Exception):
                _sync_client.close()
            _sync_client = None
    _async_clients.invalidate()


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

    from core.config import ANTHROPIC_FALLBACK_CHAIN  # H11-tail: live read
    from core.llm.fallback import MAX_RETRIES as _DEFAULT_MAX_RETRIES

    _max_retries = max_retries if max_retries is not None else _DEFAULT_MAX_RETRIES

    candidates = [model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != model]
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
        retryable_errors=_retryable_errors,
        bad_request_error=anthropic.BadRequestError,
        billing_message=(
            "Anthropic API credit balance too low. "
            "Visit https://console.anthropic.com/settings/billing to add credits, "
            "or use --dry-run mode."
        ),
        max_retries=_max_retries,
        provider_label="LLM",
        on_retry=_on_retry_journal_emit,
    )


async def retry_with_backoff_async(
    fn: Any,
    *,
    model: str,
    max_retries: int | None = None,
) -> Any:
    """Execute async fn with retry + exponential backoff + model fallback."""
    import anthropic

    from core.config import ANTHROPIC_FALLBACK_CHAIN  # H11-tail: live read
    from core.llm.fallback import MAX_RETRIES as _DEFAULT_MAX_RETRIES

    _max_retries = max_retries if max_retries is not None else _DEFAULT_MAX_RETRIES

    candidates = [model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != model]
    models_to_try = [m for m in candidates if is_model_allowed(m)]
    if not models_to_try:
        raise RuntimeError(f"All models blocked by policy: {candidates}")

    import sys

    _retryable_errors = sys.modules[__name__].RETRYABLE_ERRORS

    return await retry_with_backoff_generic_async(
        fn,
        model=models_to_try[0],
        fallback_models=models_to_try[1:],
        retryable_errors=_retryable_errors,
        bad_request_error=anthropic.BadRequestError,
        billing_message=(
            "Anthropic API credit balance too low. "
            "Visit https://console.anthropic.com/settings/billing to add credits, "
            "or use --dry-run mode."
        ),
        max_retries=_max_retries,
        provider_label="LLM",
        on_retry=_on_retry_journal_emit,
    )


# ---------------------------------------------------------------------------
# ClaudeAgenticAdapter — Anthropic LLM adapter for agentic loop
# ---------------------------------------------------------------------------

_API_ALLOWED_KEYS = frozenset(
    {"name", "description", "input_schema", "cache_control", "type", "strict", "defer_loading"}
)

# Models that support server-side context management + compaction beta.
# Haiku 4.5 (2025-10-01) predates compact-2026-01-12 and rejects the beta
# header with a 400 whose message contains "context" — misclassified as
# context_overflow.  Only 1M-context models are known to support it.
# Opus 4.8 (claude-opus-4-8) ships with a 1M context window and Claude Code
# runs it under server-side compaction, so it inherits the same contract.
# PR-DRIFT-ANCHORS (2026-06-10) — set contents live in the single SoT
# ``core/llm/model_capabilities.py``; this alias keeps the local name the
# rest of this module (and its tests) read.
_CONTEXT_MGMT_MODELS: frozenset[str] = ANTHROPIC_CONTEXT_MGMT_MODELS

# Adaptive thinking models (Opus 4.6+).  Sampling parameters
# (temperature/top_p/top_k) are rejected with 400 starting from Opus 4.7
# (https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
# #sampling-parameters-removed) and are also rejected by Opus 4.6 when
# adaptive thinking is on.  Omit them entirely on these models.
# Opus 4.8 continues the 4.6+ adaptive-thinking contract (the effort knob —
# incl. ``xhigh`` — only exists for adaptive models, and this session runs
# claude-opus-4-8 under adaptive thinking; see _XHIGH_EFFORT_MODELS note).
_ADAPTIVE_MODELS: frozenset[str] = ANTHROPIC_ADAPTIVE_MODELS

# v0.56.0 R4-mini — Opus 4.7 supports the new ``xhigh`` effort level (one
# step above ``high``); 4.6 / Sonnet 4.6 reject it with 400. Mirrors
# Hermes ``anthropic_adapter.py:49-53`` substring-based gate. Anthropic
# explicitly recommends ``xhigh`` as the starting effort for Opus 4.7
# coding/agentic workloads (platform.claude.com/docs/en/build-with-claude/
# effort) — but only the GEODE caller can opt in by setting
# ``agentic.effort = "xhigh"``; we never auto-upgrade ``high → xhigh``.
# Opus 4.8 (claude-opus-4-8) accepts ``xhigh`` — confirmed live: Claude Code
# configures this model with "xhigh effort" by default (the /model selector
# emits it). ctx7 platform docs only index up to the 4.6/4.7 family pages, so
# the 4.8-specific acceptance is grounded by the running harness rather than a
# doc page.
_XHIGH_EFFORT_MODELS: frozenset[str] = ANTHROPIC_XHIGH_MODELS


def _supports_xhigh_effort(model: str) -> bool:
    """Return True if the model accepts ``output_config.effort = "xhigh"``."""
    return model in _XHIGH_EFFORT_MODELS


_ANTHROPIC_NATIVE_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]},
    {"type": "web_fetch_20260209", "name": "web_fetch", "allowed_callers": ["direct"]},
]

# Hosted tool-search tool (PR-TOOL-SEARCH-WIRE, 2026-06-13). Official
# Messages API mechanism for large tool sets: deferred tools stay out of
# the context window until the model discovers them; the API expands
# tool_reference blocks server-side, preserving the prompt-cache prefix.
# ref: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
#   - ``defer_loading`` is an official tool-definition field
#   - model support: Opus 4.0+ / Sonnet 4.0+ / Haiku 4.5+ / Fable 5
#     (covers every model GEODE routes to this adapter)
#   - constraints: at least one tool must stay non-deferred; the search
#     tool itself must never carry defer_loading
_TOOL_SEARCH_TOOL: dict[str, Any] = {
    "type": "tool_search_tool_regex_20251119",
    "name": "tool_search_tool_regex",
}

# Policy constants (threshold + always-loaded core set) live in the
# provider-neutral ``core.llm.tool_defer`` since PR-CODEX-TOOL-SEARCH —
# the OpenAI Responses builder shares the same policy.
from core.llm.tool_defer import (  # noqa: E402  (policy import next to its use)
    TOOL_DEFER_THRESHOLD,
    TOOL_SEARCH_ALWAYS_LOADED,
)


def apply_tool_search_defer(
    api_tools: list[dict[str, Any]],
    *,
    enabled: bool = True,
    threshold: int = TOOL_DEFER_THRESHOLD,
) -> list[dict[str, Any]]:
    """Shape *api_tools* for the hosted tool-search tool.

    Above *threshold*: every custom tool outside
    :data:`TOOL_SEARCH_ALWAYS_LOADED` gets ``defer_loading: True`` and the
    hosted search tool is prepended. Hosted/native entries (anything
    carrying a ``type``) are never deferred — together with the core set
    they satisfy the API's at-least-one-non-deferred invariant. Returns
    the input unchanged when disabled, under threshold, or when nothing
    would defer (a defer pass that defers zero tools is pure overhead).
    """
    if not enabled or len(api_tools) <= threshold:
        return api_tools
    search_name = _TOOL_SEARCH_TOOL["name"]
    if any(t.get("name") == search_name or t.get("defer_loading") for t in api_tools):
        # Already shaped — idempotent pass-through (Codex review finding 2:
        # a second pass must not duplicate the search tool or re-mark defs).
        return api_tools
    shaped: list[dict[str, Any]] = []
    deferred_count = 0
    for tool in api_tools:
        if tool.get("type") or tool.get("name", "") in TOOL_SEARCH_ALWAYS_LOADED:
            shaped.append(tool)
            continue
        deferred_tool = dict(tool)
        deferred_tool["defer_loading"] = True
        shaped.append(deferred_tool)
        deferred_count += 1
    if not deferred_count:
        return api_tools
    log.info(
        "tool_search defer active: %d/%d tool defs deferred behind %s",
        deferred_count,
        len(shaped) + 1,
        _TOOL_SEARCH_TOOL["name"],
    )
    return [dict(_TOOL_SEARCH_TOOL), *shaped]


# Computer-use tool (injected when enabled via settings)
_COMPUTER_USE_TOOL: dict[str, Any] = {
    "type": "computer_20251124",
    "name": "computer",
    "display_width_px": 1280,
    "display_height_px": 800,
}


def is_computer_use_enabled() -> bool:
    """Check if computer-use is enabled (requires pyautogui + opt-in).

    Audit safety (Phase E): a Petri audit runs unattended, so it must NEVER be
    able to drive the operator's real desktop. When audit mode is active
    (``GEODE_AUDIT_UNRESTRICTED=1``) computer-use is force-disabled UNLESS it is
    routed to the sandbox (``computer_use_env=sandbox`` → a virtual desktop, not
    the host). Without this an audit scenario that emitted a computer tool_use
    would control the live screen.
    """
    import os

    from core.config import settings
    from core.tools.computer_use import computer_use_env

    if not getattr(settings, "computer_use_enabled", False):
        return False
    env = computer_use_env()
    if os.environ.get("GEODE_AUDIT_UNRESTRICTED") == "1" and env != "sandbox":
        log.debug("computer-use disabled under audit (env != sandbox; no real-desktop control)")
        return False
    if env == "sandbox":
        # Sandbox mode: the host is only an HTTP client; pyautogui lives inside
        # the container, so the host does NOT need it. (fail-loud if the
        # container is unreachable — handled at dispatch.)
        return True
    # Host mode drives the real desktop via local pyautogui.
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
        from core.config import ANTHROPIC_FALLBACK_CHAIN  # H11-tail: live read

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

        # PR-LOOP-POLLUTION-FIX (2026-06-12) — resolve the client PER CALL
        # so it is always the current event loop's client (the provider
        # getter is loop-affine; an instance slot would re-pin the first
        # loop's client across loops and reintroduce the pollution).
        # ``self._client`` survives only as a test seam: when pre-seeded it
        # wins; production code never assigns it.
        client = self._client or get_async_anthropic_client(api_key)

        # PR-M4.4 (2026-05-21) — 4-slot in-context wiring. No-op fast
        # path inside ``apply_in_context_slots`` when no SoT is
        # configured (the GEODE default), so this call adds zero
        # overhead for operators who have not opted in. Per-slot
        # graceful: any reader/apply failure is logged at DEBUG and
        # the original ``messages`` / ``system`` flow through unchanged.
        from core.self_improving.loop.inject.in_context_wiring import apply_in_context_slots

        messages, system = apply_in_context_slots(messages, system=system)

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

        # PR-TOOL-SEARCH-WIRE — large tool sets defer behind the hosted
        # tool-search tool (kill switch: settings.tool_search_defer).
        from core.config import settings as _settings

        api_tools = apply_tool_search_defer(
            api_tools, enabled=getattr(_settings, "tool_search_defer", True)
        )

        from core.config import ANTHROPIC_FALLBACK_CHAIN  # H11-tail: live read

        failover_models = [model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != model]

        async def _do_call(m: str) -> Any:
            # ``client`` is resolved right before this nested function in
            # the outer scope — loop-affine, current loop's instance.
            assert client is not None

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
            # ADR-013 T5 (2026-05-21) — cache-policy.json mutation SoT.
            # Default 3 (Anthropic cap minus 1 for system). Policy 가 부재면
            # default 그대로 (no behavior change).
            from core.llm.cache_policy import (
                _load_cache_policy_override,
                apply_cache_policy_breakpoints,
            )

            n_breakpoints = apply_cache_policy_breakpoints(
                MAX_MESSAGE_CACHE_BREAKPOINTS, _load_cache_policy_override()
            )
            cached_messages = apply_messages_cache_control(messages, n_breakpoints=n_breakpoints)

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
            async with client.messages.stream(**create_kwargs) as _stream:
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
            # v0.53.2 — preserve BillingError propagation (mirror of the
            # OpenAI/Codex/GLM fix). Without the early re-raise the loop
            # treats quota exhaustion as a generic failure → no
            # quota_exhausted IPC event fires.
            from core.llm.errors import BillingError

            if isinstance(exc, BillingError):
                raise
            self.last_error = exc
            log.warning("Agentic LLM call failed", exc_info=True)
            # Booster E — same rationale as the BadRequest branch above.
            if os.environ.get("GEODE_AUDIT_UNRESTRICTED") == "1":
                from core.audit.diagnostics import diag

                diag("petri.anthropic", f"call_failed model={model}: {exc!r}")
            return None

        if response is None:
            return None

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

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
        from core.llm.strategies.plan_registry import resolve_routing

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
