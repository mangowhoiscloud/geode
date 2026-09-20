"""Central model/provider catalogue helpers.

This module is the narrow domain boundary for model metadata that multiple
layers need: context windows, UI ``ModelSpec`` rows, and coarse capability
flags. Raw pricing/context data remains in ``model_pricing.toml``; OpenAI
wire-shape quirks remain in ``_openai_common``. Call sites should come here
instead of copying fallback context windows into adapters.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from core.config.routing_manifest import resolve_provider
from core.llm.adapters._openai_common import get_openai_model_spec
from core.llm.adapters.base import SOURCE_PAYG, SOURCE_SUBSCRIPTION, ModelSpec
from core.llm.errors import ModelSourceUnavailableError
from core.llm.model_capabilities import ANTHROPIC_TOOL_SEARCH_MODELS
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

DEFAULT_UNKNOWN_CONTEXT_WINDOW = 200_000

# Source-specific lifecycle, checked 2026-09-20 against
# https://learn.chatgpt.com/docs/models#deprecated-codex-models .
# This does not retire the same IDs from the Platform API, or rewrite pricing
# and historical evaluation records. GPT-5.5's 2026-10-14 retirement is future.
_UNAVAILABLE_CODEX_MODELS: dict[str, tuple[str, str]] = {
    "gpt-5.4": ("retired on 2026-08-31", "gpt-5.6-terra"),
    "gpt-5.4-mini": ("retired on 2026-08-31", "gpt-5.6-luna"),
    "gpt-5.2": ("deprecated", "gpt-5.6-sol"),
    "gpt-5.3-codex": ("deprecated", "gpt-5.6-sol"),
}
# Anthropic-operated API lifecycle, retrieved 2026-09-21 (all listed dates
# precede the 2026-09-20 audit snapshot). This does not assert partner-hosted
# retirement dates: https://platform.claude.com/docs/en/about-claude/model-deprecations .
# Keys include GEODE's historical bare IDs; dated snapshots and -latest aliases
# below normalize only to these exact retired families, never to a newer model.
_UNAVAILABLE_ANTHROPIC_API_MODELS: dict[str, tuple[str, str]] = {
    "claude-opus-4-1": ("retired on 2026-08-05", "claude-opus-4-8"),
    "claude-opus-4": ("retired on 2026-06-15", "claude-opus-4-8"),
    "claude-sonnet-4": ("retired on 2026-06-15", "claude-sonnet-4-6"),
    "claude-3-7-sonnet": ("retired on 2026-02-19", "claude-sonnet-4-6"),
    "claude-3-5-haiku": ("retired on 2026-02-19", "claude-haiku-4-5-20251001"),
    "claude-3-haiku": ("retired on 2026-04-20", "claude-haiku-4-5-20251001"),
    "claude-3-5-sonnet": ("retired on 2025-10-28", "claude-sonnet-4-6"),
    "claude-3-opus": ("retired on 2026-01-05", "claude-opus-4-8"),
    "claude-3-sonnet": ("retired on 2025-07-21", "claude-sonnet-4-6"),
    "claude-2.0": ("retired on 2025-07-21", "claude-opus-4-8"),
    "claude-2.1": ("retired on 2025-07-21", "claude-opus-4-8"),
}


def model_source_unavailable_reason(
    model_id: str, *, provider: str, source: str, base_url: str | None = None
) -> str | None:
    """Explain a documented source retirement, not account-level availability."""
    normalized = normalize_model_provider(provider)
    if normalized == "openai" and source == SOURCE_SUBSCRIPTION:
        retired = _UNAVAILABLE_CODEX_MODELS.get(model_id)
        source_label = "Codex with ChatGPT sign-in (subscription)"
        source_note = "Platform API availability is separate; "
    elif normalized == "anthropic" and source == SOURCE_PAYG:
        # GEODE passes an explicit API key, not an SDK credentials profile.
        # Its uncached client's endpoint is therefore env > SDK default. Call
        # sites holding a client must pass its actual URL: an existing client
        # does not change endpoint when the environment changes.
        endpoint = (
            base_url
            if base_url is not None
            else os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        )
        if urlsplit(endpoint).hostname != "api.anthropic.com":
            return None
        bare_id = re.sub(r"-\d{8}$", "", model_id.removesuffix("-latest"))
        retired = _UNAVAILABLE_ANTHROPIC_API_MODELS.get(bare_id)
        source_label = "the direct Anthropic API (payg)"
        source_note = "Partner-hosted lifecycle is separate; "
    else:
        return None
    if retired is None:
        return None
    status, replacement = retired
    return (
        f"{model_id} is {status} for {source_label}. "
        f"Select {replacement} explicitly. {source_note}"
        "GEODE will not switch models or billing sources automatically."
    )


def require_model_source_available(
    model_id: str, *, provider: str, source: str, base_url: str | None = None
) -> None:
    """Reject known retired source/model pairs without selecting a replacement."""
    reason = model_source_unavailable_reason(
        model_id, provider=provider, source=source, base_url=base_url
    )
    if reason is not None:
        raise ModelSourceUnavailableError(reason)


@dataclass(frozen=True, slots=True)
class ModelCatalogSpec:
    """Provider-normalised model metadata used across GEODE surfaces."""

    id: str
    provider: str
    context_window: int
    supports_thinking: bool
    supports_tool_search: bool = False


def normalize_model_provider(provider: str) -> str:
    """Collapse routing-only provider aliases to executable adapter providers."""
    return "openai" if provider == "openai-codex" else provider


def context_window_for(model_id: str, *, default: int = DEFAULT_UNKNOWN_CONTEXT_WINDOW) -> int:
    """Return the catalogued context window for ``model_id``."""
    return int(MODEL_CONTEXT_WINDOW.get(model_id, default))


def get_model_catalog_spec(model_id: str, provider: str | None = None) -> ModelCatalogSpec:
    """Resolve model metadata from the central catalogue.

    ``provider`` may be supplied by an adapter to avoid re-resolving. When
    omitted, routing rules identify the provider family. ``openai-codex`` is a
    routing/source distinction; executable capability semantics are OpenAI.
    """
    routed_provider = provider or resolve_provider(model_id)
    normalized = normalize_model_provider(routed_provider)
    context_window = context_window_for(model_id)

    supports_thinking = False
    supports_tool_search = False
    if normalized == "anthropic":
        supports_thinking = model_id.startswith("claude-")
        supports_tool_search = re.sub(r"-\d{8}$", "", model_id) in ANTHROPIC_TOOL_SEARCH_MODELS
    elif normalized == "openai":
        openai_spec = get_openai_model_spec(model_id)
        supports_thinking = openai_spec.reasoning_effort_values is not None
        supports_tool_search = openai_spec.supports_tool_search
    elif normalized == "glm":
        # The GLM adapter currently owns the thinking/reasoning toggle policy
        # separately and does not expose a user-facing effort surface.
        supports_thinking = False

    return ModelCatalogSpec(
        id=model_id,
        provider=normalized,
        context_window=context_window,
        supports_thinking=supports_thinking,
        supports_tool_search=supports_tool_search,
    )


def model_spec_for_adapter(
    model_id: str,
    *,
    label: str | None = None,
    provider: str | None = None,
    supports_tools: bool = True,
) -> ModelSpec:
    """Build the adapter-facing ``ModelSpec`` from catalog metadata."""
    spec = get_model_catalog_spec(model_id, provider)
    return ModelSpec(
        id=model_id,
        label=label or model_id,
        context_tokens=spec.context_window,
        supports_thinking=spec.supports_thinking,
        supports_tools=supports_tools,
    )


__all__ = [
    "DEFAULT_UNKNOWN_CONTEXT_WINDOW",
    "ModelCatalogSpec",
    "context_window_for",
    "get_model_catalog_spec",
    "model_source_unavailable_reason",
    "model_spec_for_adapter",
    "normalize_model_provider",
    "require_model_source_available",
]
