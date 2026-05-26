"""LiteratureReview agent — Loop 3 of the seed-generation 3-loop port (PR-CSP-14).

Background
==========

open-coscientist (``nodes/literature_review.py:840-873``) runs a
**per-paper analysis loop** inside its literature_review node: query
generation → arxiv fetch → per-paper LLM analysis → synthesis. GEODE
Phase 1 (PR #1504) ported Loop 2 (debate-turn); this is Loop 3.

Architecture (mirrors upstream's 4-phase internal pipeline)
===========================================================

Per ``docs/plans/2026-05-23-seed-gen-loop3-bundle-serving.md`` § 3.2,
the agent runs a single dispatched sub-agent whose system prompt
(``agents/literature_review.md``) walks through 4 internal phases:

1. **query_gen** — 1 LLM call generates 3-5 arxiv search queries.
2. **paper_fetch** — for each query: ``arxiv_search`` + ``paper_fetch_arxiv`` +
   ``freeze_paper_snapshot``. Cache-hits skip re-write.
3. **per_paper_analysis** — for each unique paper (deduped by arxiv_id),
   1 LLM analysis call per paper. THIS IS LOOP 3.
4. **synthesis** — 1 LLM call rolls insights into a single
   ``articles_with_reasoning`` markdown block, consumed by downstream
   ``generator`` / ``critic`` / ``evolver`` prompts.

Insertion point — iteration 0 only
==================================

The orchestrator's ``_PHASE_ORDER`` inserts ``literature_review`` after
``supervisor`` and before ``generator``. ``_ITERATION_PHASE_ORDER`` (the
N≥1 cycle) does **not** include literature_review — the agent runs
once per run (papers are constant within a run; re-fetching every
iteration is pure cost).

``max_papers = 0`` short-circuit
================================

The manifest knob ``[seed_generation.role.literature_review].max_papers``
defaults to 0 (off). When 0, the agent returns immediately with
``articles_with_reasoning = ""`` — byte-equivalent to pre-PR-CSP-14
behavior. Operators flip the knob in their ``config.toml`` to opt in.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from plugins.seed_generation.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
)
from plugins.seed_generation.json_schemas import LITERATURE_REVIEW_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["LiteratureReview"]


_DEFAULT_LITERATURE_REVIEW_MODEL = "claude-opus-4-7"
_LITERATURE_REVIEW_AGENT_NAME = "seed_literature_review"
_TASK_TYPE = "seed-literature-review"

_DEFAULT_MAX_PAPERS = 0  # 0 = phase off (back-compat)
_DEFAULT_QUERIES_PER_RUN = 3


class LiteratureReview(BaseSeedAgent):
    """Single sub-agent that walks the 4-phase literature pipeline.

    Returns ``state.articles_with_reasoning`` (markdown block) +
    ``state.literature_snapshots`` (dict of arxiv_id → snapshot path).

    The agent SHORT-CIRCUITS to a no-op when ``manifest_role['max_papers']``
    is 0 (the default). This preserves pre-PR-CSP-14 behavior — operators
    opt in via ``[self_improving_loop.seed_generation.roles.literature_review]
    max_papers = N`` in ``~/.geode/config.toml``.
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_LITERATURE_REVIEW_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="literature_review",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Dispatch the 4-phase literature pipeline (or short-circuit on max_papers=0)."""
        max_papers = self._max_papers()
        if max_papers <= 0:
            # Back-compat path: no LLM calls, empty output, downstream agents
            # fall through to their non-literature prompts (same as
            # pre-PR-CSP-14 runs).
            return SeedAgentResult(
                role=self.role,
                output={
                    "articles_with_reasoning": "",
                    "literature_snapshots": {},
                },
            )

        task = self._build_task(state, max_papers)
        log.info(
            "seed-generation literature_review dispatching aggregate phase to %r "
            "(max_papers=%d, queries=%d)",
            _LITERATURE_REVIEW_AGENT_NAME,
            max_papers,
            self._queries_per_run(),
        )
        results = await self._manager.adelegate([task], announce=False)
        if not results:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="literature_review_failed",
                error_message="SubAgentManager returned no results for literature_review.",
            )

        result = results[0]
        if not result.success:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="literature_review_failed",
                error_message=result.error or "literature_review sub-agent failed",
            )

        parsed = parse_structured_output(
            result.output,
            required_fields=("articles_with_reasoning", "snapshots"),
        )
        if parsed is None:
            # Graceful degradation — Loop 3 is opt-in evidence augmentation,
            # not a hard prerequisite. If the agent flubbed the JSON, log
            # but keep the run going with empty literature.
            log.warning(
                "literature_review: malformed payload (run_id=%s); "
                "proceeding with empty literature",
                state.run_id,
            )
            return SeedAgentResult(
                role=self.role,
                output={
                    "articles_with_reasoning": "",
                    "literature_snapshots": {},
                },
            )

        articles = str(parsed.get("articles_with_reasoning", "") or "")
        snapshots_raw = parsed.get("snapshots", {}) or {}
        if not isinstance(snapshots_raw, dict):
            snapshots_raw = {}
        literature_snapshots: dict[str, str] = {
            str(k): str(v) for k, v in snapshots_raw.items() if isinstance(k, str)
        }
        return SeedAgentResult(
            role=self.role,
            output={
                "articles_with_reasoning": articles,
                "literature_snapshots": literature_snapshots,
            },
        )

    def _max_papers(self) -> int:
        """Resolve the per-role ``max_papers`` knob (defaults to 0 = off).

        Reads ``manifest_role['max_papers']`` populated by the registry.
        Out-of-range or non-int values fall back to 0 (defensive).
        """
        raw = (self.manifest_role or {}).get("max_papers")
        if isinstance(raw, int) and raw > 0:
            return raw
        return _DEFAULT_MAX_PAPERS

    def _queries_per_run(self) -> int:
        """Resolve the per-role ``queries_per_run`` knob (default 3)."""
        raw = (self.manifest_role or {}).get("queries_per_run")
        if isinstance(raw, int) and raw > 0:
            return raw
        return _DEFAULT_QUERIES_PER_RUN

    def _build_task(self, state: PipelineState, max_papers: int) -> SubTask:
        """Build the single SubTask carrying the budget + run anchors."""
        from core.agent.sub_agent import SubTask

        queries = self._queries_per_run()
        description = self._build_description(state, max_papers, queries)
        return SubTask(
            task_id=f"litreview-{state.run_id}",
            description=description,
            task_type=_TASK_TYPE,
            args={
                "run_id": state.run_id,
                "target_dim": state.target_dim,
                "gen_tag": state.gen_tag,
                "max_papers": max_papers,
                "queries_per_run": queries,
            },
            agent=_LITERATURE_REVIEW_AGENT_NAME,
            # PR-SCHEMA-PARSER-DRIFT-CLOSE (2026-05-26) — pre-fix this
            # spawn omitted ``response_schema=`` so the worker-side
            # ``_needs_schema_retry`` never fired when the literature
            # review LLM dropped one of the two required keys
            # (``articles_with_reasoning`` / ``snapshots``). The schema
            # itself has existed since PR-JSON-WIRE (#79) but was
            # un-wired at the spawn site.
            response_schema=LITERATURE_REVIEW_SCHEMA,
        )

    def _build_description(
        self,
        state: PipelineState,
        max_papers: int,
        queries_per_run: int,
    ) -> str:
        """Compose the user message for the 4-phase pipeline.

        The system prompt (``agents/literature_review.md``) walks through
        the four phases; this description fills in per-run parameters
        (budget, target_dim, supervisor priors if present).
        """
        supervisor_block = _format_supervisor(state)
        prefix = (supervisor_block + "\n\n") if supervisor_block else ""
        return (
            f"{prefix}"
            f"Run the literature_review 4-phase pipeline for seed-generation "
            f"run {state.run_id!r}. Target dim: {state.target_dim!r}. "
            f"Budget: max_papers={max_papers}, queries_per_run={queries_per_run}. "
            "Per your system prompt: (1) generate queries grounded in "
            "target_dim + supervisor priors, (2) for each query run "
            "``arxiv_search`` then ``paper_fetch_arxiv`` + "
            "``freeze_paper_snapshot`` to commit the paper, (3) per-paper "
            "analyse the abstract against target_dim, (4) synthesise into "
            "a single ``articles_with_reasoning`` markdown block. Return "
            "JSON with keys ``articles_with_reasoning`` (str) and "
            "``snapshots`` (dict[arxiv_id, snapshot_path]).\n\n"
            # PR-ROLE-JSON-ENFORCE-EXTENSION (2026-05-26) — even though
            # the orchestrator gracefully degrades on JSON parse failure
            # (Loop 3 is opt-in evidence, not a hard prerequisite), the
            # enforcement language eliminates the failure path entirely
            # so downstream Generator / Critic actually receive the
            # evidence block when ``max_papers >= 1``.
            "Your FINAL response must be ONLY the JSON object with the "
            "two required keys (`articles_with_reasoning`, `snapshots`). "
            "No prose summary, no markdown bullets, no preamble. "
            "Start with `{` and end with `}`."
        )


def _format_supervisor(state: PipelineState) -> str:
    """Inject Supervisor's literature_review phase guidance if present.

    Mirrors the pattern in ``generator.py:_format_supervisor`` — looks
    up ``state.supervisor_guidance['phase_guidance']['literature_review']``
    (when present) and formats it as a prefix block. No-op when the key
    is missing (Supervisor may emit only generation/critique/evolution
    keys for runs that don't activate Loop 3).
    """
    guidance = getattr(state, "supervisor_guidance", None) or {}
    phase_guidance = guidance.get("phase_guidance") if isinstance(guidance, dict) else None
    if not isinstance(phase_guidance, dict):
        return ""
    lit_guidance = phase_guidance.get("literature_review")
    if not isinstance(lit_guidance, str) or not lit_guidance.strip():
        return ""
    return f"## Supervisor guidance (literature_review)\n\n{lit_guidance.strip()}"
