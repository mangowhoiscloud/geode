"""Petri audit manifest loader — declarative role × source × adapter schema.

Reads ``plugins/petri_audit/petri.plugin.toml`` into a validated pydantic
tree so the rest of the plugin (registry, /petri picker, to_inspect_model
router) operates on a single source-of-truth instead of hardcoded
if/elif chains.

Layers (mirroring TOML structure):

- :class:`RoleSpec` — per-role default model + allowed model set
- :class:`SourceSpec` — per-family default credential source + allowed sources
- :class:`AdapterSpec` — concrete (module, inspect_prefix, env vars) binding
- :class:`PetriManifest` — top-level container with cross-layer consistency

The loader does **not** import adapter modules — that stays lazy in
``plugins.petri_audit.adapters.__init__`` so the default ``uv sync``
(no ``[audit]`` extra) keeps cold-start clean.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "AdapterSpec",
    "PetriManifest",
    "RoleContract",
    "RoleSpec",
    "SourceSpec",
    "load_manifest",
    "parse_role_contract",
]

DEFAULT_MANIFEST_PATH = Path(__file__).parent / "petri.plugin.toml"

# "auto" is a sentinel — resolved at binding time via
# ``settings.{family}_credential_source`` + keychain probe — so it
# never appears as a concrete adapter key.
AUTO_SOURCE = "auto"


class RoleSpec(BaseModel):
    """Per-role default + allowed model set + contract path."""

    default_model: str
    allowed_models: list[str]
    role_contract: str | None = None

    @model_validator(mode="after")
    def _default_in_allowed(self) -> RoleSpec:
        if self.default_model not in self.allowed_models:
            raise ValueError(
                f"default_model {self.default_model!r} not in allowed_models {self.allowed_models}"
            )
        return self


class SourceSpec(BaseModel):
    """Per-family default credential source + allowed source set."""

    default: str
    allowed: list[str]

    @model_validator(mode="after")
    def _default_in_allowed(self) -> SourceSpec:
        if self.default not in self.allowed:
            raise ValueError(f"source default {self.default!r} not in allowed {self.allowed}")
        return self


class AdapterSpec(BaseModel):
    """Concrete adapter binding for a (family, source) pair.

    ``module`` — dotted import path; loaded lazily by the adapter registry.
    ``inspect_prefix`` — prefix that ``to_inspect_model`` emits (e.g.
    ``anthropic/<model>``, ``claude-code/<model>``, ``openai-codex/<model>``,
    ``geode/<model>``).
    ``auth_env_vars`` — env vars consulted for credentials; used by the
    /petri picker to flag missing credentials.
    ``endpoint`` / ``binary`` — adapter-specific extras (HTTP base URL,
    CLI executable name).
    """

    module: str
    inspect_prefix: str
    auth_env_vars: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    binary: str | None = None


class PetriManifest(BaseModel):
    """Top-level manifest container with cross-layer consistency checks."""

    enabled_roles: list[str]
    roles: dict[str, RoleSpec]
    sources: dict[str, SourceSpec]
    adapters: dict[str, dict[str, AdapterSpec]]

    @model_validator(mode="after")
    def _consistency(self) -> PetriManifest:
        # 1. role list <-> role spec coverage
        if set(self.enabled_roles) != set(self.roles):
            raise ValueError(
                f"enabled_roles {self.enabled_roles} != role spec keys {sorted(self.roles)}"
            )
        # 2. every (family, source) in source.allowed has an adapter
        #    (excluding the "auto" sentinel — resolved at binding time)
        for family, source_spec in self.sources.items():
            family_adapters = self.adapters.get(family, {})
            for source in source_spec.allowed:
                if source == AUTO_SOURCE:
                    continue
                if source not in family_adapters:
                    raise ValueError(
                        f"family={family} source={source} listed in "
                        f"[petri.source.{family}].allowed but no adapter at "
                        f"[petri.adapter.{family}.{source}]"
                    )
        return self

    # ── Accessors (used by registry / picker / router) ────────────────────

    def get_role(self, role: str) -> RoleSpec:
        if role not in self.roles:
            raise KeyError(f"Unknown petri role {role!r}; enabled={self.enabled_roles}")
        return self.roles[role]

    def get_source(self, family: str) -> SourceSpec:
        if family not in self.sources:
            raise KeyError(f"Unknown petri family {family!r}; known={sorted(self.sources)}")
        return self.sources[family]

    def get_adapter(self, family: str, source: str) -> AdapterSpec:
        if source == AUTO_SOURCE:
            raise ValueError(
                "Cannot resolve adapter for 'auto' — caller must resolve to a "
                "concrete source first (e.g. via credential_source.resolve)"
            )
        family_adapters = self.adapters.get(family, {})
        if source not in family_adapters:
            raise KeyError(
                f"No adapter for family={family} source={source}; "
                f"known sources for this family={sorted(family_adapters)}"
            )
        return family_adapters[source]

    def get_role_contract(self, role: str, *, base_dir: Path | None = None) -> RoleContract:
        """Parse and validate the role contract MD for ``role``.

        ``base_dir`` defaults to the directory holding the manifest TOML;
        relative ``role_contract`` paths in the manifest resolve against it.
        Raises ``ValueError`` on frontmatter / manifest mismatch.
        """
        spec = self.get_role(role)
        if not spec.role_contract:
            raise ValueError(f"role {role!r} has no role_contract path in manifest")
        base = base_dir or DEFAULT_MANIFEST_PATH.parent
        contract_path = (base / spec.role_contract).resolve()
        contract = parse_role_contract(contract_path)
        if contract.role != role:
            raise ValueError(
                f"{contract_path}: frontmatter role={contract.role!r} != manifest key {role!r}"
            )
        if contract.default_model != spec.default_model:
            raise ValueError(
                f"{contract_path}: frontmatter default_model="
                f"{contract.default_model!r} != manifest default_model="
                f"{spec.default_model!r}"
            )
        if contract.default_model not in spec.allowed_models:
            raise ValueError(
                f"{contract_path}: default_model={contract.default_model!r} "
                f"not in manifest allowed_models {spec.allowed_models}"
            )
        return contract


class RoleContract(BaseModel):
    """Parsed YAML frontmatter from a `roles/<role>.md` contract file.

    The contract MD is human-readable documentation + machine-readable
    metadata; runtime authority remains with the manifest. This schema
    enforces frontmatter shape so a malformed contract is caught at
    load time, not when /petri picker reads ``description``.
    """

    role: str
    description: str
    default_model: str
    default_source: str
    inline_skills: list[str] = Field(default_factory=list)


def parse_role_contract(path: Path) -> RoleContract:
    """Parse a role contract MD's YAML frontmatter.

    Expected layout::

        ---
        role: ...
        description: ...
        ---

        # Body (markdown — ignored by this parser)

    Raises :class:`ValueError` when the file is missing a frontmatter
    block, the YAML is not a mapping, or required fields are absent.
    """
    import yaml  # lazy — only role contract loading triggers it

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: missing YAML frontmatter (file must start with '---')")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: malformed frontmatter — expected '---\\n...\\n---\\n' block")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise ValueError(f"{path}: frontmatter is not a YAML mapping (got {type(data).__name__})")
    return RoleContract(**data)


def _parse_manifest_dict(data: dict[str, Any]) -> PetriManifest:
    """Build a :class:`PetriManifest` from the parsed TOML dict.

    Split out so tests can feed dict literals without round-tripping through
    a TOML file.
    """
    petri = data.get("petri")
    if not petri:
        raise ValueError("Manifest missing [petri] root section")
    return PetriManifest(
        enabled_roles=petri.get("enabled_roles", []),
        roles={k: RoleSpec(**v) for k, v in petri.get("role", {}).items()},
        sources={k: SourceSpec(**v) for k, v in petri.get("source", {}).items()},
        adapters={
            family: {src: AdapterSpec(**v) for src, v in srcs.items()}
            for family, srcs in petri.get("adapter", {}).items()
        },
    )


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> PetriManifest:
    data = tomllib.loads(Path(path_str).read_text(encoding="utf-8"))
    return _parse_manifest_dict(data)


def load_manifest(path: Path | str | None = None) -> PetriManifest:
    """Load and validate the Petri manifest at ``path``.

    Defaults to :data:`DEFAULT_MANIFEST_PATH`. Results are cached per absolute
    path (max 4 entries) so repeated callers (registry, picker, router) share
    the parsed tree.
    """
    target = Path(path) if path is not None else DEFAULT_MANIFEST_PATH
    return _load_cached(str(target.resolve()))


def clear_manifest_cache() -> None:
    """Drop the lru_cache — used by tests that mutate manifest fixtures."""
    _load_cached.cache_clear()
