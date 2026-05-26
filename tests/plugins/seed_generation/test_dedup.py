"""Tests for post-Elo seed survivor deduplication."""

from __future__ import annotations

from plugins.seed_generation.dedup import dedup_survivors_by_cluster


def test_dedup_survivors_keeps_best_high_similarity_by_elo() -> None:
    filtered, removed = dedup_survivors_by_cluster(
        survivors=["c-low", "c-best", "c-other"],
        ratings={"c-low": 990.0, "c-best": 1030.0, "c-other": 1000.0},
        pilot_scores={
            "c-low": {"dim_means": {"dim_01": 0.9}},
            "c-best": {"dim_means": {"dim_01": 0.1}},
        },
        similarity_clusters=[
            {
                "cluster_id": "cluster-a",
                "topic": "same mechanism",
                "similar_hypotheses": [
                    {"candidate_id": "c-low", "similarity_degree": "high"},
                    {"candidate_id": "c-best", "similarity_degree": "high"},
                    {"candidate_id": "c-other", "similarity_degree": "medium"},
                ],
            }
        ],
    )

    assert filtered == ["c-best", "c-other"]
    assert removed == [
        {
            "candidate_id": "c-low",
            "cluster_id": "cluster-a",
            "topic": "same mechanism",
            "reason": "post_elo_high_similarity_duplicate",
            "kept_instead": "c-best",
            "elo_rating": 990.0,
            "pilot_score_sum": 0.9,
        }
    ]


def test_dedup_survivors_uses_pilot_sum_as_tiebreaker() -> None:
    filtered, removed = dedup_survivors_by_cluster(
        survivors=["c-a", "c-b"],
        ratings={"c-a": 1000.0, "c-b": 1000.0},
        pilot_scores={
            "c-a": {"dim_means": {"dim_01": 0.3, "dim_02": 0.2}},
            "c-b": {"dim_means": {"dim_01": 0.6}},
        },
        similarity_clusters=[
            {
                "cluster_id": "cluster-a",
                "similar_hypotheses": [
                    {"candidate_id": "c-a", "similarity_degree": "high"},
                    {"candidate_id": "c-b", "similarity_degree": "high"},
                ],
            }
        ],
    )

    assert filtered == ["c-b"]
    assert removed[0]["candidate_id"] == "c-a"
    assert removed[0]["kept_instead"] == "c-b"


def test_dedup_survivors_ignores_non_survivors_and_non_high_entries() -> None:
    filtered, removed = dedup_survivors_by_cluster(
        survivors=["c-a", "c-b"],
        ratings={"c-a": 1000.0, "c-b": 990.0, "c-c": 1200.0},
        pilot_scores={},
        similarity_clusters=[
            {
                "cluster_id": "cluster-a",
                "similar_hypotheses": [
                    {"candidate_id": "c-a", "similarity_degree": "medium"},
                    {"candidate_id": "c-b", "similarity_degree": "low"},
                    {"candidate_id": "c-c", "similarity_degree": "high"},
                ],
            }
        ],
    )

    assert filtered == ["c-a", "c-b"]
    assert removed == []
