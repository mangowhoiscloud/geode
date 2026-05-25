"""Evolution agent — Phase F of the seed generation (Reflection-driven section rewrite).

For each top-K survivor (from Ranker), the Evolver fans out one
sub-agent per survivor; the sub-agent reads the Critic's
``rewrite_section`` hint (the section name + critique that the
Reflection agent flagged) and rewrites ONLY that section while
preserving frontmatter + target_dim + ±20% token budget. The evolved
seed is written to ``<run_dir>/candidates_evolved/<uuid>.md`` and a
manifest entry is added to ``state.evolved_candidates`` for re-piloting
in the next generation.

Per-survivor sub-agent contract (``plugins/seed_generation/agents/evolver.md``):

.. code-block:: json

   {
     "parent_id": "<original-uuid>",
     "evolved_id": "<new-uuid>",
     "evolved_path": "<run_dir>/candidates_evolved/<new-uuid>.md",
     "rewrite_section": "<section name>",
     "verdict": "ok" | "evolution_skipped" | "failed",
     "notes": "<= 200 tokens"
   }

P-checklist application:

- **P1 Stub Fidelity Audit** — tests cover reverse-order completion
  pairing via the shared :func:`parse_structured_output` helper.
- **P7 Caller-Callee Contract** — Evolver consumes ``state.survivors``
  + ``state.reflections`` + ``state.pilot_scores`` (all three signals
  the AgentDef mandates the voter see). Emits ``state.evolved_candidates``
  list rows whose schema mirrors :class:`PipelineState.candidates`
  (id / path / target_dim / gen_tag / task_id / duration_ms) plus the
  evolution-specific ``parent_id`` + ``rewrite_section`` fields.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
)
from plugins.seed_generation.json_schemas import EVOLVE_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Evolver"]


_DEFAULT_EVOLVER_MODEL = "claude-sonnet-4-6"
_EVOLVER_AGENT_NAME = "seed_evolver"
_TASK_TYPE = "seed-evolve"

_REQUIRED_EVOLVE_FIELDS = (
    "parent_id",
    "evolved_id",
    "evolved_path",
    "rewrite_section",
    "verdict",
)
_VALID_VERDICTS = frozenset({"ok", "evolution_skipped", "failed"})

# CSP-6 (2026-05-22) — anti-convergence Jaccard threshold. An evolved
# seed body whose 5-gram Jaccard against any sibling evolved (or
# pre-existing) candidate exceeds this is treated as "too close" —
# the verdict gets coerced to ``evolution_skipped`` so the parent
# candidate stays.
#
# Raised 0.70 → 0.90 in PR-EVOLVER-JACCARD-OBS (2026-05-25). The
# original 0.70 mirrored co-scientist's ``DUPLICATE_SIMILARITY_
# THRESHOLD`` (``open-coscientist/nodes/evolve.py:14``), but
# co-scientist's evolver was free to rewrite the entire body.
# ``plugins/seed_generation/agents/evolver.md`` instead mandates
# *single-section* rewrite with ±20% body-token budget — under that
# contract, two compliant evolutions naturally share 80-90% of their
# 5-grams. Smoke 14 (archive ``.audit/smoke-archives/
# smoke-14-1779674544/``) iter-2 evolver returned ``verdict: "ok"``
# for parent ``gen1-002-e2b9f471``; the evolved body's 5-gram Jaccard
# against the parent measured **0.8437** (single bullet rewrite,
# "all other bullets preserved verbatim" per the LLM's own
# ``notes``), and the 0.70 threshold falsely coerced it to
# ``evolution_skipped`` → ``verdict_not_ok`` phase failure. Raising
# to 0.90 admits compliant section-rewrites while still catching the
# "barely changed" failure mode (Jaccard > 0.95). Proximity keeps
# its stricter 0.40 because it's deduping against the entire pool;
# this guard fires AFTER the Evolver writes the file.
ANTI_CONVERGENCE_JACCARD_THRESHOLD = 0.90


class Evolver(BaseSeedAgent):
    """Spawn one sub-agent per survivor; collect evolved candidate rows.

    Why per-survivor fan-out:
    -------------------------

    Each survivor's evolution is independent (no cross-survivor
    information needed — the Critic feedback is per-candidate, the
    Pilot dim_means are per-candidate). Fan-out keeps the K=5
    evolution batch within one rollout's wall-time, gated by the
    ``seed-generation`` Lane (max_concurrent=16).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_EVOLVER_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="evolver",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Fan out N evolution sub-agents and collect evolved candidate rows."""
        if not state.survivors:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Evolver requires state.survivors to be non-empty — "
                    "did the Ranker phase produce any survivors?"
                ),
            )

        candidates_by_id: dict[str, dict[str, Any]] = {c["id"]: c for c in state.candidates}
        tasks = self._build_tasks(state, candidates_by_id)
        if not tasks:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Evolver could not match any survivor id to "
                    "state.candidates — survivors list out of sync with "
                    "candidates."
                ),
            )

        log.info(
            "seed-generation evolver dispatching %d evolution tasks to %r",
            len(tasks),
            _EVOLVER_AGENT_NAME,
        )
        results = await self._manager.adelegate(tasks, announce=False)

        tasks_by_id: dict[str, Any] = {t.task_id: t for t in tasks}
        evolved_rows: list[dict[str, Any]] = []
        failed: list[tuple[str, str]] = []
        for result in results:
            task = tasks_by_id.get(result.task_id)
            if task is None:
                failed.append((result.task_id, f"unmatched_result: {result.error or 'no_task'}"))
                continue
            if not result.success:
                failed.append((task.task_id, result.error or "unknown"))
                continue
            parsed = parse_structured_output(
                result.output,
                required_fields=_REQUIRED_EVOLVE_FIELDS,
                pin_field="parent_id",
                pin_value=task.args["parent_id"],
            )
            if parsed is None:
                failed.append(
                    (
                        task.task_id,
                        f"malformed_evolve: result.output={result.output!r}",
                    )
                )
                continue
            if parsed.get("verdict") not in _VALID_VERDICTS:
                log.warning(
                    "seed-generation evolver: parent=%s invalid verdict=%r",
                    task.args["parent_id"],
                    parsed.get("verdict"),
                )
                continue
            if parsed["verdict"] != "ok":
                # Evolution skipped or failed — original candidate stays.
                continue
            # CSP-6 (2026-05-22) — anti-convergence Jaccard guard. If
            # the evolved body's 5-gram Jaccard against ANY sibling
            # evolved row or the candidate it parents from exceeds
            # the threshold, treat the spawn as "evolution_skipped"
            # (original candidate stays) rather than admit a
            # near-duplicate into the next iteration's candidate pool.
            # The Evolver's verdict is best-effort LLM intent; this
            # guard is a deterministic safety net for the case where
            # the model thinks it diversified but actually didn't.
            is_dup, score, against = self._check_near_duplicate(
                parsed, evolved_rows, candidates_by_id
            )
            if is_dup:
                # PR-EVOLVER-JACCARD-OBS (2026-05-25) — log the actual
                # Jaccard score + the offending comparison target
                # ("parent" or "sibling:<id>") so future threshold
                # tuning has empirical data, not just the static cutoff.
                log.info(
                    "seed-generation evolver: parent=%s evolved body too close "
                    "to %s (Jaccard %.4f ≥ threshold %.2f) — coercing verdict "
                    "to evolution_skipped.",
                    task.args["parent_id"],
                    against,
                    score,
                    ANTI_CONVERGENCE_JACCARD_THRESHOLD,
                )
                continue
            evolved_rows.append(self._build_evolved_row(parsed, task, state.gen_tag))

        if failed:
            log.warning(
                "seed-generation evolver: %d/%d sub-agents failed: %s",
                len(failed),
                len(tasks),
                failed[:3],
            )

        if not evolved_rows:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="evolution_failed",
                error_message=(
                    f"all {len(tasks)} evolution sub-agents either failed "
                    f"or returned verdict != 'ok'; "
                    f"first error: {failed[0][1] if failed else 'verdict_not_ok'}"
                ),
            )

        return SeedAgentResult(
            role=self.role,
            output={"evolved_candidates": evolved_rows},
        )

    def _build_tasks(
        self,
        state: PipelineState,
        candidates_by_id: dict[str, dict[str, Any]],
    ) -> list[SubTask]:
        """One SubTask per survivor that has a corresponding candidate row."""
        from core.agent.sub_agent import SubTask

        tasks: list[SubTask] = []
        for survivor_id in state.survivors:
            candidate = candidates_by_id.get(survivor_id)
            if candidate is None:
                log.warning(
                    "seed-generation evolver: survivor %r missing from state.candidates "
                    "— skipping evolution",
                    survivor_id,
                )
                continue
            reflection = state.reflections.get(survivor_id, {})
            rewrite_section = reflection.get("rewrite_section") or "Body"
            pilot = state.pilot_scores.get(survivor_id, {})
            description = self._build_description(
                candidate=candidate,
                rewrite_section=rewrite_section,
                weaknesses=reflection.get("weaknesses", []),
                dim_means=pilot.get("dim_means", {}) if isinstance(pilot, dict) else {},
                baseline_snapshot=state.baseline_snapshot,
                supervisor_guidance=state.supervisor_guidance,
                articles_with_reasoning=state.articles_with_reasoning,
            )
            tasks.append(
                SubTask(
                    task_id=f"evolve-{survivor_id}",
                    description=description,
                    task_type=_TASK_TYPE,
                    args={
                        "parent_id": survivor_id,
                        "parent_path": candidate["path"],
                        "target_dim": candidate.get("target_dim", state.target_dim),
                        "rewrite_section": rewrite_section,
                        "gen_tag": state.gen_tag,
                    },
                    agent=_EVOLVER_AGENT_NAME,
                    source=self.adapter_source,
                    # PR-JSON-WIRE (2026-05-25) — force evolve JSON shape.
                    response_schema=EVOLVE_SCHEMA,
                )
            )
        return tasks

    def _build_description(
        self,
        *,
        candidate: dict[str, Any],
        rewrite_section: str,
        weaknesses: list[Any],
        dim_means: dict[str, Any],
        baseline_snapshot: Any = None,
        supervisor_guidance: dict[str, Any] | None = None,
        articles_with_reasoning: str = "",
    ) -> str:
        """Compose the per-survivor user message for the sub-agent.

        The system prompt is owned by ``plugins/seed_generation/agents/evolver.md``.
        The description fills in the parent candidate path, the section
        the Critic flagged, the per-candidate weaknesses list, the
        Pilot dim_means, AND (G3) the baseline-evidence block for the
        target dim — so the evolver has both the in-run Pilot signal
        and the cross-run audit regression context.
        """
        weakness_summary = "; ".join(str(w) for w in weaknesses) or "n/a"
        means_summary = ", ".join(f"{k}={v}" for k, v in dim_means.items()) or "n/a"
        target_dim = candidate.get("target_dim", "unknown")
        prefix_blocks: list[str] = []
        # CSP-4 (2026-05-22) — Supervisor's evolution guidance at the
        # top of the prefix stack, above per-dim baseline evidence.
        if supervisor_guidance:
            try:
                from plugins.seed_generation.baseline_reader import format_supervisor_block

                supervisor_block = format_supervisor_block(supervisor_guidance, phase="evolution")
                if supervisor_block:
                    prefix_blocks.append(supervisor_block)
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
        # CSP-14 (2026-05-23) — Loop 3 literature evidence block.
        # Empty string short-circuits (max_papers=0 default).
        if articles_with_reasoning and articles_with_reasoning.strip():
            prefix_blocks.append(
                "## Literature evidence (from LiteratureReview phase)\n\n"
                + articles_with_reasoning.strip()
            )
        prefix = ("\n\n".join(prefix_blocks) + "\n\n") if prefix_blocks else ""
        return (
            f"{prefix}"
            f"Evolve ONE Petri seed candidate. Parent id: {candidate['id']!r}. "
            f"Parent path: {candidate['path']!r}. Target dim: "
            f"{target_dim!r}. Rewrite section: "
            f"{rewrite_section!r}. Reflection weaknesses: {weakness_summary}. "
            f"Pilot dim_means: {means_summary}. Per your system prompt, "
            "rewrite ONLY that section, preserve frontmatter + target_dim, "
            "keep total tokens within ±20% of original. Write to "
            f"<run_dir>/candidates_evolved/<new-uuid>.md and return JSON with "
            "`parent_id`, `evolved_id`, `evolved_path`, `rewrite_section`, "
            "`verdict` (one of 'ok'/'evolution_skipped'/'failed'), and "
            "`notes` (<= 200 tokens)."
        )

    def _build_evolved_row(
        self,
        parsed: dict[str, Any],
        task: Any,
        gen_tag: str,
    ) -> dict[str, Any]:
        """Translate a parsed sub-result into a candidates-list row.

        Schema mirrors :class:`PipelineState.candidates` (id / path /
        target_dim / gen_tag / task_id / duration_ms) plus evolution-
        specific provenance (``parent_id``, ``rewrite_section``,
        ``notes``).
        """
        return {
            "id": str(parsed["evolved_id"]),
            "path": str(parsed["evolved_path"]),
            "target_dim": task.args.get("target_dim"),
            "gen_tag": gen_tag,
            "task_id": task.task_id,
            "duration_ms": 0.0,
            "parent_id": str(parsed["parent_id"]),
            "rewrite_section": str(parsed["rewrite_section"]),
            "notes": parsed.get("notes", ""),
        }

    def _check_near_duplicate(
        self,
        parsed: dict[str, Any],
        already_admitted: list[dict[str, Any]],
        candidates_by_id: dict[str, dict[str, Any]],
    ) -> tuple[bool, float, str]:
        """Compare the evolved body to siblings + parent; return verdict
        + the offending Jaccard score + a label for the comparison
        target so the caller can log empirical data (not just the
        static threshold).

        CSP-6 (2026-05-22) reads the evolved file body and compares
        its 5-gram Jaccard against:

        1. Every already-admitted evolved row (the sibling spawns this
           run already accepted) — ``against = "sibling:<evolved_id>"``.
        2. The parent candidate's body (to catch the "evolution returned
           almost the same text" failure mode the LLM verdict can miss)
           — ``against = "parent:<parent_id>"``.

        Returns ``(True, score, against)`` as soon as ANY comparison
        exceeds :data:`ANTI_CONVERGENCE_JACCARD_THRESHOLD`. Returns
        ``(False, max_score_seen, against_or_"")`` when no comparison
        crosses the threshold — ``max_score_seen`` is the highest
        Jaccard observed across all comparisons (or 0.0 when no
        comparison ran), so even non-dup admissions surface their
        closest-neighbor score in logs if a caller wants to record it.

        Returns ``(False, 0.0, "")`` when the evolved file is
        unreadable (defensive — failing closed on every IO blip
        would mask legitimate evolutions, per CSP-6 docstring).

        PR-EVOLVER-JACCARD-OBS (2026-05-25) — refactored from the
        boolean ``_is_near_duplicate`` so callers can log the actual
        score + comparison target. Threshold raised 0.70 → 0.90 to
        match the prompt's single-section ±20% rewrite contract.
        """
        from pathlib import Path

        from core.utils.similarity import jaccard_similarity, shingles

        evolved_path = parsed.get("evolved_path")
        parent_id = parsed.get("parent_id")
        if not evolved_path:
            return (False, 0.0, "")
        try:
            evolved_body = Path(str(evolved_path)).read_text(encoding="utf-8")
        except OSError as exc:
            log.warning(
                "seed-generation evolver: anti-convergence guard could not "
                "read evolved body at %s (%s) — admitting the row.",
                evolved_path,
                exc,
            )
            return (False, 0.0, "")
        evolved_shingles = shingles(evolved_body)
        max_score = 0.0
        max_against = ""
        # Sibling check.
        for row in already_admitted:
            other_path = row.get("path")
            if not other_path:
                continue
            try:
                other_body = Path(str(other_path)).read_text(encoding="utf-8")
            except OSError:
                continue
            score = jaccard_similarity(evolved_shingles, shingles(other_body))
            label = f"sibling:{row.get('id', '<unknown>')}"
            if score > max_score:
                max_score = score
                max_against = label
            if score >= ANTI_CONVERGENCE_JACCARD_THRESHOLD:
                return (True, score, label)
        # Parent-vs-evolved check — catches the "barely changed" LLM
        # output the verdict didn't flag.
        if parent_id:
            parent_row = candidates_by_id.get(str(parent_id))
            if parent_row:
                parent_path = parent_row.get("path")
                if parent_path:
                    try:
                        parent_body = Path(str(parent_path)).read_text(encoding="utf-8")
                    except OSError:
                        parent_body = ""
                    if parent_body:
                        score = jaccard_similarity(evolved_shingles, shingles(parent_body))
                        label = f"parent:{parent_id}"
                        if score > max_score:
                            max_score = score
                            max_against = label
                        if score >= ANTI_CONVERGENCE_JACCARD_THRESHOLD:
                            return (True, score, label)
        return (False, max_score, max_against)
