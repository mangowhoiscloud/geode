"""Outer-loop config — single SoT loader.

Reads ``~/.geode/config.toml`` ``[self_improving_loop.*]`` sections into a typed
pydantic v2 model. The loader is the SoT consumed by autoresearch /
seed-generation / petri_audit / geode_main wherever self-improving-loop runtime
decisions are made.

Why a separate module from :mod:`core.config`
=============================================

:class:`core.config._settings.Settings` carries the user-facing GEODE
runtime config (anthropic credential source, default model, etc.) and
is consumed by hundreds of call sites. Adding self-improving-loop fields there
would inflate every cold-start invocation that just wants a single
constant.

Outer-loop config is opt-in — only autoresearch / seed-generation /
petri callers load it, and the cost is paid lazily inside their
``run`` entrypoints. The two configs share the same file
(``~/.geode/config.toml``) but live in disjoint sections so they
never overwrite each other.

Precedence (Codex / OpenAI Agents pattern)
==========================================

1. Per-component env var override (e.g. ``AUTORESEARCH_TARGET_MODEL``)
   — handled at the caller, not here.
2. ``~/.geode/config.toml`` ``[self_improving_loop.*]`` section — this loader.
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
    "MutatorConfig",
    "PetriRoleConfig",
    "SeedGenerationConfig",
    "SelfImprovingLoopBindings",
    "SelfImprovingLoopConfig",
    "Source",
    "load_self_improving_loop_config",
]


Source = Literal["claude-cli", "openai-codex", "api_key", "auto"]
"""Credential source label — matches ``plugins.petri_audit.petri.plugin.toml``."""


class SelfImprovingLoopBindings(BaseModel):
    """Generic per-role binding (model + source + optional fallback override)."""

    model_config = ConfigDict(extra="forbid")

    model: str
    source: Source
    fallback_to_payg: bool | None = None
    """``None`` → inherit ``[self_improving_loop] fallback_to_payg``."""


class PetriRoleConfig(BaseModel):
    """Petri role binding (auditor / target / judge).

    Both ``model`` and ``source`` are optional so a partial override
    (e.g. pin source but keep manifest default model) is representable —
    parity with the legacy ``~/.geode/petri.toml`` semantics that
    ``read_role_override`` exposes (both fields optional, missing →
    manifest default).
    """

    model_config = ConfigDict(extra="forbid")

    model: str = ""
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


class MutatorConfig(BaseModel):
    """Mutator-role binding for ``core/self_improving_loop/runner.py``.

    PR-1 G-A — pre-fix the runner instantiated ``anthropic.Anthropic()``
    directly and pinned ``model="claude-opus-4-7"`` as a literal, so
    every self-improving loop mutation was bound to one provider and
    one model regardless of operator intent. The new manifest section
    follows the same shape as ``[seed_generation.role.<X>]`` and
    ``[petri.role.<X>]`` — default model + allowed model set + optional
    role contract — so the mutator is a first-class role in the
    paperclip-style abstraction.

    Field semantics (each one is *consumed* by the runner; see test
    invariants in ``tests/test_self_improving_loop_gap_fill.py``):

    - ``default_model`` — primary model id the runner sends to the
      router dispatcher.
    - ``allowed_models`` — allow-list pinned by a pydantic validator
      *and* by a runtime check inside ``_default_llm_call`` (fails
      closed if the default drifts outside the list).
    - ``source`` — mirrors the petri source resolver enum
      (``auto`` / ``api_key`` / ``claude-cli`` / ``openai-codex``).
      Stored on the resolved adapter so the runner's credential
      selection records the operator's intent in telemetry, even
      though the rotator currently consumes the same enum implicitly
      via ``[petri.source.<provider>]``.
    - ``role_contract`` — path (repo-relative) to the mutator's
      operator-facing contract document. Surfaced by ``/petri`` /
      ``/login`` views so the operator can grep the contract before
      flipping the model.
    - ``max_tokens`` — passed through to ``adapter.agentic_call``.
    """

    model_config = ConfigDict(extra="forbid")

    default_model: str = "claude-opus-4-7"
    allowed_models: list[str] = Field(
        default_factory=lambda: [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "gpt-5.5",
            "gpt-5.4",
        ]
    )
    source: Literal["auto", "api_key", "claude-cli", "openai-codex"] = "auto"
    role_contract: str = ".claude/agents/self_improving_loop_mutator.md"
    max_tokens: Annotated[int, Field(ge=128, le=200_000)] = 1024
    fallback_to_payg: bool | None = None

    @model_validator(mode="after")
    def _default_in_allowed(self) -> MutatorConfig:
        """Allow-list invariant — ``default_model`` must appear in
        ``allowed_models`` (matches the petri / seed_generation manifest
        contract). Pre-validator drift would let an operator set a
        ``default_model`` that the runtime guard then rejects, which is
        confusing — fail at load time with the same message."""
        if self.allowed_models and self.default_model not in self.allowed_models:
            raise ValueError(
                f"MutatorConfig.default_model={self.default_model!r} not in "
                f"allowed_models={self.allowed_models!r}"
            )
        return self


class SeedGenerationConfig(BaseModel):
    """seed-generation runtime knobs.

    Per-role bindings live under ``[self_improving_loop.seed_generation.role.<X>]``
    and are loaded into :attr:`roles`.
    """

    model_config = ConfigDict(extra="forbid")

    candidates_default: Annotated[int, Field(ge=1, le=100)] = 15
    default_gen_tag: str = "gen1"
    roles: dict[str, SelfImprovingLoopBindings] = Field(default_factory=dict)
    fallback_to_payg: bool | None = None


class SelfImprovingLoopConfig(BaseModel):
    """Top-level [self_improving_loop.*] config root.

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
    seed_generation: SeedGenerationConfig = Field(default_factory=SeedGenerationConfig)
    mutator: MutatorConfig = Field(default_factory=MutatorConfig)
    """PR-1 G-A — mutator role manifest. Closes the hardcoded
    ``model="claude-opus-4-7"`` + direct ``anthropic.Anthropic()``
    call in ``core/self_improving_loop/runner.py``."""

    @model_validator(mode="after")
    def _abort_above_warn(self) -> SelfImprovingLoopConfig:
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


def _emit_defaults_notice(reason: str, path: Path) -> None:
    """Notify the active SessionJournal that the loader fell back to defaults.

    P2 — closes the "config loader default sub silent" gap from the
    2026-05-19 observability audit §4. ``reason`` is one of
    ``file_missing`` / ``read_error`` / ``section_missing`` so the
    operator can tell which fallback fired without re-reading the file.
    The emit is a no-op outside an :func:`session_journal_scope` so
    callers that load the config without an active audit run (REPL
    bootstrap, petri user-overrides) stay unaffected.
    """
    try:
        from core.observability import current_session_journal

        journal = current_session_journal()
        if journal is None:
            return
        journal.append(
            "self_improving_loop_config_defaults_applied",
            level="warn" if reason == "read_error" else "info",
            payload={"reason": reason, "path": str(path)},
        )
    except Exception:  # pragma: no cover - defensive
        log.debug(
            "self-improving-loop config: defaults-notice emit failed (reason=%r)",
            reason,
            exc_info=True,
        )


def load_self_improving_loop_config(path: Path | str | None = None) -> SelfImprovingLoopConfig:
    """Load + validate the ``[self_improving_loop.*]`` section of ``config.toml``.

    Returns a fully-defaulted :class:`SelfImprovingLoopConfig` when:
    - the file does not exist, or
    - the file has no ``[self_improving_loop]`` section.

    Raises:
        ValueError: when the ``[self_improving_loop.*]`` section exists but
            contains unknown fields or fails pydantic validation.
            The error is bubbled verbatim so the operator sees the
            offending key / value.
    """
    resolved = _resolve_config_path(path)
    if not resolved.is_file():
        log.debug("self-improving-loop config: %s does not exist; using defaults", resolved)
        _emit_defaults_notice("file_missing", resolved)
        return SelfImprovingLoopConfig()
    try:
        with resolved.open("rb") as fh:
            raw = tomllib.load(fh)
    except OSError as exc:
        log.warning(
            "self-improving-loop config: could not read %s (%s); using defaults",
            resolved,
            exc,
        )
        _emit_defaults_notice("read_error", resolved)
        return SelfImprovingLoopConfig()
    section = raw.get("self_improving_loop")
    if not isinstance(section, dict):
        _emit_defaults_notice("section_missing", resolved)
        return SelfImprovingLoopConfig()
    return SelfImprovingLoopConfig.model_validate(section)
