"""Unit tests for ``plugins.seed_pipeline.agents.proximity``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity** — `text_embed.embed_texts` stub returns vectors
  aligned 1:1 with input order (matches production contract).
- **P7 Caller-Callee Contract** — Proximity consumes Generator's
  ``state.candidates`` schema + Critic's ``state.reflections`` schema.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from plugins.seed_pipeline.agents.proximity import (
    EMBED_SIMILARITY_THRESHOLD,
    LEXICAL_JACCARD_THRESHOLD,
    Proximity,
    _jaccard,
    _shingles,
)
from plugins.seed_pipeline.orchestrator import PipelineState


def _make_candidate(
    cid: str, path: Path, *, body: str, target_dim: str = "broken_tool_use"
) -> dict[str, str]:
    path.write_text(body, encoding="utf-8")
    return {
        "id": cid,
        "path": str(path),
        "target_dim": target_dim,
        "gen_tag": "gen2",
        "task_id": f"gen-{cid}",
        "duration_ms": 100.0,
    }


def _make_state(tmp_path: Path) -> PipelineState:
    return PipelineState(
        run_id="t-proximity",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=3,
        run_dir=tmp_path,
    )


def test_shingles_basic() -> None:
    out = _shingles("the quick brown fox jumps over lazy dog", n=3)
    assert "the quick brown" in out
    assert "brown fox jumps" in out


def test_shingles_short_text_returns_single() -> None:
    assert _shingles("only two", n=5) == {"only two"}


def test_shingles_empty_text_returns_empty() -> None:
    assert _shingles("", n=5) == set()


def test_jaccard_identical_returns_one() -> None:
    s = {"a", "b", "c"}
    assert _jaccard(s, s) == 1.0


def test_jaccard_disjoint_returns_zero() -> None:
    assert _jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_both_empty_returns_zero() -> None:
    assert _jaccard(set(), set()) == 0.0


def test_proximity_empty_candidates_returns_error(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    result = Proximity().execute(state)
    assert not result.success
    assert result.error_category == "validation"


def test_proximity_embedding_track_marks_duplicates(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body="alpha beta"),
        _make_candidate("c2", tmp_path / "c2.md", body="distinct unrelated"),
        _make_candidate("c3", tmp_path / "c3.md", body="totally separate"),
    ]
    fake_vectors = [
        [1.0, 0.0, 0.0, 0.0],  # c1
        [1.0, 0.0, 0.0, 0.0],  # c2 — dup of c1
        [0.0, 1.0, 0.0, 0.0],  # c3 — distinct
    ]
    proximity = Proximity()
    candidate_texts = proximity._load_candidate_texts(state)
    with patch("core.tools.text_embed.embed_texts", return_value=fake_vectors):
        embed_dupes = proximity._embedding_track(candidate_texts, [])
    assert "c2" in embed_dupes
    assert "c1" not in embed_dupes
    assert "c3" not in embed_dupes


def test_proximity_lexical_track_marks_duplicates(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    body_a = " ".join(["foo bar baz qux qaz wxy abc def"] * 3)
    body_a_dup = body_a + " trailing"
    body_c = " ".join(["completely different other words here now"] * 3)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body=body_a),
        _make_candidate("c2", tmp_path / "c2.md", body=body_a_dup),
        _make_candidate("c3", tmp_path / "c3.md", body=body_c),
    ]
    proximity = Proximity()
    candidate_texts = proximity._load_candidate_texts(state)
    lexical_dupes = proximity._lexical_track(candidate_texts, [])
    assert "c2" in lexical_dupes


def test_proximity_role_track_overlapping_dims(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body="x"),
        _make_candidate("c2", tmp_path / "c2.md", body="y"),
        _make_candidate("c3", tmp_path / "c3.md", body="z"),
    ]
    state.reflections = {
        "c1": {"target_dims_actual": ["broken_tool_use"]},
        "c2": {"target_dims_actual": ["broken_tool_use"]},  # overlaps
        "c3": {"target_dims_actual": ["overrefusal"]},
    }
    proximity = Proximity()
    role_dupes = proximity._role_track(state)
    assert "c2" in role_dupes
    assert "c1" not in role_dupes
    assert "c3" not in role_dupes


def test_proximity_role_track_empty_reflections(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body="x"),
        _make_candidate("c2", tmp_path / "c2.md", body="y"),
    ]
    proximity = Proximity()
    assert proximity._role_track(state) == set()


def test_proximity_three_track_vote_drops_majority(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    shared_body = " ".join(["foo bar baz qux qaz wxy abc def"] * 5)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body=shared_body),
        _make_candidate("c2", tmp_path / "c2.md", body=shared_body),
        _make_candidate("c3", tmp_path / "c3.md", body="distinct unique text"),
    ]
    state.reflections = {
        "c1": {"target_dims_actual": ["broken_tool_use"]},
        "c2": {"target_dims_actual": ["broken_tool_use"]},
        "c3": {"target_dims_actual": ["overrefusal"]},
    }
    fake_vectors = [
        [1.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    with patch("core.tools.text_embed.embed_texts", return_value=fake_vectors):
        result = Proximity().execute(state)
    assert result.success
    survivor_ids = {c["id"] for c in state.candidates}
    assert "c1" in survivor_ids
    assert "c2" not in survivor_ids
    assert "c3" in survivor_ids


def test_proximity_embedding_failure_graceful(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body="unique a"),
        _make_candidate("c2", tmp_path / "c2.md", body="unique b"),
    ]
    state.reflections = {}
    with patch(
        "core.tools.text_embed.embed_texts",
        side_effect=RuntimeError("OPENAI down"),
    ):
        result = Proximity().execute(state)
    assert result.success
    assert len(state.candidates) == 2


def test_proximity_missing_candidate_file(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    state.candidates = [
        {
            "id": "c1",
            "path": str(tmp_path / "nonexistent.md"),
            "target_dim": "x",
            "gen_tag": "gen2",
            "task_id": "gen-c1",
            "duration_ms": 0.0,
        },
    ]
    proximity = Proximity()
    assert proximity._load_candidate_texts(state) == {}


def test_thresholds_pinned() -> None:
    assert EMBED_SIMILARITY_THRESHOLD == 0.85
    assert LEXICAL_JACCARD_THRESHOLD == 0.40


def test_proximity_pool_dedup_lexical(tmp_path: Path) -> None:
    """Pool-vs-candidate dedup — candidate matching a pool seed by lexical
    track is marked, even if no sibling candidate matches.
    """
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    pool_body = " ".join(["foo bar baz qux qaz wxy abc def ghi"] * 4)
    (pool_dir / "pool_seed.md").write_text(pool_body, encoding="utf-8")

    state = _make_state(tmp_path)
    state.pool_path_in = pool_dir
    # c1 is similar to pool_seed; c2 is unique
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body=pool_body),
        _make_candidate(
            "c2", tmp_path / "c2.md", body="totally unrelated content here"
        ),
    ]
    proximity = Proximity()
    candidate_texts = proximity._load_candidate_texts(state)
    pool_texts = proximity._load_pool_texts(state)
    lexical_dupes = proximity._lexical_track(candidate_texts, pool_texts)
    assert "c1" in lexical_dupes
    assert "c2" not in lexical_dupes


def test_proximity_pool_dedup_embedding(tmp_path: Path) -> None:
    """Pool-vs-candidate dedup — embedding track marks candidate matching pool."""
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    (pool_dir / "pool_seed.md").write_text("pool body content", encoding="utf-8")

    state = _make_state(tmp_path)
    state.pool_path_in = pool_dir
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body="x"),
        _make_candidate("c2", tmp_path / "c2.md", body="y"),
    ]
    # 2 candidates + 1 pool — c1's vector matches the pool vector.
    fake_vectors = [
        [1.0, 0.0, 0.0],  # c1
        [0.0, 1.0, 0.0],  # c2 — distinct
        [1.0, 0.0, 0.0],  # pool_seed — matches c1
    ]
    proximity = Proximity()
    candidate_texts = proximity._load_candidate_texts(state)
    pool_texts = proximity._load_pool_texts(state)
    with patch("core.tools.text_embed.embed_texts", return_value=fake_vectors):
        embed_dupes = proximity._embedding_track(candidate_texts, pool_texts)
    assert "c1" in embed_dupes
    assert "c2" not in embed_dupes


def test_proximity_pool_path_missing_dir_logged(tmp_path: Path) -> None:
    """Non-existent pool_path_in path returns empty list with WARNING."""
    state = _make_state(tmp_path)
    state.pool_path_in = tmp_path / "nonexistent_pool"
    proximity = Proximity()
    pool_texts = proximity._load_pool_texts(state)
    assert pool_texts == []
