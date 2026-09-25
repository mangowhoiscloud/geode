"""Anthropic provider — low-level shaping and quota utilities.

Owns quota banner feeding, prompt-cache helpers, native-tool shaping consumed
by ``core/llm/adapters``, and a compatibility retry wrapper. SDK clients live
in the adapters layer; the provider-level getter was removed 2026-07-29 once
its last caller was gone.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from core.config import is_model_allowed
from core.llm.fallback import (
    retry_with_backoff_generic_async,
)
from core.llm.model_capabilities import (
    ANTHROPIC_ADAPTIVE_MODELS,
    ANTHROPIC_CONTEXT_MGMT_MODELS,
    ANTHROPIC_XHIGH_MODELS,
)

if TYPE_CHECKING:
    import httpx

    from core.config.policy_source import PolicySourcePaths
    from core.observability.run_event import RunEventSinkProvider

    # v0.88.0 — declare the lazy module-level tuples so mypy / IDEs see a
    # concrete type for ``except RETRYABLE_ERRORS:`` etc.  Runtime values
    # come from ``__getattr__`` below.  Use ``Exception`` (not
    # ``BaseException``) to match the ``retry_with_backoff_generic_async``
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
# ``evals.petri.credential_source``, which is in the product ring and
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
    unparsable (defensive — never raise from the response hook). Both
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
    response path it observes (parity with RunTimeline.append).
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


async def _async_response_hook(response: object) -> None:
    """httpx async event hook — delegates to the banner feeder.

    Consumed by ``core/llm/adapters/_anthropic_common.build_async_anthropic_client``
    via a lazy in-function import (the live Anthropic client path), NOT by
    this module — a 2026-07-29 prune pass nearly dropped it as an orphan.
    """
    _feed_banner_from_anthropic_response(response)


def _emit_retry_activity(
    activity_sink_provider: RunEventSinkProvider,
    *,
    model: str,
    attempt: int,
    max_retries: int,
    delay_s: float,
    elapsed_s: float,
    error_type: str,
) -> None:
    """Emit one retry marker through the explicitly injected activity sink."""
    try:
        journal = activity_sink_provider()
        if journal is None:
            return
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
    except Exception:  # pragma: no cover - observability must not break retries
        log.debug("anthropic llm_retry activity emit failed", exc_info=True)


# v0.88.0 — RETRYABLE_ERRORS / NON_RETRYABLE_ERRORS resolve through the
# module-level ``__getattr__`` hook (defined above) on first use.  Their
# concrete tuples used to live here as eager module-level expressions
# (``RETRYABLE_ERRORS = (anthropic.RateLimitError, …)``), which forced
# the anthropic SDK import at module load.

# H11-tail: the module-level FALLBACK_MODELS alias (a boot-frozen copy of
# ANTHROPIC_FALLBACK_CHAIN, also re-exported to router/calls/streaming.py) was
# replaced by function-local ``from core.config import ANTHROPIC_FALLBACK_CHAIN``
# reads at each consumer so a routing.toml reload is seen without a restart.


def _static_system_cache_control() -> dict[str, str]:
    """``cache_control`` for the stable static system prefix (agentic adapter).

    The stable prefix can request a 1-hour TTL for gaps longer than five
    minutes. Frequent hits already refresh the default 5-minute TTL for free;
    the 2x write price is justified by reuse cadence, not the number of turns.
    ``settings.prompt_cache_extended_ttl=False`` selects the 5-minute default.

    SDK: ``anthropic.types.CacheControlEphemeralParam`` exposes optional ``ttl``
    (verified 0.100.0).
    ref: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
    """
    from core.config import settings

    if getattr(settings, "prompt_cache_extended_ttl", True):
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


# Anthropic allows up to 4 cache_control breakpoints per request.  The agentic
# adapter uses one on the static system block. Keep 3
# slots for the messages array — Hermes "system_and_3" strategy.
MAX_MESSAGE_CACHE_BREAKPOINTS = 3

# Keep the existing conservative raw-block spacing heuristic. The current API
# groups consecutive tool_use/tool_result blocks into one lookup position;
# this local count is not a cache-hit guarantee or a tokenizer simulation.
_CACHE_LOOKBACK_BLOCKS = 20
_CACHE_BREAKPOINT_BLOCK_STRIDE = 18  # under the 20-block window, with margin


def _content_block_count(content: Any) -> int:
    """Raw block count used by the conservative placement heuristic."""
    if isinstance(content, list):
        return len(content)
    return 1 if content else 0


# SDK ContentBlockParam / BetaContentBlockParam members accepting cache_control. Opaque thinking
# blocks stay in replay unchanged and are cached only behind an eligible block.
_CACHEABLE_BLOCK_TYPES = frozenset(
    {
        "text",
        "image",
        "document",
        "search_result",
        "tool_use",
        "tool_result",
        "server_tool_use",
        "web_search_tool_result",
        "web_fetch_tool_result",
        "code_execution_tool_result",
        "bash_code_execution_tool_result",
        "text_editor_code_execution_tool_result",
        "tool_search_tool_result",
        "container_upload",
        "mid_conv_system",
        "compaction",
        "advisor_tool_result",
        "mcp_tool_use",
        "mcp_tool_result",
    }
)


def _is_cacheable_block(block: Any) -> bool:
    return (
        isinstance(block, dict)
        and isinstance(block.get("type"), str)
        and block.get("type") in _CACHEABLE_BLOCK_TYPES
        and (block.get("type") != "text" or bool(block.get("text")))
    )


def _is_markable(content: Any) -> bool:
    """Whether the final block accepts a new marker without changing replay."""
    if isinstance(content, str):
        return bool(content)
    return bool(
        isinstance(content, list)
        and content
        and _is_cacheable_block(content[-1])
        and "cache_control" not in content[-1]
    )


def validate_cache_controls(
    *,
    messages: list[dict[str, Any]],
    system: Any = "",
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Validate explicit markers in wire order and return occupied slots."""
    from core.llm.errors import LLMRequestValidationError

    blocks = [(block, False) for block in tools or []]
    if isinstance(system, list):
        blocks.extend((block, True) for block in system)
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            blocks.extend((block, True) for block in content)
    count = 0
    seen_short_ttl = False
    for block, require_content_type in blocks:
        if not isinstance(block, dict) or "cache_control" not in block:
            continue
        control = block["cache_control"]
        if require_content_type and not _is_cacheable_block(block):
            raise LLMRequestValidationError("Anthropic cache_control requires a cacheable block")
        if (
            not isinstance(control, dict)
            or control.get("type") != "ephemeral"
            or control.get("ttl", "5m") not in ("5m", "1h")
        ):
            raise LLMRequestValidationError("Invalid Anthropic cache_control type or TTL")
        is_short = control.get("ttl", "5m") == "5m"
        if seen_short_ttl and not is_short:
            raise LLMRequestValidationError("Anthropic 1h cache markers must precede 5m markers")
        seen_short_ttl |= is_short
        count += 1
    if count > 4:
        raise LLMRequestValidationError("Anthropic supports at most 4 cache breakpoints")
    return count


def _select_breakpoint_targets(
    messages: list[dict[str, Any]],
    n_breakpoints: int,
) -> list[int]:
    """Indices of non-system messages to mark with ``cache_control``.

    Short histories (total content blocks ≤ ``_CACHE_LOOKBACK_BLOCKS``) keep the
    original "last ``n`` adjacent messages" behaviour. Long histories spread
    breakpoints ~``_CACHE_BREAKPOINT_BLOCK_STRIDE`` raw blocks apart, anchoring
    the newest markable message. Provider lookup positions can group content
    differently, so this placement heuristic cannot guarantee reuse across turns.

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

    markable = [i for i in non_system if _is_markable(messages[i].get("content"))]
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
    reserved_breakpoints: int = 1,
) -> list[dict[str, Any]]:
    """Return a copy of *messages* with ephemeral cache_control on up to
    *n_breakpoints* non-system messages' final content block.

    Short histories select adjacent trailing blocks; long histories retain
    the existing raw-block spacing heuristic. Provider prefix equality, token
    minimums, TTL and lookup rules determine actual hits.

    The function is non-mutating: returns a new list with shallow copies of
    the targeted messages and their last block.  String-content messages are
    materialised into a single text block before the marker is attached.

    Args:
        messages: Anthropic-format messages list (role + content).
        n_breakpoints: Max number of trailing non-system messages to mark.
            Default 3; existing markers consume this request's remaining slots.
        reserved_breakpoints: Slots already occupied by system/tools (default 1).

    Returns:
        New messages list ready for ``messages.create``.
    """
    from core.llm.errors import LLMRequestValidationError

    if not isinstance(n_breakpoints, int) or isinstance(n_breakpoints, bool) or n_breakpoints < 0:
        raise LLMRequestValidationError("Anthropic message cache budget must be nonnegative")
    if (
        not isinstance(reserved_breakpoints, int)
        or isinstance(reserved_breakpoints, bool)
        or not 0 <= reserved_breakpoints <= 4
    ):
        raise LLMRequestValidationError("Anthropic reserved cache slots must be between 0 and 4")
    occupied = validate_cache_controls(messages=messages)
    if occupied + reserved_breakpoints > 4:
        raise LLMRequestValidationError("Anthropic supports at most 4 cache breakpoints")
    available = min(n_breakpoints, 4 - reserved_breakpoints - occupied)
    if not messages or available == 0:
        return list(messages)

    out: list[dict[str, Any]] = list(messages)
    # New markers use 5m: do not insert one ahead of an explicit 1h marker.
    last_long_ttl = max(
        (
            i
            for i, message in enumerate(messages)
            if isinstance(message.get("content"), list)
            and any(
                isinstance(block, dict) and block.get("cache_control", {}).get("ttl") == "1h"
                for block in message["content"]
            )
        ),
        default=-1,
    )
    targets = [i for i in _select_breakpoint_targets(out, available) if i >= last_long_ttl]

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


async def retry_with_backoff_async(
    fn: Any,
    *,
    model: str,
    max_retries: int | None = None,
    activity_sink_provider: RunEventSinkProvider | None = None,
    routing_sources: PolicySourcePaths | None = None,
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
        on_retry=(
            (lambda **kwargs: _emit_retry_activity(activity_sink_provider, **kwargs))
            if activity_sink_provider
            else None
        ),
        routing_sources=routing_sources,
    )


# ---------------------------------------------------------------------------
# Request shaping helpers consumed by core/llm/adapters/_anthropic_common
# ---------------------------------------------------------------------------

_API_ALLOWED_KEYS = frozenset(
    {"name", "description", "input_schema", "cache_control", "type", "strict", "defer_loading"}
)

# Derived from the same verified records used by the adapter and effort picker.
_CONTEXT_MGMT_MODELS: frozenset[str] = ANTHROPIC_CONTEXT_MGMT_MODELS
_ADAPTIVE_MODELS: frozenset[str] = ANTHROPIC_ADAPTIVE_MODELS
_XHIGH_EFFORT_MODELS: frozenset[str] = ANTHROPIC_XHIGH_MODELS


def _supports_xhigh_effort(model: str) -> bool:
    """Return whether the verified model accepts xhigh effort."""
    from core.llm.model_capabilities import get_anthropic_model_spec

    spec = get_anthropic_model_spec(model)
    return spec is not None and "xhigh" in spec.effort_values


_ANTHROPIC_NATIVE_TOOLS: list[dict[str, Any]] = [
    {"type": "web_search_20260318", "name": "web_search", "allowed_callers": ["direct"]},
    {"type": "web_fetch_20260318", "name": "web_fetch", "allowed_callers": ["direct"]},
]

# Hosted tool-search tool (PR-TOOL-SEARCH-WIRE, 2026-06-13). Official
# Messages API mechanism for large tool sets: deferred tools stay out of
# the context window until the model discovers them; the API expands
# tool_reference blocks server-side, preserving the prompt-cache prefix.
# ref: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
#   - ``defer_loading`` is an official tool-definition field
#   - model/endpoint admission belongs to the adapter; the supported model
#     set lives in core.llm.model_capabilities
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
)


def apply_tool_search_defer(
    api_tools: list[dict[str, Any]],
    *,
    deferred_tool_names: Collection[str],
    enabled: bool = True,
    threshold: int = TOOL_DEFER_THRESHOLD,
) -> list[dict[str, Any]]:
    """Shape *api_tools* for the hosted tool-search tool.

    Above *threshold*: custom tools named by the request's immutable tool-plan
    projection get ``defer_loading: True`` and the hosted search tool is
    prepended. Hosted/native entries (anything carrying a ``type``) are never
    deferred. Returns the input unchanged when disabled, under threshold, or
    when nothing would defer (a defer pass that defers zero tools is pure
    overhead).
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
        if (
            tool.get("type")
            or "cache_control" in tool
            or tool.get("name", "") not in deferred_tool_names
        ):
            # A deferred definition with cache_control is an API 400. Keep
            # that breakpoint's tool eager without moving or dropping it.
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

    A Petri audit runs unattended, so audit mode always disables computer-use.
    Without that fail-closed guard an audit scenario that emitted a computer
    tool_use could control the operator's live screen.
    """
    from core.config import settings
    from core.runtime_audit import runtime_audit_active
    from core.tools.computer_use import (
        computer_use_driver,
        computer_use_helper_path,
    )

    if not getattr(settings, "computer_use_enabled", False):
        return False
    if runtime_audit_active():
        log.debug("computer-use disabled under unattended audit")
        return False
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
    except KeyError as exc:
        # PyAutoGUI/mouseinfo reads DISPLAY while importing on headless Linux.
        # An unavailable desktop must not break ordinary model requests.
        if exc.args != ("DISPLAY",):
            raise
        log.debug("computer-use disabled: no X11 DISPLAY")
        return False


# This module is a low-level utility layer (clients, retry, quota, cache
# helpers, native-tool shaping) consumed by ``core/llm/adapters``.
# Context management and native web tools are injected by the builders in
# ``core/llm/adapters/_anthropic_common.py``. The current documented contracts
# and offline verification boundary live in the provider refresh research note.
