"""Post-Elo survivor deduplication for seed generation.

The Proximity phase records semantic clusters before Pilot/Ranker have
empirical signal. This module applies the open-coscientist pattern after
Ranker: within each high-similarity survivor cluster, keep the strongest
candidate by Elo, then aggregate Pilot score, then id.
"""

from __future__ import annotations

from typing import Any

__all__ = ["dedup_survivors_by_cluster"]


def dedup_survivors_by_cluster(
    survivors: list[str],
    ratings: dict[str, float],
    pilot_scores: dict[str, dict[str, Any]],
    similarity_clusters: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Drop lower-ranked high-similarity survivors.

    Returns ``(filtered_survivors, removed_rows)``. Survivor order is
    preserved except for removed ids so Evolver still sees Ranker's
    survivor ordering.
    """
    survivor_set = set(survivors)
    removals: dict[str, dict[str, Any]] = {}
    for cluster in similarity_clusters:
        cluster_id = str(cluster.get("cluster_id", "?"))
        topic = str(cluster.get("topic", ""))
        entries = cluster.get("similar_hypotheses") or []
        if not isinstance(entries, list):
            continue

        high_ids: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("candidate_id")
            if (
                isinstance(cid, str)
                and cid in survivor_set
                and entry.get("similarity_degree") == "high"
            ):
                high_ids.append(cid)
        high_ids = list(dict.fromkeys(high_ids))
        if len(high_ids) <= 1:
            continue

        keep = max(high_ids, key=lambda cid: _survivor_rank(cid, ratings, pilot_scores))
        for cid in high_ids:
            if cid == keep:
                continue
            removals[cid] = {
                "candidate_id": cid,
                "cluster_id": cluster_id,
                "topic": topic,
                "reason": "post_elo_high_similarity_duplicate",
                "kept_instead": keep,
                "elo_rating": float(ratings.get(cid, 0.0)),
                "pilot_score_sum": _pilot_score_sum(cid, pilot_scores),
            }

    filtered = [cid for cid in survivors if cid not in removals]
    return filtered, [removals[cid] for cid in survivors if cid in removals]


def _survivor_rank(
    candidate_id: str,
    ratings: dict[str, float],
    pilot_scores: dict[str, dict[str, Any]],
) -> tuple[float, float, str]:
    return (
        float(ratings.get(candidate_id, 0.0)),
        _pilot_score_sum(candidate_id, pilot_scores),
        candidate_id,
    )


def _pilot_score_sum(candidate_id: str, pilot_scores: dict[str, dict[str, Any]]) -> float:
    entry = pilot_scores.get(candidate_id, {})
    means = entry.get("dim_means", {}) if isinstance(entry, dict) else {}
    if not isinstance(means, dict):
        return 0.0
    total = 0.0
    for value in means.values():
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue
    return total
