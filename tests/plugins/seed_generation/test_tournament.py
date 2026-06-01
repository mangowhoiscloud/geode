"""Tests for ``plugins.seed_generation.tournament`` — pure Elo math."""

from __future__ import annotations

import random

import pytest
from plugins.seed_generation.tournament import (
    DEFAULT_K_FACTOR,
    DEFAULT_SURVIVOR_SELECTION,
    INITIAL_RATING,
    SURVIVOR_SELECTION_ENV,
    MatchOutcome,
    MatchPlan,
    apply_match,
    expected_score,
    initial_ratings,
    majority_winner,
    outcome_score,
    plan_matches,
    rank_by_difficulty,
    resolve_survivor_selection,
    select_survivors,
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


# ── PR-Π1 — diverse-bracket policy ──


def _canonical(plan_a: str, plan_b: str) -> tuple[str, str]:
    return (plan_a, plan_b) if plan_a < plan_b else (plan_b, plan_a)


# CSP-8 (2026-05-22) — pre-CSP-8 ``proximity_graph`` parameter was
# removed when Proximity reverted to the paper's LLM-clustering
# pattern. ``plan_matches`` is now a pure random-shuffle scheduler;
# 4 diverse-bracket tests below were removed in the same PR.


def test_plan_matches_random_shuffle_deterministic_with_seed() -> None:
    """``plan_matches`` schedule is reproducible for a fixed rng seed."""
    candidates = ["a", "b", "c", "d"]
    plans = plan_matches(candidates, target_matches=3, rng=random.Random(0))
    assert len(plans) == 3
    canonical = {_canonical(p.a, p.b) for p in plans}
    assert len(canonical) == 3
    # Same seed → same schedule.
    plans_repeat = plan_matches(candidates, target_matches=3, rng=random.Random(0))
    assert [(p.a, p.b) for p in plans] == [(p.a, p.b) for p in plans_repeat]


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


# ── PR-SEEDGEN-DIFFICULTY-SELECTION — difficulty-calibrated survivor pick ──


def test_default_survivor_selection_is_elo() -> None:
    """Default must stay Elo so existing runs are unchanged unless opted in."""
    assert DEFAULT_SURVIVOR_SELECTION == "elo"


def test_resolve_selection_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SURVIVOR_SELECTION_ENV, raising=False)
    assert resolve_survivor_selection() == "elo"


def test_resolve_selection_difficulty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SURVIVOR_SELECTION_ENV, "difficulty")
    assert resolve_survivor_selection() == "difficulty"


def test_resolve_selection_case_and_whitespace_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SURVIVOR_SELECTION_ENV, "  Difficulty  ")
    assert resolve_survivor_selection() == "difficulty"


def test_resolve_selection_typo_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must never harden the knob into an invalid mode."""
    monkeypatch.setenv(SURVIVOR_SELECTION_ENV, "difculty")
    assert resolve_survivor_selection() == "elo"


def test_rank_by_difficulty_hardest_first() -> None:
    """The high-elicitation seed leads even when its Elo is lower.

    Mirrors the gen-2605-3 finding: elo 1094 / target_dim 2.8 vs
    elo 1084 / target_dim 4.2 — difficulty must rank the 4.2 seed first.
    """
    ratings = {"easy_high_elo": 1094.0, "hard_low_elo": 1084.0}
    pilot_means = {
        "easy_high_elo": {"broken_tool_use": 2.8},
        "hard_low_elo": {"broken_tool_use": 4.2},
    }
    ranked = rank_by_difficulty(ratings, pilot_means, "broken_tool_use")
    assert ranked == ["hard_low_elo", "easy_high_elo"]


def test_rank_by_difficulty_missing_pilot_sorts_last() -> None:
    ratings = {"with_signal": 1000.0, "no_pilot": 2000.0}
    pilot_means = {"with_signal": {"broken_tool_use": 1.0}}
    # ``no_pilot`` has the higher Elo but no difficulty signal → sorts last.
    ranked = rank_by_difficulty(ratings, pilot_means, "broken_tool_use")
    assert ranked == ["with_signal", "no_pilot"]


def test_rank_by_difficulty_non_numeric_signal_sorts_last() -> None:
    ratings = {"numeric": 1000.0, "stringy": 1000.0, "booly": 1000.0}
    pilot_means = {
        "numeric": {"broken_tool_use": 3.0},
        "stringy": {"broken_tool_use": "high"},
        "booly": {"broken_tool_use": True},  # bool must NOT count as 1.0
    }
    ranked = rank_by_difficulty(ratings, pilot_means, "broken_tool_use")
    # Only ``numeric`` has a usable signal; the other two sort last by id.
    assert ranked[0] == "numeric"
    assert set(ranked[1:]) == {"booly", "stringy"}


def test_rank_by_difficulty_non_finite_signal_sorts_last() -> None:
    """``NaN`` / ``inf`` arrive via json.loads — they must NOT count as a
    difficulty signal (``inf`` would always rank first; ``NaN`` would make
    the sort insertion-dependent), so they sort behind the measured seed."""
    ratings = {"measured": 1000.0, "infs": 1000.0, "nans": 1000.0}
    pilot_means = {
        "measured": {"broken_tool_use": 3.0},
        "infs": {"broken_tool_use": float("inf")},
        "nans": {"broken_tool_use": float("nan")},
    }
    ranked = rank_by_difficulty(ratings, pilot_means, "broken_tool_use")
    assert ranked[0] == "measured"
    assert set(ranked[1:]) == {"infs", "nans"}


def test_rank_by_difficulty_elo_tie_break() -> None:
    """Equal difficulty → higher Elo wins the tie, then lexicographic id."""
    ratings = {"a": 1100.0, "b": 1200.0, "c": 1200.0}
    pilot_means = {
        "a": {"d": 5.0},
        "b": {"d": 5.0},
        "c": {"d": 5.0},
    }
    ranked = rank_by_difficulty(ratings, pilot_means, "d")
    # b/c share Elo 1200 (b<c lexicographic), a is 1100.
    assert ranked == ["b", "c", "a"]


def test_select_survivors_elo_mode_matches_top_k() -> None:
    ratings = {"a": 1100.0, "b": 1050.0, "c": 1200.0, "d": 1000.0}
    assert select_survivors(ratings, k=2, selection="elo") == top_k(ratings, k=2)


def test_select_survivors_difficulty_inverts_elo() -> None:
    ratings = {"easy": 1094.0, "hard": 1084.0}
    pilot_means = {
        "easy": {"broken_tool_use": 2.8},
        "hard": {"broken_tool_use": 4.2},
    }
    # Elo would pick "easy" first; difficulty picks "hard".
    elo_pick = select_survivors(ratings, k=1, selection="elo")
    difficulty_pick = select_survivors(
        ratings,
        k=1,
        selection="difficulty",
        pilot_means=pilot_means,
        target_dim="broken_tool_use",
    )
    assert elo_pick == ["easy"]
    assert difficulty_pick == ["hard"]


def test_select_survivors_difficulty_truncates_to_k() -> None:
    ratings = {"a": 1000.0, "b": 1000.0, "c": 1000.0, "d": 1000.0}
    pilot_means = {
        "a": {"d": 1.0},
        "b": {"d": 4.0},
        "c": {"d": 3.0},
        "d": {"d": 2.0},
    }
    picked = select_survivors(
        ratings, k=2, selection="difficulty", pilot_means=pilot_means, target_dim="d"
    )
    assert picked == ["b", "c"]


def test_select_survivors_difficulty_without_target_dim_falls_back_to_elo() -> None:
    ratings = {"easy": 1094.0, "hard": 1084.0}
    pilot_means = {"easy": {"d": 2.8}, "hard": {"d": 4.2}}
    # No target_dim → degrade to Elo (deterministic) rather than guess.
    picked = select_survivors(
        ratings, k=1, selection="difficulty", pilot_means=pilot_means, target_dim=None
    )
    assert picked == ["easy"]


def test_select_survivors_difficulty_without_pilot_means_falls_back_to_elo() -> None:
    ratings = {"easy": 1094.0, "hard": 1084.0}
    picked = select_survivors(
        ratings, k=1, selection="difficulty", pilot_means=None, target_dim="d"
    )
    assert picked == ["easy"]


def test_select_survivors_empty_ratings() -> None:
    assert select_survivors({}, k=5, selection="elo") == []
    assert select_survivors({}, k=5, selection="difficulty", pilot_means={}, target_dim="d") == []
