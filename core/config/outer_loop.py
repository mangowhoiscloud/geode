"""Outer-loop config — single SoT loader.

Reads ``~/.geode/config.toml`` ``[outer_loop.*]`` sections into a typed
pydantic v2 model. The loader is the SoT consumed by autoresearch /
seed-pipeline / petri_audit / geode_main wherever outer-loop runtime
decisions are made.

Why a separate module from :mod:`core.config`
=============================================

:class:`core.config._settings.Settings` carries the user-facing GEODE
runtime config (anthropic credential source, default model, etc.) and
is consumed by hundreds of call sites. Adding outer-loop fields there
would inflate every cold-start invocation that just wants a single
constant.

Outer-loop config is opt-in — only autoresearch / seed-pipeline /
petri callers load it, and the cost is paid lazily inside their
``run`` entrypoints. The two configs share the same file
(``~/.geode/config.toml``) but live in disjoint sections so they
never overwrite each other.

Precedence (Codex / OpenAI Agents pattern)
==========================================

1. Per-component env var override (e.g. ``AUTORESEARCH_TARGET_MODEL``)
   — handled at the caller, not here.
2. ``~/.geode/config.toml`` ``[outer_loop.*]`` section — this loader.
3. Module-level constants in ``autoresearch/train.py`` / picker
   defaults — fallback when the section is missing.
4. Pydantic model default — last resort.

Source: 2026-05-19 config consolidation plan (settled decision #1).
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.paths import GLOBAL_CONFIG_TOML

log = logging.getLogger(__name__)

__all__ = [
    "AutoresearchConfig",
    "OuterLoopBindings",
    "OuterLoopConfig",
    "PetriRoleConfig",
    "SeedPipelineConfig",
    "Source",
    "load_outer_loop_config",
]


Source = Literal["claude-cli", "openai-codex", "api_key", "auto"]
"""Credential source label — matches ``plugins.petri_audit.petri.plugin.toml``."""


class OuterLoopBindings(BaseModel):
    """Generic per-role binding (model + source + optional fallback override)."""

    model_config = ConfigDict(extra="forbid")

    model: str
    source: Source
    fallback_to_payg: bool | None = None
    """``None`` → inherit ``[outer_loop] fallback_to_payg``."""


class PetriRoleConfig(BaseModel):
    """Petri role binding (auditor / target / judge)."""

    model_config = ConfigDict(extra="forbid")

    model: str
    source: Source = "auto"
    fallback_to_payg: bool | None = None


class AutoresearchConfig(BaseModel):
    """autoresearch/train.py runtime knobs."""

    model_config = ConfigDict(extra="forbid")

    budget_minutes: Annotated[int, Field(ge=1, le=60)] = 5
    target_model: str = "geode/gpt-5.5"
    judge_model: str = "claude-code/opus"
    use_oauth: bool = True
    seed_limit: Annotated[int, Field(ge=1, le=1000)] = 10
    seed_select: str = "plugins/petri_audit/seeds"
    dim_set: str = "5axes"
    max_turns: Annotated[int, Field(ge=1, le=200)] = 10
    fallback_to_payg: bool | None = None


class SeedPipelineConfig(BaseModel):
    """seed-pipeline runtime knobs.

    Per-role bindings live under ``[outer_loop.seed_pipeline.role.<X>]``
    and are loaded into :attr:`roles`.
    """

    model_config = ConfigDict(extra="forbid")

    candidates_default: Annotated[int, Field(ge=1, le=100)] = 15
    default_gen_tag: str = "gen1"
    roles: dict[str, OuterLoopBindings] = Field(default_factory=dict)
    fallback_to_payg: bool | None = None


class OuterLoopConfig(BaseModel):
    """Top-level [outer_loop.*] config root.

    Validation entry point — every field has a documented default so an
    empty / missing config file still produces a usable instance.
    """

    model_config = ConfigDict(extra="forbid")

    # Global flags
    fallback_to_payg: bool = False
    """Subscription-soft default — true forces all source resolvers to
    fall through to ``api_key`` on subscription exhaustion. False (the
    default) aborts with an actionable error. Codex CLI's
    ``forced_login_method`` pattern."""

    warn_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    """Quota usage ratio above which the FE banner turns yellow."""

    abort_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.9
    """Quota usage ratio above which the FE banner turns red and the
    run aborts."""

    # Per-component sub-configs
    autoresearch: AutoresearchConfig = Field(default_factory=AutoresearchConfig)
    petri: dict[str, PetriRoleConfig] = Field(default_factory=dict)
    """Map of role name → PetriRoleConfig. Expected keys: auditor /
    target / judge."""
    seed_pipeline: SeedPipelineConfig = Field(default_factory=SeedPipelineConfig)

    @model_validator(mode="after")
    def _abort_above_warn(self) -> OuterLoopConfig:
        # ``model_validator(mode='after')`` runs after every field is
        # populated (including defaults), so the inversion is caught
        # even when the user only sets one of the two thresholds.
        if self.abort_threshold <= self.warn_threshold:
            raise ValueError(
                f"abort_threshold ({self.abort_threshold}) must be greater than "
                f"warn_threshold ({self.warn_threshold})"
            )
        return self


def _resolve_config_path(path: Path | str | None) -> Path:
    """Resolve which TOML to load.

    Order: explicit ``path`` argument → ``GEODE_CONFIG_TOML`` env →
    :data:`core.paths.GLOBAL_CONFIG_TOML`. Mirrors the pattern used by
    :mod:`core.auth.auth_toml`.
    """
    if path is not None:
        return Path(path).expanduser()
    env = os.environ.get("GEODE_CONFIG_TOML", "").strip()
    if env:
        return Path(env).expanduser()
    return GLOBAL_CONFIG_TOML


def load_outer_loop_config(path: Path | str | None = None) -> OuterLoopConfig:
    """Load + validate the ``[outer_loop.*]`` section of ``config.toml``.

    Returns a fully-defaulted :class:`OuterLoopConfig` when:
    - the file does not exist, or
    - the file has no ``[outer_loop]`` section.

    Raises:
        ValueError: when the ``[outer_loop.*]`` section exists but
            contains unknown fields or fails pydantic validation.
            The error is bubbled verbatim so the operator sees the
            offending key / value.
    """
    resolved = _resolve_config_path(path)
    if not resolved.is_file():
        log.debug("outer-loop config: %s does not exist; using defaults", resolved)
        return OuterLoopConfig()
    try:
        with resolved.open("rb") as fh:
            raw = tomllib.load(fh)
    except OSError as exc:
        log.warning(
            "outer-loop config: could not read %s (%s); using defaults",
            resolved,
            exc,
        )
        return OuterLoopConfig()
    section = raw.get("outer_loop")
    if not isinstance(section, dict):
        return OuterLoopConfig()
    return OuterLoopConfig.model_validate(section)
