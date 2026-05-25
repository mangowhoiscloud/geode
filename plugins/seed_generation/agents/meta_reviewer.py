"""Meta-review agent — Phase G of the seed generation.

Per ADR-001 paper §3 Meta-review: after the Ranker + Evolver phases,
analyse the entire candidate batch and emit a coverage report + next-
generation hypothesis prior + session summary. The orchestrator merges
the report under :attr:`PipelineState.meta_review` and persists it as
part of the parent-context offload (S8 second deliverable, handled in
``plugins.seed_generation.orchestrator``).

Single-shot, single sub-agent — unlike Generator / Critic / Pilot /
Ranker / Evolver this phase doesn't fan out per-candidate. One
sub-agent reads the aggregated state (candidates, pilot_scores,
elo_ratings, survivors, reflections, evolved_candidates) and produces
one structured report.

Sub-agent contract (``plugins/seed_generation/agents/meta_reviewer.md``):

.. code-block:: json

   {
     "coverage": {"<target_dim>": <count>, ...},
     "underrepresented_dims": ["<dim>", ...],
     "overrepresented_dims": ["<dim>", ...],
     "next_gen_priors": [
       {"target_dim": "<dim>", "weight": <0..1>, "rationale": "<= 80 tokens"}
     ],
     "elo_distribution": {"min": <float>, "p50": <float>, "p95": <float>},
     "evolution_yield": {"attempted": <int>, "successful": <int>},
     "session_summary": "<= 300 tokens"
   }

P-checklist application:

- **P1 Stub Fidelity Audit** — tests cover failure paths (missing
  fields, non-dict shape, JSON-as-text fallback) via
  :func:`parse_structured_output`'s contract.
- **P7 Caller-Callee Contract Pair Read** — Meta-reviewer reads ALL
  6 upstream-phase state fields. Emits `state.meta_review` whose keys
  the S10 results.tsv writer + S11 CLI summary renderer consume.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
)
from plugins.seed_generation.json_schemas import META_REVIEW_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["MetaReviewer"]


_DEFAULT_META_REVIEWER_MODEL = "claude-opus-4-7"
_META_REVIEWER_AGENT_NAME = "seed_meta_reviewer"
_TASK_TYPE = "seed-meta-review"

_REQUIRED_META_FIELDS = (
    "coverage",
    "underrepresented_dims",
    "overrepresented_dims",
    "next_gen_priors",
    "elo_distribution",
    "evolution_yield",
    "session_summary",
)


class MetaReviewer(BaseSeedAgent):
    """Single-shot aggregate analyzer.

    Dispatches ONE sub-agent (via SubAgentManager.delegate with a
    single-item list to keep the supervisor's announce-queue / lane
    plumbing uniform with the per-candidate phases).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_META_REVIEWER_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="meta_reviewer",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Dispatch one meta-review sub-agent and parse the structured report."""
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "MetaReviewer requires state.candidates to be non-empty — "
                    "the run produced no candidates to review."
                ),
            )

        task = self._build_task(state)
        log.info(
            "seed-generation meta_reviewer dispatching aggregate review to %r",
            _META_REVIEWER_AGENT_NAME,
        )
        results = await self._manager.adelegate([task], announce=False)
        if not results:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="meta_review_failed",
                error_message="SubAgentManager returned no results for meta_reviewer task.",
            )

        result = results[0]
        if not result.success:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="meta_review_failed",
                error_message=result.error or "meta_review sub-agent failed",
            )
        parsed = parse_structured_output(
            result.output,
            required_fields=_REQUIRED_META_FIELDS,
        )
        if parsed is None:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="meta_review_failed",
                error_message=(f"malformed meta_review payload: result.output={result.output!r}"),
            )

        return SeedAgentResult(
            role=self.role,
            output={"meta_review": parsed},
        )

    def _build_task(self, state: PipelineState) -> SubTask:
        """Build the single SubTask carrying the aggregate state snapshot."""
        from core.agent.sub_agent import SubTask

        snapshot = _state_snapshot(state)
        return SubTask(
            task_id=f"meta-{state.run_id}",
            description=self._build_description(state, snapshot),
            task_type=_TASK_TYPE,
            args={
                "run_id": state.run_id,
                "target_dim": state.target_dim,
                "gen_tag": state.gen_tag,
                "snapshot": snapshot,
            },
            agent=_META_REVIEWER_AGENT_NAME,
            source=self.adapter_source,
            # PR-JSON-WIRE (2026-05-25) — force meta_review JSON shape.
            response_schema=META_REVIEW_SCHEMA,
        )

    def _build_description(
        self,
        state: PipelineState,
        snapshot: dict[str, Any],
    ) -> str:
        """Compose the user message for the single sub-agent.

        Includes the *counts* (not the raw rows) because the AgentDef
        contract caps the meta-reviewer's output at one paragraph + a
        few aggregate dicts — passing all candidate bodies would blow
        the context budget for what is fundamentally an aggregate
        statistics call.

        PR-CSP-13a (2026-05-23) — when Loop 2 (debate-turn) ran for any
        candidate, append a one-line debate summary so the meta-reviewer
        can attribute its effect on coverage / priors. The block is
        omitted entirely when the snapshot has no ``debate_summary`` key
        (``num_turns=0`` path OR iteration cycle with no surviving
        debate transcripts) to preserve pre-PR back-compat.
        """
        debate = snapshot.get("debate_summary")
        if debate is not None:
            debate_block = (
                f" Debate (Loop 2) ran for {debate['candidates_with_debate']} of "
                f"{len(snapshot['candidate_ids'])} candidates "
                f"(avg {debate['avg_turns']} turns/candidate, "
                f"sample {debate['sample_candidate_id']!r} = "
                f"{debate['sample_turn_count']} turns); attribute its effect "
                "on the proposal-side coverage + suggest next_gen_priors that "
                "either widen or sharpen the debate budget."
            )
        else:
            debate_block = ""

        return (
            f"Produce ONE meta-review report for the seed-generation run "
            f"{state.run_id!r}. Aggregate state snapshot: "
            f"{snapshot['summary']}. Target dim for this gen: "
            f"{state.target_dim!r}. Per your system prompt, return JSON "
            "with fields `coverage`, `underrepresented_dims`, "
            "`overrepresented_dims`, `next_gen_priors`, "
            "`elo_distribution`, `evolution_yield`, `session_summary` "
            "(<= 300 tokens). Reference the candidate ids "
            f"{snapshot['candidate_ids'][:5]!r} (showing first 5 of "
            f"{len(snapshot['candidate_ids'])}). Use `read_document` to "
            "inspect specific candidates as needed; do NOT request the "
            f"entire pool body.{debate_block}"
        )


def _state_snapshot(state: PipelineState) -> dict[str, Any]:
    """Build a compact serializable snapshot of state for the meta_reviewer.

    The snapshot is small enough to fit in a single sub-agent task
    description (~ 1KB) so the LLM doesn't have to re-fetch upstream
    state — it gets counts + ids and the AgentDef tells it to use
    ``read_document`` for specific candidates.

    PR-CSP-13a (2026-05-23) — also rolls up ``debate_summary`` from the
    Loop 2 (debate-turn) ``state.debate_transcripts`` dict so the
    meta-reviewer can attribute the debate's effect on coverage /
    next_gen_priors. Empty dict (``num_turns=0`` path) → ``None`` so
    ``_build_description`` skips the block.
    """
    candidate_ids = [c["id"] for c in state.candidates]
    coverage: dict[str, int] = {}
    for c in state.candidates:
        dim = c.get("target_dim", state.target_dim)
        coverage[dim] = coverage.get(dim, 0) + 1
    elo_values = sorted(state.elo_ratings.values())
    elo_distribution = {
        "min": elo_values[0] if elo_values else 0.0,
        "p50": elo_values[len(elo_values) // 2] if elo_values else 0.0,
        "p95": elo_values[int(len(elo_values) * 0.95)] if elo_values else 0.0,
    }
    summary = (
        f"{len(state.candidates)} candidates, "
        f"{len(state.reflections)} reflections, "
        f"{len(state.pilot_scores)} pilot rows, "
        f"{len(state.survivors)} survivors, "
        f"{len(state.evolved_candidates)} evolved, "
        f"elo p50={elo_distribution['p50']:.1f}"
    )
    snapshot: dict[str, Any] = {
        "summary": summary,
        "candidate_ids": candidate_ids,
        "survivors": list(state.survivors),
        "coverage": coverage,
        "elo_distribution": elo_distribution,
        "evolution_yield": {
            "attempted": len(state.survivors),
            "successful": len(state.evolved_candidates),
        },
    }
    # PR-CSP-13a (Codex MCP MEDIUM fix-up) — only add ``debate_summary``
    # when there's something to report. Otherwise the snapshot dict
    # (which is serialized into ``SubTask.args`` and rendered into the
    # worker's "Parameters:" line) gains a ``debate_summary: None`` row
    # that breaks byte-equivalence with the pre-CSP-13a back-compat
    # path. ``_build_description`` already gates on ``snapshot.get(...)``
    # so the omit-the-key shape is what the renderer needs to see.
    debate = _debate_summary(state, candidate_ids)
    if debate is not None:
        snapshot["debate_summary"] = debate
    return snapshot


def _debate_summary(state: PipelineState, candidate_ids: list[str]) -> dict[str, Any] | None:
    """Roll up ``state.debate_transcripts`` into an aggregate row.

    Returns ``None`` when no transcript matches the current batch.
    Causes:

    - Loop 2 ``num_turns=0`` path (debate dict empty), OR
    - num_turns >= 2 but no sub-agent emitted any turn, OR
    - iteration cycle N≥1 where the only transcripts on state are from
      candidates that have since been replaced (Codex MCP MEDIUM fix-up
      — ``state.candidates`` flips per iteration but the dict accumulates
      across iterations because ``PipelineState.merge`` uses ``dict
      .update``, so stale candidate-ids must be filtered).

    Filtering keeps the reported counts truthful — ``candidates_with_debate``
    means "current candidates that have a transcript", not "transcripts
    on the state dict regardless of provenance". Sample id pick stays
    deterministic over the *filtered* set.

    Shape (when present)::

        {
          "candidates_with_debate": int,   # how many *current* candidates ran a debate
          "total_turns": int,              # sum across the filtered set
          "avg_turns": float,              # mean turns per debate
          "sample_candidate_id": str,      # deterministic — alphabetically first id
          "sample_turn_count": int,        # turns recorded for the sample
        }
    """
    transcripts = getattr(state, "debate_transcripts", None) or {}
    if not transcripts:
        return None
    current = set(candidate_ids)
    # Filter to current batch — drops stale entries from prior iteration
    # cycles whose candidates are no longer in ``state.candidates``.
    relevant = {cid: turns for cid, turns in transcripts.items() if cid in current}
    if not relevant:
        return None
    total_turns = sum(len(turns) for turns in relevant.values())
    candidates_with_debate = len(relevant)
    # Deterministic sample pick: smallest candidate_id over the filtered
    # set (stable across runs / re-orderings).
    sample_id = min(relevant.keys())
    return {
        "candidates_with_debate": candidates_with_debate,
        "total_turns": total_turns,
        "avg_turns": round(total_turns / candidates_with_debate, 2),
        "sample_candidate_id": sample_id,
        "sample_turn_count": len(relevant[sample_id]),
    }
