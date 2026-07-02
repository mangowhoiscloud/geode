"""Central model/provider catalogue helpers.

This module is the narrow domain boundary for model metadata that multiple
layers need: context windows, UI ``ModelSpec`` rows, and coarse capability
flags. Raw pricing/context data remains in ``model_pricing.toml``; OpenAI
wire-shape quirks remain in ``_openai_common``. Call sites should come here
instead of copying fallback context windows into adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config.routing_manifest import resolve_provider
from core.llm.adapters._openai_common import get_openai_model_spec
from core.llm.adapters.base import ModelSpec
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

DEFAULT_UNKNOWN_CONTEXT_WINDOW = 200_000


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
    "model_spec_for_adapter",
    "normalize_model_provider",
]
