"""Provider resolution — Plan-aware routing for LLM call dispatch.

Wraps ``resolve_routing(model)`` so the LLM call dispatch sees the
actually-routed provider (e.g. ``openai-codex`` when a Plus OAuth Plan is
registered) instead of the static ``_resolve_provider`` mapping.
"""

from __future__ import annotations

import logging

from core.config import _resolve_provider

log = logging.getLogger(__name__)


def _route_provider(model: str) -> str:
    """Resolve the provider for a model, honoring registered Plans.

    v0.52.4 — wraps ``resolve_routing(model)`` so the LLM call dispatch
    sees the actually-routed provider (e.g. ``openai-codex`` when a Plus
    OAuth Plan is registered) instead of the static
    ``_resolve_provider`` mapping (which always returned ``openai`` for
    ``gpt-5.4`` regardless of OAuth state). Falls back to the static
    resolver when no Plan is registered.

    Caller flow unchanged: dispatch sees a provider string and looks up
    the client via ``_get_provider_client(provider)``. The credential
    lookup inside each provider client (``_get_codex_client`` etc.) now
    consults the same ProfileStore, so the path is end-to-end coherent.
    """
    try:
        from core.llm.routing.plan_registry import resolve_routing

        target = resolve_routing(model)
        if target is not None:
            return target.plan.provider
    except Exception:
        log.debug("resolve_routing failed for model=%s", model, exc_info=True)
    return _resolve_provider(model)
