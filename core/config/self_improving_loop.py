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
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

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
# ``openai-codex`` (ChatGPT subscription OAuth) / ``auto`` (manifest cascade).
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
    """autoresearch/train.py runtime knobs + per-role model bindings.

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
      ``core/self_improving_loop/runner.py:_default_llm_call``.

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
    :func:`core.self_improving_loop.runner._default_llm_call`."""

    # P1-revised (2026-05-25) — DAPO-inspired variance gate + GRPO-inspired
    # group-relative scoring 의 *selection* layer 만 inference-time 으로 채택.
    # **Not policy optimization; no parameter update; no gradient.** 본 sprint
    # plan: ``docs/plans/2026-05-25-baseline-fitness-rl-grounding.md``.
    group_size: Annotated[int, Field(ge=1, le=8)] = 1
    """Number of sibling mutations to propose+audit per self-improving cycle.

    - ``1`` (default): legacy (1+1)-ES + previous-baseline 비교. group sampling
      disabled, backward-compat 보존.
    - ``2`` (MVP): N=2 sibling parallel mutator call + sequential audit + group
      mean/std → DAPO-inspired variance gate + GRPO-inspired z-score ranking.
      P1-revised 의 시작값.
    - ``4`` (full): frontier-inspired (GRPO uses N=8 for *training* — here we
      use it for *selection* only, cost-trimmed). audit cost 4x 부담.

    cost 영향 — N 배 audit cost (subscription source 는 quota window 안에서
    무료, ``core/llm/audit_lane.py`` OL-P2 audit_lane=1 으로 sequential 강제).
    """

    group_variance_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.01
    """DAPO-inspired variance gate threshold ε.

    N sibling mutation 의 fitness std 가 이 값 미만이면 group 폐기 (cycle skip
    + log). gate 의 의도: 모든 sibling 이 비슷한 결과를 내면 selection signal
    0 → 무신호 cycle 의 audit cost 낭비 회피 (DAPO paper reports wall-clock
    25% saving when applied as a *training* filter — here we use it as a
    *selection* gate, separate concern).

    Default 0.01 is a placeholder — no externally-verified production value
    is currently grounded for this knob. PR-VAR-ADAPTIVE (2026-05-27)
    closes the follow-up with the ``group_variance_threshold_mode`` /
    ``group_variance_history_window`` / ``group_variance_percentile``
    knobs below. When ``mode="percentile"`` and the history has ≥window
    entries, this fixed value is ignored in favour of the percentile.
    """

    group_variance_threshold_mode: Literal["fixed", "percentile"] = "fixed"
    """PR-VAR-ADAPTIVE (2026-05-27) — variance gate threshold source.

    - ``"fixed"`` (default, backward-compat): use
      ``group_variance_threshold`` as the hard floor regardless of
      observed history. Legacy behaviour preserved.
    - ``"percentile"``: read
      ``autoresearch/state/group_variance_history.jsonl`` (git-tracked),
      filter to the most recent ``group_variance_history_window``
      entries for the active ``target_kind`` (when available — else
      pooled across kinds), and use the ``group_variance_percentile``
      th-percentile std as the threshold. When the history has fewer
      than the window count, falls back to the fixed value so an
      operator can enable the mode without bootstrapping a synthetic
      history. Closes the 2026-05-26 attribution sprint Phase A
      audit's "fitness-scale drift" concern — operators changing
      fitness_margin_floor or weight schemas no longer need to
      manually re-tune the variance threshold.
    """

    group_variance_history_window: Annotated[int, Field(ge=5, le=1000)] = 30
    """PR-VAR-ADAPTIVE (2026-05-27) — number of history entries to use
    when computing the percentile threshold. Default 30 ≈ 25 day window
    at min_interval=20h. Below the window count the percentile mode
    falls back to ``group_variance_threshold`` (fixed). Range floor of
    5 ensures the percentile has enough samples to be meaningful;
    ceiling of 1000 caps memory + read latency."""

    group_variance_percentile: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.05
    """PR-VAR-ADAPTIVE (2026-05-27) — which percentile of historical
    group std becomes the threshold. ``0.05`` = 5th percentile (skip
    only the bottom 5% of historical variance, i.e. the truly
    low-signal groups). Higher values (e.g. ``0.10``) are more
    aggressive at filtering. Must be in ``(0.0, 1.0)`` — exact 0 / 1
    are degenerate."""

    max_group_resamples: Annotated[int, Field(ge=0, le=10)] = 0
    """PR-RESAMPLE-BUDGET (2026-05-27) — number of additional group
    proposals to attempt when ``_compute_group_advantage`` returns
    ``filtered_low_variance``. ``0`` (default) preserves legacy
    behaviour (one shot, low-variance group → cycle skip). Non-zero
    enables a retry loop bounded by this budget. DAPO frontier
    equivalent: ``max_num_gen_batches`` — informative-batch
    retention. Each retry costs N audit subprocesses, so the
    operator-facing knob is bounded at 10."""

    resample_on_low_variance: bool = False
    """PR-RESAMPLE-BUDGET (2026-05-27) — must be True for
    ``max_group_resamples`` to take effect. Separate flag (vs reading
    ``max_group_resamples > 0`` directly) so an operator can pre-set
    the budget but keep the feature disabled until A/B data validates
    it. Default False preserves backward-compat."""

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

    pareto_mode: bool = False
    """P2-revised (2026-05-25) — Pareto archive + Dynamic Reward Weighting
    enable knob. plan ``docs/plans/2026-05-25-p2-pareto-archive-dynamic-reward-weighting.md``.

    - ``False`` (default, legacy): apply_group_proposals 의 top-1 by linear
      advantage. PR-5 P1-revised 동작 그대로.
    - ``True``: archive 의 Pareto-non-dominated set 에 mutation insert +
      sample. concave Pareto front 영역 도달 가능 (Das-Dennis 1997 한계
      회피). group_size>=2 와 결합 시 의미 (single mutation 은 archive
      비교 없음).

    pareto_mode=True 시 ``baseline_archive.jsonl`` writer 활성.
    """

    hypervolume_reference_point: dict[str, float] = Field(default_factory=dict)
    """P2-revised — hypervolume 계산의 reference point (per-dim nadir,
    worst-case). 빈 dict 이면 archive entry 의 dim 최솟값 자동 사용.

    Higher-is-better convention — caller 는 good-low palette dim 의 score
    를 미리 invert (e.g., ``10 - input_hallucination_score``). reference
    point 는 unreachable worst-case (e.g., dim 별 0).
    """

    sub_agent_count: Annotated[int, Field(ge=1, le=5)] = 1
    """P4 (2026-05-25, Kimi K2.6 PARL inference-time 변형) — swarm-level
    sub-agent 개수. plan ``docs/plans/2026-05-25-p4-parl-swarm-scaffolding.md``.

    - ``1`` (default, legacy): single mutation chain. P1-revised group
      sampling (group_size) 만 활성.
    - ``3``: MVP — 3 sub-agent 가 각자 다른 agent_contract policy slice
      로 mutation chain 진행. swarm-mean baseline.
    - ``5``: full — Kimi K2.6 PARL 의 inference-time 축소판.

    audit cost = sub_agent_count × group_size × per-cycle cost. config
    cap = 5 로 unconstrained cost explosion 방지.
    """

    swarm_aggregation: Literal["mean", "median", "max"] = "mean"
    """P4 — sub-agent fitness aggregation strategy. ``mean`` 이 PARL 의
    swarm-mean 패턴 (Kimi K2.6 추정). ``median`` 은 outlier-resilient,
    ``max`` 는 best-of-M exploration."""

    anchor_confidence_mode: bool = False
    """P3-revised (2026-05-25, SPCT + Meta-Rewarding) — anchor 3
    (admirable / disappointing / needs_attention) → fitness 의 confidence
    multiplier routing knob. plan ``docs/plans/2026-05-25-p3-anchor-calibration-crm-spct.md``.

    - ``False`` (default, legacy): anchor 3 가 dim_means 에 measured 되지만
      fitness 계산에는 weight=0 (제외). PR-5 이전 동작 그대로.
    - ``True``: ``compute_anchor_confidence_multiplier`` helper 가
      ``0.7 + 0.3 × normalized_anchor`` range [0.7, 1.0] 의 multiplier
      산출. caller (autoresearch/train.py compute_fitness — P3.1 후속 wiring)
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
    source: Source = "claude-cli"
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

    max_generation: Annotated[int, Field(ge=0, le=100_000)] = 0
    """PR-MAX-GEN (2026-05-26) — hard cap on total ``fired`` rows in
    ``~/.geode/self-improving-loop/auto_trigger_history.jsonl``. When
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
        from core.self_improving_loop.run_transcript import current_run_transcript

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
