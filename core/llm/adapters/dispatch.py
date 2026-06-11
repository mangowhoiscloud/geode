"""Central dispatch — strict single-adapter routing.

PR-NO-FALLBACK (2026-05-28). Replaces the prior fallback-chain pattern
that silently walked PAYG → Subscription, Anthropic → OpenAI → GLM until
something succeeded. The operator's explicit ``/login source`` choice is
the **sole** switch — silent cross-provider / cross-source fallback
exposes the operator to unexpected billing (a Codex-subscription user
should never have web_search silently land on a GLM coding plan they
happen to have configured for a different workflow).

Each dispatch call:

1. **Selects exactly one adapter** via:

   a. ``(prefer_provider, prefer_source)`` when both given — the
      AgenticLoop's resolved adapter identity (via
      :class:`core.tools.base.ToolContext` from PR-TOOL-EXEC-CONTEXT).
      An exact ``(provider, source)`` match is required; partial /
      unmatched preferences raise :class:`AdapterUnavailableError`.
   b. Operator's default-resolved adapter (``infer_source`` + provider
      order) when no preference — for hook / compaction callers
      outside the tool-dispatch flow.

2. **Tries that single adapter — and only that adapter.** No fallback to
   other adapters even on failure. One exception class gets a bounded
   SAME-adapter re-attempt: connection-class transport errors (broken
   pooled connection in the long-lived daemon) retry once on a fresh
   connection — see the "Connection-transient retry policy" section.
   Billing-fatal errors are never retried.

3. **On failure** → raises a structured error with an honest hint
   listing all three credential-source switch options (subscription,
   PAYG, agent-CLI) so the operator can make an informed manual switch:

   - :class:`BillingError`: credit / quota exhausted on this source.
   - :class:`AdapterUnavailableError`: no adapter registered matches.
   - :class:`AdapterDispatchError`: transient error from the single
     attempt.

Observability — every attempt fires
:attr:`core.hooks.HookEvent.ADAPTER_DISPATCH_ATTEMPT` and logs at INFO
level with adapter name, capability, outcome, elapsed time. The
structured ``attempt`` payload becomes a single row in serve logs /
journals so operators can trace exactly which adapter was tried.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from core.llm.adapters.base import (
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.adapters.registry import list_adapters
from core.llm.errors import BillingError, is_billing_fatal

log = logging.getLogger(__name__)


_DEFAULT_PROVIDER_ORDER: tuple[str, ...] = ("anthropic", "openai", "glm")


# ---------------------------------------------------------------------------
# Per-session adapter usage counter — PR-DISPATCH-OBS-EXT (2026-05-28)
# ---------------------------------------------------------------------------
#
# A ContextVar holding an ``{adapter_name: {outcome: count}}`` map. Set fresh
# at session start (via :func:`begin_session_adapter_tracking`), incremented
# inside :func:`_fire_attempt`, read at session end (via
# :func:`get_session_adapter_usage`) so the SESSION_ENDED hook payload can
# carry an aggregate breakdown of which adapter handled how many calls and
# with what outcome — the operator-facing answer to "what did this session
# actually route through" in one row, not N rows.
#
# Defaults to ``None`` so dispatches outside an AgenticLoop session (CLI
# helpers, tests, hooks running between sessions) silently skip the
# accumulation — the per-attempt hook + INFO log remain the universal
# observability surface.

_session_adapter_usage_ctx: ContextVar[dict[str, dict[str, int]] | None] = ContextVar(
    "session_adapter_usage", default=None
)


def begin_session_adapter_tracking() -> None:
    """Reset the session-scoped adapter usage counter.

    Called once by :class:`AgenticLoop` at session start so dispatch
    attempts during this session accumulate into a fresh dict that
    SESSION_ENDED can emit.
    """
    _session_adapter_usage_ctx.set({})


def get_session_adapter_usage() -> dict[str, dict[str, int]]:
    """Return the current session's adapter usage breakdown.

    Empty dict when called outside a tracked session — safe for callers
    that emit unconditionally.
    """
    counter = _session_adapter_usage_ctx.get()
    return dict(counter) if counter is not None else {}


def end_session_adapter_tracking() -> None:
    """Clear the per-session counter back to ``None`` (Codex MCP audit
    2026-05-28).

    Called by the lifecycle helper AFTER it has read the final breakdown
    via :func:`get_session_adapter_usage` so any stray dispatch that
    fires in the same context after session finalisation (background
    hook task, leaked async coroutine) does not mutate a stale counter
    that no longer corresponds to an active session.
    """
    _session_adapter_usage_ctx.set(None)


_SOURCE_SWITCH_HINT = (
    "Switch credential source explicitly via /login: "
    "/login source subscription | payg | cli. "
    "Automatic cross-provider / cross-source fallback is disabled "
    "(PR-NO-FALLBACK 2026-05-28) to prevent unintended billing."
)


# ---------------------------------------------------------------------------
# Structured error types — every error carries the attempted adapter so
# operators can see exactly what was tried.
# ---------------------------------------------------------------------------


class AdapterDispatchError(RuntimeError):
    """Raised when the single attempted adapter failed for a non-billing,
    non-availability reason (network, schema, etc.)."""

    def __init__(self, message: str, *, attempt: AdapterAttempt | None = None) -> None:
        super().__init__(message)
        self.attempt = attempt


class AdapterUnavailableError(RuntimeError):
    """Raised when no registered adapter satisfies the dispatch criteria.

    Two trigger conditions:

    - The capability flag is not advertised by any registered adapter
      (e.g. ``codex-cli`` does not currently expose web_search).
    - A preference ``(prefer_provider, prefer_source)`` was given but
      no registered adapter matches both.

    In both cases the operator's options are honest and finite — the
    error message lists every registered adapter so they know what
    sources are available to switch to.
    """


@dataclass(frozen=True, slots=True)
class AdapterAttempt:
    """One adapter try — emitted as ``ADAPTER_DISPATCH_ATTEMPT`` hook
    payload and surfaced in error messages so operators can correlate
    the failure to a specific (adapter, capability) pair.

    ``outcome`` is one of:

    - ``"success"`` — call returned a result.
    - ``"billing"`` — billing-fatal (quota / 402 / 401 / OAuth credit).
    - ``"transient"`` — connection / 5xx / schema-shape mismatch.
    - ``"unavailable"`` — adapter pre-flight check failed before the
      actual call (no credential, missing client, etc.).
    """

    adapter_name: str
    provider: str
    source: str
    capability: str
    outcome: str
    elapsed_ms: float
    error_type: str = ""
    error_msg: str = ""


# ---------------------------------------------------------------------------
# Adapter selection — strict (no fallback)
# ---------------------------------------------------------------------------


_CAPABILITY_METHOD: dict[str, str] = {
    "supports_web_search": "aweb_search",
    "supports_text_completion": "acomplete_text",
}


def _capability_adapters(capability_attr: str) -> list[Any]:
    """Enumerate adapters advertising the capability AND implementing the
    matching async method. A flag-set / method-missing adapter is dropped
    with a warning — that contract bug would otherwise present as a
    transient ``AttributeError`` at call time."""
    method_name = _CAPABILITY_METHOD.get(capability_attr, "")
    out: list[Any] = []
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
        out.append(adapter)
    return out


def _select_adapter(
    capability_attr: str,
    *,
    prefer_provider: str | None,
    prefer_source: str | None,
    provider_order: tuple[str, ...],
) -> Any | None:
    """Return exactly one adapter or ``None`` (strict — no fallback chain).

    Selection rule:

    - **Both** ``prefer_provider`` and ``prefer_source`` set: exact match
      required. No match → ``None`` (caller raises
      :class:`AdapterUnavailableError` with the available adapters list).
    - **Partial preference** (only one of the two set): treated identically
      to "no match" — strict mode never silently widens to a different
      provider or source. Returns ``None``. The AgenticLoop always supplies
      both via ``ToolContext``, so partial preference indicates a caller
      bug worth surfacing rather than papering over.
    - **Neither set** (hook / compaction / orphan callers): operator's
      default-resolved adapter — first provider in ``provider_order`` for
      which ``infer_source`` resolves to a registered capable adapter.

    Codex MCP audit (2026-05-28) — pre-PR partial preference fell
    through to the default-resolved path, which contradicted the
    docstring claim that partial preferences raise unavailable and was an
    uncovered widening surface.
    """
    capable = _capability_adapters(capability_attr)
    if not capable:
        return None

    # Partial-or-full preference path. Exact match required; partial =
    # missing-half = no match (strict mode never silently widens).
    if prefer_provider or prefer_source:
        if not (prefer_provider and prefer_source):
            return None
        for adapter in capable:
            if adapter.provider == prefer_provider and adapter.source == prefer_source:
                return adapter
        return None

    # Default-resolved path — operator settings + ProfileStore + provider order.
    from core.llm.adapters._source_inference import infer_source

    for provider in provider_order:
        provider_pool = [a for a in capable if a.provider == provider]
        if not provider_pool:
            continue
        resolved_source = infer_source(provider)
        for adapter in provider_pool:
            if adapter.source == resolved_source:
                return adapter
        # No exact source match for this provider's resolved source — refuse
        # to widen. Move to next provider in operator-configured order.
    return None


def _registered_adapter_summary() -> str:
    """One-line ``(provider/source, ...)`` listing for error messages so
    operators see what alternatives exist to switch to."""
    parts = [f"{a.name}({a.provider}/{a.source})" for a in list_adapters()]
    return ", ".join(parts) if parts else "<none registered>"


# ---------------------------------------------------------------------------
# Observability — per-attempt hook fire + INFO log
# ---------------------------------------------------------------------------


def _fire_attempt(attempt: AdapterAttempt) -> None:
    """Fire ``ADAPTER_DISPATCH_ATTEMPT`` hook + INFO log + accumulate
    per-session counter.

    Hook payload mirrors :class:`AdapterAttempt` fields so journal /
    serve-log writers see a single structured row per attempt. Hook
    failures must not poison dispatch — :func:`fire_hook` swallows
    handler errors at DEBUG; the surrounding try guards module-load
    edge cases (router hooks not yet wired).

    PR-DISPATCH-OBS-EXT (2026-05-28) — also increments the per-session
    ``_session_adapter_usage_ctx`` counter so SESSION_ENDED can surface
    an aggregate ``{adapter_name: {outcome: count}}`` breakdown without
    requiring the lifecycle helper to re-parse the per-attempt event
    stream.
    """
    counter = _session_adapter_usage_ctx.get()
    if counter is not None:
        bucket = counter.setdefault(attempt.adapter_name, {})
        bucket[attempt.outcome] = bucket.get(attempt.outcome, 0) + 1
    log.info(
        "dispatch[%s] %s (%s/%s) → %s in %.0fms%s",
        attempt.capability,
        attempt.adapter_name,
        attempt.provider,
        attempt.source,
        attempt.outcome,
        attempt.elapsed_ms,
        f" [{attempt.error_type}: {attempt.error_msg[:120]}]" if attempt.error_msg else "",
    )
    try:
        # The router's ``_hooks_ctx`` is the same HookSystem the agent
        # loop / tool executor write to — set once during runtime
        # bootstrap via ``set_router_hooks``. Reusing it keeps dispatch
        # observability in the same stream as LLM_CALL_* / TOOL_EXEC_*
        # events instead of standing up a parallel ContextVar.
        from core.hooks.dispatch import fire_hook
        from core.hooks.system import HookEvent
        from core.llm.router._hooks import _hooks_ctx

        fire_hook(
            _hooks_ctx,
            HookEvent.ADAPTER_DISPATCH_ATTEMPT,
            {
                "adapter_name": attempt.adapter_name,
                "provider": attempt.provider,
                "source": attempt.source,
                "capability": attempt.capability,
                "outcome": attempt.outcome,
                "elapsed_ms": attempt.elapsed_ms,
                "error_type": attempt.error_type,
                "error_msg": attempt.error_msg,
            },
        )
    except Exception as exc:
        log.debug("ADAPTER_DISPATCH_ATTEMPT hook fire failed: %s", exc)


# ---------------------------------------------------------------------------
# Connection-transient retry policy — PR-DISPATCH-TRANSIENT-RETRY (2026-06-11)
# ---------------------------------------------------------------------------
#
# Adapter-owned clients are built with ``max_retries=0``
# (core/llm/adapters/_anthropic_common.py) because the *app-level* retry in
# AgenticLoop covers ``acomplete``. ``web_search_via_adapters`` has no such
# outer retry, so a single broken pooled httpx connection in the long-lived
# serve daemon failed the next request in ~2-4ms as ``APIConnectionError``
# with no recovery (serve.log 2026-06-10 22:08/22:48/22:51 — sibling calls on
# fresh connections succeeded in 27-50s while the poisoned one insta-failed).
#
# Policy: retry the SAME adapter once when the failure is connection-class.
# This is NOT a fallback chain — PR-NO-FALLBACK semantics are preserved:
# never a different adapter, never a different (provider, source), and
# billing-fatal errors are never retried.

_CONNECTION_TRANSIENT_RETRIES = 1

# Matched by exception type NAME (not isinstance) so the policy covers both
# ``anthropic.APIConnectionError`` and raw ``httpx`` transport errors without
# importing either SDK here. Names checked across the __cause__/__context__
# chain, depth-limited to the first 4 links (see _cause_chain).
_CONNECTION_TRANSIENT_ERROR_NAMES: frozenset[str] = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "WriteError",
        "RemoteProtocolError",
    }
)


def _cause_chain(exc: BaseException, *, limit: int = 4) -> list[BaseException]:
    """Return ``exc`` plus its ``__cause__``/``__context__`` chain (cycle-safe)."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(chain) < limit:
        seen.add(id(cur))
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    return chain


def _is_connection_transient(exc: Exception) -> bool:
    """True when ``exc`` (or any link in its cause chain, depth-limited)
    is a connection-class transport error eligible for a same-adapter retry.

    Billing-fatal errors are categorically excluded — quota / credit
    failures must surface immediately (PR-NO-FALLBACK billing honesty).
    The billing check runs on EVERY chain link, not just the outer
    exception, so a connection-named wrapper around a billing-fatal root
    (``raise APIConnectionError(...) from quota_exc``) cannot smuggle a
    quota failure into the retry path (Codex MCP review 2026-06-11).
    """
    chain = _cause_chain(exc)
    for link in chain:
        if isinstance(link, BillingError):
            return False
        if isinstance(link, Exception) and is_billing_fatal(link):
            return False
    return any(type(link).__name__ in _CONNECTION_TRANSIENT_ERROR_NAMES for link in chain)


def _error_with_cause(exc: BaseException) -> str:
    """Format ``exc`` with its cause chain — ``APIConnectionError: Connection
    error. <- ReadError:`` — so serve logs show the transport-level root
    cause instead of the SDK's generic wrapper message."""
    return " <- ".join(f"{type(link).__name__}: {link}" for link in _cause_chain(exc))


# ---------------------------------------------------------------------------
# web_search — strict single-adapter dispatch
# ---------------------------------------------------------------------------


async def web_search_via_adapters(
    query: str,
    *,
    max_results: int = 5,
    prefer_provider: str | None = None,
    prefer_source: str | None = None,
) -> WebSearchResult:
    """Route a web-search request through the adapter registry, strictly
    using one adapter (no fallback chain).

    See module docstring for the selection rule + error contract.
    ``prefer_provider`` / ``prefer_source`` flow from the AgenticLoop via
    :class:`core.tools.base.ToolContext` (PR-TOOL-EXEC-CONTEXT) — when
    set, the exact (provider, source) match is required.
    """
    capability = "supports_web_search"
    adapter = _select_adapter(
        capability,
        prefer_provider=prefer_provider,
        prefer_source=prefer_source,
        provider_order=_DEFAULT_PROVIDER_ORDER,
    )
    if adapter is None:
        raise AdapterUnavailableError(
            f"web_search: no adapter registered matching "
            f"(provider={prefer_provider!r}, source={prefer_source!r}). "
            f"Registered adapters: {_registered_adapter_summary()}. " + _SOURCE_SWITCH_HINT
        )

    # Same-adapter retry on connection-class transients ONLY — see the
    # retry-policy section above. The loop exits via ``break`` (success) or
    # ``raise``; ``continue`` happens at most _CONNECTION_TRANSIENT_RETRIES
    # times because the final iteration cannot satisfy the retry guard.
    for try_no in range(_CONNECTION_TRANSIENT_RETRIES + 1):
        t0 = time.monotonic()
        try:
            result: WebSearchResult = await adapter.aweb_search(query, max_results=max_results)
        except BillingError as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            attempt = AdapterAttempt(
                adapter_name=adapter.name,
                provider=adapter.provider,
                source=adapter.source,
                capability=capability,
                outcome="billing",
                elapsed_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_msg=str(exc),
            )
            _fire_attempt(attempt)
            # Re-raise with adapter context attached so the tool layer can show
            # the operator exactly which credential was exhausted.
            billing = BillingError(
                f"{adapter.name} ({adapter.source}) credit exhausted: {exc}. "
                + _SOURCE_SWITCH_HINT,
                provider=adapter.provider,
                plan_id=getattr(exc, "plan_id", ""),
                plan_display_name=adapter.name,
                upgrade_url=getattr(exc, "upgrade_url", ""),
                resets_in_seconds=getattr(exc, "resets_in_seconds", 0),
            )
            raise billing from exc
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            if is_billing_fatal(exc):
                attempt = AdapterAttempt(
                    adapter_name=adapter.name,
                    provider=adapter.provider,
                    source=adapter.source,
                    capability=capability,
                    outcome="billing",
                    elapsed_ms=elapsed_ms,
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                )
                _fire_attempt(attempt)
                raise BillingError(
                    f"{adapter.name} ({adapter.source}) credit exhausted: {exc}. "
                    + _SOURCE_SWITCH_HINT,
                    provider=adapter.provider,
                    plan_id="",
                    plan_display_name=adapter.name,
                ) from exc
            attempt = AdapterAttempt(
                adapter_name=adapter.name,
                provider=adapter.provider,
                source=adapter.source,
                capability=capability,
                outcome="transient",
                elapsed_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_msg=_error_with_cause(exc),
            )
            _fire_attempt(attempt)
            if try_no < _CONNECTION_TRANSIENT_RETRIES and _is_connection_transient(exc):
                log.warning(
                    "web_search via %s (%s) hit a connection-class transient "
                    "(%s) after %.0fms — retrying the SAME adapter on a fresh "
                    "connection (retry %d/%d)",
                    adapter.name,
                    adapter.source,
                    _error_with_cause(exc),
                    elapsed_ms,
                    try_no + 1,
                    _CONNECTION_TRANSIENT_RETRIES,
                )
                await asyncio.sleep(0.1 * (try_no + 1))
                continue
            raise AdapterDispatchError(
                f"web_search via {adapter.name} ({adapter.source}) failed: "
                f"{_error_with_cause(exc)}. "
                f"No automatic fallback — {_SOURCE_SWITCH_HINT}",
                attempt=attempt,
            ) from exc
        break

    elapsed_ms = (time.monotonic() - t0) * 1000
    _fire_attempt(
        AdapterAttempt(
            adapter_name=adapter.name,
            provider=adapter.provider,
            source=adapter.source,
            capability=capability,
            outcome="success",
            elapsed_ms=elapsed_ms,
        )
    )
    # PR-DISPATCH-OBS-EXT (2026-05-28) — enrich the result with the selected
    # adapter's identity so the tool layer can surface it inline in
    # ``tool_exec_end`` metadata. Single-point enrichment avoids touching
    # every capability impl in :mod:`_capability_impls`.
    return dataclasses.replace(
        result,
        adapter_name=adapter.name,
        adapter_provider=adapter.provider,
        adapter_source=adapter.source,
    )


# ---------------------------------------------------------------------------
# text_completion — strict single-adapter dispatch
# ---------------------------------------------------------------------------


async def complete_text_via_adapters(
    prompt: str,
    *,
    system: str = "",
    model: str = "",
    max_tokens: int = 1024,
    provider_order: tuple[str, ...] = _DEFAULT_PROVIDER_ORDER,
    model_by_provider: dict[str, str] | None = None,
    prefer_provider: str | None = None,
    prefer_source: str | None = None,
) -> TextCompletionResult:
    """Route a single-turn text-completion request through the adapter
    registry — strict single-adapter dispatch, no fallback.

    Used by conversation compaction + learning extraction + context-
    exhausted message. ``model_by_provider`` retained for the per-adapter
    model override (e.g. ``{"glm": "glm-4.7-flash", "anthropic":
    ANTHROPIC_BUDGET}``) — applies to the single selected adapter; the
    pre-PR multi-adapter foot-gun (passing GLM's model to Anthropic in
    cross-provider fallback) is gone because there is no cross-provider
    fallback any more.

    ``prefer_provider`` / ``prefer_source`` flow from the AgenticLoop's
    :class:`core.tools.base.ToolContext` for tool-dispatch callers;
    hook / compaction callers (outside the tool flow) leave them ``None``
    and the dispatch resolves via operator's ``infer_source`` settings.
    """
    capability = "supports_text_completion"
    adapter = _select_adapter(
        capability,
        prefer_provider=prefer_provider,
        prefer_source=prefer_source,
        provider_order=provider_order,
    )
    if adapter is None:
        raise AdapterUnavailableError(
            f"complete_text: no adapter registered matching "
            f"(provider={prefer_provider!r}, source={prefer_source!r}). "
            f"Registered adapters: {_registered_adapter_summary()}. " + _SOURCE_SWITCH_HINT
        )

    overrides = model_by_provider or {}
    chosen_model = overrides.get(adapter.provider, model)
    # Same-adapter retry on connection-class transients ONLY — mirrors
    # web_search_via_adapters. Compaction / learning-extraction callers have
    # no app-level outer retry (unlike AgenticLoop's ``acomplete``), so the
    # same broken-pooled-connection failure mode applies here (serve.log
    # 2026-06-10 22:51 — reflection calls insta-failed twice, then succeeded).
    for try_no in range(_CONNECTION_TRANSIENT_RETRIES + 1):
        t0 = time.monotonic()
        try:
            result: TextCompletionResult = await adapter.acomplete_text(
                prompt, system=system, model=chosen_model, max_tokens=max_tokens
            )
        except BillingError as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            attempt = AdapterAttempt(
                adapter_name=adapter.name,
                provider=adapter.provider,
                source=adapter.source,
                capability=capability,
                outcome="billing",
                elapsed_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_msg=str(exc),
            )
            _fire_attempt(attempt)
            raise BillingError(
                f"{adapter.name} ({adapter.source}) credit exhausted: {exc}. "
                + _SOURCE_SWITCH_HINT,
                provider=adapter.provider,
                plan_id=getattr(exc, "plan_id", ""),
                plan_display_name=adapter.name,
                upgrade_url=getattr(exc, "upgrade_url", ""),
                resets_in_seconds=getattr(exc, "resets_in_seconds", 0),
            ) from exc
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            if is_billing_fatal(exc):
                _fire_attempt(
                    AdapterAttempt(
                        adapter_name=adapter.name,
                        provider=adapter.provider,
                        source=adapter.source,
                        capability=capability,
                        outcome="billing",
                        elapsed_ms=elapsed_ms,
                        error_type=type(exc).__name__,
                        error_msg=str(exc),
                    )
                )
                raise BillingError(
                    f"{adapter.name} ({adapter.source}) credit exhausted: {exc}. "
                    + _SOURCE_SWITCH_HINT,
                    provider=adapter.provider,
                    plan_id="",
                    plan_display_name=adapter.name,
                ) from exc
            attempt = AdapterAttempt(
                adapter_name=adapter.name,
                provider=adapter.provider,
                source=adapter.source,
                capability=capability,
                outcome="transient",
                elapsed_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_msg=_error_with_cause(exc),
            )
            _fire_attempt(attempt)
            if try_no < _CONNECTION_TRANSIENT_RETRIES and _is_connection_transient(exc):
                log.warning(
                    "complete_text via %s (%s) hit a connection-class transient "
                    "(%s) after %.0fms — retrying the SAME adapter on a fresh "
                    "connection (retry %d/%d)",
                    adapter.name,
                    adapter.source,
                    _error_with_cause(exc),
                    elapsed_ms,
                    try_no + 1,
                    _CONNECTION_TRANSIENT_RETRIES,
                )
                await asyncio.sleep(0.1 * (try_no + 1))
                continue
            raise AdapterDispatchError(
                f"complete_text via {adapter.name} ({adapter.source}) failed: "
                f"{_error_with_cause(exc)}. "
                f"No automatic fallback — {_SOURCE_SWITCH_HINT}",
                attempt=attempt,
            ) from exc
        break

    elapsed_ms = (time.monotonic() - t0) * 1000
    _fire_attempt(
        AdapterAttempt(
            adapter_name=adapter.name,
            provider=adapter.provider,
            source=adapter.source,
            capability=capability,
            outcome="success",
            elapsed_ms=elapsed_ms,
        )
    )
    # PR-DISPATCH-OBS-EXT (2026-05-28) — mirror the web_search enrichment so
    # text-completion callers (compaction / extraction / context-exhausted)
    # can record which adapter handled the call without re-querying the
    # registry.
    return dataclasses.replace(
        result,
        adapter_name=adapter.name,
        adapter_provider=adapter.provider,
        adapter_source=adapter.source,
    )


__all__ = [
    "AdapterAttempt",
    "AdapterDispatchError",
    "AdapterUnavailableError",
    "begin_session_adapter_tracking",
    "complete_text_via_adapters",
    "end_session_adapter_tracking",
    "get_session_adapter_usage",
    "web_search_via_adapters",
]
