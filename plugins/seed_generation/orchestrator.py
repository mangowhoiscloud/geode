"""Pipeline orchestrator — 7-phase generate-debate-evolve loop.

Maps the ADR-001 7-phase topology (Generation → Proximity → Reflection
→ Pilot → Ranking → Evolution → Meta-review) onto a sequential phase
dispatcher backed by :class:`PipelineRegistry`. Each phase is a method
that reads :class:`PipelineState`, looks up the role's agent from the
registry, awaits :meth:`BaseSeedAgent.aexecute`, and merges the
result's ``output`` dict back into state.

Why a flat orchestrator, not LangGraph
======================================

GEODE has no LangGraph in core. The ``SubAgentManager`` +
``IsolatedRunner`` + ``HookSystem`` already provide the supervisor
+ workers + observability pattern (depth=1 enforced — sub-agents
cannot recurse, so the parent ``AgenticLoop`` IS the StateGraph).
Each phase runs in the parent loop; within a phase, the role can
fan out via ``await self._manager.adelegate(tasks=[…])``.

Phases as methods
=================

The pipeline owns the phase sequence; the roles own the work. This
keeps the phase-order policy (and the bootstrap rule — first
generation runs with ``baseline=None``) at one place. The roles can
be swapped or omitted at runtime (e.g. a smoke-test run skips Pilot)
via the registry.

S1 skeleton scope
=================

This module ships the orchestrator class + state dataclass + registry
+ phase methods. The phase methods raise :class:`RuntimeError` with a
descriptive message when the role has no registered agent — this is
NOT a stub: the dispatch logic, hook events, state merging, and
budget plumbing are all functional. Concrete agents land in S2-S8 and
register themselves; once registered the phase calls succeed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.hooks import HookEvent, HookSystem
from core.memory.atomic_write import iter_jsonl

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult

if TYPE_CHECKING:
    from core.orchestration.lane_queue import LaneQueue

log = logging.getLogger(__name__)

__all__ = [
    "Pipeline",
    "PipelineRegistry",
    "PipelineState",
]


# PR-SEEDS-HIRES (2026-05-26) — task_id prefix → phase mapping used by
# :meth:`Pipeline._persist_per_phase_costs` when ``sub_agents/<task_id>/
# session.json`` lacks ``metadata.phase`` (older runs, test fixtures).
# Prefixes match the SubTask naming convention used by each agent.
_TASK_PREFIX_TO_PHASE: tuple[tuple[str, str], ...] = (
    ("super-", "supervisor"),
    ("lit-", "literature_review"),
    ("gen-", "generator"),
    ("prox-", "proximity"),
    ("crit-", "critic"),
    ("pilot-", "pilot"),
    ("vote-", "ranker"),
    ("evolve-", "evolver"),
    ("meta-", "meta_reviewer"),
)


def _infer_phase_from_task(task_dir: Path) -> str | None:
    """Determine the seed-gen phase a sub-agent belongs to.

    Prefers ``session.json.metadata.phase`` when present; falls back to
    the task_id directory-name prefix. Returns None when neither signal
    resolves (skipped silently — the cost rollup is informational).
    """
    session_path = task_dir / "session.json"
    if session_path.is_file():
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            meta = data.get("metadata") if isinstance(data, dict) else None
            phase_field = meta.get("phase") if isinstance(meta, dict) else None
            if isinstance(phase_field, str) and phase_field:
                return phase_field
        except (OSError, json.JSONDecodeError):
            pass
    name = task_dir.name
    for prefix, phase in _TASK_PREFIX_TO_PHASE:
        if name.startswith(prefix):
            return phase
    return None


def _state_to_json(state: PipelineState) -> str:
    """Serialize PipelineState fields safe for JSON persistence.

    Skips runtime-only fields (``run_dir`` path
    object). Path-typed fields are coerced to strings so the JSON is
    portable across machines (re-hydration converts back).
    """
    payload: dict[str, Any] = {
        "run_id": state.run_id,
        "target_dim": state.target_dim,
        # ADR-012 S4 (2026-05-21) — persist cohort so a state.json
        # replay re-hydrates the same picker semantics.
        "cohort": state.cohort,
        # PR-SG-SELECTION-ALIGN (2026-05-25, G4) — attribution dim set.
        # Resume path must rehydrate this so the evolver's anchor /
        # scenario_realism scope stays stable across a resume. Codex MCP
        # review of PR-CHECKPOINT-RESUME-TIMEBUDGET caught the omission.
        "target_dims_attribution": list(state.target_dims_attribution),
        "gen_tag": state.gen_tag,
        "candidates_requested": state.candidates_requested,
        "pool_path_in": str(state.pool_path_in) if state.pool_path_in else None,
        "pool_path_out": str(state.pool_path_out) if state.pool_path_out else None,
        "run_dir": str(state.run_dir) if state.run_dir else None,
        "candidates": state.candidates,
        "reflections": state.reflections,
        "pilot_scores": state.pilot_scores,
        "elo_ratings": state.elo_ratings,
        "survivors": state.survivors,
        "evolved_candidates": state.evolved_candidates,
        "meta_review": state.meta_review,
        "usd_spent": state.usd_spent,
        "prompt_tokens": state.prompt_tokens,
        "completion_tokens": state.completion_tokens,
        "baseline_means": state.baseline_means,
        "baseline_stderr": state.baseline_stderr,
        # CSP-4 (2026-05-22) — persist the Supervisor's run-level
        # guidance so a state.json replay carries the same strategy
        # the live run consumed (audit trail + reproducibility).
        "supervisor_guidance": state.supervisor_guidance,
        # CSP-5 (2026-05-22) — persist iteration cursor so a state.json
        # replay knows how many iteration cycles already ran.
        "max_iterations": state.max_iterations,
        "current_iteration": state.current_iteration,
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — per-phase
        # checkpoint audit trail. ``audit-seeds resume <run_id>`` reads
        # this list (or the union with on-disk checkpoints/<phase>.json
        # via ``checkpointer.list_completed_phases``) to skip
        # already-completed phases on the second walk through
        # ``_PHASE_ORDER``.
        "completed_phases": list(state.completed_phases),
        # CSP-8 (2026-05-22) — proximity LLM-clustering output. The
        # meta_reviewer + operator-readable summary both consume these
        # as a coverage signal (replaces the pre-CSP-8 proximity_graph).
        "similarity_clusters": state.similarity_clusters,
        "removed_duplicates": state.removed_duplicates,
        # CSP-13 (2026-05-23) — Loop 2 debate transcripts per candidate.
        # Codex MCP MEDIUM fix-up: persist so state.json replay shows
        # the multi-turn evidence the generator's debate produced, and
        # downstream meta_reviewer / operator inspection can audit
        # the per-candidate reasoning trail.
        "debate_transcripts": state.debate_transcripts,
        # CSP-14 (2026-05-23) — Loop 3 literature output. Both keys
        # are empty when ``max_papers = 0`` (default back-compat); the
        # synthesized block + per-paper snapshot paths persist so
        # state.json replay shows what evidence Generator/Critic saw.
        "articles_with_reasoning": state.articles_with_reasoning,
        "literature_snapshots": state.literature_snapshots,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _emit_orchestrator_event(
    event: str,
    *,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a seed-generation event into the active RunTranscript.

    P1c — closes the "per-stage transition silent" gap from the
    2026-05-19 observability audit §4. Discovered via the ContextVar
    that ``run_audit_seeds`` activates around ``pipeline.run()``; no-op
    outside that scope. SoT contract per P0a §6: payload carries only
    event-scoped context (role, duration_ms, error head), never
    canonical run-level metrics like ``survivors`` / ``usd_spent`` /
    ``pool_path_out`` which live in sessions.jsonl. Failure to emit is
    swallowed so the pipeline contract is unchanged.
    """
    try:
        from core.self_improving.loop.observe.run_transcript import current_run_transcript

        journal = current_run_transcript()
        if journal is None:
            return
        journal.append(event, level=level, payload=payload or {})
    except Exception:  # pragma: no cover - defensive
        log.debug("seed-generation: journal emit %s failed", event, exc_info=True)


_PHASE_ORDER: tuple[str, ...] = (
    # CSP-4 (2026-05-22) — Supervisor runs FIRST so its strategy
    # synthesis lands in ``state.supervisor_guidance`` before any
    # per-candidate phase prefixes the relevant ``phase_guidance.*``
    # entry into its own prompt. The phase short-circuits when no
    # Supervisor agent is registered (test fixtures that mock a
    # subset of roles) — see ``Pipeline._arun_phase``.
    "supervisor",
    # CSP-14 (2026-05-23) — Loop 3 (literature paper-analysis) of the
    # 3-loop port. Runs after Supervisor (which may emit a
    # ``phase_guidance.literature_review`` block) but BEFORE Generator
    # so the per-paper insights land in ``state.articles_with_reasoning``
    # for the Generator's prompt prefix. Short-circuits when
    # ``[seed_generation.role.literature_review] max_papers = 0``
    # (default — back-compat for runs that don't want external lit).
    "literature_review",
    "generator",
    "proximity",
    "critic",
    "pilot",
    "ranker",
    "evolver",
    "meta_reviewer",
)

# CSP-5 (2026-05-22) — phase sequence for iteration cycles 1..N
# (post-meta_reviewer of iteration 0). The Supervisor / Generator /
# Proximity steps DON'T re-run — iteration cycles operate on the
# *evolved* candidates that the previous iteration's Evolver
# produced, not on a fresh draft batch. Mirrors the paper's iteration
# loop (``meta_review → evolve → review → ranking → proximity``)
# adapted to GEODE's phase names: previous iteration ended with
# meta_reviewer; we promote its evolved_candidates into candidates,
# then critique / pilot / rank / evolve / meta-review again.
_ITERATION_PHASE_ORDER: tuple[str, ...] = (
    "critic",
    "pilot",
    "ranker",
    "evolver",
    "meta_reviewer",
)


@dataclass
class PipelineState:
    """In-flight pipeline state shared across the 7 phases.

    Mutated by each phase's :meth:`BaseSeedAgent.aexecute` return
    payload. Persisted at run end to
    ``state/seed_generation/<run_id>/state.json`` (S8 wires the
    offload via ``note_save``).
    """

    run_id: str
    target_dim: str
    gen_tag: str
    # ADR-012 S4 (2026-05-21) — seed cohort label. Default preserves
    # the pre-S4 contract (Petri 17-dim). Switching to ``"task_completion"``
    # tells the picker + downstream agents to interpret ``target_dim``
    # as a ux_means field (e.g. ``"success_rate"``).
    # See :mod:`plugins.seed_generation.baseline_reader.SEED_COHORTS`.
    cohort: str = "petri_17dim"
    # PR-SG-SELECTION-ALIGN (2026-05-25) — G4. Plural attribution scope
    # alongside singular ``target_dim`` (run-level INTENT). When
    # populated, this is the dim set the evolver frames its anchor /
    # scenario_realism rewrite around. Empty list preserves the
    # pre-G4 single-dim contract — callers that only set
    # ``target_dim`` behave exactly as before.
    target_dims_attribution: list[str] = field(default_factory=list)
    candidates_requested: int = 15
    # CSP-5 (2026-05-22) — paper §3 iteration loop. Default 0 keeps
    # the pre-CSP-5 single-pass behaviour (Pipeline.arun() executes
    # ``_PHASE_ORDER`` once and persists). With ``max_iterations >= 1``
    # the orchestrator re-enters the post-meta_reviewer cycle
    # (``_ITERATION_PHASE_ORDER``: critic → pilot → ranker → evolver →
    # meta_reviewer) that many times, promoting ``evolved_candidates``
    # into ``candidates`` between iterations. ``current_iteration`` is
    # the cursor (0 = initial draft batch).
    max_iterations: int = 0
    current_iteration: int = 0
    # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — audit trail
    # of phases that have written a per-phase checkpoint under
    # ``<run_dir>/checkpoints/<phase>.json``. ``arun(resume_from_phase=...)``
    # consults this list (post-hydrate) so a re-run is idempotent —
    # already-completed phases are skipped on the second pass.
    completed_phases: list[str] = field(default_factory=list)
    pool_path_in: Path | None = None
    pool_path_out: Path | None = None
    run_dir: Path | None = None
    # populated by phases
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reflections: dict[str, dict[str, Any]] = field(default_factory=dict)
    pilot_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    elo_ratings: dict[str, float] = field(default_factory=dict)
    survivors: list[str] = field(default_factory=list)
    evolved_candidates: list[dict[str, Any]] = field(default_factory=list)
    meta_review: dict[str, Any] = field(default_factory=dict)
    # CSP-8 (2026-05-22) — paper §3 proximity_node output. The Proximity
    # phase emits its LLM-clustering result here; the orchestrator reads
    # nothing from it (state.candidates is filtered in-place), but the
    # downstream meta_reviewer and the operator-readable state.json
    # snapshot both consume it as a coverage signal.
    similarity_clusters: list[dict[str, Any]] = field(default_factory=list)
    removed_duplicates: list[dict[str, Any]] = field(default_factory=list)
    # cost rollup
    usd_spent: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # baseline (None on first generation — bootstrap)
    baseline_means: dict[str, float] | None = None
    baseline_stderr: dict[str, float] | None = None
    # G3 — full BaselineSnapshot (dim_means + dim_stderr + evidence) loaded
    # from ``~/.geode/self-improving/baseline.json`` when the CLI flow auto-picks
    # or the operator explicitly opts into baseline-grounded generation. The
    # generator / critic / evolver agents read ``snapshot.evidence[target_dim]``
    # via :func:`plugins.seed_generation.baseline_reader.format_evidence_block`.
    # ``None`` = bootstrap run (no audit baseline yet) — agents fall through
    # to their non-baseline prompts.
    baseline_snapshot: Any = None
    # G4 — MetaReviewSnapshot loaded from the *previous* seed-generation
    # run's ``latest_meta_review.json``. Carries ``next_gen_priors`` +
    # ``underrepresented_dims`` so the current run's generator / critic
    # can attend to the gaps the prior run's meta-reviewer flagged.
    # ``None`` = no prior run (bootstrap) — agents skip the priors block.
    meta_review_snapshot: Any = None
    # CSP-4 (2026-05-22) — run-level strategy synthesis emitted by the
    # Supervisor phase (paper §3 Supervisor). Empty dict before
    # Supervisor runs OR when the role isn't registered (test fixtures).
    # Structure mirrors ``plugins/seed_generation/agents/supervisor.md`` contract:
    # ``research_goal_analysis`` + ``phase_guidance`` (keys: generation,
    # critique, evolution) + ``session_summary``. Downstream sub-agents
    # prefix the relevant ``phase_guidance.*`` value into their own
    # ``_build_description`` so each spawn shares one canonical reading
    # of the run's priors.
    supervisor_guidance: dict[str, Any] = field(default_factory=dict)
    # CSP-14 (2026-05-23) — Loop 3 (literature paper-analysis) of the
    # 3-loop port. Populated by the ``literature_review`` phase.
    # ``articles_with_reasoning`` is the markdown block consumed by
    # downstream Generator / Critic / Evolver prompts as a literature
    # evidence prefix; ``literature_snapshots`` is the arxiv_id →
    # snapshot path map for cross-ref with mutations.jsonl evidence and
    # the bundle's literature index. Both empty when the role's
    # ``max_papers = 0`` (back-compat, the default).
    articles_with_reasoning: str = ""
    literature_snapshots: dict[str, str] = field(default_factory=dict)
    # CSP-13 (2026-05-23) — Loop 2 (debate-turn) of the 3-loop port.
    # Maps ``candidate_id`` → ``[{turn, speaker, content, ts}, ...]``
    # parsed from the per-candidate ``.debate.jsonl`` sidecar the
    # ``seed_debate_turn`` tool writes inside each Generator sub-agent.
    # Empty dict when:
    #   - the manifest's ``[seed_generation.role.generator] num_turns``
    #     is 0 (single-shot path, debate disabled), OR
    #   - operator override at
    #     ``[self_improving_loop.seed_generation.roles.generator] num_turns = 0``
    #     overrides the manifest, OR
    #   - the sub-agent failed before emitting any turn (tool error
    #     budget exhausted etc.)
    # Downstream meta_reviewer reads this for coverage analysis.
    debate_transcripts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def merge(self, role: str, output: dict[str, Any]) -> None:
        """Merge a phase agent's ``output`` payload into state.

        Known keys are mapped onto the corresponding state field;
        unknown keys are ignored with a warning so the schema cannot
        silently drift.
        """
        known = {
            "candidates",
            "reflections",
            "pilot_scores",
            "elo_ratings",
            "survivors",
            "evolved_candidates",
            "meta_review",
            # CSP-4 (2026-05-22) — Supervisor phase output. Dict-typed
            # so ``merge`` overlays the new payload via ``dict.update``.
            "supervisor_guidance",
            # CSP-8 (2026-05-22) — Proximity phase paper-fidelity output
            # (replaces the pre-CSP-8 proximity_graph). Both list-typed
            # so the orchestrator's list-extend merge semantics keep the
            # full set across iterations (Proximity only runs in iter 0,
            # so a single extend is the steady state).
            "similarity_clusters",
            "removed_duplicates",
            # CSP-13 (2026-05-23) — Loop 2 debate transcripts (dict
            # keyed by candidate_id). Generator emits this only when
            # ``num_turns >= 2`` and the candidate sub-agent actually
            # ran turns; empty dict otherwise. Merge semantics: dict
            # update so iteration cycles can re-evolve the same
            # candidate ids without losing earlier transcripts.
            "debate_transcripts",
            # CSP-14 (2026-05-23) — Loop 3 literature output. Both
            # keys come from the ``literature_review`` agent. Merge
            # semantics: ``articles_with_reasoning`` is a string —
            # the merge handler overwrites with new value (the agent
            # runs once per run, iteration cycles don't re-emit, so
            # the second-write case is the test fixture path only).
            # ``literature_snapshots`` is a dict updated additively.
            "articles_with_reasoning",
            "literature_snapshots",
        }
        unknown = set(output) - known
        if unknown:
            log.warning(
                "seed-generation role=%r returned unknown output keys: %s",
                role,
                sorted(unknown),
            )
        for key in known & set(output):
            cur = getattr(self, key)
            new = output[key]
            if isinstance(cur, list):
                cur.extend(new)
            elif isinstance(cur, dict):
                cur.update(new)
            else:
                setattr(self, key, new)


class PipelineRegistry:
    """Role-name → ``BaseSeedAgent`` lookup, populated at startup.

    S2-S8 each register their role's concrete agent; the Pipeline
    constructor accepts the populated registry. Tests construct a
    registry with mock agents directly.
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseSeedAgent] = {}

    def register(self, agent: BaseSeedAgent) -> None:
        if agent.role in self._agents:
            log.warning("re-registering seed-generation role=%r", agent.role)
            _emit_orchestrator_event(
                "agent_reregistered",
                level="warn",
                payload={"role": agent.role},
            )
        self._agents[agent.role] = agent

    def get(self, role: str) -> BaseSeedAgent | None:
        return self._agents.get(role)

    def list_roles(self) -> list[str]:
        return list(self._agents.keys())

    def has(self, role: str) -> bool:
        return role in self._agents


class Pipeline:
    """Orchestrate the 7-phase generate-debate-evolve loop.

    Constructed once per ``geode audit-seeds generate`` invocation.
    :meth:`arun` walks ``_PHASE_ORDER`` and emits per-phase hook events.
    """

    def __init__(
        self,
        state: PipelineState,
        registry: PipelineRegistry,
        *,
        hooks: HookSystem | None = None,
        lane_queue: LaneQueue | None = None,
        on_phase_error: Any | None = None,
        bindings: dict[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self._hooks = hooks
        self._lane_queue = lane_queue
        self._on_phase_error = on_phase_error
        # v0.99.40 Follow-up B — picker-resolved per-role bindings
        # (``role_name → RoleBinding``). Stored for observability /
        # journaling; agents themselves are already constructed with
        # the binding's model + source, so the Pipeline does not re-
        # inject the values into SubTask creation.
        self.bindings = bindings or {}

    async def arun(self, *, resume_from_phase: str | None = None) -> PipelineState:
        """Walk the 7 phases (then optional iteration cycles). Returns the final state.

        PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — when
        ``resume_from_phase`` is set, iteration 0 starts at that phase
        and earlier phases are skipped (idempotent — their checkpoints
        already populated ``state.candidates`` / ``reflections`` /
        ``pilot_scores`` etc.). The caller (CLI ``audit-seeds resume``)
        is responsible for hydrating ``state`` from
        ``<run_dir>/checkpoints/<phase>.json`` before invoking
        ``arun``. Pass ``None`` (default) for a fresh run.

        PR-Async-Phase-C step 2 (2026-05-22) — async-native pipeline
        walker. Replaces sync ``run`` which is now a deprecation
        shim. Each phase calls :meth:`_arun_phase` (await), which
        acquires the OpenClaw lane chain via the LaneQueue's
        async ``acquire_all_async`` and awaits the agent's
        :meth:`BaseSeedAgent.aexecute` — fan-out via
        :meth:`SubAgentManager.adelegate` inside the agent.
        """
        log.info(
            "seed-generation run started: run_id=%s target=%s gen=%s max_iters=%d",
            self.state.run_id,
            self.state.target_dim,
            self.state.gen_tag,
            self.state.max_iterations,
        )
        started_at = time.time()
        aborted = False
        # PR-SEEDS-HIRES (2026-05-26) — start background live-sync loop
        # so the published bundle reflects in-flight transcripts +
        # progress every 5s. Cancelled at run end (after final
        # _persist_progress).
        self._live_run_started_at = started_at
        self._phase_durations_ms: dict[str, float] = {}
        self._persist_progress(current_phase="starting", current_step=None)
        live_sync_task = asyncio.create_task(self._live_sync_loop())
        # CSP-5 (2026-05-22) — iteration 0 walks the full
        # ``_PHASE_ORDER``; iterations 1..max_iterations re-enter the
        # ``_ITERATION_PHASE_ORDER`` cycle, promoting evolved
        # candidates into the candidates list between cycles.
        for iteration in range(self.state.max_iterations + 1):
            self.state.current_iteration = iteration
            if iteration > 0:
                if not self._promote_evolved_for_iteration():
                    log.info(
                        "seed-generation iteration %d skipped — no evolved "
                        "candidates from previous iteration's Evolver.",
                        iteration,
                    )
                    _emit_orchestrator_event(
                        "iteration_skipped",
                        level="info",
                        payload={
                            "iteration": iteration,
                            "reason": "no_evolved_candidates",
                        },
                    )
                    break
                log.info(
                    "seed-generation iteration %d/%d started: %d evolved → candidates",
                    iteration,
                    self.state.max_iterations,
                    len(self.state.candidates),
                )
                _emit_orchestrator_event(
                    "iteration_started",
                    payload={
                        "iteration": iteration,
                        "candidates": len(self.state.candidates),
                    },
                )
            order = _PHASE_ORDER if iteration == 0 else _ITERATION_PHASE_ORDER
            # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) —
            # resume cursor only affects iteration 0; iteration >= 1
            # is a fresh cycle by design (evolved candidates replace
            # the prior pool). When ``resume_from_phase`` names a
            # phase in the current order, skip everything before it.
            resume_idx = 0
            if iteration == 0 and resume_from_phase and resume_from_phase in order:
                resume_idx = order.index(resume_from_phase)
                if resume_idx > 0:
                    log.info(
                        "seed-generation resume: skipping %d completed phase(s) before %r",
                        resume_idx,
                        resume_from_phase,
                    )
                    _emit_orchestrator_event(
                        "resume_skipped_phases",
                        payload={
                            "skipped": list(order[:resume_idx]),
                            "resume_from": resume_from_phase,
                        },
                    )
            for phase in order[resume_idx:]:
                phase_started = time.time()
                # PR-SEEDS-HIRES — heartbeat at phase start so live
                # readers see the current phase before the agent fires.
                self._persist_progress(
                    current_phase=phase,
                    current_step=f"iteration={iteration}",
                )
                phase_result = await self._arun_phase(phase)
                self._phase_durations_ms[phase] = (time.time() - phase_started) * 1000.0
                # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) —
                # checkpoint the post-phase state so a downstream
                # crash doesn't lose this phase's work. Failures
                # here are logged but don't abort the run (the
                # checkpoint is a recovery convenience, not a hard
                # contract — the run continues either way).
                #
                # PR-CHECKPOINT-ON-FAILURE (2026-05-25) — only checkpoint
                # phases that actually succeeded. Smoke 17 wrote a
                # ``proximity.json`` checkpoint despite the proximity
                # phase emitting ``phase_failed (raised=False)`` because
                # ``_arun_phase`` returned normally (it catches and
                # logs soft failures). A future ``audit-seeds resume``
                # would then SKIP proximity on the next attempt — the
                # opposite of what the operator wants. Now the
                # checkpoint is gated on ``phase_result.success`` so
                # resume re-runs failed phases instead of pretending
                # they completed.
                if iteration == 0 and self.state.run_dir is not None and phase_result.success:
                    if phase == "ranker":
                        self._apply_post_elo_dedup()
                    self._record_checkpoint(
                        phase,
                        duration_ms=(time.time() - phase_started) * 1000.0,
                    )
                elif phase == "ranker" and phase_result.success:
                    self._apply_post_elo_dedup()
                # PR-COSCI-1 (2026-05-21) — abort early when the
                # candidates pool is empty after a phase that should
                # have populated or filtered it. The check is scoped
                # to iteration 0 phases (generator / proximity) — in
                # later iterations the pool is pre-seeded from
                # evolved_candidates so generator/proximity don't run.
                if phase in {"generator", "proximity"} and not self.state.candidates:
                    log.warning(
                        "seed-generation aborting: phase %r left state.candidates empty "
                        "(target_dim=%s, run_id=%s). Downstream phases would emit "
                        "empty survivors/elo_ratings — abort early so the operator "
                        "sees the root cause rather than a 'successful but empty' run.",
                        phase,
                        self.state.target_dim,
                        self.state.run_id,
                    )
                    _emit_orchestrator_event(
                        "empty_candidates_abort",
                        level="error",
                        payload={
                            "after_phase": phase,
                            "target_dim": self.state.target_dim,
                            "run_id": self.state.run_id,
                        },
                    )
                    aborted = True
                    break
            if aborted:
                break
        # P0b — cross-loop handoff runs FIRST so ``state.pool_path_out``
        # is stamped before ``_persist_state`` snapshots state.json.
        # Otherwise the offload would freeze a stale ``null`` for
        # the pool_path_out field.
        self._persist_survivors()
        # S8 parent-context offload — persist the final state.json so a
        # follow-up CLI invocation (S11) can resume the meta-review +
        # survivor pool without re-reading every candidate body.
        self._persist_state()
        # G4 — persist meta_review.json as a first-class artifact AND
        # update the cross-run ``latest_meta_review.json`` symlink so the
        # next seed-generation run reads it as priors.
        self._persist_meta_review()
        # PR-SEEDS-HIRES (2026-05-26) — per-phase cost ledger + final
        # progress stamp so the hub renders cost breakdown and the
        # active-runs page filters this run out of "in progress".
        self._persist_per_phase_costs()
        self._persist_progress(current_phase="done", current_step=None)
        # Cancel the background live-sync loop. The post-run
        # ``sync_run_to_bundle`` below performs the final authoritative
        # copy (verbatim, no mtime gate) so any race between the last
        # live tick and run end resolves to the latest content.
        live_sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):  # pragma: no cover
            await live_sync_task
        # P1a — append to the shared self-improving-loop session registry.
        self._append_session_index(started_at=started_at, ended_at=time.time())
        # CSP-14 (2026-05-23) — auto-sync the publish-set of the run dir
        # into ``docs/self-improving/petri-bundle/seeds/<run_id>/`` so the Pages-published
        # bundle picks it up on next deploy. Mirrors audit-side
        # ``plugins.petri_audit.bundle_sync.sync_eval_to_bundle``.
        # Failures are logged but don't break the run — the bundle is a
        # publish convenience; the canonical artefacts live in
        # ``state/seed_generation/<run_id>/`` regardless.
        if self.state.run_dir is not None:
            try:
                from plugins.seed_generation.bundle_sync import sync_run_to_bundle

                sync_run_to_bundle(self.state.run_dir)
            except Exception:
                log.warning(
                    "seed-generation: bundle_sync failed for run_id=%s (non-fatal)",
                    self.state.run_id,
                    exc_info=True,
                )
        log.info(
            "seed-generation run finished: run_id=%s survivors=%d usd=%.4f",
            self.state.run_id,
            len(self.state.survivors),
            self.state.usd_spent,
        )
        return self.state

    def _promote_evolved_for_iteration(self) -> bool:
        """Promote ``evolved_candidates`` into ``candidates`` for the next iteration.

        CSP-5 (2026-05-22) — between iterations the post-meta_reviewer
        cycle (``_ITERATION_PHASE_ORDER``) starts at the Critic phase,
        which expects ``state.candidates`` populated. The previous
        iteration's Evolver wrote new rows into
        ``state.evolved_candidates``; we replace ``state.candidates``
        with those rows (NOT extend — we don't want the previous
        iteration's already-evolved candidates re-evaluated) and clear
        the per-iteration ephemeral state (reflections, pilot_scores,
        elo_ratings, survivors, evolved_candidates) so the next cycle
        runs against a clean slate.

        Returns False when no evolved candidates exist (the Evolver
        produced none, or wasn't registered) — the caller skips the
        iteration and breaks the outer loop.
        """
        if not self.state.evolved_candidates:
            return False
        self.state.candidates = list(self.state.evolved_candidates)
        self.state.evolved_candidates = []
        # Per-iteration ephemera reset — these belong to the previous
        # cycle's candidate set and would mislead the new Critic /
        # Pilot / Ranker if left behind.
        self.state.reflections = {}
        self.state.pilot_scores = {}
        self.state.elo_ratings = {}
        self.state.survivors = []
        # CSP-8 (2026-05-22) — proximity phase only runs in iter 0,
        # so ``similarity_clusters`` / ``removed_duplicates`` stay
        # populated from the initial draft batch. Iteration cycles
        # don't re-cluster (evolved candidates are deduped by the
        # Evolver's anti-convergence Jaccard guard, CSP-6).
        return True

    def _apply_post_elo_dedup(self) -> None:
        """Filter high-similarity survivor clusters after Ranker.

        Proximity records semantic clusters before Pilot/Ranker have
        score signal. This post-Elo pass mirrors open-coscientist's
        high-similarity dedup rule, but uses GEODE's survivor ids, Elo
        ratings, and Pilot dim means.
        """
        from plugins.seed_generation.dedup import dedup_survivors_by_cluster

        if not self.state.survivors or not self.state.similarity_clusters:
            return
        filtered, removed = dedup_survivors_by_cluster(
            survivors=list(self.state.survivors),
            ratings=dict(self.state.elo_ratings),
            pilot_scores=dict(self.state.pilot_scores),
            similarity_clusters=list(self.state.similarity_clusters),
        )
        if not removed:
            return
        self.state.survivors = filtered
        self.state.removed_duplicates.extend(removed)
        log.info(
            "seed-generation post-Elo dedup: removed %d high-similarity survivors",
            len(removed),
        )
        _emit_orchestrator_event(
            "post_elo_dedup_finished",
            payload={
                "removed": len(removed),
                "survivors_before": len(filtered) + len(removed),
                "survivors_after": len(filtered),
            },
        )

    def _append_session_index(self, *, started_at: float, ended_at: float) -> None:
        """Append one row to the cross-run ``handoff/sessions.jsonl`` index.

        P1a — shared cross-loop registry. ``session_id`` defaults to
        ``state.run_id`` (already unique per ``audit-seeds generate``
        invocation). I/O failures are logged but never raise; the
        in-memory ``state`` stays authoritative.
        """
        # The handoff index is RUNTIME (per-run pointers, not versioned). Post
        # PR-STATE-SOT-RUNTIME-SPLIT (2026-06-14) it lives under the runtime root
        # (``~/.geode/self-improving/handoff/`` by default, env-overridable via
        # ``GEODE_STATE_ROOT``) — moved OUT of the interim in-repo ``state/``
        # tree so a clone/worktree never carries another host's run pointers.
        from core.paths import AUTORESEARCH_HANDOFF_DIR

        handoff_home = AUTORESEARCH_HANDOFF_DIR
        index_path = handoff_home / "sessions.jsonl"
        payload = {
            "session_id": self.state.run_id,
            "gen_tag": self.state.gen_tag,
            "component": "seed-generation",
            "started_at": started_at,
            "ended_at": ended_at,
            "target_dim": self.state.target_dim,
            "candidates": len(self.state.candidates),
            "survivors": len(self.state.survivors),
            "usd_spent": round(self.state.usd_spent, 6),
            "pool_path_out": (str(self.state.pool_path_out) if self.state.pool_path_out else None),
        }
        try:
            handoff_home.mkdir(parents=True, exist_ok=True)
            with index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning(
                "seed-generation session-index append failed at %s: %s",
                index_path,
                exc,
            )

    def _persist_survivors(self) -> None:
        """Cross-loop handoff: emit ``survivors.json`` + ``survivors/`` dir.

        P0b — defect #13 from 2026-05-19 self-improving-loop wiring plan. Writes
        two artifacts under ``<run_dir>``:

        1. ``survivors.json`` — metadata view for downstream queries
           (Elo rating, pilot score per survivor)::

               {
                 "gen_tag": "...",
                 "target_dim": "...",
                 "run_id": "...",
                 "survivors": [
                   {"id": "...", "path": "candidates/<id>.md",
                    "elo_rating": 1612.4, "pilot": {...} | null}
                 ]

           ``path`` is RELATIVE to ``run_dir`` (e.g. ``candidates/<id>.md``
           or ``candidates_evolved/<id>.md``) so a clone on another machine
           — or a GitHub-Pages mirror — resolves bodies without a broken
           absolute path into the original generation scratch tree.
               }

        2. ``survivors/`` — directory of **file copies** (was: symlinks,
           pre-CSP-7) of each survivor's candidate body. This is what
           ``inspect-petri`` 's flat-glob ``--seed-select`` consumer
           expects (``flatten_for_inspect_petri`` passes a directory of
           ``*.md`` through unchanged). File copies (vs symlinks) make
           the survivors directory self-contained so a clone on a
           different machine still has the candidate bodies even when
           the original ``<run_dir>/candidates/`` is absent.
           ``state.pool_path_out`` is stamped to this directory so a
           parent driver can set ``AUTORESEARCH_SEED_SELECT=<pool_path_out>``
           and the next audit will pick up the winners.

        Skipped when ``state.run_dir`` is unset (test fixtures often
        omit it). I/O failures log a WARNING but do not raise — the
        in-memory ``state.survivors`` stays authoritative.
        """
        if self.state.run_dir is None:
            return
        candidates_by_id = {c["id"]: c for c in self.state.candidates}
        run_dir = self.state.run_dir
        rows: list[dict[str, Any]] = []
        # Absolute source path per row, kept out of the JSON payload — the
        # copy loop below copies from here while the row stores only the
        # run-dir-relative path (cross-machine / Pages-safe).
        copy_sources: list[str | None] = []
        for cid in self.state.survivors:
            cand = candidates_by_id.get(cid, {})
            cand_path = cand.get("path")
            # Store path RELATIVE to run_dir so survivors.json is
            # self-contained — an absolute scratch-tree path breaks on a
            # clone / GitHub-Pages mirror where that tree is absent.
            rel = os.path.relpath(cand_path, run_dir) if cand_path else None
            rows.append(
                {
                    "id": cid,
                    "path": rel,
                    "elo_rating": self.state.elo_ratings.get(cid),
                    "pilot": self.state.pilot_scores.get(cid),
                }
            )
            copy_sources.append(cand_path)
        payload = {
            "gen_tag": self.state.gen_tag,
            "target_dim": self.state.target_dim,
            "run_id": self.state.run_id,
            "survivors": rows,
        }
        try:
            self.state.run_dir.mkdir(parents=True, exist_ok=True)
            survivors_json = self.state.run_dir / "survivors.json"
            survivors_json.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            survivors_dir = self.state.run_dir / "survivors"
            survivors_dir.mkdir(parents=True, exist_ok=True)
            # CSP-7 (2026-05-22) — clear stale entries (file copies +
            # any legacy symlinks left from a pre-CSP-7 run) so the
            # survivor set is exactly the current rows.
            for entry in survivors_dir.iterdir():
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
            import shutil

            # Copy from the absolute source (``copy_sources``), not the now
            # run-dir-relative ``row["path"]`` — the relative path would not
            # resolve from the process CWD.
            for src_str in copy_sources:
                if not src_str:
                    continue
                src = Path(src_str)
                if not src.is_file():
                    continue
                dst = survivors_dir / src.name
                # CSP-7 — file copy (was symlink). Makes the survivors
                # directory self-contained for cross-machine reproducibility.
                shutil.copy2(src, dst)
            self.state.pool_path_out = survivors_dir
            # CSP-7 (2026-05-22) — write the cross-run pointer with
            # seed_pool only (meta_review may be empty for this run;
            # ``_persist_meta_review`` will re-write the pointer with
            # both fields once it has meta_review_path). Idempotent
            # writes — the meta-review call overwrites the file.
            self._write_latest_pointer(
                survivors_dir=survivors_dir,
                meta_review_path=None,
            )
            log.info(
                "seed-generation cross-loop handoff: %d survivors → %s (metadata at %s)",
                len(rows),
                survivors_dir,
                survivors_json,
            )
        except OSError as exc:
            log.warning(
                "seed-generation survivors export failed at %s: %s",
                self.state.run_dir,
                exc,
            )

    def _write_latest_pointer(
        self,
        *,
        survivors_dir: Path | None,
        meta_review_path: Path | None,
    ) -> None:
        """Update the cross-run forward pointer JSON.

        CSP-7 (2026-05-22) — replaces the pre-CSP-7
        ``~/.geode/autoresearch/handoff/latest_seed_pool`` +
        ``latest_meta_review.json`` symlink pair with a single JSON
        file at :data:`core.paths.STATE_LATEST_POINTER_PATH`. The
        readers (autoresearch ``_resolve_seed_select`` +
        ``baseline_reader.load_latest_meta_review``) consume the
        pointer instead of dereferencing symlinks, so the handoff
        survives a fresh clone on a different machine.

        Both args are optional — pass only what this run produced.
        Failures are logged but never raise; the canonical handoff is
        ``state.pool_path_out`` + the per-run artefacts, and the
        pointer is a convenience accelerator (next-run readers fall
        back to env vars / config when the pointer is missing).
        """
        from core.paths import write_latest_pointer

        try:
            write_latest_pointer(
                run_id=self.state.run_id,
                gen_tag=self.state.gen_tag,
                seed_pool=survivors_dir,
                meta_review=meta_review_path,
            )
        except OSError as exc:
            log.warning(
                "seed-generation latest_pointer.json update failed: %s",
                exc,
            )

    def _persist_meta_review(self) -> None:
        """Persist ``state.meta_review`` as a standalone JSON + cross-run symlink.

        G4 closed-loop wiring (2026-05-20 self-improving-loop sprint).
        Two artifacts:

        1. ``<run_dir>/meta_review.json`` — first-class file for this
           run's meta-review report. Already serialised inside
           ``state.json``; the standalone copy lets a downstream tool
           (or the next CLI invocation's priors reader) load just the
           meta-review without re-parsing the entire state blob.
        2. ``~/.geode/autoresearch/handoff/latest_meta_review.json``
           symlink — atomic forward pointer to the most-recent run's
           ``meta_review.json``. The next ``geode audit-seeds generate``
           reads this symlink to seed the generator / critic prompts
           with the previous round's ``next_gen_priors`` +
           ``underrepresented_dims`` hints.

        Skipped (silently) when:
        - ``state.run_dir`` is None (test fixtures), or
        - ``state.meta_review`` is empty (bootstrap run / failed meta
          phase).

        I/O failures log WARNING but never raise — observability must
        not break the run it observes.
        """
        if self.state.run_dir is None:
            return
        if not self.state.meta_review:
            return
        meta_review_path = self.state.run_dir / "meta_review.json"
        try:
            self.state.run_dir.mkdir(parents=True, exist_ok=True)
            meta_review_path.write_text(
                json.dumps(self.state.meta_review, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning(
                "seed-generation meta_review persist failed at %s: %s",
                meta_review_path,
                exc,
            )
            return
        # CSP-7 (2026-05-22) — pointer file update (was: symlink to
        # ``~/.geode/autoresearch/handoff/latest_meta_review.json``).
        # The pointer also carries ``seed_pool`` from the prior
        # ``_persist_survivors`` call (same run) so a single read
        # gets both signals.
        self._write_latest_pointer(
            survivors_dir=self.state.pool_path_out,
            meta_review_path=meta_review_path,
        )

    def _record_checkpoint(self, phase: str, *, duration_ms: float) -> None:
        """Write a ``<run_dir>/checkpoints/<phase>.json`` snapshot.

        PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — recovery
        path: a future ``audit-seeds resume <run_id>`` invocation
        reads these files to skip already-completed phases. Failures
        log a WARNING and continue — the run's primary state lives
        in memory + final ``state.json``; checkpoints are a
        convenience for crash recovery.
        """
        if self.state.run_dir is None:
            return
        try:
            from plugins.seed_generation.checkpointer import write_checkpoint

            # Codex MCP review of PR-CHECKPOINT-RESUME-TIMEBUDGET — append
            # BEFORE serializing so the snapshot's ``completed_phases``
            # reflects the just-completed phase. Pre-fix the on-disk
            # snapshot was one phase behind the in-memory state.
            if phase not in self.state.completed_phases:
                self.state.completed_phases.append(phase)
            snapshot = json.loads(_state_to_json(self.state))
            write_checkpoint(
                self.state.run_dir,
                phase=phase,
                state_snapshot=snapshot,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.warning(
                "seed-generation: failed to write %s checkpoint — %s",
                phase,
                exc,
            )

    def _persist_state(self) -> None:
        """Write a JSON snapshot of state to ``<run_dir>/state.json``.

        S8 parent-context offload — the parent loop should not have to
        carry the entire pool in memory after the meta_review fires.
        Persisting the state at end-of-run is the offload boundary; the
        S11 CLI ``geode audit-seeds resume`` will re-hydrate from here.

        Skipped when ``state.run_dir`` is None (test fixtures often
        omit it); state is kept in memory for the caller to consume.
        Persistence failures log a WARNING but do not raise — the
        primary signal is the in-memory state, not the disk artifact.
        """
        if self.state.run_dir is None:
            return
        try:
            self.state.run_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = self.state.run_dir / "state.json"
            snapshot_path.write_text(
                _state_to_json(self.state),
                encoding="utf-8",
            )
            log.info(
                "seed-generation parent-context offload: state persisted to %s",
                snapshot_path,
            )
        except OSError as exc:
            log.warning(
                "seed-generation parent-context offload failed at %s: %s",
                self.state.run_dir,
                exc,
            )

    def _persist_progress(
        self,
        *,
        current_phase: str,
        current_step: str | None,
        current_agent_task_id: str | None = None,
    ) -> None:
        """Write ``<run_dir>/progress.json`` heartbeat.

        PR-SEEDS-HIRES (2026-05-26) — live-status surface. The hub's
        ``/active/`` page filters runs where ``current_phase != "done"``;
        per-phase ETA derives from the mean duration of already-finished
        phases × remaining count. Atomic via tmp+os.replace so concurrent
        readers (geode serve SSE in PR 3) never see partial writes.

        I/O failures log WARNING and continue — progress is observability,
        not a hard contract on the run.
        """
        if self.state.run_dir is None:
            return
        finished = list(self._phase_durations_ms.keys())
        remaining_count = max(0, len(_PHASE_ORDER) - len(finished))
        if finished:
            mean_ms = sum(self._phase_durations_ms.values()) / len(finished)
            eta_seconds = (mean_ms * remaining_count) / 1000.0
        else:
            eta_seconds = None
        payload = {
            "run_id": self.state.run_id,
            "gen_tag": self.state.gen_tag,
            "target_dim": self.state.target_dim,
            "current_phase": current_phase,
            "current_step": current_step,
            "current_agent_task_id": current_agent_task_id,
            "iteration": self.state.current_iteration,
            "max_iterations": self.state.max_iterations,
            "phases_completed": finished,
            "started_at": self._live_run_started_at,
            "last_updated_at": time.time(),
            "eta_seconds": eta_seconds,
            "usd_spent": self.state.usd_spent,
        }
        try:
            self.state.run_dir.mkdir(parents=True, exist_ok=True)
            target = self.state.run_dir / "progress.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, target)
        except OSError as exc:
            log.warning(
                "seed-generation progress.json write failed: %s",
                exc,
            )

    def _persist_per_phase_costs(self) -> None:
        """Aggregate sub-agent ``dialogue.jsonl`` session_end events by phase.

        PR-SEEDS-HIRES (2026-05-26) — per-phase cost breakdown so the
        hub can render a cost grid alongside the phase timeline. Walks
        every ``sub_agents/<task_id>/`` dir under run_dir, reads each
        session.json's ``metadata.phase`` (or falls back to inferring
        from task_id prefix when metadata is absent), then sums
        ``session_end.total_cost`` / ``duration_s`` per phase from the
        sibling ``dialogue.jsonl``.

        Output shape (each phase row optional):
        ``{<phase>: {cost_usd, prompt_tokens, completion_tokens, duration_ms, agent_count}}``.
        """
        if self.state.run_dir is None:
            return
        sub_agents_dir = self.state.run_dir / "sub_agents"
        rollup: dict[str, dict[str, float | int]] = {}
        if sub_agents_dir.is_dir():
            for task_dir in sub_agents_dir.iterdir():
                if not task_dir.is_dir():
                    continue
                phase = _infer_phase_from_task(task_dir)
                if phase is None:
                    continue
                agg = rollup.setdefault(
                    phase,
                    {
                        "cost_usd": 0.0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "duration_ms": 0.0,
                        "agent_count": 0,
                    },
                )
                agg["agent_count"] = int(agg["agent_count"]) + 1
                dialogue = task_dir / "dialogue.jsonl"
                for evt in iter_jsonl(dialogue):
                    if evt.get("event") != "session_end":
                        continue
                    with contextlib.suppress(TypeError, ValueError):
                        agg["cost_usd"] = float(agg["cost_usd"]) + float(
                            evt.get("total_cost") or 0.0
                        )
                    with contextlib.suppress(TypeError, ValueError):
                        agg["duration_ms"] = (
                            float(agg["duration_ms"]) + float(evt.get("duration_s") or 0.0) * 1000.0
                        )
                    with contextlib.suppress(TypeError, ValueError):
                        agg["prompt_tokens"] = int(agg["prompt_tokens"]) + int(
                            evt.get("prompt_tokens") or 0
                        )
                    with contextlib.suppress(TypeError, ValueError):
                        agg["completion_tokens"] = int(agg["completion_tokens"]) + int(
                            evt.get("completion_tokens") or 0
                        )
        # Always include known finished phases even when agent_count == 0
        # (e.g. supervisor that did no sub-agent fan-out). Operators
        # expect the timeline + cost grid to reflect every phase ran.
        for phase, dur_ms in self._phase_durations_ms.items():
            agg = rollup.setdefault(
                phase,
                {
                    "cost_usd": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "duration_ms": 0.0,
                    "agent_count": 0,
                },
            )
            # If we didn't record any sub-agent duration, fall back to the
            # outer phase wall-clock so the hub timeline shows a non-zero
            # bar for short phases (e.g. proximity has no sub-agents).
            if int(agg["agent_count"]) == 0:
                agg["duration_ms"] = float(dur_ms)
        try:
            target = self.state.run_dir / "per_phase_costs.json"
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(rollup, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, target)
        except OSError as exc:
            log.warning(
                "seed-generation per_phase_costs.json write failed: %s",
                exc,
            )

    async def _live_sync_loop(self) -> None:
        """Background incremental bundle sync — fires every 5s during a run.

        PR-SEEDS-HIRES (2026-05-26) — gives the published bundle near-
        real-time content. The orchestrator cancels this task at end of
        :meth:`arun` and runs the final authoritative ``sync_run_to_bundle``
        immediately after. Kill switch: ``GEODE_SEED_LIVE_SYNC_DISABLED=1``.

        Failures are swallowed — the loop must NOT propagate an exception
        that would crash the running pipeline. The final post-run sync
        is authoritative.
        """
        if os.environ.get("GEODE_SEED_LIVE_SYNC_DISABLED") == "1":
            return
        if self.state.run_dir is None:
            return
        try:
            from plugins.seed_generation.bundle_sync import sync_run_incremental
        except Exception:  # pragma: no cover — import shouldn't fail
            return
        while True:
            try:
                sync_run_incremental(self.state.run_dir)
            except Exception:
                # Observability must never crash the run — log and keep ticking.
                log.debug("seed-generation live-sync tick failed (non-fatal)", exc_info=True)
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                return

    async def _arun_phase(self, role: str) -> SeedAgentResult:
        """Look up the role's agent, invoke it (async), merge the result.

        PR-Async-Phase-C step 2 (2026-05-22) — async-native phase
        runner. Wraps the agent's ``aexecute`` in the OpenClaw lane
        chain via :meth:`_aacquire_lane` (which uses LaneQueue's
        ``acquire_all_async``). For phases that fan out via
        :meth:`SubAgentManager.adelegate` the lane gates concurrency
        at the seed-generation cap (default 4 per Phase 1
        ``DEFAULT_SEED_PIPELINE_CONCURRENCY``).

        Cost rollup is purely informational — the agent (or its test
        stub) sets ``result.usd_spent`` / ``prompt_tokens`` /
        ``completion_tokens`` directly and the orchestrator sums them
        into ``state.*``. The pre-PR-1 BudgetGuard hard-cap layer was  # slop:keep
        removed (2026-05-18); operators control spend via the
        pre-run cost preview + human gate at the CLI surface.
        """
        agent = self.registry.get(role)
        if agent is None:
            # CSP-4 (2026-05-22) — Supervisor is OPTIONAL. Test
            # fixtures that mock a subset of roles, or pre-CSP-4
            # callers that haven't been migrated, may skip it.
            # ``state.supervisor_guidance`` stays at its default
            # (empty dict) and downstream sub-agents detect "no
            # guidance" via that empty check rather than KeyError.
            #
            # CSP-14 (2026-05-23) — ``literature_review`` is also
            # OPTIONAL (Loop 3 of the 3-loop port). The phase
            # short-circuits when not registered so existing test
            # fixtures + pre-CSP-14 callers keep working. The agent
            # would have short-circuited on ``max_papers = 0`` anyway.
            if role in ("supervisor", "literature_review"):
                log.info(
                    "seed-generation %s role not registered — skipping.",
                    role,
                )
                _emit_orchestrator_event(
                    "phase_skipped",
                    level="info",
                    payload={"role": role, "reason": "agent_not_registered"},
                )
                return SeedAgentResult(role=role, status="skipped")
            raise RuntimeError(
                f"seed-generation phase {role!r} has no registered agent — "
                f"expected one of {_PHASE_ORDER}. Did the S2-S8 PR for "
                f"{role} land?"
            )

        self._emit_hook(HookEvent.SUBAGENT_STARTED, role)
        _emit_orchestrator_event("phase_started", payload={"role": role})
        started = time.time()

        result: SeedAgentResult | None = None
        async with self._aacquire_lane(role):
            try:
                result = await agent.aexecute(self.state)
            except Exception as exc:
                duration = (time.time() - started) * 1000
                log.exception("seed-generation phase %s raised", role)
                self._emit_hook(HookEvent.SUBAGENT_FAILED, role, error=str(exc))
                _emit_orchestrator_event(
                    "phase_failed",
                    level="error",
                    payload={
                        "role": role,
                        "duration_ms": round(duration, 3),
                        "error": str(exc)[:200],
                        "raised": True,
                    },
                )
                if self._on_phase_error is not None:
                    self._on_phase_error(role, exc)
                raise
            else:
                duration = (time.time() - started) * 1000
                if result.duration_ms == 0.0:
                    result.duration_ms = duration

        # Cost rollup from the agent's result. Agents (or their test
        # stubs) set result.* directly; the orchestrator sums into
        # state.* for the run-level total.
        if result.usd_spent > 0 or result.prompt_tokens > 0 or result.completion_tokens > 0:
            self.state.usd_spent += result.usd_spent
            self.state.prompt_tokens += result.prompt_tokens
            self.state.completion_tokens += result.completion_tokens

        if result.success:
            self.state.merge(role, result.output)
            self._emit_hook(HookEvent.SUBAGENT_COMPLETED, role)
            _emit_orchestrator_event(
                "phase_finished",
                payload={"role": role, "duration_ms": round(duration, 3)},
            )
        else:
            self._emit_hook(HookEvent.SUBAGENT_FAILED, role, error=result.error_message)
            _emit_orchestrator_event(
                "phase_failed",
                level="error",
                payload={
                    "role": role,
                    "duration_ms": round(duration, 3),
                    "error": (result.error_message or "")[:200],
                    "raised": False,
                },
            )
        return result

    def _aacquire_lane(self, role: str) -> Any:
        """Return an async context manager walking the OpenClaw lane chain.

        PR-Async-Phase-C step 2 (2026-05-22) — async sibling of
        :meth:`_acquire_lane`. Acquires
        ``["session", "seed-generation", "global"]`` in order via
        :meth:`LaneQueue.acquire_all_async` so per-role concurrency
        is bounded by BOTH the seed-generation workload cap and the
        global cap (PR-LQ-Phase1). The SessionLane keys on
        ``seed-generation:<run_id>`` so two concurrent
        ``Pipeline.arun()`` calls for the same ``run_id`` serialize.

        When no ``LaneQueue`` was supplied (test path) or the
        ``seed-generation`` lane is not registered, returns an async
        nullcontext.
        """
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _noop() -> Any:
            yield

        if self._lane_queue is None:
            return _noop()
        if self._lane_queue.get_lane("seed-generation") is None:
            return _noop()
        session_key = f"seed-generation:{self.state.run_id}"
        return self._lane_queue.acquire_all_async(
            session_key,
            ["session", "seed-generation", "global"],
        )

    def _emit_hook(self, event: HookEvent, role: str, **extra: Any) -> None:
        if self._hooks is None:
            return
        payload: dict[str, Any] = {
            "subject": f"seed-generation/{self.state.run_id}/{role}",
            "subject_id": self.state.run_id,
            "role": role,
            "target_dim": self.state.target_dim,
            **extra,
        }
        try:
            self._hooks.trigger(event, payload)
        except Exception:
            log.warning("seed-generation hook trigger failed: %s", event, exc_info=True)
