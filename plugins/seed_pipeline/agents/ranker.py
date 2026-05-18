"""Ranker agent — Phase E of the seed pipeline (Elo tournament + 3-judge panel).

For each pairwise match in the tournament plan, the Ranker fans out 3
voter sub-agents (one per :class:`VoterBinding` from the picker output)
and majority-votes to determine the match winner. The
:func:`plugins.seed_pipeline.tournament.apply_match` update is applied
in place to a rolling ``elo_ratings`` dict; final survivors are the
top-K by descending rating.

Per ADR-001 §3 Ranking + the panel diversity gate (manifest-time
``required_diversity_families ≥ 2``, runtime-validated by the S5.5
picker), the Ranker NEVER judges directly — it only orchestrates the
voters.

Per-voter sub-agent contract (``.claude/agents/seed_ranker.md`` +
voter-specific judges):

.. code-block:: json

   {
     "match_id": "m007",
     "winner": "A" | "B" | "tie",
     "rationale": "<= 200 tokens"
   }

P-checklist application:

- **P1 Stub Fidelity Audit** — tests cover the *completion-order*
  pairing path (results returned in reverse submission order, mixed
  failures, malformed votes).
- **P7 Caller-Callee Contract Pair Read** — the Ranker consumes the
  picker's ``voters`` list and the orchestrator's
  ``state.candidates`` + ``state.pilot_scores`` outputs. Emits
  ``state.elo_ratings`` + ``state.survivors``.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any

from plugins.seed_pipeline.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
)
from plugins.seed_pipeline.orchestrator import PipelineState
from plugins.seed_pipeline.picker import VoterBinding
from plugins.seed_pipeline.tournament import (
    DEFAULT_K_FACTOR,
    DEFAULT_TOP_K,
    MatchOutcome,
    MatchPlan,
    apply_match,
    initial_ratings,
    majority_winner,
    plan_matches,
    top_k,
)

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Ranker"]


_DEFAULT_RANKER_MODEL = "claude-sonnet-4-6"
_TASK_TYPE = "seed-ranker-vote"

_REQUIRED_VOTE_FIELDS = ("match_id", "winner", "rationale")
_VALID_WINNER_LABELS = frozenset({"A", "B", "tie"})


class Ranker(BaseSeedAgent):
    """Elo tournament orchestrator with 3-voter judge panel.

    Constructor accepts the resolved ``voters`` list from the S5.5
    picker so the Ranker is decoupled from manifest loading — tests
    can build a 3-voter list explicitly without touching the file
    system or the Petri source-table cross-validator.
    """

    def __init__(
        self,
        manager: SubAgentManager,
        voters: list[VoterBinding],
        *,
        model: str = _DEFAULT_RANKER_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
        k_factor: float = DEFAULT_K_FACTOR,
        survivors_k: int = DEFAULT_TOP_K,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(
            role="ranker",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        if len(voters) < 2:
            raise ValueError(
                f"Ranker requires ≥ 2 voters (panel diversity gate); got {len(voters)}"
            )
        self._manager = manager
        self._voters = voters
        self._k_factor = k_factor
        self._survivors_k = survivors_k
        self._rng = rng

    def execute(self, state: PipelineState) -> SeedAgentResult:
        """Run the Elo tournament against ``state.candidates`` survivors."""
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Ranker requires state.candidates to be non-empty — "
                    "did upstream phases drop all survivors?"
                ),
            )
        if len(state.candidates) < 2:
            # Single candidate trivially survives; emit a degenerate result
            # rather than raising, so the pipeline can complete the run.
            sole = state.candidates[0]["id"]
            return SeedAgentResult(
                role=self.role,
                output={
                    "elo_ratings": {sole: 1000.0},
                    "survivors": [sole],
                },
            )

        candidate_ids = [c["id"] for c in state.candidates]
        # Snapshot pilot dim_means per candidate (read-only) so the
        # voter-task builder can surface the empirical signal to each
        # judge per .claude/agents/seed_ranker.md contract. Absent
        # pilot_scores → empty dict (judges fall back to seed bodies).
        pilot_means: dict[str, dict[str, Any]] = {}
        for cid in candidate_ids:
            entry = state.pilot_scores.get(cid, {})
            means = entry.get("dim_means", {}) if isinstance(entry, dict) else {}
            if isinstance(means, dict):
                pilot_means[cid] = means

        ratings = initial_ratings(candidate_ids)
        match_plan = plan_matches(candidate_ids, rng=self._rng)
        log.info(
            "seed-pipeline ranker: %d candidates → %d matches × %d voters",
            len(candidate_ids),
            len(match_plan),
            len(self._voters),
        )

        outcomes: list[MatchOutcome] = []
        for match in match_plan:
            outcome = self._play_match(match, pilot_means=pilot_means)
            if outcome is None:
                continue
            outcomes.append(outcome)
            apply_match(ratings, outcome, k_factor=self._k_factor)

        survivors = top_k(ratings, k=self._survivors_k)
        self._emit_elo_log(state, outcomes, ratings)
        log.info(
            "seed-pipeline ranker: %d/%d matches counted, survivors=%s",
            len(outcomes),
            len(match_plan),
            survivors[:3],
        )

        return SeedAgentResult(
            role=self.role,
            output={
                "elo_ratings": ratings,
                "survivors": survivors,
            },
        )

    def _play_match(
        self,
        match: MatchPlan,
        *,
        pilot_means: dict[str, dict[str, Any]] | None = None,
    ) -> MatchOutcome | None:
        """Dispatch the 3 voters for one match; return ``None`` on quorum loss."""
        tasks = self._build_voter_tasks(match, pilot_means=pilot_means or {})
        results = self._manager.delegate(tasks, announce=False)
        tasks_by_id: dict[str, Any] = {t.task_id: t for t in tasks}

        votes: list[str] = []
        voter_ids: list[str] = []
        for result in results:
            task = tasks_by_id.get(result.task_id)
            if task is None or not result.success:
                continue
            parsed = parse_structured_output(
                result.output,
                required_fields=_REQUIRED_VOTE_FIELDS,
                pin_field="match_id",
                pin_value=match.match_id,
            )
            if parsed is None:
                continue
            winner = parsed.get("winner")
            if winner not in _VALID_WINNER_LABELS:
                log.warning(
                    "seed-pipeline ranker: match=%s voter=%s invalid winner=%r",
                    match.match_id,
                    task.args.get("voter_id"),
                    winner,
                )
                continue
            votes.append(str(winner))
            voter_ids.append(str(task.args.get("voter_id", "?")))

        if len(votes) < 2:
            # Need ≥ 2 votes to declare a majority. Quorum loss → skip the
            # match entirely so a single judge's failure can't push a
            # candidate up or down.
            log.warning(
                "seed-pipeline ranker: match=%s quorum lost (%d/%d votes)",
                match.match_id,
                len(votes),
                len(self._voters),
            )
            return None
        winner_label = majority_winner(tuple(votes))  # type: ignore[arg-type]
        return MatchOutcome(
            match_id=match.match_id,
            a=match.a,
            b=match.b,
            winner=winner_label,
            votes=tuple(votes),  # type: ignore[arg-type]
            voter_ids=tuple(voter_ids),
        )

    def _build_voter_tasks(
        self,
        match: MatchPlan,
        *,
        pilot_means: dict[str, dict[str, Any]],
    ) -> list[SubTask]:
        """One SubTask per voter for one match."""
        from core.agent.sub_agent import SubTask

        means_a = pilot_means.get(match.a, {})
        means_b = pilot_means.get(match.b, {})
        tasks: list[SubTask] = []
        for voter in self._voters:
            voter_id = f"{voter.family}.{voter.source}"
            tasks.append(
                SubTask(
                    task_id=f"vote-{match.match_id}-{voter_id}",
                    description=self._build_description(
                        match=match,
                        voter=voter,
                        means_a=means_a,
                        means_b=means_b,
                    ),
                    task_type=_TASK_TYPE,
                    args={
                        "match_id": match.match_id,
                        "candidate_a": match.a,
                        "candidate_b": match.b,
                        "pilot_means_a": means_a,
                        "pilot_means_b": means_b,
                        "voter_id": voter_id,
                        "voter_model": voter.model,
                        "voter_source": voter.source,
                    },
                    agent=f"seed_ranker_voter_{voter.family}",
                )
            )
        return tasks

    def _build_description(
        self,
        *,
        match: MatchPlan,
        voter: VoterBinding,
        means_a: dict[str, Any],
        means_b: dict[str, Any],
    ) -> str:
        """Compose the per-voter user message for the sub-agent.

        Includes Pilot dim_means alongside the seed paths so the judge
        (per ``.claude/agents/seed_ranker.md``) can weigh empirical
        engagement signal against the seed body. When pilot_scores is
        missing for a candidate, the corresponding dim_means is empty
        and the judge falls back to seed body alone.
        """
        means_summary_a = ", ".join(f"{k}={v}" for k, v in means_a.items()) or "n/a"
        means_summary_b = ", ".join(f"{k}={v}" for k, v in means_b.items()) or "n/a"
        return (
            f"Judge ONE seed-candidate match for the seed-pipeline Elo "
            f"tournament. Match id: {match.match_id}. Candidate A: "
            f"{match.a!r} (run_dir/candidates/{match.a}.md, pilot "
            f"dim_means: {means_summary_a}). Candidate B: "
            f"{match.b!r} (run_dir/candidates/{match.b}.md, pilot "
            f"dim_means: {means_summary_b}). You are voter "
            f"{voter.family}.{voter.source} ({voter.model!r}). Read both "
            "candidate seeds, weigh dim_means signal, apply the rubric in "
            'your system prompt, and return JSON `{"match_id": "<id>", '
            '"winner": "A"|"B"|"tie", "rationale": "<= 200 tokens"}`. '
            "Do not skip the rationale."
        )

    def _emit_elo_log(
        self,
        state: PipelineState,
        outcomes: list[MatchOutcome],
        ratings: dict[str, float],
    ) -> None:
        """Persist per-match log to ``<run_dir>/elo_log.tsv``.

        Per the seed_ranker AgentDef contract — TSV is commit-friendly
        and integrates with the S10 ``results.tsv`` consumer. Skipped
        when ``state.run_dir`` is unset (test fixtures often omit it);
        the Ranker's primary signal stays the in-memory
        ``output["elo_ratings"]``.
        """
        if state.run_dir is None:
            return
        log_path = state.run_dir / "elo_log.tsv"
        try:
            state.run_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8") as fh:
                fh.write("match_id\ta\tb\twinner\tvotes\tvoter_ids\trating_a\trating_b\n")
                for o in outcomes:
                    fh.write(
                        "\t".join(
                            [
                                o.match_id,
                                o.a,
                                o.b,
                                o.winner,
                                ",".join(o.votes),
                                ",".join(o.voter_ids),
                                f"{ratings.get(o.a, 0.0):.2f}",
                                f"{ratings.get(o.b, 0.0):.2f}",
                            ]
                        )
                        + "\n"
                    )
        except OSError as exc:
            log.warning(
                "seed-pipeline ranker: failed to write elo_log.tsv at %s: %s",
                log_path,
                exc,
            )
