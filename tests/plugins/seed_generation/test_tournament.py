"""Tests for ``plugins.seed_generation.tournament`` — pure Elo math."""

from __future__ import annotations

import random

from plugins.seed_generation.tournament import (
    DEFAULT_K_FACTOR,
    INITIAL_RATING,
    MatchOutcome,
    MatchPlan,
    apply_match,
    expected_score,
    initial_ratings,
    majority_winner,
    outcome_score,
    plan_matches,
    top_k,
)


def test_initial_ratings_seed_value() -> None:
    rs = initial_ratings(["a", "b", "c"])
    assert rs == {"a": 1000.0, "b": 1000.0, "c": 1000.0}


def test_initial_ratings_fresh_copy_per_call() -> None:
    seed = ["a", "b"]
    rs1 = initial_ratings(seed)
    rs2 = initial_ratings(seed)
    rs1["a"] = 1500.0
    assert rs2["a"] == 1000.0


def test_expected_score_equal_returns_half() -> None:
    assert abs(expected_score(1000.0, 1000.0) - 0.5) < 1e-9


def test_expected_score_higher_wins_more() -> None:
    assert expected_score(1200.0, 1000.0) > expected_score(1100.0, 1000.0) > 0.5


def test_expected_score_symmetric() -> None:
    e_ab = expected_score(1100.0, 900.0)
    e_ba = expected_score(900.0, 1100.0)
    assert abs(e_ab + e_ba - 1.0) < 1e-9


def test_outcome_score_a_wins() -> None:
    assert outcome_score("A") == (1.0, 0.0)


def test_outcome_score_b_wins() -> None:
    assert outcome_score("B") == (0.0, 1.0)


def test_outcome_score_tie() -> None:
    assert outcome_score("tie") == (0.5, 0.5)


def test_apply_match_a_wins_against_equal() -> None:
    ratings = {"a": 1000.0, "b": 1000.0}
    outcome = MatchOutcome(
        match_id="m1",
        a="a",
        b="b",
        winner="A",
        votes=("A", "A", "tie"),
        voter_ids=("v1", "v2", "v3"),
    )
    apply_match(ratings, outcome)
    # K=32, expected_a=0.5, score_a=1.0 → update = +16.0
    assert abs(ratings["a"] - 1016.0) < 1e-6
    assert abs(ratings["b"] - 984.0) < 1e-6


def test_apply_match_tie_no_change_for_equal_ratings() -> None:
    ratings = {"a": 1000.0, "b": 1000.0}
    outcome = MatchOutcome(
        match_id="m1",
        a="a",
        b="b",
        winner="tie",
        votes=("tie", "tie", "tie"),
        voter_ids=("v1", "v2", "v3"),
    )
    apply_match(ratings, outcome)
    assert ratings == {"a": 1000.0, "b": 1000.0}


def test_apply_match_custom_k_factor() -> None:
    ratings = {"a": 1000.0, "b": 1000.0}
    outcome = MatchOutcome(
        match_id="m1",
        a="a",
        b="b",
        winner="A",
        votes=("A",),
        voter_ids=("v1",),
    )
    apply_match(ratings, outcome, k_factor=64.0)
    assert abs(ratings["a"] - 1032.0) < 1e-6


def test_apply_match_handles_missing_candidate_with_default() -> None:
    ratings: dict[str, float] = {}
    outcome = MatchOutcome(
        match_id="m1",
        a="x",
        b="y",
        winner="A",
        votes=("A",),
        voter_ids=("v1",),
    )
    apply_match(ratings, outcome)
    assert "x" in ratings
    assert "y" in ratings
    assert ratings["x"] > INITIAL_RATING


def test_plan_matches_empty_for_solo_candidate() -> None:
    assert plan_matches(["a"]) == []


def test_plan_matches_deterministic_with_seeded_rng() -> None:
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    p1 = plan_matches(["a", "b", "c", "d"], rng=rng1)
    p2 = plan_matches(["a", "b", "c", "d"], rng=rng2)
    assert p1 == p2


def test_plan_matches_count_under_default_schedule() -> None:
    plans = plan_matches(["a", "b", "c", "d", "e"], rng=random.Random(0))
    # 5 candidates → ceil(5 * log2(5)) = ceil(11.6) = 12, capped at C(5,2)=10
    assert len(plans) == 10


def test_plan_matches_no_duplicate_pairs() -> None:
    plans = plan_matches(list("abcdefghij"), rng=random.Random(7))
    seen: set[tuple[str, str]] = set()
    for p in plans:
        canonical = tuple(sorted((p.a, p.b)))
        assert canonical not in seen, f"duplicate pair {canonical}"
        seen.add(canonical)


def test_plan_matches_respects_target_matches() -> None:
    plans = plan_matches(
        ["a", "b", "c", "d"],
        target_matches=2,
        rng=random.Random(0),
    )
    assert len(plans) == 2


def test_top_k_orders_by_rating_descending() -> None:
    ratings = {"a": 1100.0, "b": 1050.0, "c": 1200.0, "d": 1000.0}
    assert top_k(ratings, k=2) == ["c", "a"]


def test_top_k_tie_broken_lexicographically() -> None:
    ratings = {"x": 1000.0, "a": 1000.0, "m": 1000.0}
    assert top_k(ratings, k=3) == ["a", "m", "x"]


def test_top_k_caps_at_dict_size() -> None:
    ratings = {"a": 1100.0, "b": 1050.0}
    assert top_k(ratings, k=10) == ["a", "b"]


def test_majority_winner_two_of_three_for_a() -> None:
    assert majority_winner(("A", "A", "B")) == "A"


def test_majority_winner_two_of_three_for_b() -> None:
    assert majority_winner(("B", "tie", "B")) == "B"


def test_majority_winner_three_way_split_is_tie() -> None:
    assert majority_winner(("A", "B", "tie")) == "tie"


def test_majority_winner_all_tie() -> None:
    assert majority_winner(("tie", "tie", "tie")) == "tie"


def test_majority_winner_two_ties_one_a_is_tie() -> None:
    """2 ties + 1 A → no strict majority for A → tie."""
    assert majority_winner(("tie", "tie", "A")) == "tie"


def test_match_plan_is_frozen() -> None:
    import pytest

    p = MatchPlan(match_id="m0", a="x", b="y")
    with pytest.raises(Exception):
        p.match_id = "m1"  # type: ignore[misc]


def test_default_k_factor_pinned() -> None:
    """Sprint plan §13 default K=32 — regression guard."""
    assert DEFAULT_K_FACTOR == 32.0
