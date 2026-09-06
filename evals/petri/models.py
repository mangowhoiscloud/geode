"""Model identifier mapping for Petri audit (P3-b-2 prep).

Bridges between GEODE's internal model IDs (``MODEL_PRICING`` keys in
``core/llm/token_tracker.py``) and ``inspect_ai``'s ``provider/model``
identifier convention. Used by ``runner.run_audit`` to translate user
input (``--judge sonnet-4-6``) into the form ``inspect eval`` expects
(``--model-role judge=anthropic/claude-sonnet-4-6``).

Mapping policy:

- Raw identifiers pass through except retired Claude CLI prefixes, which
  fail before dispatch, and ``codex-cli/``, which normalizes to OpenAI OAuth.
  Other forms remain an escape hatch for ``openai-api/...``,
  ``anthropic/...:tier`` etc.
- ``claude-*``                → ``anthropic/<model>``      (inspect_ai native)
- ``gpt-*``, ``o3``, ``o4-mini`` → ``openai/<model>``       (inspect_ai native)
- ``glm-*``                  → ``geode/<model>``           (routed through our
  registered ``GeodeModelAPI`` because inspect_ai has no native GLM provider).
- target role                → ``geode/<model>`` regardless of provider. The
  whole point of the audit is GEODE-as-a-system, so the target is always
  routed through ``GeodeModelAPI``; the user only chooses the *base* LLM.
"""

from __future__ import annotations

import warnings

from core.llm.token_tracker import MODEL_PRICING

__all__ = [
    "AuditModelMappingError",
    "is_oauth_routed",
    "list_audit_models",
    "provider_of",
    "same_provider",
    "to_inspect_model",
    "to_inspect_target",
]


# P2-D (2026-05-17) — routing-provider → audit-provider normalisation.
# ``provider_of`` was the second hardcoded routing table after
# ``core.config._resolve_provider``; both now share
# ``core.config.routing_manifest``'s prefix table. ``provider_of`` adds a
# thin routing-provider → audit-provider translation (e.g. raw "glm" →
# Petri credential provider "zhipuai") so the M1 provider-mismatch guard
# in :mod:`evals.petri.optimize` stays conservative.
_ROUTING_TO_AUDIT_PROVIDER: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-codex": "openai",
    "glm": "zhipuai",
}


def provider_of(model_id: str) -> str:
    """Return the LLM provider ('anthropic' / 'openai' / 'zhipuai' / 'unknown').

    Used by :mod:`evals.petri.optimize` to enforce **M1 — Judge
    must not share a provider with the generator** (mitigation against
    in-context reward hacking + self-preference bias).

    Raw provider-prefixed ids ("anthropic/...", "openai-api/...") are
    parsed by stripping the trailing segment and re-classifying the
    bare model id; "geode/<base>" routes through us so the provider is
    that of the base model.

    P2-D: delegates to ``core.config.routing_manifest.resolve_provider``
    + a small routing-provider → audit-provider normalisation table.
    Providers without a Petri credential mapping (``google`` /
    ``deepseek`` / ``meta`` / ``alibaba``) collapse to ``"unknown"``.
    """
    if not model_id:
        return "unknown"
    base = model_id.rsplit("/", 1)[-1]
    if not base:
        return "unknown"
    try:
        from core.config.routing_manifest import load_routing_manifest

        manifest = load_routing_manifest()
    except Exception:
        return "unknown"
    # Walk codex_only_models / codex_suffixes / prefixes explicitly. We
    # deliberately do NOT fall through to the manifest's fallback_provider
    # — legacy provider_of returned "unknown" for ids that matched no rule,
    # and the optimiser's M1 guard depends on that conservatism (an
    # unrecognised judge model must not silently be classified as
    # "openai" same-provider with a gpt-* generator).
    rules = manifest.routing
    if base in rules.codex_only_models or any(base.endswith(s) for s in rules.codex_suffixes):
        provider: str | None = "openai-codex"
    else:
        provider = None
        for prefix, target in rules.prefixes.items():
            if base.startswith(prefix):
                provider = target
                break
    if provider is None:
        return "unknown"
    return _ROUTING_TO_AUDIT_PROVIDER.get(provider, "unknown")


def same_provider(model_a: str, model_b: str) -> bool:
    """True when ``provider_of(a) == provider_of(b)`` and provider is known.

    Two ``unknown`` ids are NOT treated as same-provider — caller decides
    whether to fail-fast or accept the lower-confidence pair.
    """
    fam_a = provider_of(model_a)
    fam_b = provider_of(model_b)
    if fam_a == "unknown" or fam_b == "unknown":
        return False
    return fam_a == fam_b


class AuditModelMappingError(ValueError):
    """Raised when a model id cannot be mapped to an ``inspect_ai`` identifier."""


def to_inspect_model(
    geode_id: str, *, use_oauth: bool | None = None, source: str | None = None
) -> str:
    """Map a GEODE model id to an ``inspect_ai`` ``provider/model`` identifier.

    Used for the ``auditor`` and ``judge`` Petri model-roles. The ``target``
    role uses :func:`to_inspect_target` instead because target is always
    routed through ``geode/...``.

    Raw passthrough: any supported string containing ``/`` is returned untouched —
    callers can pass ``anthropic/claude-haiku-4-5-20251001`` or
    ``openai-api/glm/glm-5.1`` directly when the alias rules don't fit.
    A user who explicitly pins ``openai/gpt-5.5`` stays on per-token
    PAYG; the OAuth re-routing happens only on bare ``gpt-*`` ids.

    ``use_oauth=None`` uses the credential resolver and the SIL PAYG fallback
    policy. ``True`` requests OpenAI OAuth; ``False`` explicitly selects the
    API-key route. A concrete ``source`` takes precedence over this flag.

    The current bare-id OAuth heuristic covers only ``gpt-5*`` names. A
    concrete subscription source pin bypasses that heuristic, not credential
    resolution. Other names require an explicit source or raw provider/model
    identifier; a mapping limitation is not proof of backend availability.
    """
    if not geode_id:
        raise AuditModelMappingError("Empty model id")
    if "/" in geode_id:
        if geode_id.startswith(("claude-code/", "claude-cli/")):
            from core.config.credential_source import CLAUDE_CLI_RETIRED_MESSAGE

            raise AuditModelMappingError(CLAUDE_CLI_RETIRED_MESSAGE)
        if geode_id.startswith("codex-cli/"):
            warnings.warn(
                "codex-cli/<model> is a legacy alias; use openai-codex/<model>",
                DeprecationWarning,
                stacklevel=2,
            )
            return f"openai-codex/{geode_id.removeprefix('codex-cli/')}"
        return geode_id

    provider = provider_of(geode_id)
    if provider == "unknown":
        raise AuditModelMappingError(
            f"Unknown model id {geode_id!r}. Use a MODEL_PRICING key (claude-*, "
            f"gpt-*, o3, o4-mini, glm-*) or a raw 'provider/model' string."
        )

    # PR-CRED-SOURCE-CENTRALIZE — an explicit per-role ``source``
    # (``[self_improving_loop.petri.<role>].source``) wins over the
    # use_oauth-derived default, so an operator who pins ``source = "api_key"``
    # for the auditor/judge actually routes there. ``auto`` (the unpinned
    # default) defers to use_oauth detection + the manifest cascade.
    from core.config.credential_source import CredentialSource

    if source and source != CredentialSource.AUTO:
        source_override: str | None = source
    else:
        source_override = _source_from_use_oauth(provider, use_oauth)

    # P1-G — credential_source layer handles settings → manifest default →
    # 'auto' cascade. Lazy import keeps this module loadable on the
    # bootstrap-free path (matches the existing _credential_source
    # helper's contract).
    from evals.petri.credential_source import (
        _settings_source,
        resolve_credential_source,
        self_improving_loop_fallback_policy,
    )
    from evals.petri.manifest import load_manifest

    fallback_to_payg = self_improving_loop_fallback_policy()
    pinned_source = (
        source if source and source != CredentialSource.AUTO else _settings_source(provider)
    )
    # A name heuristic is not billing authorization. Preserve its legacy
    # API-key mapping only when the operator permits PAYG fallback.
    if (
        fallback_to_payg
        and source_override is None
        and pinned_source is None
        and provider != "anthropic"
        and not _supports_oauth_for_provider(geode_id, provider)
    ):
        source_override = "api_key"

    source = resolve_credential_source(
        provider,
        override=source_override,
        fallback_to_payg=fallback_to_payg,
    )

    if (
        source == CredentialSource.OPENAI_CODEX
        and pinned_source != CredentialSource.OPENAI_CODEX
        and not _supports_oauth_for_provider(geode_id, provider)
    ):
        raise AuditModelMappingError(
            f"The current audit OAuth mapping does not cover {geode_id!r}. "
            "Select a concrete source or an explicit 'provider/model' identifier."
        )

    manifest = load_manifest()
    adapter = manifest.get_adapter(provider, source)
    return f"{adapter.inspect_prefix}/{geode_id}"


def _supports_oauth_for_provider(model: str, provider: str) -> bool:
    """Return this mapper's bare-id OAuth coverage, not backend entitlement."""
    if provider == "openai":
        return model.startswith("gpt-5")
    return False


def _source_from_use_oauth(provider: str, use_oauth: bool | None) -> str | None:
    """Translate the legacy ``use_oauth`` flag to a manifest source override.

    ``None`` → no override. ``False`` → ``api_key``. ``True`` selects
    OpenAI Codex OAuth; unmapped names fail after source resolution instead
    of authorizing PAYG. Other providers stay on ``api_key``.
    """
    if use_oauth is None:
        return None
    if use_oauth is False:
        return "api_key"
    if provider == "openai":
        return "openai-codex"
    return "api_key"


def is_oauth_routed(inspect_id: str) -> bool:
    """True when an ``inspect_ai`` model id is routed through subscription OAuth.

    The cost estimator and audit-report renderer use this to zero out
    the per-token cost line for judge / auditor calls that hit ChatGPT
    Plus quota or historical Claude subscription receipts instead of the PAYG
    endpoint.

    ``claude-code/`` and ``codex-cli/`` stay recognised only when reading
    historical eval IDs; new routing rejects those retired execution paths.
    """
    return inspect_id.startswith(("openai-codex/", "claude-code/", "claude-cli/", "codex-cli/"))


def to_inspect_target(geode_id: str | None) -> str:
    """Map a GEODE model id to a ``geode/<model>`` target identifier.

    Auto-prefixes ``geode/`` unless the input already contains ``/`` (raw
    passthrough). The Petri audit always routes the target through our
    registered ``GeodeModelAPI`` so the *whole* GEODE stack — agentic loop,
    tools, hooks, memory — is what gets evaluated; the user only picks the
    base LLM that GEODE will use internally for the run.

    **N6-followup**: ``None`` / empty string returns the
    ``geode/default`` sentinel, which ``GeodeModelAPI.generate`` reads
    as "caller did not pin a base — let GEODE's regular drift sync
    pick ``settings.model``". Pinned ids stay sticky for the audit's
    lifetime.
    """
    if not geode_id:
        return "geode/default"
    if geode_id.startswith(("claude-code/", "claude-cli/")):
        from core.config.credential_source import CLAUDE_CLI_RETIRED_MESSAGE

        raise AuditModelMappingError(CLAUDE_CLI_RETIRED_MESSAGE)
    if "/" in geode_id:
        return geode_id
    return f"geode/{geode_id}"


def list_audit_models() -> list[tuple[str, str]]:
    """Return ``(geode_id, inspect_id)`` pairs for every catalog model.

    Uses the manifest's API-key prefix for display only, without resolving
    credentials or billing policy. Execution still uses :func:`to_inspect_model`.
    Skips pricing keys whose provider the audit mapping does not recognise.
    """
    from evals.petri.manifest import load_manifest

    manifest = load_manifest()
    pairs: list[tuple[str, str]] = []
    for geode_id in MODEL_PRICING:
        provider = provider_of(geode_id)
        if provider == "unknown":
            continue
        adapter = manifest.get_adapter(provider, "api_key")
        pairs.append((geode_id, f"{adapter.inspect_prefix}/{geode_id}"))
    return pairs
