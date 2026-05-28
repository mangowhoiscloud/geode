"""Central dispatch — capability-based adapter fallback chains.

PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28). Paperclip-pattern alignment
(``server/src/adapters/registry.ts:768`` ``findActiveServerAdapter``): tool
callers (web_search, compaction, learning extraction) never instantiate
provider SDKs directly. They call into this module's helpers, which:

1. Enumerate adapters in the registry advertising the requested capability
   (``isinstance(adapter, WebSearchCapable)`` etc.)
2. Order by source preference — operator's ``{provider}_credential_source``
   setting + ProfileStore OAuth presence drives whether subscription adapters
   land before PAYG (same :func:`infer_source` flow the agent loop uses)
3. Try each in order, distinguishing billing-fatal (no retry helps) from
   transient (try next provider) failures
4. Raise :class:`BillingError` when every candidate hit billing-fatal so the
   operator sees a single actionable hint instead of N retry timeouts
5. Raise :class:`AdapterDispatchError` when every candidate failed for
   non-billing reasons (network, schema, etc.)

Without this central layer, every tool re-implemented its own
``try Anthropic / try OpenAI / try GLM`` chain with hardcoded PAYG clients —
which broke operator settings-driven switching (PR-SOURCE-ROUTING #1822 only
fixed the agent loop main path; tools stayed fragmented).
"""

from __future__ import annotations

import logging
from typing import Any

from core.llm.adapters.base import (
    SOURCE_PAYG,
    SOURCE_SUBSCRIPTION,
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.adapters.registry import list_adapters
from core.llm.errors import BillingError, is_billing_fatal

log = logging.getLogger(__name__)


class AdapterDispatchError(RuntimeError):
    """Raised when every capable adapter failed for non-billing reasons."""


# ---------------------------------------------------------------------------
# Ordering — paperclip ``findActiveServerAdapter`` mirror with source pref
# ---------------------------------------------------------------------------


def _source_preference(provider: str) -> tuple[str, ...]:
    """Return source ordering for *provider* based on operator settings.

    Uses the same :func:`core.llm.adapters._source_inference.infer_source`
    flow as the agent loop main path so the tool layer is consistent with
    the dispatch the operator already configured via ``/login``.
    """
    from core.llm.adapters._source_inference import infer_source

    primary = infer_source(provider)
    if primary == SOURCE_SUBSCRIPTION:
        return (SOURCE_SUBSCRIPTION, SOURCE_PAYG)
    return (SOURCE_PAYG, SOURCE_SUBSCRIPTION)


_CAPABILITY_METHOD: dict[str, str] = {
    "supports_web_search": "aweb_search",
    "supports_text_completion": "acomplete_text",
}


def _apply_prefer(
    candidates: list[Any],
    *,
    prefer_provider: str | None,
    prefer_source: str | None,
) -> list[Any]:
    """Stable-reorder candidates so the (provider, source) matching the
    caller's preference comes first.

    PR-TOOL-EXEC-CONTEXT (2026-05-28). The AgenticLoop already resolved
    an adapter for its main LLM dispatch; LLM-touching tools called
    inside that loop pass the loop's ``(provider, source)`` as a
    preference so dispatch keeps the operator's single ``/login``
    choice consistent across the main path and the tool calls.

    Empty / ``None`` preference falls through to the default
    provider-priority + per-provider source preference order built by
    :func:`_capability_candidates`. Partial preferences are honoured —
    e.g. only ``prefer_provider`` set still floats the chosen provider's
    candidates ahead, but their internal (source) order is the dispatch
    default.
    """
    if not prefer_provider and not prefer_source:
        return candidates

    def _rank(adapter: Any) -> int:
        # Exact provider+source match wins, then provider-only, then source-only,
        # then everything else. Stable sort preserves the dispatch default
        # ordering within each rank bucket.
        if prefer_provider and adapter.provider == prefer_provider:
            if prefer_source and adapter.source == prefer_source:
                return 0
            return 1
        if prefer_source and adapter.source == prefer_source:
            return 2
        return 3

    return sorted(candidates, key=_rank)


def _capability_candidates(
    capability_attr: str,
    *,
    provider_order: tuple[str, ...] = ("anthropic", "openai", "glm"),
) -> list[Any]:
    """Enumerate registered adapters advertising the named capability flag
    (e.g. ``"supports_web_search"``), ordered by provider priority + operator
    source preference within each provider.

    Returns ``list[Any]`` deliberately — callers narrow via the matching
    capability Protocol's mixin methods at the call site. Returning the
    capability-typed list would require a TypeVar bound to a runtime_checkable
    Protocol, which mypy rejects as ``Only concrete class can be given``.

    Codex MCP audit (2026-05-28) — both the ``supports_*`` flag AND the
    matching async method must be present. A flag-set / method-missing
    adapter would raise ``AttributeError`` mid-dispatch and that error
    would be classified as transient, silently masking the contract bug.
    The ``_CAPABILITY_METHOD`` lookup guards both halves.
    """
    method_name = _CAPABILITY_METHOD.get(capability_attr, "")
    by_provider: dict[str, list[Any]] = {}
    for adapter in list_adapters():
        if not getattr(adapter, capability_attr, False):
            continue
        if method_name and not callable(getattr(adapter, method_name, None)):
            log.warning(
                "%s advertises %s=True but lacks callable %s() — skipping. "
                "Adapter contract bug: both flag AND method are required.",
                getattr(adapter, "name", repr(adapter)),
                capability_attr,
                method_name,
            )
            continue
        by_provider.setdefault(adapter.provider, []).append(adapter)
    ordered: list[Any] = []
    for provider in provider_order:
        candidates = by_provider.get(provider, [])
        if not candidates:
            continue
        source_pref = _source_preference(provider)
        candidates.sort(
            key=lambda a: source_pref.index(a.source) if a.source in source_pref else 99
        )
        ordered.extend(candidates)
    # Trailing providers not in the priority list (future plugins) — append
    # in registration order so they remain reachable.
    for provider, candidates in by_provider.items():
        if provider not in provider_order:
            ordered.extend(candidates)
    return ordered


# ---------------------------------------------------------------------------
# web_search — replaces the 3-provider direct-SDK chain in ``web_tools.py``
# ---------------------------------------------------------------------------


async def web_search_via_adapters(
    query: str,
    *,
    max_results: int = 5,
    prefer_provider: str | None = None,
    prefer_source: str | None = None,
) -> WebSearchResult:
    """Route a web-search request through the adapter registry.

    Iterates web-search-capable adapters in (provider × source) priority and
    returns the first success. Error precedence on exhausted candidates:

    1. If ANY candidate hit billing-fatal (no candidate succeeded), surface
       that :class:`BillingError` — operator's actionable next step is to
       add credits or switch credential source. This includes the
       "mixed billing + transient" case: billing wins because (a) the
       operator can act on it immediately and (b) the transient may
       resolve once the billing is fixed.
    2. Otherwise (all transient), wrap the last transient in
       :class:`AdapterDispatchError`.

    This replaces the 6× silent-retry pattern that the legacy
    ``web_tools.py`` would have done — operator sees one actionable error.

    PR-TOOL-EXEC-CONTEXT (2026-05-28) — ``prefer_provider`` /
    ``prefer_source`` come from the AgenticLoop's resolved LLM identity
    via :class:`core.tools.base.ToolContext`. When set, the candidate
    matching (provider, source) is tried first, with fallbacks still
    iterated on failure — so an operator running on Claude OAuth
    subscription gets web_search on the same subscription instead of
    independently re-resolving to PAYG.
    """
    candidates = _apply_prefer(
        _capability_candidates("supports_web_search"),
        prefer_provider=prefer_provider,
        prefer_source=prefer_source,
    )
    if not candidates:
        raise AdapterDispatchError(
            "web_search: no registered adapter advertises supports_web_search=True"
        )
    last_billing: BillingError | None = None
    last_other: Exception | None = None
    for adapter in candidates:
        try:
            result: WebSearchResult = await adapter.aweb_search(query, max_results=max_results)
            log.debug("web_search_via_adapters: success via %s", adapter.name)
            return result
        except BillingError as exc:
            last_billing = exc
            log.debug("web_search_via_adapters: billing-fatal on %s: %s", adapter.name, exc)
            continue
        except Exception as exc:
            if is_billing_fatal(exc):
                last_billing = BillingError(
                    str(exc),
                    provider=adapter.provider,
                    plan_id="",
                    plan_display_name=adapter.name,
                )
                log.debug(
                    "web_search_via_adapters: classified billing on %s: %s", adapter.name, exc
                )
                continue
            last_other = exc
            log.debug("web_search_via_adapters: transient on %s: %s", adapter.name, exc)
            continue
    if last_billing is not None:
        raise last_billing
    raise AdapterDispatchError(
        f"web_search: all {len(candidates)} web-search-capable adapters failed. "
        f"Last error: {last_other!r}"
    )


# ---------------------------------------------------------------------------
# text_completion — replaces direct SDK calls in compaction / extraction
# ---------------------------------------------------------------------------


async def complete_text_via_adapters(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    max_tokens: int = 1024,
    provider_order: tuple[str, ...] = ("anthropic", "openai", "glm"),
    model_by_provider: dict[str, str] | None = None,
    prefer_provider: str | None = None,
    prefer_source: str | None = None,
) -> TextCompletionResult:
    """Route a single-turn text-completion request through the adapter registry.

    Used by conversation compaction + learning extraction — single LLM round-
    trip, no tool use, no streaming. Same billing-fatal vs transient
    distinction as :func:`web_search_via_adapters`.

    Model selection (Codex MCP audit 2026-05-28, PR-EXTRACT-LEARNING-MODELS-
    ADAPTER) — three layers, most specific first:

    1. ``model_by_provider[adapter.provider]`` — per-provider override; the
       caller knows which model to ask each provider for (e.g.
       ``{"glm": "glm-4.7-flash", "anthropic": ANTHROPIC_BUDGET}``).
    2. ``model`` — single model id; passed to every candidate. Use only
       when the caller is confident every fallback adapter accepts it
       (e.g. the model is a no-op string that each adapter ignores).
    3. ``""`` (empty) — each adapter's ``acomplete_text`` falls back to
       its own primary (``ANTHROPIC_PRIMARY``, ``OPENAI_PRIMARY``, etc.).

    Without per-provider mapping the fallback chain becomes a foot-gun:
    passing ``model="glm-4.7-flash"`` to the Anthropic adapter (because GLM
    failed) makes Anthropic call its API with ``model=glm-4.7-flash`` and
    fail. Callers should pass ``model_by_provider`` when fallback across
    providers is intended.

    PR-TOOL-EXEC-CONTEXT (2026-05-28) — ``prefer_provider`` /
    ``prefer_source`` parameters mirror :func:`web_search_via_adapters`
    so future LLM-backed tools (web_extract / web_crawl / summarise) can
    pass the AgenticLoop's resolved adapter forward and stay on the
    operator's chosen credential surface. Current hook / extraction
    callers leave them ``None`` because they live outside the tool
    dispatch flow.
    """
    candidates = _apply_prefer(
        _capability_candidates("supports_text_completion", provider_order=provider_order),
        prefer_provider=prefer_provider,
        prefer_source=prefer_source,
    )
    if not candidates:
        raise AdapterDispatchError(
            "complete_text: no registered adapter advertises supports_text_completion=True"
        )
    last_billing: BillingError | None = None
    last_other: Exception | None = None
    overrides = model_by_provider or {}
    for adapter in candidates:
        chosen_model = overrides.get(adapter.provider, model)
        try:
            text_result: TextCompletionResult = await adapter.acomplete_text(
                prompt, system=system, model=chosen_model, max_tokens=max_tokens
            )
            log.debug("complete_text_via_adapters: success via %s", adapter.name)
            return text_result
        except BillingError as exc:
            last_billing = exc
            continue
        except Exception as exc:
            if is_billing_fatal(exc):
                last_billing = BillingError(
                    str(exc),
                    provider=adapter.provider,
                    plan_id="",
                    plan_display_name=adapter.name,
                )
                continue
            last_other = exc
            continue
    if last_billing is not None:
        raise last_billing
    raise AdapterDispatchError(
        f"complete_text: all {len(candidates)} text-completion-capable adapters failed. "
        f"Last error: {last_other!r}"
    )


__all__ = [
    "AdapterDispatchError",
    "complete_text_via_adapters",
    "web_search_via_adapters",
]
