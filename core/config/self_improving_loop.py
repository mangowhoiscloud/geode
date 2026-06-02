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
2. Picker defaults in ``core/self_improving/train.py`` (``BUDGET_MINUTES``,
   ``SEED_LIMIT``, etc.) — fallback when the section is missing. Role
   models fall back to the manifest ``default_model`` in
   ``plugins/petri_audit/petri.plugin.toml`` via
   ``core.self_improving.train._petri_role_model``.
3. Pydantic model default — last resort.

Source: 2026-05-19 config consolidation plan (settled decision #1),
finalized by the 2026-05-22 PR-CSP-12 single-SoT consolidation.
"""

from __future__ import annotations

import logging
import os
import tomllib
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.config.credential_source import CredentialSource
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


# PR-CRED-SOURCE-CENTRALIZE (2026-05-29) — ``Source`` is now a backward-compat
# re-export of the canonical :class:`core.config.credential_source.CredentialSource`
# enum (single SoT). Previously this module, ``MutatorConfig.source``,
# ``plugins.seed_generation.auth_coverage.Source`` and
# ``settings.{provider}_credential_source`` each spelled the source set
# differently (``api_key`` in some, not others; ``auto`` in some, not others) —
# they now all reference one enum, so a change can no longer silently diverge.
#
# PAYG: ``api_key`` is a valid member again. The
# ``project_payg_exclusion_decision`` intent — a subscription-only run must not
# *silently* fall through to PAYG — is preserved at resolution time
# (``plugins.petri_audit.credential_source.resolve_credential_source`` filters
# ``api_key`` out of ``auto`` expansion unless ``[self_improving_loop]
# fallback_to_payg=true``); an operator may still *explicitly* set
# ``source = "api_key"`` to opt in. The earlier type-level exclusion only caused
# the fragmentation above and blocked that explicit opt-in.
Source = CredentialSource
"""Backward-compat alias of :class:`CredentialSource` (the canonical enum)."""


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

    CSP-14 (2026-05-23) — adds ``max_papers`` + ``queries_per_run`` for
    the Loop 3 (literature paper-analysis) port. Only the
    ``literature_review`` role consults them; other roles ignore the
    knobs. ``max_papers = 0`` (default) short-circuits the phase to a
    no-op; 1-20 = active per-paper loop.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    source: Source
    num_turns: int = 0
    max_papers: int = 0
    queries_per_run: int = 3

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

    @model_validator(mode="after")
    def _max_papers_in_range(self) -> SelfImprovingLoopBindings:
        # CSP-14 — mirror manifest-side bounds for literature_review.
        if self.max_papers < 0 or self.max_papers > 20:
            raise ValueError(f"max_papers={self.max_papers} invalid; must be 0 (off) or in [1, 20]")
        if self.queries_per_run < 1 or self.queries_per_run > 10:
            raise ValueError(f"queries_per_run={self.queries_per_run} invalid; must be in [1, 10]")
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
    same role from different angles. ``core/self_improving/train.py`` calls
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
    source: Source = CredentialSource.CLAUDE_CLI


class AutoresearchConfig(BaseModel):
    """core/self_improving/train.py runtime knobs + per-role model bindings.

    Step J-b.1 (2026-05-23) — **autoresearch is the control-layer SoT**
    for every model selection in the self-improving pipeline. Pipeline:

    ``run → seed gen → petri baseline → autoresearch [GEODE 노출 표면
    조정] → petri audit → autoresearch [Drop | commit 판단] → 표면
    재조정 (반복)``

    Control flows top-down — autoresearch is the upper layer that
    decides what models the audit (executor) uses and what model the
    mutator runner uses for surface engineering. The previous PR #1496
    (2026-05-22) collapse moved the SoT *into* ``[petri.<role>]``, but
    that placed config ownership in the executor layer. Step J-b.1
    relocates the SoT back to the control layer while keeping a
    1-release back-compat reader on the old sections.

    Four sub-roles live here as nested objects:

    - ``target`` / ``judge`` / ``auditor`` — petri eval roles. The
      petri_audit role binding resolver (``get_binding``) reads from
      these.
    - ``mutator`` — autoresearch's own in-process LLM (the engineer
      that proposes GEODE surface mutations). Consumed by
      ``core/self_improving/loop/runner.py:_default_llm_call``.

    Standalone ``geode audit`` (run outside the self-improving loop)
    still reads the same sections — same single SoT, just different
    invocation context.

    The legacy ``target_model`` / ``judge_model`` string slots remain
    as deprecated no-op fields (back-compat with pre-2026-05-22
    configs); operators on those configs already see them silently
    ignored, so this PR doesn't change that behaviour.
    """

    model_config = ConfigDict(extra="forbid")

    budget_minutes: Annotated[int, Field(ge=1, le=600)] = 5

    # Step J-b.1 — role sub-fields (the SoT relocation).
    target: PetriRoleConfig = Field(default_factory=PetriRoleConfig)
    """petri eval ``target`` role binding (model + source). Read by
    :func:`plugins.petri_audit.registry.get_binding` when the runtime
    resolves the audit target."""
    judge: PetriRoleConfig = Field(default_factory=PetriRoleConfig)
    """petri eval ``judge`` role binding."""
    auditor: PetriRoleConfig = Field(default_factory=PetriRoleConfig)
    """petri eval ``auditor`` role binding."""
    mutator: MutatorConfig = Field(default_factory=lambda: MutatorConfig())
    """In-process mutator runner binding. Consumed by
    :func:`core.self_improving.loop.runner._default_llm_call`."""

    mutator_feedback_window: Annotated[int, Field(ge=0, le=200)] = 20
    """PR-MUTATOR-HISTORY-FEEDBACK (2026-05-27) — number of most-recent
    ``ApplyRecord`` + ``AttributionRecord`` rows fed back into the
    mutator's user prompt as a compact per-dim credit + kind×dim
    matrix summary.

    Default ``20`` matches the operator dashboard convention
    (``core/cli/commands/self_improving.py:_WIRE_DEFAULT_LAST``, PR-WIRE-1).
    Same window across both surfaces means the mutator sees the same
    slice the operator inspects in ``geode self-improve wire`` — single
    source of truth for "what counts as recent history". The PR-WIRE-1
    pick was itself anchored at "≈25-day window at min_interval=20h",
    which keeps the recency signal load-bearing without saturating
    the prompt budget.

    ``0`` disables the feedback block entirely (legacy behaviour
    before PR-MUTATOR-HISTORY-FEEDBACK). Cap of 200 prevents an
    operator from blowing the mutator prompt budget — the formatted
    block is roughly 20-40 tokens per record, so 200 rows ≈ 6-8 KB
    of prompt overhead.
    """

    mutator_dedup_window: Annotated[int, Field(ge=0, le=200)] = 20
    """PR-MUTATOR-DEDUP-GUARD (2026-05-27) — number of most-recent
    apply rows checked for repetitive mutation similarity. The runner
    rejects a proposal whose ``(target_kind, target_section, new_value)``
    triple has a ``difflib.SequenceMatcher.ratio()`` above
    ``mutator_dedup_threshold`` against any row in this window.

    Default ``20`` mirrors :attr:`mutator_feedback_window` — operators
    only need to reason about one "recent history" length across the
    two related guards. ``0`` disables the dedup check (legacy
    behaviour). Cap 200 mirrors the feedback window cap for symmetry.
    """

    mutator_dedup_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.85
    """PR-MUTATOR-DEDUP-GUARD (2026-05-27) — similarity threshold above
    which a proposed mutation is treated as a repeat of a recent apply
    row and rejected. Uses ``difflib.SequenceMatcher.ratio()`` from
    Python stdlib, which the official docs (cpython
    ``Lib/difflib.py:get_close_matches`` default ``cutoff=0.6``) describe
    as "a measure of the sequences' similarity as a float in the range
    [0, 1]".

    Default ``0.85`` is **conservative dedup**: stdlib's own
    ``get_close_matches`` defaults to ``0.6`` for "close matches" in
    typo-correction contexts; ``0.85`` sits well above that band so
    only near-identical mutations trigger the guard. The threshold
    catches cosmetic whitespace / phrasing edits (ratio typically
    ≥0.9) while letting the mutator iterate on a section it has
    touched before with materially new content (ratio typically
    ≤0.7 after a meaningful rewrite). Operators tuning the guard
    can drop to ``0.75`` for stricter dedup or raise to ``0.95`` to
    only block exact-duplicate proposals.
    """

    anchor_confidence_mode: bool = False
    """P3-revised (2026-05-25, SPCT + Meta-Rewarding) — anchor 3
    (admirable / disappointing / needs_attention) → fitness 의 confidence
    multiplier routing knob. plan ``docs/plans/2026-05-25-p3-anchor-calibration-crm-spct.md``.

    - ``False`` (default, legacy): anchor 3 가 dim_means 에 measured 되지만
      fitness 계산에는 weight=0 (제외). PR-5 이전 동작 그대로.
    - ``True``: ``compute_anchor_confidence_multiplier`` helper 가
      ``0.7 + 0.3 × normalized_anchor`` range [0.7, 1.0] 의 multiplier
      산출. caller (core/self_improving/train.py compute_fitness — P3.1 후속 wiring)
      가 base_fitness × multiplier 적용.

    사용자 결정 D2 (2026-05-25): anchor 3 → self-improving loop baseline 의
    input. PSM 패턴 거부 후 RL-derived (AutoGLM ORM confidence band).
    """

    target_model: str | None = None
    """**Deprecated pre-PR #1496 slot** — surviving for back-compat
    config file load. Never consulted at runtime. Will be dropped in a
    future release once operator configs are migrated to the
    ``[self_improving_loop.autoresearch.target] model = ...`` shape."""
    judge_model: str | None = None
    """**Deprecated pre-PR #1496 slot** — see :attr:`target_model`."""
    # PR-SIL-5THEME C6 (2026-05-23) — default ``auto`` → ``claude-cli``.
    # Operator decision (``project_payg_exclusion_decision.md``, 2026-05-23)
    # 으로 ``api_key`` 는 ``Source`` literal 에서 제거. ``auto`` 는 manifest
    # cascade 가 PAYG 까지 silent fallback 가능 → ``claude-cli`` (Claude
    # Code Max OAuth) 가 새 default.
    source: Source = CredentialSource.CLAUDE_CLI
    """Credential source for the audit subprocess. PR-SIL-5THEME C6 후 PAYG
    (``api_key``) 는 Source literal 에서 제거. ``claude-cli`` = Claude Code
    Max OAuth (default), ``openai-codex`` = ChatGPT subscription OAuth, ``auto`` =
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
    """The **co-evolving** seed pool that supplies SELECTION PRESSURE.

    This pool *mutates across generations* — the seed-generation co-scientist
    grows / replaces adversarial seeds alongside the agent, and
    :func:`core.self_improving.train._resolve_seed_select` swaps in the freshest
    survivor pool. Because the seed set moves every generation, the fitness it
    produces is a *moving ruler*: useful for ranking candidates WITHIN a
    generation (the (1+1) accept/revert decision), NOT for comparing fitness
    ACROSS generations. Cross-generation comparability is the job of
    :attr:`held_out_bench`."""
    held_out_bench: str | None = None
    """E2 (2026-05-30) — a **VERSION-FROZEN held-out** seed set, NEVER mutated,
    used ONLY to MEASURE fitness on a *fixed ruler*.

    Where :attr:`seed_select` co-evolves (and so cannot anchor a cross-generation
    fitness curve), ``held_out_bench`` is a directory of frozen seeds that the
    mutator / seed-generation loop must NOT touch. Scoring the champion on this
    fixed set every promote yields a ``held_out_fitness`` whose values ARE
    comparable across generations — it is the only curve that counts as evidence
    of real improvement.

    ``None`` (default) → no held-out bench is configured; the held-out fields are
    omitted from the baseline registry row (backward-compatible: existing readers
    see the same shape they always have). Set this to a frozen seed directory path
    (absolute, ``~``-relative, or repo-relative — same shape as ``seed_select``)
    to activate the fixed-ruler measurement.

    Resolution precedence is mirrored from ``seed_select`` in
    :func:`core.self_improving.train._resolve_held_out_bench` (env
    ``GEODE_HELD_OUT_BENCH`` / ``AUTORESEARCH_HELD_OUT_BENCH`` → this config field
    → ``None``)."""
    promote_policy: Literal["gate", "random", "never"] = "gate"
    """E3 (2026-05-30) — the **control-arm promote policy** for a matched 3-arm
    held-out comparison (selection vs no-mutation vs random-accept):

    - ``"gate"`` (default) — today's behaviour: the ``_should_promote`` fitness
      gate decides. The SELECTION arm.
    - ``"random"`` — random-accept control: the mutation is still applied +
      audited, but the PROMOTE decision is a coin-flip from a SEEDED RNG
      (``promote_policy_seed`` + the cycle index), NOT the gate. Reproducible.
    - ``"never"`` — no-mutation floor: never promote (baseline frozen across the
      campaign). Each cycle still scores the held-out → the curve shows pure
      drift / judge-noise — the floor the other arms must beat.

    Each arm is run as its OWN full N-cycle campaign; the per-cycle held-out
    records are tagged with this policy so the three arms' curves are
    distinguishable + comparable on the shared frozen ruler. ``promote_policy``
    is also part of the baseline epoch spec (gate / random / never hash to
    different epochs — different production logic, correctly not averaged).

    Resolution precedence mirrors ``held_out_bench``:
    :func:`core.self_improving.train._resolve_promote_policy` (env
    ``GEODE_PROMOTE_POLICY`` / ``AUTORESEARCH_PROMOTE_POLICY`` → CLI
    ``--promote-policy`` → this config field → ``"gate"``)."""
    promote_policy_seed: int = 0
    """E3 (2026-05-30) — the explicit RNG seed for ``promote_policy="random"``.

    The random arm's per-cycle promote draw is ``Random(seed + cycle_index)``,
    so the entire random campaign is reproducible (no bare nondeterminism) and is
    RECORDED on the held-out + baseline rows. Ignored for the ``gate`` / ``never``
    arms. Resolution precedence mirrors ``promote_policy``
    (:func:`core.self_improving.train._resolve_promote_policy_seed`)."""
    replicate: Annotated[int, Field(ge=1, le=20)] = 1
    """E4 (2026-05-30) — per-mutation REPLICATE count ``M``.

    The audit is run ``M`` times per mutation/cycle to estimate the WITHIN-mutation
    variance (provider non-determinism) SEPARATELY from the BETWEEN-seed variance
    (the N samples inside one audit). ``M=1`` (default) leaves today's behaviour
    unchanged — the audit runs once, within-mutation variance is honestly left
    unestimated, and there is NO extra cost. ``M>1`` runs ``M`` full audits (so the
    cost scales linearly — the operator opts in for the variance decomposition).
    Resolution precedence mirrors ``promote_policy`` (env ``GEODE_AUDIT_REPLICATE``
    / ``AUTORESEARCH_REPLICATE`` → CLI ``--replicate`` → this config field → ``1``)."""
    target_effect_size: Annotated[float, Field(gt=0.0, le=1.0)] = 0.02
    """E4 (2026-05-30) — the fitness-scale effect size δ the power analysis targets.

    Feeds :func:`core.self_improving.loop.statistical_power.required_samples` to
    compute the required ``N_seed × M_replicate`` to DETECT δ at α=0.05 / 80% power.
    Default ~0.02 sits just above the promote gate's zero-noise floor — see the
    ``DEFAULT_TARGET_EFFECT_SIZE`` docstring for the full justification. Resolution
    precedence mirrors ``replicate`` (env ``GEODE_TARGET_EFFECT_SIZE`` /
    ``AUTORESEARCH_TARGET_EFFECT_SIZE`` → CLI ``--target-effect-size`` → this config
    field → ``0.02``)."""
    dim_set: str = "subset"
    max_turns: Annotated[int, Field(ge=1, le=200)] = 10


class MutatorConfig(BaseModel):
    """Mutator-role binding for ``core/self_improving/loop/runner.py``.

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
    source: CredentialSource = CredentialSource.AUTO
    """Canonical :class:`CredentialSource`. The router's credential rotator
    consumes the same enum via ``[petri.source.<provider>]``."""
    max_tokens: Annotated[int, Field(ge=128, le=200_000)] = 1024
    """Passed through to ``adapter.acomplete``."""


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
    (``~/.geode/autoresearch/handoff/auto_trigger.lock`` via
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
    on ``~/.geode/autoresearch/handoff/auto_trigger_last_run.txt``).
    Cron firings closer together than this are silently skipped — the
    lockfile already prevents concurrent runs, this knob prevents
    *back-to-back* runs. Must satisfy ``min_interval_minutes <= cron
    period`` for the schedule to actually fire."""

    max_generation: Annotated[int, Field(ge=0, le=100_000)] = 0
    """PR-MAX-GEN (2026-05-26) — hard cap on total ``fired`` rows in
    ``~/.geode/autoresearch/handoff/auto_trigger_history.jsonl``. When
    the cap is reached the trigger returns ``max_generation_reached``
    without invoking the mutator runner. ``0`` (default) preserves
    legacy unbounded behaviour — recommended only for operators who
    set ``min_interval_minutes`` aggressively and trust the cron
    expression. Suggested production value: ``100`` (covers ~25 days
    at min_interval=360 = 6h). Closes 2026-05-26 attribution sprint
    Phase A audit (§5.6) — runaway auto-trigger no-stop-condition
    leak. The cap is checked both pre-lock (skips no-op lock acquire
    when the history is already saturated) and post-lock (catches the
    race where two parallel callers both observed count=N-1 before
    either appended). Operators needing strict uniqueness across
    independent host processes should also pick a cron expression
    that fires less frequently than ``min_interval_minutes``."""


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

    openai_source: Source | None = None
    """Single entry point for the OpenAI credential lane of the **autoresearch
    audit subprocess, target, and mutator** roles.

    That OpenAI surface is split across three sub-fields that each drive a
    distinct consumer: ``autoresearch.source`` (the ``geode audit`` subprocess's
    ``--use-oauth`` flag, ``core/self_improving/train.py``), ``autoresearch.target.source``
    (the petri ``target`` adapter via ``plugins.petri_audit.registry.get_binding``),
    and ``autoresearch.mutator.source`` (the in-process mutator LLM via
    ``core/self_improving/loop/runner.py:_default_llm_call``). Keeping them in
    sync by hand is the kind of three-place edit that silently drifts, so this
    field is the ONE knob an operator flips to move those three between
    subscription and PAYG:

    - ``"openai-codex"`` → ChatGPT subscription OAuth (per-minute rate-limited)
    - ``"api_key"``      → OpenAI PAYG (api.openai.com, no per-minute cap)

    Only those two values are accepted (``_openai_source_is_openai_lane``); it is
    an OpenAI-lane knob, not a general source default. **Scope** — it does NOT
    reach the Anthropic ``auditor`` / ``judge`` roles (they carry their own
    ``source``) nor the ``[self_improving_loop.seed_generation]`` voters (those
    pin their own source in the seed-generation manifest); those are separate
    surfaces by design.

    When set, ``_propagate_openai_source`` fills the three sub-fields and is
    **authoritative** — a per-role ``source`` that was *explicitly* set to a
    different value is superseded with a ``UserWarning`` (visible, but not a
    swallowed ``ValidationError`` — so the chosen lane is deterministic even on
    the petri-CLI ``read_role_override`` path that gracefully degrades on
    validation errors). ``None`` (default) → no propagation; each role keeps its
    own ``source`` (full back-compat)."""

    warn_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    """Quota usage ratio above which the FE banner turns yellow."""

    abort_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.9
    """Quota usage ratio above which the FE banner turns red and the
    run aborts."""

    # Per-component sub-configs
    autoresearch: AutoresearchConfig = Field(default_factory=AutoresearchConfig)
    """Control-layer SoT — owns ``target`` / ``judge`` / ``auditor`` /
    ``mutator`` role bindings (Step J-b.1)."""
    seed_generation: SeedGenerationConfig = Field(default_factory=SeedGenerationConfig)

    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    """PR-OL-A1 — auto-trigger schedule. Default off; operator opts in
    via ``[self_improving_loop.scheduler] enabled = true``. The cron
    fires the mutator runner with lockfile + min-interval guards."""

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_role_namespaces(cls, data: Any) -> Any:
        """Step J-b.1 — relocate model SoT from executor to control layer.

        The previous layout placed audit role bindings under
        ``[self_improving_loop.petri.<role>]`` (executor namespace)
        and the mutator binding under ``[self_improving_loop.mutator]``
        (top-level). Step J-b.1 reunites them inside
        ``[self_improving_loop.autoresearch.<role>]`` because
        autoresearch is the control layer that decides what runs.

        This validator pops the legacy sections from the raw input dict
        and grafts them under ``autoresearch`` so old configs keep
        loading. A ``DeprecationWarning`` fires on each migration so
        operators see the new location in their next config edit.

        The fields are removed from the schema (``extra="forbid"``)
        rather than kept as no-op slots so future operator typos
        ``[self_improving_loop.petr.target]`` fail loudly instead of
        silently ignoring the binding.
        """
        if not isinstance(data, dict):
            return data
        autoresearch_section = data.setdefault("autoresearch", {})
        if not isinstance(autoresearch_section, dict):
            return data  # let pydantic surface the type error

        legacy_petri = data.pop("petri", None)
        if isinstance(legacy_petri, dict) and legacy_petri:
            for role_name in ("target", "judge", "auditor"):
                if role_name in legacy_petri and role_name not in autoresearch_section:
                    autoresearch_section[role_name] = legacy_petri[role_name]
            warnings.warn(
                "[self_improving_loop.petri.*] is deprecated; move audit "
                "role bindings to [self_improving_loop.autoresearch.<role>] "
                "(autoresearch is the control-layer SoT). The legacy "
                "section will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2,
            )

        legacy_mutator = data.pop("mutator", None)
        if isinstance(legacy_mutator, dict) and legacy_mutator:
            if "mutator" not in autoresearch_section:
                autoresearch_section["mutator"] = legacy_mutator
            warnings.warn(
                "[self_improving_loop.mutator] is deprecated; move the "
                "mutator binding to [self_improving_loop.autoresearch.mutator] "
                "(autoresearch owns its own engineering LLM). The legacy "
                "section will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2,
            )

        return data

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

    @model_validator(mode="after")
    def _propagate_openai_source(self) -> SelfImprovingLoopConfig:
        """Fan the single ``openai_source`` knob out to the three OpenAI-role sources.

        Runs after the legacy-namespace migration (``mode="before"``) has already
        grafted ``[petri.*]`` / ``[mutator]`` into ``autoresearch``, so the three
        sub-models are fully populated and their ``model_fields_set`` faithfully
        reflects what the operator pinned explicitly.

        A sub-field that the operator set explicitly to a DIFFERENT value raises
        (ambiguous — the operator should drop the per-role pin or align it). An
        explicit pin equal to ``openai_source`` is allowed (redundant, harmless).
        Anything left at its schema default is overwritten with ``openai_source``.
        """
        if self.openai_source is None:
            return self
        lane = self.openai_source
        ar = self.autoresearch

        def _apply(current: Source, explicit: bool, path: str) -> Source:
            # Authoritative: openai_source supersedes an explicit per-role pin, but
            # WARNS (not raises) so the resolved lane is deterministic even on the
            # ``read_role_override`` path that swallows ValidationError for graceful
            # petri-CLI degradation. A swallowed conflict-raise there would let the
            # target silently fall back to the manifest cascade — the warn+overwrite
            # avoids that entirely.
            if explicit and current != lane:
                warnings.warn(
                    f"[self_improving_loop] openai_source={lane.value!r} supersedes the "
                    f"explicit {path}={current.value!r} (openai_source is the single entry "
                    f"point for the OpenAI credential lane). Remove the per-role source pin "
                    f"to silence this.",
                    UserWarning,
                    stacklevel=2,
                )
            return lane

        # Direct per-field assignment (not a heterogeneous loop) so each owner is
        # concretely typed and carries its own ``source`` attribute.
        ar.source = _apply(ar.source, "source" in ar.model_fields_set, "autoresearch.source")
        ar.target.source = _apply(
            ar.target.source, "source" in ar.target.model_fields_set, "autoresearch.target.source"
        )
        ar.mutator.source = _apply(
            ar.mutator.source,
            "source" in ar.mutator.model_fields_set,
            "autoresearch.mutator.source",
        )
        return self

    @field_validator("openai_source")
    @classmethod
    def _openai_source_is_openai_lane(cls, value: Source | None) -> Source | None:
        """Restrict the knob to the two OpenAI credential lanes.

        ``openai_source`` is an OpenAI-lane selector, not a general source default —
        ``auto`` / ``claude-cli`` would propagate to the OpenAI roles (e.g. route the
        mutator through Claude CLI), which is never what an OpenAI-lane knob should do.
        """
        if value is not None and value not in (
            CredentialSource.OPENAI_CODEX,
            CredentialSource.API_KEY,
        ):
            raise ValueError(
                f"openai_source must be 'openai-codex' (subscription) or 'api_key' (PAYG), "
                f"got {value.value!r}. It selects only the OpenAI credential lane; Anthropic "
                f"roles carry their own source."
            )
        return value


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
    """Notify the active RunTranscript that the loader fell back to defaults.

    P2 — closes the "config loader default sub silent" gap from the
    2026-05-19 observability audit §4. ``reason`` is one of
    ``file_missing`` / ``read_error`` / ``section_missing`` so the
    operator can tell which fallback fired without re-reading the file.
    The emit is a no-op outside an :func:`run_transcript_scope` so
    callers that load the config without an active audit run (REPL
    bootstrap, petri user-overrides) stay unaffected.
    """
    try:
        from core.self_improving.loop.run_transcript import current_run_transcript

        journal = current_run_transcript()
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
