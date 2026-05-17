"""Pipeline orchestrator — 7-phase generate-debate-evolve loop.

Maps ADR-001 의 7-phase topology (Generation → Proximity → Reflection
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

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.hooks import HookEvent, HookSystem

from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult

log = logging.getLogger(__name__)

__all__ = [
    "Pipeline",
    "PipelineRegistry",
    "PipelineState",
]


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
    ``~/.geode/seed-pipeline/<run_id>/state.json`` (S8 wires the
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
    meta_review: dict[str, Any] = field(default_factory=dict)
    # cost rollup
    usd_spent: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # baseline (None on first generation — bootstrap)
    baseline_means: dict[str, float] | None = None
    baseline_stderr: dict[str, float] | None = None

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
            "meta_review",
        }
        unknown = set(output) - known
        if unknown:
            log.warning(
                "seed-pipeline role=%r returned unknown output keys: %s",
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
            log.warning("re-registering seed-pipeline role=%r", agent.role)
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
        on_phase_error: Any | None = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self._hooks = hooks
        self._on_phase_error = on_phase_error

    def run(self) -> PipelineState:
        """Walk all 7 phases in order. Returns the final state."""
        log.info(
            "seed-pipeline run started: run_id=%s target=%s gen=%s",
            self.state.run_id,
            self.state.target_dim,
            self.state.gen_tag,
        )
        for phase in _PHASE_ORDER:
            self._run_phase(phase)
        log.info(
            "seed-pipeline run finished: run_id=%s survivors=%d usd=%.4f",
            self.state.run_id,
            len(self.state.survivors),
            self.state.usd_spent,
        )
        return self.state

    def _run_phase(self, role: str) -> SeedAgentResult:
        """Look up the role's agent, invoke it, merge the result."""
        agent = self.registry.get(role)
        if agent is None:
            raise RuntimeError(
                f"seed-pipeline phase {role!r} has no registered agent — "
                f"expected one of {_PHASE_ORDER}. Did the S2-S8 PR for "
                f"{role} land?"
            )

        self._emit_hook(HookEvent.SUBAGENT_STARTED, role)
        started = time.time()
        try:
            result = agent.execute(self.state)
        except Exception as exc:
            duration = (time.time() - started) * 1000
            log.exception("seed-pipeline phase %s raised", role)
            self._emit_hook(HookEvent.SUBAGENT_FAILED, role, error=str(exc))
            result = SeedAgentResult(
                role=role,
                status="error",
                duration_ms=duration,
                error_category=type(exc).__name__,
                error_message=str(exc),
            )
            if self._on_phase_error is not None:
                self._on_phase_error(role, exc)
            raise
        else:
            duration = (time.time() - started) * 1000
            if result.duration_ms == 0.0:
                result.duration_ms = duration

        # Cost rollup
        self.state.usd_spent += result.usd_spent
        self.state.prompt_tokens += result.prompt_tokens
        self.state.completion_tokens += result.completion_tokens

        if result.success:
            self.state.merge(role, result.output)
            self._emit_hook(HookEvent.SUBAGENT_COMPLETED, role)
        else:
            self._emit_hook(HookEvent.SUBAGENT_FAILED, role, error=result.error_message)
        return result

    def _emit_hook(self, event: HookEvent, role: str, **extra: Any) -> None:
        if self._hooks is None:
            return
        payload: dict[str, Any] = {
            "subject": f"seed-pipeline/{self.state.run_id}/{role}",
            "subject_id": self.state.run_id,
            "role": role,
            "target_dim": self.state.target_dim,
            **extra,
        }
        try:
            self._hooks.trigger(event, payload)
        except Exception:
            log.warning("seed-pipeline hook trigger failed: %s", event, exc_info=True)
