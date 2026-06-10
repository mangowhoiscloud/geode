"""Supervisor agent — Phase 0 of the seed generation (CSP-4, 2026-05-22).

Per the open-coscientist paper (arXiv:2502.18864 §3 Supervisor), this
role analyses the research goal up front and emits a domain-strategy
guide that every downstream sub-agent prefixes onto its own prompt.

GEODE re-domain mapping
=======================

The paper's "research goal" is free-text (``"Cure cancer"``); GEODE's
equivalent is the ``target_dim`` enum + the in-flight signals
(``baseline_snapshot`` per-dim evidence, ``meta_review_snapshot``
cross-run priors). The Supervisor's value here is *synthesising* those
signals into a coherent per-generation strategy that the
generator/critic/evolver wouldn't reconstruct independently:

- *Which* sub-dim of ``target_dim`` is most under-explored this run?
- *Which* prior-run failure pattern should the generator avoid?
- *Which* baseline-evidence row is the strongest hint for the critic?

Without Supervisor each sub-agent re-reads the same snapshots and
produces its own (potentially divergent) interpretation. The Supervisor
emits one canonical reading that the rest of the pipeline shares.

Single-shot per run
===================

Like Meta-reviewer, Supervisor dispatches ONE sub-agent (single-item
``delegate``) — the output is run-level guidance, not per-candidate
work. Costs one Opus call at the front of the run (paid once for all
the downstream sub-agent spawns to consume).

Sub-agent contract (``plugins/seed_generation/agents/supervisor.md``)::

    {
      "research_goal_analysis": {
        "target_dim_focus":   "<one-sentence sharpened goal>",
        "sub_dim_priorities": ["<sub-dim-1>", "<sub-dim-2>"],
        "key_constraints":    ["<constraint-1>"]
      },
      "phase_guidance": {
        "generation": "<= 80 token guidance for the seed_generator role",
        "critique":   "<= 80 token guidance for the seed_critic role",
        "evolution":  "<= 80 token guidance for the seed_evolver role"
      },
      "session_summary": "<= 200 token plain-prose summary"
    }

Downstream consumers prefix the relevant ``phase_guidance.*`` entry
into their per-candidate description (see
``Generator._build_description`` etc., wired in CSP-4 alongside this
module). ``session_summary`` is logged for the operator.

Why NOT make this the orchestrator's responsibility?

The orchestrator owns *control flow* (phase order, lane gating, state
merging). Compute-bearing prompts (LLM calls) belong in sub-agents —
the orchestrator stays test-friendly without an LLM budget, and the
Supervisor itself can be unit-tested with a stub manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import (
    DEFAULT_AGENT_MODEL,
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
    sum_sub_result_tokens,
)
from plugins.seed_generation.json_schemas import SUPERVISOR_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Supervisor"]


_DEFAULT_SUPERVISOR_MODEL = DEFAULT_AGENT_MODEL
_SUPERVISOR_AGENT_NAME = "seed_supervisor"
_TASK_TYPE = "seed-supervisor"

_REQUIRED_SUPERVISOR_FIELDS = (
    "research_goal_analysis",
    "phase_guidance",
    "session_summary",
)


class Supervisor(BaseSeedAgent):
    """Run-level strategy synthesis. Dispatches ONE Opus sub-agent.

    Why Opus, not the cheaper Sonnet default?
    -----------------------------------------

    Supervisor reads multiple snapshots (baseline evidence + meta-review
    priors + cohort hints) and emits structured guidance the rest of
    the pipeline depends on for an entire run. The synthesis quality
    bottlenecks the value of every downstream Opus / Sonnet call, so
    the marginal cost of one extra Opus invocation up front is dwarfed
    by the cost of misaligned generation across N candidates. Matches
    the Meta-reviewer model choice (also Opus).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_SUPERVISOR_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="supervisor",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Dispatch one supervisor sub-agent and parse its guidance."""
        task = self._build_task(state)
        log.info(
            "seed-generation supervisor dispatching strategy synthesis to %r",
            _SUPERVISOR_AGENT_NAME,
        )
        results = await self._manager.adelegate([task], announce=False)
        if not results:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="supervisor_failed",
                error_message="SubAgentManager returned no results for supervisor task.",
            )

        result = results[0]
        # PR-SEEDGEN-TOKENS (2026-05-30) — forward sub-agent LLM usage (0
        # for subscription calls) onto every return below.
        prompt_tokens, completion_tokens, usd_spent = sum_sub_result_tokens(results)
        if not result.success:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="supervisor_failed",
                error_message=result.error or "supervisor sub-agent failed",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_spent=usd_spent,
            )
        parsed = parse_structured_output(
            result.output,
            required_fields=_REQUIRED_SUPERVISOR_FIELDS,
        )
        if parsed is None:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="supervisor_failed",
                error_message=(f"malformed supervisor payload: result.output={result.output!r}"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_spent=usd_spent,
            )

        return SeedAgentResult(
            role=self.role,
            output={"supervisor_guidance": parsed},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd_spent=usd_spent,
        )

    def _build_task(self, state: PipelineState) -> SubTask:
        """Build the single SubTask carrying the snapshot summaries."""
        from core.agent.sub_agent import SubTask

        snapshot = _state_snapshot(state)
        return SubTask(
            task_id=f"supervisor-{state.run_id}",
            description=self._build_description(state, snapshot),
            task_type=_TASK_TYPE,
            args={
                "run_id": state.run_id,
                "target_dim": state.target_dim,
                "gen_tag": state.gen_tag,
                "cohort": state.cohort,
                "snapshot": snapshot,
            },
            agent=_SUPERVISOR_AGENT_NAME,
            model=self.model,
            source=self.adapter_source,
            # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — pre-fix this
            # spawn omitted ``response_schema=`` so the worker-side
            # ``_needs_schema_retry`` never fired on supervisor
            # malformed output. Combined with the missing
            # SUPERVISOR_SCHEMA definition, supervisor was the one
            # Loop-1 phase running without structured-output enforcement
            # (and the only role missing from smoke 18 checkpoints).
            response_schema=SUPERVISOR_SCHEMA,
        )

    def _build_description(
        self,
        state: PipelineState,
        snapshot: dict[str, Any],
    ) -> str:
        """Compose the per-run user message for the single sub-agent.

        The system prompt is owned by ``plugins/seed_generation/agents/supervisor.md``;
        the description fills in the per-run context (target dim, cohort,
        and the *summary* of the snapshots — never the raw rows). Keeping
        the description compact (< 1KB) so the Opus call is dominated by
        reasoning, not snapshot regurgitation.
        """
        return (
            f"Analyse the upcoming seed-generation run "
            f"{state.run_id!r}. Target dim: {state.target_dim!r}. Cohort: "
            f"{state.cohort!r}. Generation tag: {state.gen_tag!r}. "
            f"Candidates requested: {state.candidates_requested}. "
            f"Snapshot summary: {snapshot['summary']}. "
            f"Baseline evidence rows available: "
            f"{snapshot['baseline_evidence_count']} "
            f"(for target_dim {state.target_dim!r}: "
            f"{snapshot['baseline_evidence_for_target']}). "
            f"Prior-run meta-review priors available: "
            f"{snapshot['has_meta_review_snapshot']}. "
            "Per your system prompt, return JSON with fields "
            "`research_goal_analysis`, `phase_guidance` "
            "(keys: generation, critique, evolution), and "
            "`session_summary` (<= 200 tokens). Read upstream "
            "snapshots via `read_document` if you need the raw rows; "
            "the description above only gives counts.\n\n"
            # PR-ROLE-JSON-ENFORCE-EXTENSION (2026-05-26) — mirror the
            # PR-HANDOFF-SCHEMAS gate so the LLM can't slip prose past
            # the parser. Supervisor wasn't observed failing in smoke
            # 17 because the role isn't registered in default test
            # fixtures, but the same gap pattern applies once the role
            # is enabled in production.
            "Your FINAL response must be ONLY the JSON object with fields "
            "`research_goal_analysis`, `phase_guidance` (keys: generation, "
            "critique, evolution), `session_summary`. No prose summary, no "
            "markdown bullets, no preamble. Start with `{` and end with `}`."
        )


def _state_snapshot(state: PipelineState) -> dict[str, Any]:
    """Compact snapshot summary for the supervisor task description.

    Counts only — the supervisor sub-agent can pull raw rows via
    ``read_document`` if needed. Keeps the per-task description under
    1KB so the Opus call stays dominated by reasoning, not snapshot
    parsing.
    """
    baseline_snapshot = getattr(state, "baseline_snapshot", None)
    baseline_rows = 0
    baseline_for_target = 0
    if baseline_snapshot is not None:
        evidence = getattr(baseline_snapshot, "evidence", None) or {}
        if isinstance(evidence, dict):
            baseline_rows = sum(len(v) if isinstance(v, list) else 1 for v in evidence.values())
            target_rows = evidence.get(state.target_dim, [])
            baseline_for_target = (
                len(target_rows) if isinstance(target_rows, list) else (1 if target_rows else 0)
            )
    has_priors = getattr(state, "meta_review_snapshot", None) is not None
    summary = (
        f"run_id={state.run_id} target={state.target_dim} cohort={state.cohort} "
        f"gen={state.gen_tag} candidates={state.candidates_requested}"
    )
    return {
        "summary": summary,
        "baseline_evidence_count": baseline_rows,
        "baseline_evidence_for_target": baseline_for_target,
        "has_meta_review_snapshot": has_priors,
    }
