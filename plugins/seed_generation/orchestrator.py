"""Pipeline orchestrator — 7-phase generate-debate-evolve loop.

Maps the ADR-001 7-phase topology (Generation → Proximity → Reflection
→ Pilot → Ranking → Evolution → Meta-review) onto a sequential phase
dispatcher backed by :class:`PipelineRegistry`. Each phase is a method
that reads :class:`PipelineState`, looks up the role's agent from the
registry, invokes :meth:`BaseSeedAgent.execute`, and merges the
result's ``output`` dict back into state.

Why a flat orchestrator, not LangGraph
======================================

GEODE has no LangGraph in core. The ``SubAgentManager`` +
``IsolatedRunner`` + ``HookSystem`` already provide the supervisor
+ workers + observability pattern (depth=1 enforced — sub-agents
cannot recurse, so the parent ``AgenticLoop`` IS the StateGraph).
Each phase runs in the parent loop; within a phase, the role can
fan out via ``delegate(tasks=[…])``.

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

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.hooks import HookEvent, HookSystem

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult

if TYPE_CHECKING:
    from core.orchestration.lane_queue import LaneQueue

log = logging.getLogger(__name__)

__all__ = [
    "Pipeline",
    "PipelineRegistry",
    "PipelineState",
]


def _state_to_json(state: PipelineState) -> str:
    """Serialize PipelineState fields safe for JSON persistence.

    Skips runtime-only fields (``run_dir`` path
    object). Path-typed fields are coerced to strings so the JSON is
    portable across machines (re-hydration converts back).
    """
    payload: dict[str, Any] = {
        "run_id": state.run_id,
        "target_dim": state.target_dim,
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
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _emit_orchestrator_event(
    event: str,
    *,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a seed-generation event into the active SessionJournal.

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
        from core.observability import current_session_journal

        journal = current_session_journal()
        if journal is None:
            return
        journal.append(event, level=level, payload=payload or {})
    except Exception:  # pragma: no cover - defensive
        log.debug("seed-generation: journal emit %s failed", event, exc_info=True)


_PHASE_ORDER: tuple[str, ...] = (
    "generator",
    "proximity",
    "critic",
    "pilot",
    "ranker",
    "evolver",
    "meta_reviewer",
)


@dataclass
class PipelineState:
    """In-flight pipeline state shared across the 7 phases.

    Mutated by each phase's :meth:`BaseSeedAgent.execute` return
    payload. Persisted at run end to
    ``~/.geode/seed-generation/<run_id>/state.json`` (S8 wires the
    offload via ``note_save``).
    """

    run_id: str
    target_dim: str
    gen_tag: str
    candidates_requested: int = 15
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
    # PR-Π1 — pair-wise similarity scores emitted by the Proximity phase
    # (PR-Π1 §A). Key is the sorted ``(cid_a, cid_b)`` tuple (a < b);
    # value is the composite similarity in ``[0.0, 1.0]`` (1.0 = identical).
    # The Ranker (S6) consumes this in its ``plan_matches`` call to seed
    # the Elo bracket toward diverse pairings — Co-Scientist §3.3.4
    # "showcasing a diverse range of ideas". Sparse — only candidate
    # pairs the Proximity phase scored are present; missing pairs are
    # treated as maximally distant (proximity = 0.0).
    proximity_graph: dict[tuple[str, str], float] = field(default_factory=dict)
    # cost rollup
    usd_spent: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # baseline (None on first generation — bootstrap)
    baseline_means: dict[str, float] | None = None
    baseline_stderr: dict[str, float] | None = None
    # G3 — full BaselineSnapshot (dim_means + dim_stderr + evidence) loaded
    # from ``autoresearch/state/baseline.json`` when the CLI flow auto-picks
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
    :meth:`run` walks ``_PHASE_ORDER`` and emits per-phase hook events.
    """

    def __init__(
        self,
        state: PipelineState,
        registry: PipelineRegistry,
        *,
        hooks: HookSystem | None = None,
        lane_queue: LaneQueue | None = None,
        on_phase_error: Any | None = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self._hooks = hooks
        self._lane_queue = lane_queue
        self._on_phase_error = on_phase_error

    def run(self) -> PipelineState:
        """Walk all 7 phases in order. Returns the final state."""
        log.info(
            "seed-generation run started: run_id=%s target=%s gen=%s",
            self.state.run_id,
            self.state.target_dim,
            self.state.gen_tag,
        )
        started_at = time.time()
        for phase in _PHASE_ORDER:
            self._run_phase(phase)
            # PR-COSCI-1 (2026-05-21) — abort early when the
            # candidates pool is empty after a phase that should
            # have populated or filtered it. Pre-fix the
            # downstream phases (critic / pilot / ranker) would
            # silently run with zero candidates and emit empty
            # ``elo_ratings`` / ``pilot_scores`` / ``survivors``,
            # making the operator chase a "successful but empty
            # run" rather than the actual root cause. Phases
            # AFTER generator must see candidates; ``meta_reviewer``
            # is the only exception (operates on the run record,
            # not the candidates pool).
            if (
                phase in {"generator", "proximity"}
                and not self.state.candidates
            ):
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
        # P1a — append to the shared self-improving-loop session registry.
        self._append_session_index(started_at=started_at, ended_at=time.time())
        log.info(
            "seed-generation run finished: run_id=%s survivors=%d usd=%.4f",
            self.state.run_id,
            len(self.state.survivors),
            self.state.usd_spent,
        )
        return self.state

    def _append_session_index(self, *, started_at: float, ended_at: float) -> None:
        """Append one row to ``~/.geode/self-improving-loop/sessions.jsonl``.

        P1a — shared cross-loop registry. ``session_id`` defaults to
        ``state.run_id`` (already unique per ``audit-seeds generate``
        invocation). I/O failures are logged but never raise; the
        in-memory ``state`` stays authoritative.
        """
        self_improving_loop_home = Path.home() / ".geode" / "self-improving-loop"
        index_path = self_improving_loop_home / "sessions.jsonl"
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
            self_improving_loop_home.mkdir(parents=True, exist_ok=True)
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
                   {"id": "...", "path": "<candidate.md path>",
                    "elo_rating": 1612.4, "pilot": {...} | null}
                 ]
               }

        2. ``survivors/`` — directory of symlinks to each survivor's
           candidate body file. This is what
           ``inspect-petri`` 's flat-glob ``--seed-select`` consumer
           expects (``flatten_for_inspect_petri`` passes a directory of
           ``*.md`` through unchanged). ``state.pool_path_out`` is
           stamped to this directory so a parent driver can set
           ``AUTORESEARCH_SEED_SELECT=<pool_path_out>`` and the next
           audit will pick up the winners.

        Skipped when ``state.run_dir`` is unset (test fixtures often
        omit it). I/O failures log a WARNING but do not raise — the
        in-memory ``state.survivors`` stays authoritative.
        """
        if self.state.run_dir is None:
            return
        candidates_by_id = {c["id"]: c for c in self.state.candidates}
        rows: list[dict[str, Any]] = []
        for cid in self.state.survivors:
            cand = candidates_by_id.get(cid, {})
            rows.append(
                {
                    "id": cid,
                    "path": cand.get("path"),
                    "elo_rating": self.state.elo_ratings.get(cid),
                    "pilot": self.state.pilot_scores.get(cid),
                }
            )
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
            # Clear stale entries from a previous run so the symlink set
            # is exactly the current survivors.
            for entry in survivors_dir.iterdir():
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
            for row in rows:
                src_str = row.get("path")
                if not src_str:
                    continue
                src = Path(src_str)
                if not src.is_file():
                    continue
                dst = survivors_dir / src.name
                dst.symlink_to(src.resolve())
            self.state.pool_path_out = survivors_dir
            self._update_latest_seed_pool_symlink(survivors_dir)
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

    @staticmethod
    def _update_latest_seed_pool_symlink(survivors_dir: Path) -> None:
        """Point ``~/.geode/self-improving-loop/latest_seed_pool`` at this run's survivors.

        G1 closed-loop wiring: autoresearch ``_resolve_seed_select`` reads
        this symlink as the env-less fallback so the next audit
        automatically consumes the freshest survivor pool without a
        manual ``AUTORESEARCH_SEED_SELECT=…`` export. Older runs stay
        addressable by their ``<run_dir>/survivors/`` path; only the
        symlink target moves forward.

        Failures are logged but never raise — the canonical handoff is
        ``state.pool_path_out`` + ``sessions.jsonl``; the symlink is a
        convenience accelerator, not a correctness boundary.
        """
        latest = Path.home() / ".geode" / "self-improving-loop" / "latest_seed_pool"
        try:
            latest.parent.mkdir(parents=True, exist_ok=True)
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(survivors_dir.resolve())
        except OSError as exc:
            log.warning(
                "seed-generation latest_seed_pool symlink update failed at %s: %s",
                latest,
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
        2. ``~/.geode/self-improving-loop/latest_meta_review.json``
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
        # Symlink update is best-effort — survivor handoff already
        # writes state.pool_path_out + sessions.jsonl row, so a stale
        # latest_meta_review never makes the run incorrect.
        latest = Path.home() / ".geode" / "self-improving-loop" / "latest_meta_review.json"
        try:
            latest.parent.mkdir(parents=True, exist_ok=True)
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(meta_review_path.resolve())
        except OSError as exc:
            log.warning(
                "seed-generation latest_meta_review symlink update failed at %s: %s",
                latest,
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

    def _run_phase(self, role: str) -> SeedAgentResult:
        """Look up the role's agent, invoke it, merge the result.

        Wraps the execute call in an optional ``seed-generation`` lane
        acquisition (when a ``LaneQueue`` was passed). For sequential
        phases the lane is effectively a no-op; for phases that fan
        out via ``delegate(tasks=[…])`` in S2+ the lane gates
        concurrency at 16 (see ``DEFAULT_SEED_PIPELINE_CONCURRENCY``
        in ``core/wiring/container.py``).

        Cost rollup is purely informational — the agent (or its test
        stub) sets ``result.usd_spent`` / ``prompt_tokens`` /
        ``completion_tokens`` directly and the orchestrator sums them
        into ``state.*``. The pre-PR-1 BudgetGuard hard-cap layer was  # slop:keep
        removed (2026-05-18); operators control spend via the
        pre-run cost preview + human gate at the CLI surface.
        """
        agent = self.registry.get(role)
        if agent is None:
            raise RuntimeError(
                f"seed-generation phase {role!r} has no registered agent — "
                f"expected one of {_PHASE_ORDER}. Did the S2-S8 PR for "
                f"{role} land?"
            )

        self._emit_hook(HookEvent.SUBAGENT_STARTED, role)
        _emit_orchestrator_event("phase_started", payload={"role": role})
        started = time.time()

        result: SeedAgentResult | None = None
        with self._acquire_lane(role):
            try:
                result = agent.execute(self.state)
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

    def _acquire_lane(self, role: str) -> Any:
        """Return a context manager that acquires the ``seed-generation`` lane.

        When no ``LaneQueue`` was supplied (test path) or the lane is not
        registered, returns a no-op context manager. The actual semaphore
        gating only takes effect when the agent fans out via
        ``SubAgentManager.delegate(tasks=[…])`` in S2+.
        """
        from contextlib import nullcontext

        if self._lane_queue is None:
            return nullcontext()
        lane = self._lane_queue.get_lane("seed-generation")
        if lane is None:
            return nullcontext()
        return lane.acquire(f"seed-generation/{self.state.run_id}/{role}")

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
