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

1. ``~/.geode/config.toml`` ``[self_improving_loop.*]`` section — this
   loader. Per-role petri model selection lives under
   ``[self_improving_loop.petri.<role>]`` (PR-CSP-12, 2026-05-22 — the
   single SoT for ``auditor`` / ``target`` / ``judge`` after the
   duplicate-SoT consolidation removed argv defaults, the
   ``TARGET_MODEL`` / ``JUDGE_MODEL`` module constants, and the legacy
   ``~/.geode/petri.toml`` writer).
2. Picker defaults in ``autoresearch/train.py`` (``BUDGET_MINUTES``,
   ``SEED_LIMIT``, etc.) — fallback when the section is missing. Role
   models fall back to the manifest ``default_model`` in
   ``plugins/petri_audit/petri.plugin.toml`` via
   ``autoresearch.train._petri_role_model``.
3. Pydantic model default — last resort.

Source: 2026-05-19 config consolidation plan (settled decision #1),
finalized by the 2026-05-22 PR-CSP-12 single-SoT consolidation.
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
    "SchedulerConfig",
    "SeedGenerationConfig",
    "SelfImprovingLoopBindings",
    "SelfImprovingLoopConfig",
    "Source",
    "load_self_improving_loop_config",
]


# PR-SIL-5THEME C6 (2026-05-23) — D1 provider closure. PAYG (``api_key``)
# 가 ``PetriRoleConfig.source`` / ``AutoresearchConfig.source`` 의 Literal
# 에서 제거됨 (durable operator decision per ``project_payg_exclusion_decision.md``,
# 2026-05-23) — autoresearch / Petri audit 의 provider 선택지에서 영구
# exclude. 잔존 옵션: ``claude-cli`` (Claude Code Max OAuth) /
# ``openai-codex`` (ChatGPT Plus OAuth) / ``auto`` (manifest cascade).
# ``api_key`` 설정 시 Pydantic ValidationError 가 명시 PAYG 사용을 reject
# — PR-C-P1 의 silent-fallback 차단 패턴 재사용.
#
# **인프라 보존**: ``MutatorConfig.source`` (line 248 의 별도 Literal) 는
# api_key 포함 4-element 유지 — mutator LLM 호출은 audit role 과 별개,
# operator 가 Anthropic API key 로 mutator 운영 자유. ``credential_source.py``
# 의 PAYG fallback 코드 경로도 보존 (다른 caller 가 명시 호출 시 활성).
Source = Literal["claude-cli", "openai-codex", "auto"]
"""Credential source label — matches ``plugins.petri_audit.petri.plugin.toml``."""


class SelfImprovingLoopBindings(BaseModel):
    """Per-seed-generation-role binding (model + source [+ num_turns]).

    PR-MINIMAL-2 (2026-05-21) — ``fallback_to_payg`` per-component
    override removed; only the global flag at
    ``[self_improving_loop] fallback_to_payg`` survives. Pre-PR the
    per-component override had no downstream consumer, just config
    surface noise.

    CSP-13 (2026-05-23) — adds the optional ``num_turns`` knob for the
    Loop 2 (debate-turn) port. Only the ``generator`` role consults
    it; other roles ignore it. 0 = off (single-shot, back-compat
    default). 2-6 = active multi-turn debate inside the candidate
    sub-agent's AgenticLoop, recorded via ``seed_debate_turn``.
    Operator surface lives at
    ``[self_improving_loop.seed_generation.roles.generator] num_turns``
    in ``~/.geode/config.toml``; manifest default flows through when
    omitted.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    source: Source
    num_turns: int = 0

    @model_validator(mode="after")
    def _num_turns_in_range(self) -> SelfImprovingLoopBindings:
        # CSP-13 (Codex MCP MEDIUM fix-up) — operator override path
        # must enforce the same ``{0} ∪ [2, 6]`` window as the
        # manifest-side ``SeedRoleSpec`` validator. Otherwise an
        # operator could pin num_turns=1 in ``~/.geode/config.toml``
        # (meaningless debate-of-one) or num_turns=99 (runaway cost
        # per candidate) without any guardrail catching it.
        if self.num_turns != 0 and not (2 <= self.num_turns <= 6):
            raise ValueError(f"num_turns={self.num_turns} invalid; must be 0 (off) or in [2, 6]")
        return self


class PetriRoleConfig(BaseModel):
    """Petri role binding (auditor / target / judge).

    Both ``model`` and ``source`` are optional so a partial override
    (e.g. pin source but keep manifest default model) is representable —
    parity with the legacy ``~/.geode/petri.toml`` semantics that
    ``read_role_override`` exposes (both fields optional, missing →
    manifest default).

    **Precedence vs ``[self_improving_loop.autoresearch]``** — important
    operator surface to understand because two sections can name the
    same role from different angles. ``autoresearch/train.py`` calls
    ``geode audit --target <X> --judge <Y>`` with the model ids from
    ``[self_improving_loop.autoresearch].{target_model,judge_model}``.
    Inside ``geode audit``, :func:`plugins.petri_audit.registry.get_binding`
    resolves the role binding with this order::

        1. argv (caller override) — wins outright for the ``model`` axis
        2. ``[self_improving_loop.petri.<role>]`` (this class)
        3. manifest default + credential_source cascade

    So when the outer loop runs, ``[self_improving_loop.petri.target].model``
    is **silently ignored** because the autoresearch argv already pinned
    the model. ``source`` still applies through the cascade in step 2
    (argv doesn't carry per-role source). The ``[petri.<role>]`` section
    becomes load-bearing again when an operator invokes ``geode audit``
    standalone without ``--target/--judge``. Keep the two sections in
    sync to avoid the cross-model mismatch that looks like a bug.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = ""
    # PR-SIL-5THEME C6 (2026-05-23) — default ``auto`` → ``claude-cli``.
    # operator decision (``project_payg_exclusion_decision.md``, 2026-05-23)
    # 으로 subscription-first 가 새 default. ``auto`` 는 manifest cascade
    # 가 PAYG 까지 fallback 할 수 있어서 silent leak risk — 명시
    # ``claude-cli`` (Claude Code Max OAuth) 이 default 면 leak 0. operator
    # 가 explicit 으로 ``auto`` 또는 ``openai-codex`` 명시 시 그대로 적용.
    source: Source = "claude-cli"


class AutoresearchConfig(BaseModel):
    """autoresearch/train.py runtime knobs.

    Single-SoT (2026-05-22) — ``[self_improving_loop.petri.<role>].model``
    in ``~/.geode/config.toml`` is the **sole** model SoT for every audit
    role (auditor / target / judge). The autoresearch outer loop reads
    the role models through that section indirectly: it omits
    ``--target`` / ``--judge`` / ``--auditor`` from the ``geode audit``
    argv entirely, and the runner resolves each role via the binding
    registry (which reads ``[petri.<role>]``).

    The ``target_model`` / ``judge_model`` fields survive as
    **deprecated no-op slots** — silently accepted at load time so
    existing ``~/.geode/config.toml`` files don't ``extra="forbid"``
    on the loader, but never consulted at runtime. ``_build_audit_command``
    no longer reads them; the next release will drop the fields
    entirely after operators have migrated to ``[petri.<role>].model``.

    Operators who want an autoresearch-only model now edit
    ``[petri.target].model`` / ``[petri.judge].model`` directly;
    standalone ``geode audit`` and the outer loop share the same
    bindings end-to-end.
    """

    model_config = ConfigDict(extra="forbid")

    budget_minutes: Annotated[int, Field(ge=1, le=60)] = 5
    target_model: str | None = None
    """**Deprecated** — surviving slot for back-compat config file load.
    The runtime always resolves the target through
    ``[self_improving_loop.petri.target].model`` via the binding
    registry; this field is silently ignored. Will be dropped in a
    future release once operator configs are migrated."""
    judge_model: str | None = None
    """**Deprecated** — surviving slot for back-compat config file load.
    The runtime resolves the judge through
    ``[self_improving_loop.petri.judge].model`` via the binding
    registry; this field is silently ignored. Will be dropped in a
    future release once operator configs are migrated."""
    # PR-SIL-5THEME C6 (2026-05-23) — default ``auto`` → ``claude-cli``.
    # Operator decision (``project_payg_exclusion_decision.md``, 2026-05-23)
    # 으로 ``api_key`` 는 ``Source`` literal 에서 제거. ``auto`` 는 manifest
    # cascade 가 PAYG 까지 silent fallback 가능 → ``claude-cli`` (Claude
    # Code Max OAuth) 가 새 default.
    source: Source = "claude-cli"
    """Credential source for the audit subprocess. PR-SIL-5THEME C6 후 PAYG
    (``api_key``) 는 Source literal 에서 제거. ``claude-cli`` = Claude Code
    Max OAuth (default), ``openai-codex`` = ChatGPT Plus OAuth, ``auto`` =
    manifest cascade (subscription-first, ``fallback_to_payg`` 가 True 여야
    PAYG 까지 fallback). argv translator 가 non-``api_key`` source 를
    ``--use-oauth`` 로 매핑 (모든 source 가 이제 non-api_key 라 항상 fire)."""
    seed_limit: Annotated[int, Field(ge=5, le=1000)] = 10
    """Per-audit seed count — the N that ``dim_extractor._aggregate``
    feeds into ``statistics.stdev(ddof=1)``.

    PR-C-P1 (2026-05-23) — lower bound bumped from 1 to **5**.
    ``_aggregate`` *forces* ``stderr=0.0`` only at N=1 (ddof=1
    variance undefined); N=2-4 produces a sample stderr but it is
    too unstable to drive the ``_should_promote`` gate (CV often
    exceeds the dim's own value range). ``compute_fitness`` then
    floored its margin gate at ``max(stderr, fitness_margin_floor)``
    where ``fitness_margin_floor=0.05`` (and PR-3 raised it to
    ``N1_FITNESS_MARGIN_FLOOR=0.20`` whenever any ``CRITICAL_DIMS``
    member has N≤1) — so without a sane stderr signal a 0.05+
    fitness Δ would promote against a measurement with no
    confidence. N≥5 keeps the sample stderr meaningful, so the
    stderr-derived margin rises above the default floor instead of
    collapsing onto it. Operators who want faster smoke runs should
    pass ``--dry-run`` instead of setting a low ``seed_limit``."""
    seed_select: str = "plugins/petri_audit/seeds"
    dim_set: str = "subset"
    max_turns: Annotated[int, Field(ge=1, le=200)] = 10


class MutatorConfig(BaseModel):
    """Mutator-role binding for ``core/self_improving_loop/runner.py``.

    PR-1 G-A introduced this so the mutator was a first-class role
    alongside ``[seed_generation.role.<X>]`` and ``[petri.role.<X>]``.

    PR-MINIMAL-2 (2026-05-21) — four trimmings:

    1. ``default_model`` default flipped to ``None`` so it inherits
       ``Settings.model`` when unset (G1a). Operator's ``/model`` choice
       follows automatically; explicit override still wins.
    2. The 5-model allow-list field (and its pydantic validator) was
       removed (C1). The pre-PR motivation — PR-1 G-A's *direct*
       ``anthropic.Anthropic()`` call drift — is now obsolete since
       the runner dispatches through ``core.llm.router.call_with_failover``
       which already guards model existence per provider.
    3. The role-contract path field was removed (A1) — it was logged
       in telemetry but never injected into the system prompt
       (operator-facing docs only). The file
       ``.claude/agents/self_improving_loop_mutator.md`` still
       exists as operator reference; the config field that pointed
       at it added noise without operational effect.
    4. ``fallback_to_payg`` per-component override removed (use global).
    """

    model_config = ConfigDict(extra="forbid")

    default_model: str | None = None
    """``None`` → inherit ``Settings.model``. Operator sets this only
    when the mutator LLM must differ from the GEODE primary (e.g.
    use a smaller model to keep mutation cost down)."""
    source: Literal["auto", "api_key", "claude-cli", "openai-codex"] = "auto"
    """Mirrors :data:`Source`. The router's credential rotator
    consumes the same enum implicitly via ``[petri.source.<provider>]``."""
    max_tokens: Annotated[int, Field(ge=128, le=200_000)] = 1024
    """Passed through to ``adapter.agentic_call``."""


class SeedGenerationConfig(BaseModel):
    """seed-generation runtime knobs.

    Per-role bindings live under ``[self_improving_loop.seed_generation.role.<X>]``
    and are loaded into :attr:`roles`.

    PR-MINIMAL-2 (2026-05-21) — ``fallback_to_payg`` per-component
    override removed; only the global flag survives.
    """

    model_config = ConfigDict(extra="forbid")

    candidates_default: Annotated[int, Field(ge=1, le=100)] = 15
    default_gen_tag: str = "gen1"
    roles: dict[str, SelfImprovingLoopBindings] = Field(default_factory=dict)


class SchedulerConfig(BaseModel):
    """Auto-trigger schedule for the mutator (OL-A1, 2026-05-22).

    Pre-OL-A1 the self-improving loop only fired *manually* — operator
    ran ``geode self-improve mutate`` or the autoresearch sprint runner
    invoked ``SelfImprovingLoopRunner.run_once`` synchronously. With
    OL-A1 the loop can fire on a cron schedule, so the GEODE daemon
    keeps improving the wrapper-prompt / policies even when no operator
    is at the keyboard. **Default off** — opt-in via
    ``[self_improving_loop.scheduler] enabled = true``.

    Concurrency is bounded by a filesystem lock
    (``~/.geode/self-improving-loop/auto_trigger.lock`` via
    :mod:`fcntl`), so even an over-eager cron and a manual invocation
    cannot race. The min-interval gate is the *complementary* knob: it
    prevents two cron-fires within ``min_interval_minutes`` of each
    other from doing redundant work when the lock itself would let
    them through. Together they implement Codex CLI's
    ``forced_single_instance`` semantics for this loop role.

    Operator override of the four backends (subscription Claude Code /
    Codex CLI / Anthropic PAYG / OpenAI PAYG) flows through the
    *existing* :class:`MutatorConfig.source` field — the auto-trigger
    invokes :func:`SelfImprovingLoopRunner.run_once` which honours that
    setting via the PAPERCLIP dispatch path (#1433). The scheduler does
    NOT introduce a second source vocabulary.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    """When False (default), the runtime never registers the trigger.
    Operators flip to True after they've verified the mutator role
    binding + budget. The flag is checked at wiring time, so toggling
    requires a process restart (matches scheduler service semantics)."""

    cron: str = "0 */6 * * *"
    """5-field cron expression (min hour day month weekday). Default
    fires every 6 hours starting at minute 0 — gives the autoresearch
    audit cycle enough headroom to settle between runs."""

    min_interval_minutes: Annotated[int, Field(ge=1, le=1440)] = 60
    """Floor between successive mutator firings (timestamp-based gate
    on ``~/.geode/self-improving-loop/auto_trigger_last_run.txt``).
    Cron firings closer together than this are silently skipped — the
    lockfile already prevents concurrent runs, this knob prevents
    *back-to-back* runs. Must satisfy ``min_interval_minutes <= cron
    period`` for the schedule to actually fire."""


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

    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    """PR-OL-A1 — auto-trigger schedule. Default off; operator opts in
    via ``[self_improving_loop.scheduler] enabled = true``. The cron
    fires the mutator runner with lockfile + min-interval guards."""

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
