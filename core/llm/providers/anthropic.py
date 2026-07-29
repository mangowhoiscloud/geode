"""Anthropic provider — low-level client + retry/quota utilities.

Owns the SYNC Anthropic client (configured httpx pool), retry/backoff, quota
banner feeding, prompt-cache helpers, and native-tool shaping consumed by
``core/llm/adapters``. Async clients live in the adapters layer
(``build_async_anthropic_client``) — the provider-level async getter was
removed 2026-07-29 once its last caller (the legacy agentic adapter) was gone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.config import is_model_allowed
from core.llm.fallback import (
    retry_with_backoff_generic,
    retry_with_backoff_generic_async,
)
from core.llm.model_capabilities import (
    ANTHROPIC_ADAPTIVE_MODELS,
    ANTHROPIC_CONTEXT_MGMT_MODELS,
    ANTHROPIC_XHIGH_MODELS,
)

if TYPE_CHECKING:
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
    """httpx async event hook — delegates to the banner feeder.

    Consumed by ``core/llm/adapters/_anthropic_common.build_async_anthropic_client``
    via a lazy in-function import (the live Anthropic client path), NOT by
    this module — a 2026-07-29 prune pass nearly dropped it as an orphan.
    """
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


def _static_system_cache_control() -> dict[str, str]:
    """``cache_control`` for the stable static system prefix (agentic adapter).

    The static prefix — everything before ``<dynamic_context>`` — is
    byte-identical across every turn of an agentic loop, so it benefits most
    from the **1-hour TTL**: GA as of 2026-06, enabled by ``ttl: "1h"`` on the
    ephemeral ``cache_control`` (no beta header). The 2x write premium amortizes
    after ~3 cache reads, which any multi-turn loop clears immediately. The
    5-minute default would expire between turns whenever tool execution exceeds
    5 min, forcing a fresh write every resume.

    Kill switch: ``settings.prompt_cache_extended_ttl`` (set False → 5-minute
    ephemeral default). One-shot call shapes (``system_with_cache``) and the
    dynamic / no-boundary blocks keep the 5-minute default — only the reused
    static prefix earns the extended TTL.

    SDK: ``anthropic.types.CacheControlEphemeralParam`` exposes optional ``ttl``
    (verified 0.100.0).
    ref: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
    """
    from core.config import settings

    if getattr(settings, "prompt_cache_extended_ttl", True):
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


# Anthropic allows up to 4 cache_control breakpoints per request.  The agentic
# adapter already uses 1-2 on the system block (STATIC/DYNAMIC split).  Keep 3
# slots for the messages array — Hermes "system_and_3" strategy.
MAX_MESSAGE_CACHE_BREAKPOINTS = 3

# Anthropic's cache lookup walks back at most this many content blocks from a
# breakpoint to find a prior cached entry (verified against the prompt-caching
# guide, 2026-06). When a single agentic turn appends more than this many
# tool_use/tool_result blocks, breakpoints clustered on the last few messages
# all fall outside the window on the next turn → silent full miss. Spread the
# message breakpoints ~``_CACHE_BREAKPOINT_BLOCK_STRIDE`` blocks apart so the
# newest breakpoint can always reach a prior entry. ref:
# https://platform.claude.com/docs/en/build-with-claude/prompt-caching
_CACHE_LOOKBACK_BLOCKS = 20
_CACHE_BREAKPOINT_BLOCK_STRIDE = 18  # under the 20-block window, with margin


def _content_block_count(content: Any) -> int:
    """Number of content blocks a message contributes to the lookback window."""
    if isinstance(content, list):
        return len(content)
    return 1 if content else 0


# Opening tag of the per-request system reminder. SoT for the tag name is
# ``core.agent.system_injection._REMINDER_TAG``; the literal is duplicated
# here to keep this low-level module free of core.agent imports — pinned by
# ``test_reminder_tag_constant_drift`` (dual-SoT anchor + drift invariant).
_SYSTEM_REMINDER_OPEN = "<system-reminder>"


def _is_volatile_reminder(content: Any) -> bool:
    """Per-round system reminder — byte-different every round (``Current
    round: N``), so a breakpoint on it can never be read back; marking it
    structurally wastes 1 of the 3 message slots."""
    if isinstance(content, str):
        return content.lstrip().startswith(_SYSTEM_REMINDER_OPEN)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text") or ""
                return text.lstrip().startswith(_SYSTEM_REMINDER_OPEN)
    return False


def _is_markable(content: Any) -> bool:
    """Whether :func:`apply_messages_cache_control` would actually attach a
    breakpoint to this message (mirrors its empty-text guards).

    An empty message is skipped at mark time, so selecting it as a breakpoint
    target would waste a slot (and, for the anchor, leave the newest turn
    uncached). Only markable messages should be selected.
    """
    if isinstance(content, str):
        return bool(content)
    if isinstance(content, list) and content:
        last = content[-1]
        return not (isinstance(last, dict) and last.get("type") == "text" and not last.get("text"))
    return False


def _select_breakpoint_targets(
    messages: list[dict[str, Any]],
    n_breakpoints: int,
) -> list[int]:
    """Indices of non-system messages to mark with ``cache_control``.

    Short histories (total content blocks ≤ ``_CACHE_LOOKBACK_BLOCKS``) keep the
    original "last ``n`` adjacent messages" behaviour — the whole history fits in
    one lookback window, so spreading buys nothing. Long histories spread the
    breakpoints ~``_CACHE_BREAKPOINT_BLOCK_STRIDE`` blocks apart (anchoring the
    newest markable message) so each breakpoint stays within the 20-block window
    of its predecessor across turns.

    Distance is measured in **content blocks from each message's final block**
    (where the breakpoint physically sits), counting every block in between —
    including the newer breakpoint's own blocks, which consume the lookback
    window. Only *markable* messages are eligible (an empty one is skipped at
    mark time, so anchoring/spreading on it would waste the breakpoint slot).
    """
    non_system = [i for i, m in enumerate(messages) if m.get("role") != "system"]
    # Guard n<=0 here too: ``markable[-0:]`` is ``markable[0:]`` (the whole
    # list), so the short-history branch below would mark every message. The
    # public caller already returns early on n<=0, but keep the helper safe for
    # any future caller.
    if not non_system or n_breakpoints <= 0:
        return []

    markable = [
        i
        for i in non_system
        if _is_markable(messages[i].get("content"))
        and not _is_volatile_reminder(messages[i].get("content"))
    ]
    if not markable:
        return []

    total_blocks = sum(_content_block_count(messages[i].get("content")) for i in non_system)
    if total_blocks <= _CACHE_LOOKBACK_BLOCKS:
        return markable[-n_breakpoints:]

    # ``end_offset[idx]`` = content blocks AFTER ``idx``'s final block (0 for the
    # very last message). Walk from the end accumulating each message's own block
    # count *after* recording, so the distance between two breakpoints is the
    # difference of their end_offsets.
    end_offset: dict[int, int] = {}
    acc = 0
    for idx in reversed(non_system):
        end_offset[idx] = acc
        acc += _content_block_count(messages[idx].get("content"))

    selected = [markable[-1]]
    last_offset = end_offset[markable[-1]]
    for idx in reversed(markable[:-1]):
        if len(selected) >= n_breakpoints:
            break
        if end_offset[idx] - last_offset >= _CACHE_BREAKPOINT_BLOCK_STRIDE:
            selected.append(idx)
            last_offset = end_offset[idx]
    return sorted(selected)


def apply_messages_cache_control(
    messages: list[dict[str, Any]],
    *,
    n_breakpoints: int = MAX_MESSAGE_CACHE_BREAKPOINTS,
) -> list[dict[str, Any]]:
    """Return a copy of *messages* with ephemeral cache_control on up to
    *n_breakpoints* non-system messages' final content block.

    Placement (see :func:`_select_breakpoint_targets`): short histories keep
    the original "last ``n`` adjacent messages" strategy; long histories
    (> 20 content blocks) spread the breakpoints ~18 blocks apart so the newest
    one stays within Anthropic's 20-block lookback window of its predecessor
    across turns — otherwise a single tool-heavy turn pushes every clustered
    breakpoint out of the window and the whole rolling cache silently misses.

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
    targets = _select_breakpoint_targets(out, n_breakpoints)

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
# Request shaping helpers consumed by core/llm/adapters/_anthropic_common
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
    """Check if computer-use is enabled for the selected execution driver.

    Audit safety (Phase E): a Petri audit runs unattended, so it must NEVER be
    able to drive the operator's real desktop. When audit mode is active
    (``GEODE_AUDIT_UNRESTRICTED=1``) computer-use is force-disabled UNLESS it is
    routed to the sandbox (``computer_use_env=sandbox`` → a virtual desktop, not
    the host). Without this an audit scenario that emitted a computer tool_use
    would control the live screen.
    """
    from core.config import settings
    from core.runtime_audit import runtime_audit_active
    from core.tools.computer_use import (
        computer_use_driver,
        computer_use_env,
        computer_use_helper_path,
    )

    if not getattr(settings, "computer_use_enabled", False):
        return False
    env = computer_use_env()
    if runtime_audit_active() and env != "sandbox":
        log.debug("computer-use disabled under audit (env != sandbox; no real-desktop control)")
        return False
    if env == "sandbox":
        # Sandbox mode: the host is only an HTTP client; pyautogui lives inside
        # the container, so the host does NOT need it. (fail-loud if the
        # container is unreachable — handled at dispatch.)
        return True
    driver = computer_use_driver()
    if driver == "helper":
        available = computer_use_helper_path() is not None
        if not available:
            log.debug("computer-use disabled: required macOS helper is not installed")
        return available
    if driver == "auto" and computer_use_helper_path() is not None:
        return True
    # Host python mode, or auto with no helper, drives the desktop via
    # pyautogui.
    try:
        import pyautogui  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        log.debug("computer-use disabled: pyautogui not installed")
        return False


# ── 2026-07-29 prune ───────────────────────────────────────────────────────
# ``ClaudeAgenticAdapter`` (and its private ``_resolve_plan_meta``) were
# deleted here: the class was registered nowhere and instantiated nowhere —
# the production AgenticLoop reaches Anthropic exclusively through
# ``core/llm/adapters/_anthropic_common.build_create_kwargs`` /
# ``build_stream_kwargs``, which now own the prompt-cache split, message
# breakpoints, and the ADR-012 M4.4 in-context slot wiring this class had
# stranded. This module is a low-level utility layer (clients, retry,
# quota, cache helpers, native-tool shaping) consumed by ``core/llm/adapters``.
#
# 2026-07-29 (같은 날 후속): the two deferred re-wires — context management
# (``_CONTEXT_MGMT_MODELS``) and native web_search/web_fetch injection
# (``_ANTHROPIC_NATIVE_TOOLS``) — were live-verified on anthropic-oauth
# (context-mgmt 200 with merged beta tokens; web_search 200 with a real
# ``server_tool_use`` round) and now run on the live builders in
# ``core/llm/adapters/_anthropic_common.py``. This module keeps the constants
# as the low-level SoT.
