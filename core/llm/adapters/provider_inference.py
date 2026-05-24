"""Provider inference from model id (Codex / Anthropic / GLM / OpenAI).

Used by callers that pin a model (e.g. Petri audit target
``geode/gpt-5.5``) but did not pin a provider — without this helper,
:class:`AgenticLoop` falls back to its ``provider="anthropic"`` default
and the orchestration layer (GoalDecomposer, extract hooks) silent-fails
on ``ANTHROPIC_API_KEY`` when the OAuth-only environment never had one.

PR-MAINPATH-67 (2026-05-24) — extracted from the deleted ``_legacy``
module. The OAuth-routing logic survived the legacy adapter removal
because it serves the broader Provider routing surface (not just the
deleted ``AgenticLLMPort``).
"""

from __future__ import annotations


def infer_provider_from_model(model: str) -> str:
    """Return the provider key for a model id.

    Maps a GEODE / inspect_ai model identifier to a provider string used
    by :class:`AgenticLoop`'s ``provider=`` parameter.

    Rules:

    - ``gpt-*`` / ``o3`` / ``o4-mini`` → ``"openai-codex"`` when a
      Codex OAuth token is resolvable, else ``"openai"`` (PAYG path).
    - ``claude-*`` → ``"anthropic"``.
    - ``glm-*`` → ``"glm"``.
    - Provider-prefixed ids (``anthropic/...``, ``openai/...``,
      ``openai-codex/...``, ``geode/<base>``) — the prefix wins for
      ``openai-codex`` (OAuth-routed), otherwise the bare model id is
      reclassified by the provider rules above.

    The OAuth probe is read-only and tolerates a missing
    ``plugins.petri_audit`` package (the predicate lives there because
    the bridge is plugin-scoped). When the import fails the function
    falls back to the per-token ``openai`` path.
    """
    if not model:
        return "anthropic"

    raw_prefix = model.split("/", 1)[0] if "/" in model else ""
    if raw_prefix == "openai-codex":
        return "openai-codex"
    if raw_prefix == "anthropic":
        return "anthropic"
    if raw_prefix in ("openai", "openai-api"):
        return "openai"

    base = model.rsplit("/", 1)[-1]
    if base.startswith("claude-"):
        return "anthropic"
    if base.startswith("glm-"):
        return "glm"
    if base.startswith("gpt-") or base in ("o3", "o4-mini"):
        try:
            from plugins.petri_audit.codex_provider import is_codex_oauth_available

            if is_codex_oauth_available():
                return "openai-codex"
        except ImportError:
            pass
        return "openai"
    return "anthropic"


__all__ = ["infer_provider_from_model"]
