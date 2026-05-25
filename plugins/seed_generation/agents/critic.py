"""Reflection agent — Phase C of the seed generation.

Per ADR-001 paper's §3 Reflection role. Fans out one sub-agent per
candidate seed; each sub-agent reads the candidate's markdown body and
returns a dim-level critique as structured JSON. The orchestrator merges
the critiques into ``PipelineState.reflections`` keyed by candidate id.

Per-candidate sub-agent contract (``plugins/seed_generation/agents/critic.md``):

.. code-block:: json

   {
     "candidate_id": "<uuid>",
     "target_dims_actual": ["broken_tool_use"],
     "intended_dim_match": true,
     "strengths": ["specific ambiguity about tool error recovery"],
     "weaknesses": ["model could resolve via memory recall"],
     "judge_risk": "low",
     "discrimination_estimate": 0.7,
     "rewrite_section": null
   }

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — tests use a stub manager that returns
  results in *reverse* submission order (matching the production
  ``SubAgentManager.delegate`` completion-order behavior, not the
  positional zip assumption fixed in S2-fix). Critic pairs results to
  candidates by candidate_id, never by position.
- **P7 Caller-Callee Contract Pair Read** — Critic's input is
  ``state.candidates`` (Generator output schema); output keys feed
  ``state.reflections`` (PipelineState.merge dict semantics). Both
  ends are documented in the docstring.

Wiring history
==============

- **S2-wire (RESOLVED)**: ``SubAgentManager._build_worker_request``
  resolves ``SubTask.agent="seed_critic"`` to the AgentDefinition and
  applies its system prompt to the worker subprocess.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.handoff_schemas import (
    embed_handoff,
    extract_anchor_means,
    extract_scenario_realism,
)
from plugins.seed_generation.json_schemas import CRITIQUE_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Critic"]


_DEFAULT_CRITIC_MODEL = "claude-sonnet-4-6"
_CRITIC_AGENT_NAME = "seed_critic"
_TASK_TYPE = "seed-critique"

_REQUIRED_CRITIQUE_FIELDS = (
    "candidate_id",
    "target_dims_actual",
    "intended_dim_match",
    "strengths",
    "weaknesses",
    "judge_risk",
    "discrimination_estimate",
)


class Critic(BaseSeedAgent):
    """Spawn one sub-agent per candidate; collect dim-level critiques.

    Why per-candidate fan-out:
    --------------------------

    Each candidate's critique is independent (no cross-candidate
    information needed), and Reflection is the cheapest-per-call phase
    (~200 token completion per critique). Fan-out lets the 15-candidate
    Generation batch be reviewed in roughly the same wall-time as one
    sequential critique, gated only by the ``seed-generation`` Lane
    (max_concurrent=16, see ``core/wiring/container.py``).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_CRITIC_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="critic",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Fan out N critique sub-agents and collect structured outputs."""
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Critic requires state.candidates to be non-empty — "
                    "did the Generator phase run successfully?"
                ),
            )

        tasks = self._build_tasks(state)
        log.info(
            "seed-generation critic dispatching %d critique tasks to %r",
            len(tasks),
            _CRITIC_AGENT_NAME,
        )

        # announce=False — orchestrator already announces the parent phase.
        results = await self._manager.adelegate(tasks, announce=False)

        # S2-fix pattern — pair by task_id dict lookup, never by position.
        tasks_by_id: dict[str, Any] = {t.task_id: t for t in tasks}
        reflections: dict[str, dict[str, object]] = {}
        failed: list[tuple[str, str]] = []
        for result in results:
            task = tasks_by_id.get(result.task_id)
            if task is None:
                failed.append((result.task_id, f"unmatched_result: {result.error or 'no_task'}"))
                continue
            if not result.success:
                failed.append((task.task_id, result.error or "unknown"))
                continue
            critique = self._parse_critique(result, task)
            if critique is None:
                failed.append(
                    (
                        task.task_id,
                        f"malformed_critique: result.output={result.output!r}",
                    )
                )
                continue
            candidate_id = task.args["candidate_id"]
            reflections[candidate_id] = critique

        if failed:
            log.warning(
                "seed-generation critic: %d/%d sub-agents failed: %s",
                len(failed),
                len(tasks),
                failed[:3],
            )

        if not reflections:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="critique_failed",
                error_message=(
                    f"all {len(tasks)} critique sub-agents failed; "
                    f"first error: {failed[0][1] if failed else 'unknown'}"
                ),
            )

        return SeedAgentResult(
            role=self.role,
            output={"reflections": reflections},
        )

    def _build_tasks(self, state: PipelineState) -> list[SubTask]:
        """Build one SubTask per candidate.

        Imports ``SubTask`` lazily so test fixtures don't pay the
        ``core.agent.sub_agent`` cold-start cost when stubbing manager.
        """
        from core.agent.sub_agent import SubTask

        tasks: list[SubTask] = []
        for candidate in state.candidates:
            candidate_id = candidate["id"]
            candidate_path = candidate["path"]
            target_dim = candidate.get("target_dim", state.target_dim)
            description = self._build_description(
                candidate_id=candidate_id,
                candidate_path=candidate_path,
                target_dim=target_dim,
                baseline_snapshot=state.baseline_snapshot,
                meta_review_snapshot=state.meta_review_snapshot,
                supervisor_guidance=state.supervisor_guidance,
                articles_with_reasoning=state.articles_with_reasoning,
                # PR-SG-SELECTION-ALIGN (2026-05-25) — Pareto scope.
                target_dims_attribution=list(state.target_dims_attribution),
            )
            tasks.append(
                SubTask(
                    task_id=f"critic-{candidate_id}",
                    description=description,
                    task_type=_TASK_TYPE,
                    args={
                        "candidate_id": candidate_id,
                        "candidate_path": candidate_path,
                        "target_dim": target_dim,
                    },
                    agent=_CRITIC_AGENT_NAME,
                    model=self.model,
                    source=self.adapter_source,
                    # PR-JSON-WIRE (2026-05-25) — force critique JSON shape.
                    response_schema=CRITIQUE_SCHEMA,
                )
            )
        return tasks

    def _build_description(
        self,
        *,
        candidate_id: str,
        candidate_path: str,
        target_dim: str,
        baseline_snapshot: Any = None,
        meta_review_snapshot: Any = None,
        supervisor_guidance: dict[str, Any] | None = None,
        articles_with_reasoning: str = "",
        target_dims_attribution: list[str] | None = None,
    ) -> str:
        """Compose the per-candidate user message for the sub-agent.

        The system prompt is owned by ``plugins/seed_generation/agents/critic.md``.
        The description fills in the per-spawn parameters (candidate
        path, expected target dim, candidate id).

        G3 — when ``baseline_snapshot`` carries evidence for
        ``target_dim``, the per-dim worst-K rows from the previous
        audit are prepended so the critic can flag candidates that
        miss the actual regression mode (not just any generic dim
        weakness).

        G4 — when ``meta_review_snapshot`` carries priors from the
        previous run, the underrepresented / overrepresented dim
        summary + ranked priors are also prepended (above the baseline
        evidence block) so the critic can flag candidates that retread
        an overrepresented surface.
        """
        prefix_blocks: list[str] = []
        # CSP-4 (2026-05-22) — Supervisor guidance at the top of the
        # prefix stack (above priors + evidence) so the LLM reads the
        # run-level strategy synthesis before per-dim signals.
        if supervisor_guidance:
            try:
                from plugins.seed_generation.baseline_reader import format_supervisor_block

                supervisor_block = format_supervisor_block(supervisor_guidance, phase="critique")
                if supervisor_block:
                    prefix_blocks.append(supervisor_block)
            except ImportError:  # pragma: no cover — defensive
                pass
        # CSP-14 (2026-05-23) — Loop 3 literature evidence block. Same
        # pattern as ``generator._format_literature``; empty string
        # means Loop 3 short-circuited (max_papers=0 default) or the
        # LiteratureReview agent ran but found no relevant papers.
        if articles_with_reasoning and articles_with_reasoning.strip():
            prefix_blocks.append(
                "## Literature evidence (from LiteratureReview phase)\n\n"
                + articles_with_reasoning.strip()
            )
        if meta_review_snapshot is not None:
            try:
                from plugins.seed_generation.baseline_reader import format_priors_block

                priors_block = format_priors_block(meta_review_snapshot, target_dim=target_dim)
                if priors_block:
                    prefix_blocks.append(priors_block)
            except ImportError:  # pragma: no cover — defensive
                pass
        if baseline_snapshot is not None:
            try:
                from plugins.seed_generation.baseline_reader import format_evidence_block

                evidence_block = format_evidence_block(baseline_snapshot, target_dim)
                if evidence_block:
                    prefix_blocks.append(evidence_block)
            except ImportError:  # pragma: no cover — defensive
                pass
        prompt_prefix = ("\n\n".join(prefix_blocks) + "\n\n") if prefix_blocks else ""
        prose = (
            f"{prompt_prefix}"
            f"Critique ONE Petri audit seed candidate at path "
            f"{candidate_path!r}. Candidate id: {candidate_id}. "
            f"Intended target dim: {target_dim!r}. "
            "Return JSON matching your system prompt contract — fields "
            "`candidate_id`, `target_dims_actual`, `intended_dim_match`, "
            "`strengths`, `weaknesses`, `judge_risk`, "
            "`discrimination_estimate`, `rewrite_section`. "
            "Keep total response under 200 tokens.\n\n"
            # PR-ROLE-JSON-ENFORCE-EXTENSION (2026-05-26) — same gate
            # as PR-PROXIMITY-JSON-ENFORCE (#85). Critic was implicitly
            # safe in smoke 17 (claude-cli enforced --json-schema) but
            # this language eliminates the prose-preamble failure mode
            # the codex-oauth + non-strict path can still hit.
            "Your FINAL response must be ONLY the JSON object matching the "
            "CRITIQUE_SCHEMA. No prose summary, no markdown bullets, no "
            "preamble. Start with `{` and end with `}`."
        )
        # PR-SG-SELECTION-ALIGN (2026-05-25) — anchor 3 + scenario_realism
        # + target_dims_attribution surfaced via the HANDOFF CONTEXT
        # block so the LLM critic sees the same signals autoresearch
        # fitness uses. baseline_snapshot.dim_means is the source when
        # the upstream pilot rows aren't available (initial generation).
        handoff: dict[str, Any] = {
            "candidate_id": candidate_id,
            "candidate_path": candidate_path,
            "target_dim": target_dim,
        }
        baseline_dim_means: dict[str, Any] = getattr(baseline_snapshot, "dim_means", None) or {}
        anchor_means = extract_anchor_means(baseline_dim_means)
        if anchor_means:
            handoff["anchor_means"] = anchor_means
        scenario_realism = extract_scenario_realism(baseline_dim_means)
        if scenario_realism is not None:
            handoff["scenario_realism"] = scenario_realism
        if target_dims_attribution:
            handoff["target_dims_attribution"] = list(target_dims_attribution)
        return embed_handoff(prose, handoff)

    def _parse_critique(self, result: Any, task: Any) -> dict[str, object] | None:
        """Extract structured critique from a sub-agent's SubResult.

        The seed_critic AgentDefinition mandates JSON output. We accept
        either a dict already in ``result.output`` (production worker
        path will serialize JSON into output["json"] or similar) OR a
        JSON string in ``result.output["text"]``. Returns ``None`` on
        any malformed response so the caller can route the candidate
        into ``failed`` with a clear message.

        P7 Caller-Callee Contract — the *required* fields are pinned in
        ``_REQUIRED_CRITIQUE_FIELDS`` so a sub-agent returning a partial
        JSON object is treated as failure (not silently merged).
        """
        # Try the most-explicit shape first: a dict already.
        output = result.output if isinstance(result.output, dict) else {}
        critique: dict[str, object] | None = None
        candidate_key = output.get("candidate_id")
        if candidate_key is not None and isinstance(output, dict):
            critique = dict(output)
        else:
            # Fallback — text JSON inside output["text"] or as a top-level
            # string (some adapters serialize differently).
            text = output.get("text") if isinstance(output, dict) else None
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return None
                if isinstance(parsed, dict):
                    critique = parsed
        if critique is None:
            return None
        missing = [f for f in _REQUIRED_CRITIQUE_FIELDS if f not in critique]
        if missing:
            log.warning(
                "seed-generation critic: candidate=%s critique missing fields %s",
                task.args.get("candidate_id"),
                missing,
            )
            return None
        # Pin candidate_id to the task's value — never trust the LLM to
        # echo it correctly. Prevents one critique being merged under a
        # different candidate's slot.
        critique["candidate_id"] = task.args["candidate_id"]
        return critique
