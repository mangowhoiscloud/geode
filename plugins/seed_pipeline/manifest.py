"""Seed pipeline manifest loader — declarative 7-role + 3-judge-panel schema.

Reads ``plugins/seed_pipeline/seed_pipeline.plugin.toml`` into a validated
pydantic tree. Source / adapter layers are intentionally NOT defined here
— they are reused from ``plugins/petri_audit/petri.plugin.toml`` (the
Petri manifest is the SOT for credential family/source binding). The
seed-pipeline manifest's voter rows are cross-validated against the
Petri source table at load time so a typo'd ``family`` or ``source`` is
caught immediately, not on first runtime use.

Layers (mirroring TOML structure):

- :class:`SeedRoleSpec` — per-role default model + allowed model set
- :class:`VoterSpec` — one (model, family, source) row in judge_panel
- :class:`JudgePanelSpec` — voters list + required_diversity_families gate
- :class:`SeedPipelineManifest` — top-level container with cross-layer +
  cross-manifest consistency checks

The loader does **not** import any LLM SDK or adapter module — manifest
parsing must remain cold-start clean so `geode version` does not pay the
seed-pipeline cost.

P1-P7 prevention checklist application (cycle-skill SKILL.md):

- **P4 Environment Anchor**: ``DEFAULT_MANIFEST_PATH`` is anchored at
  ``Path(__file__).parent / "seed_pipeline.plugin.toml"`` — package-
  relative, not cwd-relative. Same anchor pattern as Petri's manifest.
- **P7 Caller-Callee Contract**: voter source values are validated
  against ``petri_audit.manifest.PetriManifest.get_source(family).allowed``
  so a typo'd ``source = "claude_cli"`` (underscore vs hyphen) is
  caught at load time rather than at runtime when the picker tries
  to bind to a non-existent adapter.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "JudgePanelSpec",
    "SeedPipelineManifest",
    "SeedRoleSpec",
    "VoterSpec",
    "clear_manifest_cache",
    "load_manifest",
]

DEFAULT_MANIFEST_PATH = Path(__file__).parent / "seed_pipeline.plugin.toml"


class SeedRoleSpec(BaseModel):
    """Per-role default + allowed model set + contract path.

    Mirrors :class:`plugins.petri_audit.manifest.RoleSpec` but lives in the
    seed-pipeline domain — petri's RoleSpec validates against inspect_ai's
    ModelAPI prefixes, seed_pipeline's must validate against AgentDefinition
    paths (``.claude/agents/seed_*.md``).
    """

    default_model: str
    allowed_models: list[str]
    role_contract: str | None = None

    @model_validator(mode="after")
    def _default_in_allowed(self) -> SeedRoleSpec:
        if self.default_model not in self.allowed_models:
            raise ValueError(
                f"default_model {self.default_model!r} not in allowed_models {self.allowed_models}"
            )
        return self


class VoterSpec(BaseModel):
    """One voter row in the Ranker phase's judge panel.

    Fields:
    - ``model`` — the LLM model name (e.g. ``claude-sonnet-4-6``).
    - ``family`` — provider family (e.g. ``anthropic``, ``openai``); must
      match one of Petri's ``[petri.source.<family>]`` keys.
    - ``source`` — credential source (e.g. ``claude-cli``, ``openai-codex``,
      ``api_key``); must be in
      ``petri.source.<family>.allowed``. The ``auto`` sentinel is rejected
      here — judge voters require a concrete binding so the panel diversity
      check is meaningful.
    """

    model: str
    family: str
    source: str

    @model_validator(mode="after")
    def _source_not_auto(self) -> VoterSpec:
        if self.source == "auto":
            raise ValueError(
                f"voter ({self.model}, {self.family}) cannot use source=auto — "
                "judge panel diversity requires concrete bindings"
            )
        return self


class JudgePanelSpec(BaseModel):
    """Ranker phase's 3-voter panel + diversity gate."""

    voters: list[VoterSpec]
    required_diversity_families: int = 2

    @model_validator(mode="after")
    def _diversity(self) -> JudgePanelSpec:
        if len(self.voters) < 2:
            raise ValueError(f"judge panel requires >= 2 voters, got {len(self.voters)}")
        families = {v.family for v in self.voters}
        if len(families) < self.required_diversity_families:
            raise ValueError(
                f"judge panel diversity violated — voters span "
                f"{sorted(families)} ({len(families)} family/families) but "
                f"required_diversity_families={self.required_diversity_families}"
            )
        return self


class SeedPipelineManifest(BaseModel):
    """Top-level manifest container with cross-layer consistency checks."""

    enabled_roles: list[str]
    roles: dict[str, SeedRoleSpec]
    judge_panel: JudgePanelSpec

    @model_validator(mode="after")
    def _consistency(self) -> SeedPipelineManifest:
        if set(self.enabled_roles) != set(self.roles):
            raise ValueError(
                f"enabled_roles {self.enabled_roles} != role spec keys {sorted(self.roles)}"
            )
        return self

    # ── Accessors (used by S5.5 picker / S6 ranker / S11 CLI) ────────────

    def get_role(self, role: str) -> SeedRoleSpec:
        if role not in self.roles:
            raise KeyError(f"Unknown seed_pipeline role {role!r}; enabled={self.enabled_roles}")
        return self.roles[role]

    def list_voter_families(self) -> list[str]:
        return [v.family for v in self.judge_panel.voters]

    def voter_diversity(self) -> int:
        return len(set(self.list_voter_families()))


def _parse_manifest_dict(data: dict[str, Any]) -> SeedPipelineManifest:
    """Build a :class:`SeedPipelineManifest` from the parsed TOML dict.

    Split out so tests can feed dict literals without round-tripping
    through a TOML file.
    """
    seed = data.get("seed_pipeline")
    if not seed:
        raise ValueError("Manifest missing [seed_pipeline] root section")

    judge_data = seed.get("judge_panel", {})
    judge_panel = JudgePanelSpec(
        voters=[VoterSpec(**v) for v in judge_data.get("voters", [])],
        required_diversity_families=judge_data.get("required_diversity_families", 2),
    )

    return SeedPipelineManifest(
        enabled_roles=seed.get("enabled_roles", []),
        roles={k: SeedRoleSpec(**v) for k, v in seed.get("role", {}).items()},
        judge_panel=judge_panel,
    )


def _cross_validate_with_petri(manifest: SeedPipelineManifest) -> None:
    """Validate voter (family, source) pairs against Petri's source table.

    P7 Caller-Callee Contract — the seed_pipeline manifest depends on the
    Petri manifest as the SOT for credential source binding. A typo here
    (``claude_cli`` instead of ``claude-cli``, or a non-existent family)
    must fail at manifest load, not when the picker attempts to resolve
    the adapter. This function is the cross-manifest gate.

    Raised at the load layer rather than the validator to keep the
    pydantic schema free of the Petri import (allows seed-pipeline to
    be loaded in test fixtures without Petri available).
    """
    from plugins.petri_audit.manifest import load_manifest as load_petri_manifest

    petri = load_petri_manifest()
    for voter in manifest.judge_panel.voters:
        try:
            source_spec = petri.get_source(voter.family)
        except KeyError as exc:
            raise ValueError(
                f"voter {voter.model!r} (family={voter.family!r}) — family "
                f"not in petri.source table; "
                f"known families = {sorted(petri.sources)}"
            ) from exc
        if voter.source not in source_spec.allowed:
            raise ValueError(
                f"voter {voter.model!r} ({voter.family}.{voter.source}) — "
                f"source not in petri.source.{voter.family}.allowed = "
                f"{source_spec.allowed}"
            )


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> SeedPipelineManifest:
    data = tomllib.loads(Path(path_str).read_text(encoding="utf-8"))
    manifest = _parse_manifest_dict(data)
    _cross_validate_with_petri(manifest)
    return manifest


def load_manifest(path: Path | str | None = None) -> SeedPipelineManifest:
    """Load and validate the seed_pipeline manifest at ``path``.

    Defaults to :data:`DEFAULT_MANIFEST_PATH`. Results are cached per
    absolute path (max 4 entries) so repeated callers (picker, ranker,
    CLI) share the parsed tree.

    Raises ``ValueError`` on any schema or cross-manifest validation
    failure. The error messages are designed to point operators at the
    exact TOML key requiring attention.
    """
    target = Path(path) if path is not None else DEFAULT_MANIFEST_PATH
    return _load_cached(str(target.resolve()))


def clear_manifest_cache() -> None:
    """Drop the lru_cache — used by tests that mutate manifest fixtures."""
    _load_cached.cache_clear()


# Field reference held to silence linters that flag pydantic.Field as unused
# when only validators reference it indirectly.
_ = Field
