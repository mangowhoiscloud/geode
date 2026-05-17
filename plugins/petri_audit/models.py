"""Model identifier mapping for Petri audit (P3-b-2 prep).

Bridges between GEODE's internal model IDs (``MODEL_PRICING`` keys in
``core/llm/token_tracker.py``) and ``inspect_ai``'s ``provider/model``
identifier convention. Used by ``runner.run_audit`` to translate user
input (``--judge sonnet-4-6``) into the form ``inspect eval`` expects
(``--model-role judge=anthropic/claude-sonnet-4-6``).

Mapping policy:

- Raw passthrough — input contains ``/`` → returned untouched.
  Escape hatch for ``openai-api/...``, ``anthropic/...:tier`` etc.
- ``claude-*``                → ``anthropic/<model>``      (inspect_ai native)
- ``gpt-*``, ``o3``, ``o4-mini`` → ``openai/<model>``       (inspect_ai native)
- ``glm-*``                  → ``geode/<model>``           (routed through our
  registered ``GeodeModelAPI`` because inspect_ai has no native GLM provider).
- target role                → ``geode/<model>`` regardless of family. The
  whole point of the audit is GEODE-as-a-system, so the target is always
  routed through ``GeodeModelAPI``; the user only chooses the *base* LLM.
"""

from __future__ import annotations

from core.llm.token_tracker import MODEL_PRICING

__all__ = [
    "AuditModelMappingError",
    "family_of",
    "is_oauth_routed",
    "list_audit_models",
    "same_family",
    "to_inspect_model",
    "to_inspect_target",
]


# P2-D (2026-05-17) — provider → family normalisation. ``family_of`` was
# the second hardcoded routing table after ``core.config._resolve_provider``;
# both now share ``core.config.routing_manifest``'s prefix table. ``family_of``
# adds a thin provider → family translation so the M1 family-mismatch guard
# in :mod:`plugins.petri_audit.optimize` stays conservative.
_PROVIDER_TO_FAMILY: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-codex": "openai",
    "glm": "zhipuai",
}


def family_of(model_id: str) -> str:
    """Return the LLM family ('anthropic' / 'openai' / 'zhipuai' / 'unknown').

    Used by :mod:`plugins.petri_audit.optimize` to enforce **M1 — Judge
    must not share a family with the generator** (mitigation against
    in-context reward hacking + self-preference bias).

    Raw provider-prefixed ids ("anthropic/...", "openai-api/...") are
    parsed by stripping the trailing segment and re-classifying the
    bare model id; "geode/<base>" routes through us so the family is
    that of the base model.

    P2-D: delegates to ``core.config.routing_manifest.resolve_provider``
    + a small provider → family normalisation table. Providers without
    a Petri family mapping (``google`` / ``deepseek`` / ``meta`` /
    ``alibaba``) collapse to ``"unknown"``.
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
    # — legacy family_of returned "unknown" for ids that matched no rule,
    # and the optimiser's M1 guard depends on that conservatism (an
    # unrecognised judge model must not silently be classified as
    # "openai" same-family with a gpt-* generator).
    rules = manifest.routing
    if base in rules.codex_only_models:
        provider = "openai-codex"
    elif any(base.endswith(s) for s in rules.codex_suffixes):
        provider = "openai-codex"
    else:
        provider = None
        for prefix, target in rules.prefixes.items():
            if base.startswith(prefix):
                provider = target
                break
    if provider is None:
        return "unknown"
    return _PROVIDER_TO_FAMILY.get(provider, "unknown")


def same_family(model_a: str, model_b: str) -> bool:
    """True when ``family_of(a) == family_of(b)`` and family is known.

    Two ``unknown`` ids are NOT treated as same-family — caller decides
    whether to fail-fast or accept the lower-confidence pair.
    """
    fam_a = family_of(model_a)
    fam_b = family_of(model_b)
    if fam_a == "unknown" or fam_b == "unknown":
        return False
    return fam_a == fam_b


class AuditModelMappingError(ValueError):
    """Raised when a model id cannot be mapped to an ``inspect_ai`` identifier."""


def to_inspect_model(geode_id: str, *, use_oauth: bool | None = None) -> str:
    """Map a GEODE model id to an ``inspect_ai`` ``provider/model`` identifier.

    Used for the ``auditor`` and ``judge`` Petri model-roles. The ``target``
    role uses :func:`to_inspect_target` instead because target is always
    routed through ``geode/...``.

    Raw passthrough: any string containing ``/`` is returned untouched —
    callers can pass ``anthropic/claude-haiku-4-5-20251001`` or
    ``openai-api/glm/glm-5.1`` directly when the alias rules don't fit.
    A user who explicitly pins ``openai/gpt-5.5`` stays on per-token
    PAYG; the OAuth re-routing happens only on bare ``gpt-*`` ids.

    **PR #6 (2026-05-14) — OAuth routing**: ``gpt-5.*`` ids (``gpt-5.5``,
    ``gpt-5.4``, ``gpt-5.4-mini``, ``gpt-5.3-codex``) re-route to
    ``openai-codex/<model>`` so judge / auditor calls consume ChatGPT
    Plus quota instead of per-token billing. ``use_oauth`` controls
    the auto-detect:

    - ``None`` (default) → auto-detect: re-route when a Codex OAuth
      token resolves, else fall back to ``openai/<model>``.
    - ``True`` → force OAuth re-route regardless (token must exist or
      ``OpenAICodexAPI.__init__`` will raise at call time).
    - ``False`` → keep the legacy ``openai/<model>`` mapping.

    ``o3`` / ``o4-mini`` are NOT covered by OAuth — they are not on
    the Codex backend's model catalogue, so they always stay on the
    per-token path.
    """
    if not geode_id:
        raise AuditModelMappingError("Empty model id")
    if "/" in geode_id:
        return geode_id

    family = family_of(geode_id)
    if family == "unknown":
        raise AuditModelMappingError(
            f"Unknown model id {geode_id!r}. Use a MODEL_PRICING key (claude-*, "
            f"gpt-*, o3, o4-mini, glm-*) or a raw 'provider/model' string."
        )

    source_override = _source_from_use_oauth(geode_id, family, use_oauth)

    # Cap 'auto' cascade for ids the family's OAuth backend can't serve
    # (e.g. o3 / o4-mini are not on the Codex catalogue) — force api_key
    # so the 'auto' expansion never lands on the OAuth source for them.
    if source_override is None and not _supports_oauth_for_family(geode_id, family):
        source_override = "api_key"

    # P1-G — credential_source layer handles settings → manifest default →
    # 'auto' cascade. Lazy import keeps this module loadable on the
    # bootstrap-free path (matches the existing _credential_source
    # helper's contract).
    from plugins.petri_audit.credential_source import (
        CredentialResolutionError,
        resolve_credential_source,
    )
    from plugins.petri_audit.manifest import load_manifest

    try:
        source = resolve_credential_source(family, override=source_override)
    except CredentialResolutionError:
        # No credential resolves — legacy behaviour returned the api_key
        # prefix anyway and let inspect_ai surface the env-var error at
        # call time. Preserve that.
        source = "api_key"

    manifest = load_manifest()
    try:
        adapter = manifest.get_adapter(family, source)
    except KeyError:
        adapter = manifest.get_adapter(family, "api_key")
    return f"{adapter.inspect_prefix}/{geode_id}"


def _supports_oauth_for_family(model: str, family: str) -> bool:
    """True when ``family`` has an OAuth path that serves this model id.

    Mirrors the legacy if/elif chain's behaviour — only ``gpt-5.*`` ids
    are eligible for the Codex backend on the OpenAI side; all claude-*
    ids are eligible on the Anthropic side; GLM / zhipuai have no OAuth.
    """
    if family == "anthropic":
        return model.startswith("claude-")
    if family == "openai":
        return model.startswith("gpt-5")
    return False


def _source_from_use_oauth(geode_id: str, family: str, use_oauth: bool | None) -> str | None:
    """Translate the legacy ``use_oauth`` flag to a manifest source override.

    ``None`` → no override (resolve_credential_source decides via its
    own cascade). ``False`` → ``api_key`` (legacy "stay on PAYG"
    semantics). ``True`` → the family's OAuth source key
    (``claude-cli`` / ``openai-codex``), capped to ids the Codex
    backend actually serves (``gpt-5.*``); other ids degrade to
    ``api_key`` so ``o3`` / ``o4-mini`` retain their legacy routing.
    """
    if use_oauth is None:
        return None
    if use_oauth is False:
        return "api_key"
    if family == "anthropic" and geode_id.startswith("claude-"):
        return "claude-cli"
    if family == "openai" and geode_id.startswith("gpt-5"):
        return "openai-codex"
    return "api_key"


def is_oauth_routed(inspect_id: str) -> bool:
    """True when an ``inspect_ai`` model id is routed through subscription OAuth.

    The cost estimator and audit-report renderer use this to zero out
    the per-token cost line for judge / auditor calls that hit ChatGPT
    Plus or Claude subscription quota instead of the PAYG endpoint.
    """
    return inspect_id.startswith(("openai-codex/", "claude-code/"))


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
    if "/" in geode_id:
        return geode_id
    return f"geode/{geode_id}"


def list_audit_models() -> list[tuple[str, str]]:
    """Return ``(geode_id, inspect_id)`` pairs for every catalog model.

    Powers ``--help`` output and the tool description. Catalog source is
    ``MODEL_PRICING`` so adding a model in ``token_tracker.py`` auto-flows
    here. Skips models whose family the mapping rules don't recognise
    (defensive — should be empty in practice).
    """
    pairs: list[tuple[str, str]] = []
    for geode_id in MODEL_PRICING:
        try:
            pairs.append((geode_id, to_inspect_model(geode_id)))
        except AuditModelMappingError:
            continue
    return pairs
