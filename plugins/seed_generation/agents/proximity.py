"""Proximity agent — Phase B (dedup) of the seed generation.

CSP-8 (2026-05-22) — reverted to the open-coscientist paper's
LLM-clustering pattern (``nodes/proximity.py``). Replaces the
pre-CSP-8 GEODE-specific 3-track majority vote (embedding cosine +
5-gram Jaccard + role overlap) with a single sub-agent dispatch that
asks the LLM to cluster the candidate batch + emit per-candidate
``similarity_degree`` (``high`` / ``medium`` / ``low``). Only
``high`` entries are dropped — the rest survive.

Sub-agent contract (``plugins/seed_generation/agents/proximity.md``)::

    {
      "similarity_clusters": [
        {
          "cluster_id": "c1",
          "topic":      "<short human-readable label>",
          "similar_hypotheses": [
            {"candidate_id": "<id>", "similarity_degree": "high"|"medium"|"low"}
          ]
        }
      ]
    }

The LLM's semantic understanding subsumes the geometric distance
notion the embedding track previously enforced. Trade-offs:

- ❌ Non-deterministic (same input may cluster differently across calls).
- ❌ LLM cost dominates (1 prompt lists every candidate body).
- ✅ Paper-fidelity (matches arXiv:2502.18864 §3 Proximity).
- ✅ Single dependency-free clustering call (no embedding API,
  no rate limit, no PII surface in embedding requests).

Why drop the 3-track + proximity_graph
======================================

Pre-CSP-8 surfaced four GEODE-specific extensions (PR-Π1
proximity_graph, PR-Π2 partial-survive floor, PR-Π3 goal-conditioning,
3-track majority vote). Operator decision: revert to the paper's
intent — LLM as the *semantic* arbiter, no geometric crutch.
``proximity_graph`` dependents (Ranker bracket seeding) revert to the
legacy random-shuffle in the same PR.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
    sum_sub_result_tokens,
)
from plugins.seed_generation.json_schemas import PROXIMITY_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["HIGH_SIMILARITY_DEGREE", "Proximity"]


HIGH_SIMILARITY_DEGREE = "high"

_DEFAULT_PROXIMITY_MODEL = "claude-opus-4-8"
_PROXIMITY_AGENT_NAME = "seed_proximity"
_TASK_TYPE = "seed-proximity"

_REQUIRED_FIELDS = ("similarity_clusters",)
_VALID_DEGREES = frozenset({"high", "medium", "low"})


class Proximity(BaseSeedAgent):
    """Single-shot LLM clustering — paper §3 Proximity.

    Dispatches ONE ``seed_proximity`` sub-agent that reads every
    candidate body and emits ``similarity_clusters``. The orchestrator
    then drops every candidate marked ``similarity_degree == "high"``.
    The LLM names which entry to *keep* per cluster by omitting it
    from the ``high`` list — the orchestrator does not have to apply a
    tiebreak rule.

    Mutates ``state.candidates`` in place (filters out high-similarity
    duplicates) and emits ``state.similarity_clusters`` +
    ``state.removed_duplicates`` (paper schema).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_PROXIMITY_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="proximity",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message="Proximity requires state.candidates to be non-empty",
            )
        if len(state.candidates) == 1:
            # Trivial — no duplicates possible. Emit empty cluster set.
            return SeedAgentResult(
                role=self.role,
                output={"similarity_clusters": [], "removed_duplicates": []},
            )

        task = self._build_task(state)
        log.info(
            "seed-generation proximity dispatching LLM clustering of %d candidates to %r",
            len(state.candidates),
            _PROXIMITY_AGENT_NAME,
        )
        results = await self._manager.adelegate([task], announce=False)
        if not results:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="proximity_failed",
                error_message="SubAgentManager returned no results for proximity task.",
            )
        result = results[0]
        # PR-SEEDGEN-TOKENS (2026-05-30) — forward sub-agent LLM usage (0
        # for subscription calls) onto every return below.
        prompt_tokens, completion_tokens, usd_spent = sum_sub_result_tokens(results)
        if not result.success:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="proximity_failed",
                error_message=result.error or "proximity sub-agent failed",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_spent=usd_spent,
            )
        parsed = parse_structured_output(result.output, required_fields=_REQUIRED_FIELDS)
        if parsed is None:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="proximity_failed",
                error_message=(f"malformed proximity payload: result.output={result.output!r}"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_spent=usd_spent,
            )

        clusters = parsed.get("similarity_clusters", [])
        if not isinstance(clusters, list):
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="proximity_failed",
                error_message=(
                    f"similarity_clusters must be a list, got {type(clusters).__name__}"
                ),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd_spent=usd_spent,
            )

        removed_ids, removed_rows = _select_removals(state.candidates, clusters)
        # Mutate state.candidates in-place (orchestrator's state.merge
        # for list keys would otherwise extend rather than replace).
        state.candidates = [c for c in state.candidates if c["id"] not in removed_ids]

        log.info(
            "seed-generation proximity: %d clusters → %d removed (high similarity)",
            len(clusters),
            len(removed_ids),
        )
        return SeedAgentResult(
            role=self.role,
            output={
                "similarity_clusters": clusters,
                "removed_duplicates": removed_rows,
            },
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd_spent=usd_spent,
        )

    def _build_task(self, state: PipelineState) -> SubTask:
        from core.agent.sub_agent import SubTask

        candidate_summary = _build_candidate_summary(state.candidates)
        return SubTask(
            task_id=f"proximity-{state.run_id}",
            description=self._build_description(state, candidate_summary),
            task_type=_TASK_TYPE,
            args={
                "run_id": state.run_id,
                "target_dim": state.target_dim,
                "candidate_count": len(state.candidates),
            },
            agent=_PROXIMITY_AGENT_NAME,
            model=self.model,
            source=self.adapter_source,
            # PR-JSON-WIRE (2026-05-25) — force similarity_clusters JSON shape.
            response_schema=PROXIMITY_SCHEMA,
        )

    def _build_description(self, state: PipelineState, candidate_summary: str) -> str:
        return (
            f"Cluster the {len(state.candidates)} candidate Petri audit seeds for "
            f"target dim {state.target_dim!r} by semantic similarity. Each candidate "
            f"is listed below with its id and the first ~400 chars of its body — read "
            f"the full body via `read_document` when ambiguous. Per your system "
            "prompt contract, return JSON with field `similarity_clusters` — each "
            "cluster carries `cluster_id`, `topic`, and `similar_hypotheses` (list of "
            "`{candidate_id, similarity_degree: high|medium|low}`). Mark "
            '`similarity_degree="high"` ONLY when two candidates are near-duplicate '
            "(would produce essentially the same audit transcript). Keep ONE "
            "candidate per high-similarity group OUT of the high list — the "
            "orchestrator drops every entry marked high.\n\n"
            # PR-PROXIMITY-JSON-ENFORCE (2026-05-25) — mirror the
            # PR-HANDOFF-SCHEMAS pattern from pilot/evolver/critic.
            # Pre-fix smoke 17 hit a phase_failed because the LLM
            # returned a narrative ("Analyzing the 14 candidates by
            # reading their excerpts — grouping by mechanism…") with
            # no JSON object at all. Now the prompt is explicit about
            # JSON-only response shape so the model can't slip a prose
            # preamble past the parser.
            "Your FINAL response must be ONLY the JSON object matching the "
            "PROXIMITY_SCHEMA (single required field: `similarity_clusters`). "
            "No prose summary, no markdown bullets, no preamble. Start with "
            "`{` and end with `}`.\n\n"
            f"Candidates:\n{candidate_summary}"
        )


# ----------------------------------------------------------------------
# Pure helpers — testable without an LLM call.
# ----------------------------------------------------------------------


def _build_candidate_summary(candidates: list[dict[str, Any]]) -> str:
    """Render candidates as ``- id: <id>\\n  excerpt: <400 chars>`` blocks.

    Body is whitespace-collapsed so multi-line markdown becomes a single
    readable paragraph; full body is one ``read_document`` call away
    when the model needs more context.
    """
    lines: list[str] = []
    for cand in candidates:
        cid = str(cand.get("id", "?"))
        path = cand.get("path")
        excerpt = ""
        if path:
            try:
                body = Path(str(path)).read_text(encoding="utf-8")
                excerpt = " ".join(body.split())[:400]
            except OSError:
                excerpt = "<body unreadable — call read_document to inspect>"
        lines.append(f"- id: {cid}\n  excerpt: {excerpt}")
    return "\n".join(lines)


def _select_removals(
    candidates: list[dict[str, Any]],
    clusters: list[Any],
) -> tuple[set[str], list[dict[str, Any]]]:
    """Walk the LLM clusters and select the candidate ids to drop.

    Contract: every entry with ``similarity_degree == "high"`` is a
    duplicate to remove. The LLM keeps the "winner" of each high-
    similarity group OUT of its own high-list (paper convention).
    Unknown candidate ids are skipped with a WARNING — defensive
    against LLM hallucinating ids that don't exist in the batch.
    """
    valid_ids = {str(c["id"]) for c in candidates}
    removed_ids: set[str] = set()
    removed_rows: list[dict[str, Any]] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cluster_id = str(cluster.get("cluster_id", "?"))
        topic = str(cluster.get("topic", ""))
        sims = cluster.get("similar_hypotheses") or []
        if not isinstance(sims, list):
            continue
        for entry in sims:
            if not isinstance(entry, dict):
                continue
            cid_raw = entry.get("candidate_id")
            degree = entry.get("similarity_degree")
            if not isinstance(cid_raw, str) or degree not in _VALID_DEGREES:
                continue
            if cid_raw not in valid_ids:
                log.warning(
                    "seed-generation proximity: LLM emitted unknown candidate_id=%r "
                    "in cluster %r — ignoring.",
                    cid_raw,
                    cluster_id,
                )
                continue
            if degree == HIGH_SIMILARITY_DEGREE:
                removed_ids.add(cid_raw)
                removed_rows.append(
                    {
                        "candidate_id": cid_raw,
                        "cluster_id": cluster_id,
                        "topic": topic,
                        "reason": "high_similarity_duplicate",
                    }
                )
    return removed_ids, removed_rows
