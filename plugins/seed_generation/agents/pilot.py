"""Pilot agent — Phase D of the seed generation.

Per ADR-001 paper's §3 Pilot role (GEODE substitution for the paper's
"scientist-in-the-loop" validator). For each surviving candidate, the
Pilot runs ONE cheap Petri inner-loop audit (1 candidate seed × 1 target
× N samples) and reports the per-dim ``{dim_means, dim_stderr}``
aggregate. The orchestrator merges the per-candidate pilot scores into
``PipelineState.pilot_scores`` keyed by candidate id.

Unified extraction path (PR-PILOT-UNIFY-DIM-EXTRACT, 2026-06-04)
================================================================

The Pilot calls :func:`plugins.petri_audit.runner.run_audit` directly —
the SAME runner the ``petri_audit`` tool, ``geode audit``, and ``/audit``
all funnel through — then reads the run's archived ``.eval`` with
:func:`core.audit.dim_extractor.extract_dim_aggregates`. This is the
identical converter (and identical raw-Petri scale, baseline = 1.0) the
``broken_tool_use`` self-improving CAMPAIGN
(``core/self_improving/train.py:run_audit``) uses, so seed-gen difficulty
scores and campaign fitness scores now live on ONE scale.

There is no LLM in the dim_means loop. Before this PR the Pilot spawned a
``seed_pilot`` sub-agent that ran ``petri_audit`` *and then reformatted the
result into JSON in prose* — a step that (a) regularly failed
(``json.loads`` JSONDecodeError on a rambling response → whole phase
``pilot_failed``) and (b) used an inconsistent baseline-normalization
convention divergent from the campaign's scale. Reducing the Pilot to a
direct ``run_audit`` + ``extract_dim_aggregates`` call removes both
failure modes: a candidate's score is taken from the tool's authoritative
``.eval`` output, never from an agent's text, so a rambling pilot can no
longer crash or zero-fill the run.

GAP-audit verdict (cf. [[feedback_audit_before_migrate]]): the prior
sub-agent did nothing beyond "run one ``petri_audit`` → report" (its only
two granted tools were ``petri_audit`` + ``read_document``, and
``pilot.md`` documented a fixed 5-step pipeline with no adaptive
branching). So reduce-to-direct is the fullest unify — the agent was a
failure-prone wrapper around one deterministic tool call.

Per-candidate contract
======================

- **Input**: ``state.candidates`` (post-Proximity survivors); each carries
  ``id`` + ``path`` (+ optional ``target_dim``).
- **Output**: ``state.pilot_scores`` (``PipelineState.merge`` dict
  semantics) keyed by candidate id. Each value is
  ``{candidate_id, dim_means, dim_stderr, status}``.

Status semantics:

- ``ok`` — audit finished and ≥ ``_MIN_ENGAGED_DIMS`` dims have a non-zero
  ``dim_means``.
- ``low_engagement`` — audit completed but too few dims engaged (the seed
  did not exercise the rubric); merged so the Ranker can deprioritise it.
- A genuinely failed audit (no ``.eval`` produced — aborted / timeout /
  inspect missing) routes the candidate into ``failed`` and is NOT merged.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import DEFAULT_AGENT_MODEL, BaseSeedAgent, SeedAgentResult

if TYPE_CHECKING:
    from plugins.seed_generation.orchestrator import PipelineState

log = logging.getLogger(__name__)

__all__ = ["Pilot"]


_DEFAULT_PILOT_MODEL = DEFAULT_AGENT_MODEL

#: Target the self-improving campaign optimizes: scaffolded GEODE on
#: gpt-5.5. ``run_audit`` auto-wraps it as ``geode/gpt-5.5`` (the full
#: AgenticLoop per turn) and resolves its source from the
#: ``[self_improving_loop.petri.target]`` binding (ChatGPT subscription —
#: no api_key). Measuring difficulty against the model the loop actually
#: improves keeps the difficulty-selection lever meaningful.
_PILOT_TARGET = "gpt-5.5"

#: Built-in key for the 22-dim ``geode_judge_subset.yaml`` set — the SAME
#: dim set the campaign measures (``DEFAULT_DIM_SET`` in
#: ``plugins/petri_audit/runner.py``).
_PILOT_DIM_SET = "subset"

#: N rollouts per candidate so ``rank_by_difficulty`` ranks by a multi-
#: sample central estimate rather than a single high-variance draw
#: (gen-2606-i1-012 read 7 on its one sample but averaged 2.4±0.98 over 5).
#: ``run_audit`` stages the lone candidate ``.md`` as this many distinct
#: copies (``flatten_for_inspect_petri(samples=seeds)``) and passes
#: ``--limit`` so inspect-petri yields this many independent rollouts.
_PILOT_SAMPLES = 3

#: Petri turn cap per rollout. 5 turns is the cheap pilot setting (the
#: canonical full alignment audit uses 10).
_PILOT_MAX_TURNS = 5

#: Minimum non-zero dims for ``status="ok"``. Below this the audit ran but
#: the seed barely exercised the rubric → ``low_engagement``.
_MIN_ENGAGED_DIMS = 3


def _count_engaged_dims(dim_means: dict[str, float]) -> int:
    """Number of dims whose mean is non-zero (the audit "lit up").

    Graceful at every cast — a non-numeric value never raises, so the
    boundary contract holds for the whole dict (CLAUDE.md
    graceful-contract-boundary rule).
    """
    engaged = 0
    for value in dim_means.values():
        try:
            if float(value) != 0.0:
                engaged += 1
        except (TypeError, ValueError):
            continue
    return engaged


class Pilot(BaseSeedAgent):
    """Run one Petri audit per surviving candidate; collect dim aggregates.

    Why per-candidate fan-out:
    --------------------------

    Each candidate's pilot rollout is independent (no cross-candidate
    information needed). Pilot is the most expensive per-call phase (~1
    Petri audit per candidate). The audits are dispatched via
    :func:`asyncio.to_thread` + :func:`asyncio.gather`, but each
    ``_run_one_audit`` acquires the host's ``core.orchestration.audit_lane``
    (``max_concurrent=1``) around the ``inspect eval`` subprocess — the
    SAME lane the campaign uses — so the audits run one at a time and do
    not burst the OAuth soft-limit into a 429 storm. The fan-out is thus a
    convenience (clean per-candidate error capture), not a parallelism win.
    """

    def __init__(
        self,
        *,
        model: str = _DEFAULT_PILOT_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        # ``model`` / ``source`` are retained for registry symmetry +
        # provenance logging; the audit's target/auditor/judge models are
        # resolved by ``run_audit`` from the petri binding stack, not from
        # this role's picker binding (the pilot measures difficulty against
        # the campaign's gpt-5.5 target, not against the pilot's own model).
        super().__init__(
            role="pilot",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Run N per-candidate audits concurrently and collect dim aggregates."""
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Pilot requires state.candidates to be non-empty — "
                    "did the Proximity phase drop all survivors?"
                ),
            )

        candidates = list(state.candidates)
        target_dim_default = state.target_dim
        log.info(
            "seed-generation pilot dispatching %d candidate audit(s) "
            "(target=%s, dim_set=%s, samples=%d)",
            len(candidates),
            _PILOT_TARGET,
            _PILOT_DIM_SET,
            _PILOT_SAMPLES,
        )

        audits = await asyncio.gather(
            *(
                asyncio.to_thread(self._run_one_audit, candidate, target_dim_default)
                for candidate in candidates
            )
        )

        pilot_scores: dict[str, dict[str, Any]] = {}
        failed: list[tuple[str, str]] = []
        for candidate, (pilot, error) in zip(candidates, audits, strict=True):
            candidate_id = candidate["id"]
            if pilot is None:
                failed.append((candidate_id, error or "unknown"))
                continue
            pilot_scores[candidate_id] = pilot

        if failed:
            log.warning(
                "seed-generation pilot: %d/%d candidate audits failed: %s",
                len(failed),
                len(candidates),
                failed[:3],
            )

        if not pilot_scores:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="pilot_failed",
                error_message=(
                    f"all {len(candidates)} pilot audits failed; "
                    f"first error: {failed[0][1] if failed else 'unknown'}"
                ),
            )

        return SeedAgentResult(
            role=self.role,
            output={"pilot_scores": pilot_scores},
        )

    def _run_one_audit(
        self,
        candidate: dict[str, Any],
        target_dim_default: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Audit ONE candidate via the unified runner; extract dim aggregates.

        Returns ``(pilot_dict, None)`` on success or ``(None, error)`` on
        failure. Never raises — any exception from the runner / extractor
        is captured as an error string so one bad candidate cannot crash
        the whole fan-out.

        The dim_means / dim_stderr come from
        :func:`core.audit.dim_extractor.extract_dim_aggregates` applied to
        the audit's archived ``.eval`` — the SAME authoritative converter
        and raw-Petri scale the campaign (``train.py``) uses. No LLM
        reformats the scores.
        """
        candidate_id = str(candidate.get("id", ""))
        candidate_path = candidate.get("path")
        if not candidate_path:
            return None, f"candidate {candidate_id} has no seed path"

        from core.audit.dim_extractor import extract_dim_aggregates
        from core.orchestration.audit_lane import acquire_audit_lane

        from plugins.petri_audit.runner import run_audit

        try:
            # Serialise the inspect_ai subprocess across the host via the
            # SAME inter-process audit lane the campaign uses
            # (``core/self_improving/train.py:run_audit``). The
            # ``plugins.petri_audit.runner.run_audit`` runner does NOT acquire
            # the lane itself, so without this each fan-out candidate would
            # spawn a concurrent ``inspect eval`` — N parallel audits burst the
            # OAuth soft-limit into a 429 storm (the lane is max_concurrent=1),
            # so the gather below effectively runs the audits one at a time.
            with acquire_audit_lane(f"seed-pilot-{candidate_id}"):
                report = run_audit(
                    target=_PILOT_TARGET,
                    seeds=_PILOT_SAMPLES,
                    max_turns=_PILOT_MAX_TURNS,
                    seed_select=str(candidate_path),
                    dim_set=_PILOT_DIM_SET,
                    dry_run=False,
                    # The seed-gen run already obtained cost authorisation at
                    # the CLI; the per-candidate audits run unattended.
                    yes=True,
                )
        except Exception as exc:  # pragma: no cover - defensive
            return None, f"run_audit raised: {exc!r}"

        if report.aborted:
            note = "; ".join(report.notes) if report.notes else "no .eval produced"
            return None, f"audit aborted before producing scores: {note}"

        # Match the campaign's failure semantics: a non-zero inspect_ai exit
        # is a failure even if a partial ``.eval`` was archived
        # (``train.py:run_audit`` raises on returncode != 0;
        # ``cli_audit._emit_dim_aggregates`` suppresses emission likewise).
        # ``None`` returncode arises only on the dry-run / aborted paths
        # already handled above, so treat it as "no failure signal".
        if report.returncode not in (0, None):
            tail = (report.stderr or "").splitlines()[-3:]
            return None, (
                f"audit subprocess exit={report.returncode}"
                + (f"; stderr_tail={tail}" if tail else "")
            )

        archive = report.archived_raw
        if not archive:
            note = "; ".join(report.notes) if report.notes else "no archive path"
            return None, f"audit produced no .eval archive: {note}"

        try:
            aggregates = extract_dim_aggregates(Path(archive))
        except Exception as exc:  # pragma: no cover - defensive
            return None, f"extract_dim_aggregates raised on {archive}: {exc!r}"

        dim_means = aggregates.get("dim_means") or {}
        dim_stderr = aggregates.get("dim_stderr") or {}
        if not isinstance(dim_means, dict) or not dim_means:
            return None, (f"audit .eval at {archive} yielded no dim_means (zero samples scored)")

        engaged = _count_engaged_dims(dim_means)
        status = "ok" if engaged >= _MIN_ENGAGED_DIMS else "low_engagement"
        if status == "low_engagement":
            log.warning(
                "seed-generation pilot: candidate=%s only %d dim(s) engaged "
                "(< %d) — low_engagement (target_dim=%s)",
                candidate_id,
                engaged,
                _MIN_ENGAGED_DIMS,
                candidate.get("target_dim", target_dim_default),
            )

        return {
            "candidate_id": candidate_id,
            "dim_means": dim_means,
            "dim_stderr": dim_stderr,
            "status": status,
        }, None
