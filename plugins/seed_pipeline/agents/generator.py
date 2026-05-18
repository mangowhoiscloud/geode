"""Generation agent — Phase A of the seed pipeline.

Fans out ``state.candidates_requested`` parallel sub-agents via the parent
``SubAgentManager``. Each sub-agent is dispatched to the ``seed_generator``
AgentDefinition (``.claude/agents/seed_generator.md``) with a SubTask
description that names the target dim, generation tag, candidate id, and
output path. The sub-agent reads its system prompt + style samples from
the existing pool, then writes ONE seed markdown file to disk.

Return shape (merged into ``PipelineState.candidates``)::

    [
        {
            "id": "gen2-000-abc12345",
            "path": "<run_dir>/candidates/gen2-000-abc12345.md",
            "target_dim": "broken_tool_use",
            "gen_tag": "gen2",
            "task_id": "gen-gen2-000-abc12345",
            "duration_ms": 8421.0,
        },
        ...
    ]

The output dict is what later phases consume — Proximity (S4) reads
the file to compute embeddings, Reflection (S3) critiques it, Pilot (S5)
runs it through the Petri inner-loop subset. The candidate id is also
the basename of the seed file, so disk layout matches state shape 1:1.

Budget accounting:
====================

Per-phase ``BudgetGuard`` is attached to ``state.budget_guard`` by the
orchestrator. Generator's own ``execute`` is short (build tasks, call
``delegate``, parse results) so the dominant cost is per-sub-agent
LLM work, not Generator orchestration.

Known wiring gaps (tracked outside S2):
----------------------------------------

1. **AgentDefinition dispatch** (task #S2-wire). ``SubAgentManager.delegate``
   sets ``SubTask.agent="seed_generator"``, but the production code path
   ``_build_worker_request`` does not yet call ``_resolve_agent`` to
   apply the AgentDefinition's ``system_prompt`` / ``tools`` /
   ``model``. Without that wiring the sub-agent runs with GEODE's
   default system prompt rather than the ``.claude/agents/seed_generator.md``
   contract. The seed-pipeline plugin is correct at the orchestration
   layer; the worker-layer fix is a separate PR.

2. **BudgetGuard real-time enforcement** (task #S6.5-wire). The
   orchestrator's per-phase BudgetGuard is attached to
   ``state.budget_guard`` but not propagated into the subprocess
   worker. Sub-agent LLM call sites do not yet call
   ``guard.record_usage`` mid-flight, so a runaway sub-agent can
   exceed the soft cap within one phase. Per-phase rollup (after
   ``delegate`` returns) still works for accounting, but hard
   enforcement requires worker-layer wiring (S6.5).

Both gaps are intentional — wire-ups land in dedicated PRs to keep
S2's surface focused on the Generation phase contract.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from plugins.seed_pipeline.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_pipeline.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Generator"]


_DEFAULT_GENERATOR_MODEL = "claude-sonnet-4-6"
_GENERATOR_AGENT_NAME = "seed_generator"
_TASK_TYPE = "seed-generation"


class Generator(BaseSeedAgent):
    """Spawn N parallel sub-agents, each writing one candidate seed.

    Why a sub-agent fan-out (not a single LLM call):
    ------------------------------------------------

    Each candidate should be sampled independently from the generator
    model to avoid mode-collapse across the batch. Spawning N concurrent
    sub-agents with the same system prompt + per-candidate task gives the
    generator's temperature/stochasticity room to produce a diverse set,
    while the per-candidate file write makes the output addressable by
    later phases (Proximity needs the file paths to embed; Pilot needs
    them as audit seed inputs).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_GENERATOR_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="generator",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    def execute(self, state: PipelineState) -> SeedAgentResult:
        """Fan out N candidate-generation sub-agents and collect successes."""
        if state.run_dir is None:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message="Generator requires state.run_dir to be set",
            )
        if state.candidates_requested <= 0:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    f"state.candidates_requested must be > 0, got {state.candidates_requested}"
                ),
            )

        candidates_dir = state.run_dir / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)

        tasks = self._build_tasks(state, candidates_dir)
        log.info(
            "seed-pipeline generator dispatching %d tasks to %r",
            len(tasks),
            _GENERATOR_AGENT_NAME,
        )

        # announce=False — orchestrator already announces the parent
        # phase, individual candidate spawns are sub-events not parent
        # events.
        results = self._manager.delegate(tasks, announce=False)

        candidates: list[dict[str, object]] = []
        failed: list[tuple[str, str]] = []
        for task, result in zip(tasks, results, strict=False):
            if result.success:
                candidates.append(
                    {
                        "id": task.args["candidate_id"],
                        "path": task.args["output_path"],
                        "target_dim": task.args["target_dim"],
                        "gen_tag": task.args["gen_tag"],
                        "task_id": task.task_id,
                        "duration_ms": result.duration_ms,
                    }
                )
            else:
                failed.append((task.task_id, result.error or "unknown"))

        if failed:
            log.warning(
                "seed-pipeline generator: %d/%d sub-agents failed: %s",
                len(failed),
                len(tasks),
                failed[:3],
            )

        if not candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="generation_failed",
                error_message=(
                    f"all {len(tasks)} candidate sub-agents failed; "
                    f"first error: {failed[0][1] if failed else 'unknown'}"
                ),
            )

        return SeedAgentResult(
            role=self.role,
            output={"candidates": candidates},
        )

    def _build_tasks(self, state: PipelineState, candidates_dir: object) -> list[SubTask]:
        """Build the per-candidate SubTask list.

        Imports ``SubTask`` lazily so test fixtures that monkeypatch the
        manager don't pay the ``core.agent.sub_agent`` cold-start cost.
        """
        from core.agent.sub_agent import SubTask

        pool_path = str(state.pool_path_in) if state.pool_path_in else ""
        tasks: list[SubTask] = []
        for index in range(state.candidates_requested):
            candidate_id = f"{state.gen_tag}-{index:03d}-{uuid.uuid4().hex[:8]}"
            output_path = f"{candidates_dir}/{candidate_id}.md"
            description = self._build_description(
                state=state,
                candidate_id=candidate_id,
                output_path=output_path,
                pool_path=pool_path,
            )
            tasks.append(
                SubTask(
                    task_id=f"gen-{candidate_id}",
                    description=description,
                    task_type=_TASK_TYPE,
                    args={
                        "target_dim": state.target_dim,
                        "gen_tag": state.gen_tag,
                        "candidate_id": candidate_id,
                        "output_path": output_path,
                        "pool_path_in": pool_path,
                    },
                    agent=_GENERATOR_AGENT_NAME,
                )
            )
        return tasks

    def _build_description(
        self,
        *,
        state: PipelineState,
        candidate_id: str,
        output_path: str,
        pool_path: str,
    ) -> str:
        """Compose the per-candidate user message for the sub-agent.

        The system prompt is owned by ``.claude/agents/seed_generator.md``.
        The description fills in the per-spawn parameters (target dim,
        output path, pool reference, candidate id).
        """
        pool_hint = (
            f"Read 2-3 samples from {pool_path} for style alignment (do NOT copy verbatim)."
            if pool_path
            else "No existing pool provided; generate from scratch."
        )
        return (
            f"Generate ONE Petri audit seed targeting dim {state.target_dim!r}. "
            f"Generation tag: {state.gen_tag}. Candidate id: {candidate_id}. "
            f"Write the seed markdown to: {output_path}. "
            f"{pool_hint} "
            "See your system prompt (`seed_generator` AgentDefinition) for "
            "the full contract — frontmatter fields, body length, realism "
            "criterion, and forbidden patterns."
        )
