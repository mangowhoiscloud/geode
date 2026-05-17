"""GEODE routing manifest — declarative model / provider / credential routing.

Loads ``core/config/routing.toml`` (shipped default) merged with
``~/.geode/routing.toml`` (user override) into a validated pydantic
:class:`RoutingManifest`. Mirrors the Petri plugin's
:mod:`plugins.petri_audit.manifest` design — same 4-layer manifest
pattern (data → cross-layer consistency → cached load → typed
accessors).

P2-A scope: schema + loader only. Subsequent PRs (P2-B..E) migrate the
hardcoded constants in :mod:`core.config.__init__` (``ANTHROPIC_PRIMARY``
et al., ``_resolve_provider``, ``_PIPELINE_NODE_DEFAULTS``, onboarding
regexes) onto this loader. Until then this module is dormant — no
existing call site is rewired by P2-A.

Sections (mirroring TOML structure):

- :class:`ModelDefaults` — ``[model.defaults]`` provider → primary model
- :class:`ModelFallbacks` — ``[model.fallbacks]`` provider → fallback chain
- :class:`RoutingRules` — ``[routing.prefixes]`` + ``[routing]``
  codex_only_models, codex_suffixes, fallback_provider
- :class:`CredentialPatterns` — ``[credentials.patterns]`` regex → provider
- :class:`CredentialKeychain` — ``[credentials.keychain]`` per-provider
  macOS keychain service name
- :class:`RoutingManifest` — top-level container with consistency checks

User override semantics: ``~/.geode/routing.toml`` is merged section-by-
section over the shipped default. A user TOML that only specifies
``[model.defaults] anthropic = "claude-sonnet-4-6"`` overrides only that
single key, leaving every other shipped default intact.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "USER_OVERRIDE_PATH",
    "CredentialEnvVars",
    "CredentialKeychain",
    "CredentialPatterns",
    "ModelDefaults",
    "ModelFallbacks",
    "RoutingManifest",
    "RoutingRules",
    "clear_routing_manifest_cache",
    "load_routing_manifest",
    "resolve_provider",
]

DEFAULT_MANIFEST_PATH = Path(__file__).parent / "routing.toml"

# Re-export from `core.paths` (SoT) so the routing manifest's user
# override path stays aligned with every other ``~/.geode/`` file.
from core.paths import GLOBAL_ROUTING_TOML as USER_OVERRIDE_PATH  # noqa: E402

# ── Layer 1: model defaults ────────────────────────────────────────────────


class ModelDefaults(BaseModel):
    """``[model.defaults]`` — provider → primary model id.

    Both common providers (``anthropic`` / ``openai`` / ``codex`` /
    ``glm``) and aliases (``anthropic_secondary``, ``anthropic_budget``)
    live here. Aliases keep the legacy `ANTHROPIC_SECONDARY` /
    `ANTHROPIC_BUDGET` constants migratable without forcing every call
    site to learn a tier vocabulary.
    """

    anthropic: str
    anthropic_secondary: str | None = None
    anthropic_budget: str | None = None
    openai: str
    codex: str
    glm: str

    def get(self, key: str) -> str | None:
        """dict-like accessor — used by call sites that already address by
        string (e.g. lookups parameterised by provider name)."""
        return getattr(self, key, None)


# ── Layer 2: fallback chains ───────────────────────────────────────────────


class ModelFallbacks(BaseModel):
    """``[model.fallbacks]`` — provider → ordered fallback chain.

    Chain depth is governance-controlled (currently 2 per
    `core.config.__init__` doc; P2-B carries the same constraint into the
    manifest). The validator enforces that every chain's first element
    matches the corresponding default — so editing only the default
    surfaces the inconsistency early.
    """

    anthropic: list[str]
    openai: list[str]
    codex: list[str]
    glm: list[str]

    def get(self, key: str) -> list[str] | None:
        return getattr(self, key, None)


# ── Layer 3: routing rules ─────────────────────────────────────────────────


class RoutingRules(BaseModel):
    """``[routing.prefixes]`` + ``[routing]`` — provider resolution.

    Fields:

    - ``prefixes``: model-id prefix → provider mapping. First match wins.
    - ``codex_only_models``: bare model ids that route to ``openai-codex``
      regardless of the prefix table (gpt-5.5 etc. are OAuth-only per
      OpenAI's Codex models page).
    - ``codex_suffixes``: suffix match for ``*-codex`` / ``*-codex-max``
      / ``*-codex-mini`` ids.
    - ``fallback_provider``: last-resort when no rule matches. Preserves
      the legacy "openai" default from ``_resolve_provider``.
    """

    prefixes: dict[str, str] = Field(default_factory=dict)
    codex_only_models: list[str] = Field(default_factory=list)
    codex_suffixes: list[str] = Field(default_factory=list)
    fallback_provider: str = "openai"


# ── Layer 4: credentials ───────────────────────────────────────────────────


class CredentialPatterns(BaseModel):
    """``[credentials.patterns]`` — API-key regex → provider.

    Onboarding key wizard matches user input against these regexes to
    auto-detect the provider. Order is preserved (dict-ordered) so a
    more specific pattern can win when patterns prefix-overlap.
    """

    patterns: dict[str, str] = Field(default_factory=dict)


class CredentialKeychain(BaseModel):
    """``[credentials.keychain]`` — provider → macOS keychain service name.

    Used by ``plugins.petri_audit.claude_code_provider`` (and downstream
    code in P2-C migration) to locate the OAuth blob the local
    Claude / Codex / etc. CLI persists on login.
    """

    services: dict[str, str] = Field(default_factory=dict)


class CredentialEnvVars(BaseModel):
    """``[credentials.env_vars]`` — provider → env var name.

    Onboarding upserts the matched key into this env var. Separate
    section (rather than a 3-tuple per pattern) so the same env var
    can serve multiple patterns for one provider without duplication.
    """

    env_vars: dict[str, str] = Field(default_factory=dict)


# ── Top-level manifest ─────────────────────────────────────────────────────


class RoutingManifest(BaseModel):
    """Top-level container — composed pydantic tree with consistency checks."""

    defaults: ModelDefaults
    fallbacks: ModelFallbacks
    routing: RoutingRules
    credential_patterns: CredentialPatterns
    credential_keychain: CredentialKeychain
    credential_env_vars: CredentialEnvVars = Field(default_factory=CredentialEnvVars)

    @model_validator(mode="after")
    def _consistency(self) -> RoutingManifest:
        # 1) Every fallback chain's first element matches the corresponding
        # default — prevents drift between [model.defaults] and
        # [model.fallbacks] when only one is edited.
        for provider, chain in (
            ("anthropic", self.fallbacks.anthropic),
            ("openai", self.fallbacks.openai),
            ("codex", self.fallbacks.codex),
            ("glm", self.fallbacks.glm),
        ):
            if not chain:
                raise ValueError(f"fallback chain for {provider} is empty")
            default = self.defaults.get(provider)
            if default and chain[0] != default:
                raise ValueError(
                    f"fallback[{provider}][0]={chain[0]!r} != defaults.{provider}="
                    f"{default!r} (drift between [model.defaults] and "
                    f"[model.fallbacks.{provider}])"
                )
        # 2) Routing prefix targets reference known providers (light check
        # — we don't fail on unknown providers because new providers can
        # legitimately appear without a fallback chain yet; just guarantee
        # the value is a non-empty string).
        for prefix, provider in self.routing.prefixes.items():
            if not provider:
                raise ValueError(f"[routing.prefixes] {prefix!r} → empty provider")
        return self

    # ── Accessors ─────────────────────────────────────────────────────

    def get_default(self, provider: str) -> str | None:
        return self.defaults.get(provider)

    def get_fallback_chain(self, provider: str) -> list[str]:
        chain = self.fallbacks.get(provider)
        return list(chain) if chain else []


def _merge_section(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge override over base — used per-section."""
    merged = dict(base)
    merged.update(override)
    return merged


def _parse_manifest(data: dict[str, Any]) -> RoutingManifest:
    """Build a :class:`RoutingManifest` from the parsed TOML dict.

    Accepts the partial schema produced by section-level merge — the
    constructor's pydantic validators surface any missing required
    field with a precise error.
    """
    model_section = data.get("model", {})
    routing_section = data.get("routing", {})
    nodes_section = data.get("nodes", {})  # noqa: F841 — P2-E consumes
    credentials_section = data.get("credentials", {})

    defaults = ModelDefaults(**model_section.get("defaults", {}))
    fallbacks = ModelFallbacks(**model_section.get("fallbacks", {}))

    # The TOML expresses [routing.prefixes] (a nested table under [routing])
    # and bare [routing] scalars (codex_only_models etc.) — tomllib gives us
    # a single ``routing`` dict mixing both. Tease them apart.
    rules_kwargs: dict[str, Any] = {
        "prefixes": routing_section.get("prefixes", {}),
        "codex_only_models": routing_section.get("codex_only_models", []),
        "codex_suffixes": routing_section.get("codex_suffixes", []),
        "fallback_provider": routing_section.get("fallback_provider", "openai"),
    }
    rules = RoutingRules(**rules_kwargs)

    patterns = CredentialPatterns(patterns=credentials_section.get("patterns", {}))
    keychain = CredentialKeychain(services=credentials_section.get("keychain", {}))
    env_vars = CredentialEnvVars(env_vars=credentials_section.get("env_vars", {}))

    return RoutingManifest(
        defaults=defaults,
        fallbacks=fallbacks,
        routing=rules,
        credential_patterns=patterns,
        credential_keychain=keychain,
        credential_env_vars=env_vars,
    )


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _merge_routing_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Section-by-section merge of two parsed routing TOML dicts.

    Top-level sections (``model``, ``routing``, ``nodes``, ``credentials``)
    are deep-merged one level: every sub-table inside them is shallow-
    merged so a user file that only sets
    ``[model.defaults] anthropic = "claude-sonnet-4-6"`` overrides exactly
    that key without dropping the other defaults.
    """
    merged: dict[str, Any] = {}
    keys = set(base.keys()) | set(override.keys())
    for key in keys:
        base_section = base.get(key, {})
        override_section = override.get(key, {})
        if not isinstance(base_section, dict) or not isinstance(override_section, dict):
            merged[key] = override_section if key in override else base_section
            continue
        sub_merged: dict[str, Any] = {}
        sub_keys = set(base_section.keys()) | set(override_section.keys())
        for sub_key in sub_keys:
            bsv = base_section.get(sub_key)
            osv = override_section.get(sub_key)
            if isinstance(bsv, dict) and isinstance(osv, dict):
                sub_merged[sub_key] = _merge_section(bsv, osv)
            else:
                sub_merged[sub_key] = osv if sub_key in override_section else bsv
        merged[key] = sub_merged
    return merged


@lru_cache(maxsize=4)
def _load_cached(default_path_str: str, user_path_str: str | None) -> RoutingManifest:
    base = _read_toml(Path(default_path_str))
    override = _read_toml(Path(user_path_str)) if user_path_str else {}
    merged = _merge_routing_dicts(base, override) if override else base
    return _parse_manifest(merged)


def load_routing_manifest(
    default_path: Path | str | None = None,
    user_path: Path | str | None = None,
    *,
    use_user_override: bool = True,
) -> RoutingManifest:
    """Load + merge + validate the routing manifest.

    Defaults to ``core/config/routing.toml`` for the shipped default and
    ``~/.geode/routing.toml`` for the user override (if ``use_user_override``
    is True). Results cached by absolute path so repeated callers (resolver,
    onboarding, MCP) share the parsed tree.

    Tests that want a pristine load (no caching) call
    :func:`clear_routing_manifest_cache` first.
    """
    base = Path(default_path) if default_path is not None else DEFAULT_MANIFEST_PATH
    if use_user_override:
        user = Path(user_path) if user_path is not None else USER_OVERRIDE_PATH
        user_arg: str | None = str(user.resolve()) if user.exists() else None
    else:
        user_arg = None
    return _load_cached(str(base.resolve()), user_arg)


def clear_routing_manifest_cache() -> None:
    """Drop the lru_cache — used by tests that mutate routing.toml fixtures."""
    _load_cached.cache_clear()


# ── Convenience resolver (used by P2-D when wiring in) ─────────────────────


def resolve_provider(model: str, manifest: RoutingManifest | None = None) -> str:
    """Resolve a model id to its provider using the manifest's routing rules.

    Mirrors the legacy :func:`core.config._resolve_provider` behaviour:

    1. Codex-only models match first (e.g. gpt-5.5 → openai-codex).
    2. Codex suffixes (``*-codex`` etc.) → openai-codex.
    3. Prefix table — first matching prefix wins.
    4. Fallback provider (``openai`` by default).
    """
    m = manifest or load_routing_manifest()
    if model in m.routing.codex_only_models:
        return "openai-codex"
    for suffix in m.routing.codex_suffixes:
        if model.endswith(suffix):
            return "openai-codex"
    for prefix, provider in m.routing.prefixes.items():
        if model.startswith(prefix):
            return provider
    return m.routing.fallback_provider
