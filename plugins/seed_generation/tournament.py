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
import os
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEFAULT_K_FACTOR",
    "DEFAULT_SURVIVOR_SELECTION",
    "DEFAULT_TOP_K",
    "INITIAL_RATING",
    "SURVIVOR_SELECTION_ENV",
    "MatchOutcome",
    "MatchPlan",
    "SurvivorSelection",
    "apply_match",
    "expected_score",
    "initial_ratings",
    "outcome_score",
    "plan_matches",
    "rank_by_difficulty",
    "resolve_survivor_selection",
    "select_survivors",
    "top_k",
]


INITIAL_RATING: float = 1000.0
DEFAULT_K_FACTOR: float = 32.0
DEFAULT_TOP_K: int = 5


SurvivorSelection = Literal["elo", "difficulty"]
"""How the Ranker picks survivors from the rated candidate set.

- ``"elo"`` (default, unchanged behaviour) — top-K by descending Elo
  rating (tournament win-rate via the 3-judge panel).
- ``"difficulty"`` — top-K by descending measured pilot
  ``dim_means[target_dim]`` (Petri 1-10, HIGHER = more misbehaviour
  elicited = HARDER for the target = LOWER target fitness = MORE
  headroom for a mutation to improve). Selects the seeds the target
  struggles most with, instead of the ones the panel rated "best".
"""

DEFAULT_SURVIVOR_SELECTION: SurvivorSelection = "elo"
"""Default survivor selection mode — Elo, so existing runs are unchanged
unless the operator opts in to difficulty-calibrated selection."""

SURVIVOR_SELECTION_ENV = "GEODE_SEED_SURVIVOR_SELECTION"
"""Operator override — set to ``difficulty`` to pick the hardest seeds
(highest pilot target_dim elicitation) instead of the top-Elo seeds.
Any unrecognised / empty value falls back to
:data:`DEFAULT_SURVIVOR_SELECTION` (the knob must never harden into an
invalid mode from a typo)."""


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
) -> list[MatchPlan]:
    """Sample distinct pairwise matches for the tournament.

    Default schedule produces ``ceil(N * log2(N))`` matches (so 15
    candidates → 59 matches, well under N² = 225). Each pair appears
    at most once; presentation order is randomized.

    ``target_matches`` overrides the default when the budget guard
    needs a smaller schedule. ``rng`` is the random source — pass a
    seeded ``Random`` instance in tests for determinism.

    CSP-8 (2026-05-22) — the pre-CSP-8 ``proximity_graph`` parameter
    (PR-Π1 "diverse-bracket policy") was removed when Proximity reverted
    to the paper's LLM-clustering pattern. The Ranker now uses a pure
    random-shuffle policy; the proximity step's coverage signal lives
    in ``state.similarity_clusters`` and is consumed by the
    meta_reviewer instead of the Elo bracket.
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


def resolve_survivor_selection() -> SurvivorSelection:
    """Resolve the effective survivor-selection mode from the environment.

    Reads :data:`SURVIVOR_SELECTION_ENV`. Recognises ``"elo"`` /
    ``"difficulty"`` (case-insensitive, surrounding whitespace stripped);
    any other value — including an empty string or a typo — falls back to
    :data:`DEFAULT_SURVIVOR_SELECTION` so the knob can never harden into an
    invalid mode mid-run.
    """
    raw = os.environ.get(SURVIVOR_SELECTION_ENV, "").strip().lower()
    if raw == "difficulty":
        return "difficulty"
    if raw == "elo":
        return "elo"
    return DEFAULT_SURVIVOR_SELECTION


def _difficulty_signal(
    pilot_means: Mapping[str, Mapping[str, object]],
    candidate_id: str,
    target_dim: str,
) -> float | None:
    """Return the candidate's pilot ``dim_means[target_dim]`` as a float.

    Graceful contract at every schema-typed boundary: a missing candidate,
    a non-mapping pilot entry, a missing ``target_dim`` key, a non-numeric
    value, or a non-finite float (``NaN`` / ``inf``) all resolve to ``None``
    (sorts last in the difficulty ranking) rather than raising. ``bool`` is
    rejected explicitly so a stray ``True`` cannot masquerade as ``1.0``.
    The non-finite guard matters because pilot ``dim_means`` arrives via
    ``json.loads``, which parses ``NaN`` / ``Infinity`` — ``NaN`` would make
    the sort insertion-dependent and ``inf`` would always rank first,
    silently overriding a measured-hard seed.
    """
    means = pilot_means.get(candidate_id)
    if not isinstance(means, Mapping):
        return None
    value = means.get(target_dim)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    signal = float(value)
    if not math.isfinite(signal):
        return None
    return signal


def rank_by_difficulty(
    ratings: Mapping[str, float],
    pilot_means: Mapping[str, Mapping[str, object]],
    target_dim: str,
) -> list[str]:
    """Rank every rated candidate hardest-first by pilot ``target_dim`` elicitation.

    The sort key per candidate is ``(-difficulty, -elo_rating, candidate_id)``:

    1. **difficulty** — the pilot's measured ``dim_means[target_dim]``
       (Petri 1-10, HIGHER = harder). Descending, so the seed the target
       struggles most with leads.
    2. **elo_rating** — descending Elo as a deterministic tie-break when
       two candidates elicited the same difficulty (the harder-AND-better
       seed wins the tie).
    3. **candidate_id** — lexicographic, the final tie-break so the order
       is stable across re-runs (matters for the survivors.json / pool
       content-hash determinism downstream).

    A candidate with no usable difficulty signal (missing / non-numeric
    pilot ``dim_means[target_dim]``) sorts AFTER every candidate that has
    one — it is never crashed on and never promoted above a measured-hard
    seed. ``ratings`` defines the candidate universe (one entry per rated
    candidate); ``pilot_means`` is the read-only difficulty source.
    """

    # Candidates with a signal sort before those without; ``has_signal`` is
    # the primary key (False sorts last under reverse-of-(-x) ordering, so
    # we encode it as 0/1 and negate alongside the difficulty value).
    def _sort_key(candidate_id: str) -> tuple[int, float, float, str]:
        signal = _difficulty_signal(pilot_means, candidate_id, target_dim)
        has_signal = 1 if signal is not None else 0
        difficulty = signal if signal is not None else 0.0
        elo = ratings.get(candidate_id, INITIAL_RATING)
        # Negate has_signal + difficulty + elo for descending; id ascending.
        return (-has_signal, -difficulty, -elo, candidate_id)

    return sorted(ratings.keys(), key=_sort_key)


def select_survivors(
    ratings: Mapping[str, float],
    *,
    k: int = DEFAULT_TOP_K,
    selection: SurvivorSelection = DEFAULT_SURVIVOR_SELECTION,
    pilot_means: Mapping[str, Mapping[str, object]] | None = None,
    target_dim: str | None = None,
) -> list[str]:
    """Pick the top-``k`` survivors under the chosen selection mode.

    - ``selection="elo"`` (default) — delegates to :func:`top_k`; identical
      to the historical behaviour (top-K by descending Elo).
    - ``selection="difficulty"`` — ranks ALL rated candidates by measured
      pilot ``dim_means[target_dim]`` (hardest first via
      :func:`rank_by_difficulty`), then truncates to ``k``. This keeps the
      seeds the target struggles most with, which Elo would otherwise
      discard (a high-elicitation seed can carry a lower Elo than an easy
      one — see gen-2605-3). Falls back to Elo when ``target_dim`` is
      absent / blank or ``pilot_means`` is empty, so a misconfigured
      difficulty request degrades to the safe default rather than
      returning an arbitrary order.
    """
    if selection != "difficulty":
        return top_k(dict(ratings), k=k)
    if not target_dim or not pilot_means:
        # Difficulty requested but no usable signal source — degrade to
        # Elo so the run still produces a deterministic survivor set.
        return top_k(dict(ratings), k=k)
    ranked = rank_by_difficulty(ratings, pilot_means, target_dim)
    return ranked[:k]


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
