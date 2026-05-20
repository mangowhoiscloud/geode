"""Elo tournament math — pure functions for the seed-generation Ranker (S6).

Pure math, no I/O, no LLM dispatch. Lives next to ``agents/ranker.py``
(which owns the orchestration) so the Elo update math can be exercised
in isolation by unit tests (no SubAgentManager stubbing needed).

Per ADR-001 paper §3 Ranking — pairwise Elo update with K=32. Each
candidate starts at 1000.0 rating; a match's expected score is the
logistic of the rating delta; the actual outcome (1.0 / 0.5 / 0.0)
drives the update. The Ranker class composes:

1. :func:`initial_ratings` — seed every candidate at 1000.0.
2. :func:`plan_matches` — sample ``~N log N`` distinct pairs.
3. :func:`expected_score` / :func:`apply_match` — per-match update.
4. :func:`top_k` — final survivors by descending rating.

The K-factor is tunable (default 32 per S6 sprint plan) to allow
future calibration once S12 data lands.

P1-P7 prevention checklist application:

- **P1 Stub Fidelity Audit** — every function is pure and complete;
  no ``pass`` / ``return None`` stubs. The math is testable end-to-end
  with deterministic ``random.Random(seed=…)`` injection.
- **P7 Caller-Callee Contract** — pair sampling, match outcomes, and
  rating updates expose explicit return types so the Ranker (or any
  future consumer) cannot misuse the API by accident.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEFAULT_K_FACTOR",
    "DEFAULT_TOP_K",
    "INITIAL_RATING",
    "MatchOutcome",
    "MatchPlan",
    "apply_match",
    "expected_score",
    "initial_ratings",
    "outcome_score",
    "plan_matches",
    "top_k",
]


INITIAL_RATING: float = 1000.0
DEFAULT_K_FACTOR: float = 32.0
DEFAULT_TOP_K: int = 5


WinnerLabel = Literal["A", "B", "tie"]


@dataclass(frozen=True)
class MatchPlan:
    """One scheduled pairwise match (candidate ``a`` vs candidate ``b``).

    The order ``(a, b)`` is the *presentation order* given to the
    judges — randomly sampled to avoid position bias (the same pair
    appearing twice with reversed order is a separate ``MatchPlan``).
    """

    match_id: str
    a: str
    b: str


@dataclass(frozen=True)
class MatchOutcome:
    """Result of one match — winner label + the 3 voters' ballots.

    ``winner`` is the majority vote (≥ 2 of 3 voters agree). If the
    majority is split (e.g. one A / one B / one tie) the match is
    declared a tie and both ratings receive a 0.5 update. ``voter_ids``
    aligns 1:1 with ``votes`` for traceability into ``elo_log.tsv``.
    """

    match_id: str
    a: str
    b: str
    winner: WinnerLabel
    votes: tuple[WinnerLabel, ...]
    voter_ids: tuple[str, ...]


def initial_ratings(candidate_ids: Iterable[str]) -> dict[str, float]:
    """Seed every candidate at :data:`INITIAL_RATING`.

    Returned dict is fresh per call so the caller can mutate without
    surprising other code that shares the seed iterable.
    """
    return dict.fromkeys(candidate_ids, INITIAL_RATING)


def expected_score(rating_a: float, rating_b: float) -> float:
    """Logistic expected score for candidate A in the (A vs B) match.

    Returns ``E_A = 1 / (1 + 10**((R_B - R_A) / 400))``. ``E_B`` is
    ``1 - E_A``; the caller composes both as needed.
    """
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def outcome_score(winner: WinnerLabel) -> tuple[float, float]:
    """Translate a majority-vote outcome into ``(score_a, score_b)``."""
    if winner == "A":
        return 1.0, 0.0
    if winner == "B":
        return 0.0, 1.0
    return 0.5, 0.5


def apply_match(
    ratings: dict[str, float],
    outcome: MatchOutcome,
    *,
    k_factor: float = DEFAULT_K_FACTOR,
) -> None:
    """Apply one match's Elo update to ``ratings`` in place.

    The mutation is in place because the Ranker loops over many matches
    and a fresh dict per match would obscure the rating trajectory in
    the per-step log.
    """
    rating_a = ratings.get(outcome.a, INITIAL_RATING)
    rating_b = ratings.get(outcome.b, INITIAL_RATING)
    score_a, score_b = outcome_score(outcome.winner)
    expected_a = expected_score(rating_a, rating_b)
    expected_b = 1.0 - expected_a
    ratings[outcome.a] = rating_a + k_factor * (score_a - expected_a)
    ratings[outcome.b] = rating_b + k_factor * (score_b - expected_b)


def plan_matches(
    candidate_ids: list[str],
    *,
    rng: random.Random | None = None,
    target_matches: int | None = None,
    proximity_graph: dict[tuple[str, str], float] | None = None,
) -> list[MatchPlan]:
    """Sample distinct pairwise matches for the tournament.

    Default schedule produces ``ceil(N * log2(N))`` matches (so 15
    candidates → 59 matches, well under N² = 225). Each pair appears
    at most once; presentation order is randomized.

    ``target_matches`` overrides the default when the budget guard
    needs a smaller schedule. ``rng`` is the random source — pass a
    seeded ``Random`` instance in tests for determinism.

    PR-Π1 — ``proximity_graph`` (sorted ``(a, b)`` → similarity in
    ``[0, 1]``) enables the **diverse-bracket policy**: pairs are
    selected by ascending proximity so the tournament prioritises
    informative ("far") matches over near-duplicate ones that the
    Proximity phase would have already dropped if they crossed the
    dedup threshold. This realises Co-Scientist §3.3.4 — the Proximity
    agent "assists the Ranking agent in organizing tournament matches".
    Missing graph entries (pair never scored) default to ``0.0``
    (maximally distant) so they sort to the front. When the graph is
    ``None`` or empty the legacy random-shuffle policy is retained for
    backwards compatibility (every existing test passes unchanged).
    Presentation order per pair is still randomised to defeat position
    bias.
    """
    if len(candidate_ids) < 2:
        return []
    if rng is None:
        rng = random.Random()
    n = len(candidate_ids)
    n_pairs = n * (n - 1) // 2
    if target_matches is None:
        target_matches = min(n_pairs, math.ceil(n * math.log2(max(n, 2))))

    all_pairs: list[tuple[str, str]] = []
    for i, a in enumerate(candidate_ids):
        for b in candidate_ids[i + 1 :]:
            all_pairs.append((a, b))

    if proximity_graph:
        # Diverse-bracket policy — sort by ascending proximity (far pairs
        # first). Stable sort on a string-tiebreaker keeps deterministic
        # ordering when many pairs share the default 0.0 score.
        def _diversity_key(pair: tuple[str, str]) -> tuple[float, str, str]:
            key = pair if pair[0] < pair[1] else (pair[1], pair[0])
            return (proximity_graph.get(key, 0.0), key[0], key[1])

        all_pairs.sort(key=_diversity_key)
    else:
        rng.shuffle(all_pairs)
    selected = all_pairs[: max(0, target_matches)]

    plans: list[MatchPlan] = []
    for idx, (a, b) in enumerate(selected):
        # Randomise presentation order per match to defeat position bias.
        if rng.random() < 0.5:
            a, b = b, a
        plans.append(MatchPlan(match_id=f"m{idx:03d}", a=a, b=b))
    return plans


def top_k(
    ratings: dict[str, float],
    *,
    k: int = DEFAULT_TOP_K,
) -> list[str]:
    """Return the top ``k`` candidate ids by descending rating.

    Ties broken by lexicographic candidate id so the survivor list is
    deterministic across re-runs (matters for the ``elo_log.tsv`` /
    ``results.tsv`` integration tests in S10).
    """
    ranked = sorted(ratings.items(), key=lambda kv: (-kv[1], kv[0]))
    return [cid for cid, _ in ranked[:k]]


def majority_winner(votes: tuple[WinnerLabel, ...]) -> WinnerLabel:
    """Compute majority-vote outcome from N voter ballots.

    ``A`` / ``B`` win when they have a strict majority (e.g. 2 of 3).
    Anything else (3-way split, all-tie, 2-tie + 1 A/B) collapses to
    ``tie`` — both ratings receive 0.5.
    """
    counts: dict[WinnerLabel, int] = {"A": 0, "B": 0, "tie": 0}
    for v in votes:
        counts[v] = counts.get(v, 0) + 1
    majority_threshold = len(votes) // 2 + 1
    if counts["A"] >= majority_threshold:
        return "A"
    if counts["B"] >= majority_threshold:
        return "B"
    return "tie"
