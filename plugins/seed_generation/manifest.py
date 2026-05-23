"""Seed pipeline manifest loader — declarative 7-role + 3-judge-panel schema.

Reads ``plugins/seed_generation/seed_generation.plugin.toml`` into a validated
pydantic tree. Source / adapter layers are intentionally NOT defined here
— they are reused from ``plugins/petri_audit/petri.plugin.toml`` (the
Petri manifest is the SOT for credential provider/source binding). The
seed-generation manifest's voter rows are cross-validated against the
Petri source table at load time so a typo'd ``provider`` or ``source`` is
caught immediately, not on first runtime use.

Layers (mirroring TOML structure):

- :class:`SeedRoleSpec` — per-role default model + allowed model set
- :class:`VoterSpec` — one (model, provider, source) row in judge_panel
- :class:`JudgePanelSpec` — voters list + required_diversity_providers gate
- :class:`SeedGenerationManifest` — top-level container with cross-layer +
  cross-manifest consistency checks

The loader does **not** import any LLM SDK or adapter module — manifest
parsing must remain cold-start clean so `geode version` does not pay the
seed-generation cost.

P1-P7 prevention checklist application (cycle-skill SKILL.md):

- **P4 Environment Anchor**: ``DEFAULT_MANIFEST_PATH`` is anchored at
  ``Path(__file__).parent / "seed_generation.plugin.toml"`` — package-
  relative, not cwd-relative. Same anchor pattern as Petri's manifest.
- **P7 Caller-Callee Contract**: voter source values are validated
  against ``petri_audit.manifest.PetriManifest.get_source(provider).allowed``
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
    "SeedGenerationManifest",
    "SeedRoleSpec",
    "VoterSpec",
    "clear_manifest_cache",
    "load_manifest",
]

DEFAULT_MANIFEST_PATH = Path(__file__).parent / "seed_generation.plugin.toml"


class SeedRoleSpec(BaseModel):
    """Per-role default + allowed model set + contract path.

    Mirrors :class:`plugins.petri_audit.manifest.RoleSpec` in field shape
    (default + allowed + contract). Every shipped role is an LLM
    completion call dispatched through :class:`SubAgentManager.delegate`
    — there is no longer any embedding-driven role surface (CSP-10
    removed the pre-CSP-8 ``kind`` discriminator after CSP-8 reverted
    the only embedding consumer, Proximity, to the paper's
    LLM-clustering path).

    CSP-13 (2026-05-23) — adds the optional ``num_turns`` knob for the
    Loop 2 (debate-turn) port. 0 = no debate, fall through to the
    existing single-shot path (default + back-compat). 2-6 = active
    multi-turn debate inside the sub-agent's AgenticLoop, recorded via
    the ``seed_debate_turn`` tool. Only meaningful on the Generator
    role today; other roles ignore the knob.

    CSP-14 (2026-05-23) — adds the ``max_papers`` + ``queries_per_run``
    knobs for the Loop 3 (literature paper-analysis) port. 0 =
    literature_review phase short-circuits (default + back-compat).
    1-20 = active per-paper loop. Only meaningful on the
    ``literature_review`` role; other roles ignore the knob.
    """

    default_model: str
    allowed_models: list[str]
    role_contract: str | None = None
    num_turns: int = 0
    max_papers: int = 0
    queries_per_run: int = 3

    @model_validator(mode="after")
    def _default_in_allowed(self) -> SeedRoleSpec:
        if self.default_model not in self.allowed_models:
            raise ValueError(
                f"default_model {self.default_model!r} not in allowed_models {self.allowed_models}"
            )
        return self

    @model_validator(mode="after")
    def _num_turns_in_range(self) -> SeedRoleSpec:
        # Mirror the tool-side bounds (core/tools/seed_debate.py): 0
        # disables the debate path entirely (single-shot generation),
        # 2-6 activates the multi-turn loop. Any other value is a
        # silent foot-gun (e.g. 1 = "debate of one turn" makes no
        # sense; >6 risks runaway cost per candidate).
        if self.num_turns != 0 and not (2 <= self.num_turns <= 6):
            raise ValueError(f"num_turns={self.num_turns} invalid; must be 0 (off) or in [2, 6]")
        return self

    @model_validator(mode="after")
    def _max_papers_in_range(self) -> SeedRoleSpec:
        # CSP-14 — 0 = literature_review phase off (default), 1-20 =
        # active per-paper loop. Upper bound caps cost: max_papers=20
        # × ~$0.05/paper ≈ $1/run on Sonnet-class.
        if self.max_papers < 0 or self.max_papers > 20:
            raise ValueError(f"max_papers={self.max_papers} invalid; must be 0 (off) or in [1, 20]")
        if self.queries_per_run < 1 or self.queries_per_run > 10:
            raise ValueError(f"queries_per_run={self.queries_per_run} invalid; must be in [1, 10]")
        return self


class VoterSpec(BaseModel):
    """One voter row in the Ranker phase's judge panel.

    Fields:
    - ``model`` — the LLM model name (e.g. ``claude-sonnet-4-6``).
    - ``provider`` — provider id (e.g. ``anthropic``, ``openai``); must
      match one of Petri's ``[petri.source.<provider>]`` keys.
    - ``source`` — credential source (e.g. ``claude-cli``, ``openai-codex``,
      ``api_key``); must be in
      ``petri.source.<provider>.allowed``. The ``auto`` sentinel is rejected
      here — judge voters require a concrete binding so the panel diversity
      check is meaningful.
    """

    model: str
    provider: str
    source: str

    @model_validator(mode="after")
    def _source_not_auto(self) -> VoterSpec:
        if self.source == "auto":
            raise ValueError(
                f"voter ({self.model}, {self.provider}) cannot use source=auto — "
                "judge panel diversity requires concrete bindings"
            )
        return self


class JudgePanelSpec(BaseModel):
    """Ranker phase's 3-voter panel + diversity gate."""

    voters: list[VoterSpec]
    required_diversity_providers: int = 2

    @model_validator(mode="after")
    def _diversity(self) -> JudgePanelSpec:
        if len(self.voters) < 2:
            raise ValueError(f"judge panel requires >= 2 voters, got {len(self.voters)}")
        providers = {v.provider for v in self.voters}
        if len(providers) < self.required_diversity_providers:
            raise ValueError(
                f"judge panel diversity violated — voters span "
                f"{sorted(providers)} ({len(providers)} provider/providers) but "
                f"required_diversity_providers={self.required_diversity_providers}"
            )
        return self


class SeedGenerationManifest(BaseModel):
    """Top-level manifest container with cross-layer consistency checks."""

    enabled_roles: list[str]
    roles: dict[str, SeedRoleSpec]
    judge_panel: JudgePanelSpec

    @model_validator(mode="after")
    def _consistency(self) -> SeedGenerationManifest:
        if set(self.enabled_roles) != set(self.roles):
            raise ValueError(
                f"enabled_roles {self.enabled_roles} != role spec keys {sorted(self.roles)}"
            )
        return self

    # ── Accessors (used by S5.5 picker / S6 ranker / S11 CLI) ────────────

    def get_role(self, role: str) -> SeedRoleSpec:
        if role not in self.roles:
            raise KeyError(f"Unknown seed_generation role {role!r}; enabled={self.enabled_roles}")
        return self.roles[role]

    def list_voter_providers(self) -> list[str]:
        return [v.provider for v in self.judge_panel.voters]

    def voter_diversity(self) -> int:
        return len(set(self.list_voter_providers()))


def _parse_manifest_dict(data: dict[str, Any]) -> SeedGenerationManifest:
    """Build a :class:`SeedGenerationManifest` from the parsed TOML dict.

    Split out so tests can feed dict literals without round-tripping
    through a TOML file.
    """
    seed = data.get("seed_generation")
    if not seed:
        raise ValueError("Manifest missing [seed_generation] root section")

    judge_data = seed.get("judge_panel", {})
    judge_panel = JudgePanelSpec(
        voters=[VoterSpec(**v) for v in judge_data.get("voters", [])],
        required_diversity_providers=judge_data.get("required_diversity_providers", 2),
    )

    return SeedGenerationManifest(
        enabled_roles=seed.get("enabled_roles", []),
        roles={k: SeedRoleSpec(**v) for k, v in seed.get("role", {}).items()},
        judge_panel=judge_panel,
    )


def _cross_validate_with_petri(manifest: SeedGenerationManifest) -> None:
    """Validate voter (provider, source) pairs against Petri's source table.

    P7 Caller-Callee Contract — the seed_generation manifest depends on the
    Petri manifest as the SOT for credential source binding. A typo here
    (``claude_cli`` instead of ``claude-cli``, or a non-existent provider)
    must fail at manifest load, not when the picker attempts to resolve
    the adapter. This function is the cross-manifest gate.

    Raised at the load layer rather than the validator to keep the
    pydantic schema free of the Petri import (allows seed-generation to
    be loaded in test fixtures without Petri available).
    """
    from plugins.petri_audit.manifest import load_manifest as load_petri_manifest

    petri = load_petri_manifest()
    for voter in manifest.judge_panel.voters:
        try:
            source_spec = petri.get_source(voter.provider)
        except KeyError as exc:
            raise ValueError(
                f"voter {voter.model!r} (provider={voter.provider!r}) — provider "
                f"not in petri.source table; "
                f"known providers = {sorted(petri.sources)}"
            ) from exc
        if voter.source not in source_spec.allowed:
            raise ValueError(
                f"voter {voter.model!r} ({voter.provider}.{voter.source}) — "
                f"source not in petri.source.{voter.provider}.allowed = "
                f"{source_spec.allowed}"
            )


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> SeedGenerationManifest:
    data = tomllib.loads(Path(path_str).read_text(encoding="utf-8"))
    manifest = _parse_manifest_dict(data)
    _cross_validate_with_petri(manifest)
    return manifest


def load_manifest(path: Path | str | None = None) -> SeedGenerationManifest:
    """Load and validate the seed_generation manifest at ``path``.

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
