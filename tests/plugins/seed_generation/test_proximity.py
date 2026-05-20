"""Unit tests for ``plugins.seed_generation.agents.proximity``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity** — `text_embed.embed_texts` stub returns vectors
  aligned 1:1 with input order (matches production contract).
- **P7 Caller-Callee Contract** — Proximity consumes Generator's
  ``state.candidates`` schema + Critic's ``state.reflections`` schema.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from plugins.seed_generation.agents.proximity import (
    EMBED_SIMILARITY_THRESHOLD,
    GRAPH_WEIGHT_EMBED,
    GRAPH_WEIGHT_LEXICAL,
    LEXICAL_JACCARD_THRESHOLD,
    PARTIAL_SURVIVE_FLOOR,
    Proximity,
    _jaccard,
    _pair_key,
    _shingles,
)
from plugins.seed_generation.orchestrator import PipelineState


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
        embed_dupes, _scores = proximity._embedding_track(candidate_texts, [])
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
    lexical_dupes, _scores = proximity._lexical_track(candidate_texts, [])
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


# ── PR-Π1 — proximity graph emit ──


def test_pair_key_sorts_alphabetically() -> None:
    assert _pair_key("b", "a") == ("a", "b")
    assert _pair_key("a", "b") == ("a", "b")
    assert _pair_key("c2", "c10") == ("c10", "c2")  # lexicographic, not numeric


def test_graph_weights_sum_to_one() -> None:
    """Composite-score weights must sum to 1.0 so the graph value is in [0, 1]."""
    assert GRAPH_WEIGHT_EMBED + GRAPH_WEIGHT_LEXICAL == 1.0


def test_proximity_emits_graph_into_state(tmp_path: Path) -> None:
    """``execute`` populates ``state.proximity_graph`` for every candidate pair."""
    state = _make_state(tmp_path)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body="alpha beta gamma"),
        _make_candidate("c2", tmp_path / "c2.md", body="alpha beta gamma"),  # near-dup
        _make_candidate("c3", tmp_path / "c3.md", body="totally separate words"),
    ]
    state.reflections = {}
    fake_vectors = [
        [1.0, 0.0, 0.0, 0.0],  # c1
        [0.95, 0.05, 0.0, 0.0],  # c2 — close to c1 but not dedup-triggering
        [0.0, 1.0, 0.0, 0.0],  # c3 — far
    ]
    with patch("core.tools.text_embed.embed_texts", return_value=fake_vectors):
        Proximity().execute(state)
    # All 3 candidate-candidate pairs land in the graph.
    pair_c1_c2 = _pair_key("c1", "c2")
    pair_c1_c3 = _pair_key("c1", "c3")
    pair_c2_c3 = _pair_key("c2", "c3")
    assert pair_c1_c2 in state.proximity_graph
    assert pair_c1_c3 in state.proximity_graph
    assert pair_c2_c3 in state.proximity_graph
    # Near-duplicate pair scores higher than the orthogonal pair.
    assert state.proximity_graph[pair_c1_c2] > state.proximity_graph[pair_c1_c3]
    # All values are in [0, 1].
    for score in state.proximity_graph.values():
        assert 0.0 <= score <= 1.0


def test_proximity_graph_empty_on_embedding_failure_but_lexical_filled(
    tmp_path: Path,
) -> None:
    """Embedding failure → embed_scores empty, but lexical track still fills graph."""
    state = _make_state(tmp_path)
    # Use bodies long enough for shingles to overlap meaningfully.
    body = " ".join(["foo bar baz qux qaz wxy abc def"] * 3)
    state.candidates = [
        _make_candidate("c1", tmp_path / "c1.md", body=body),
        _make_candidate("c2", tmp_path / "c2.md", body=body),
    ]
    state.reflections = {}
    with patch(
        "core.tools.text_embed.embed_texts",
        side_effect=RuntimeError("OPENAI down"),
    ):
        Proximity().execute(state)
    # Graph still gets the lexical contribution alone.
    pair = _pair_key("c1", "c2")
    assert pair in state.proximity_graph
    # Embed weight × 0 + lexical weight × jaccard — bounded above by lexical weight.
    assert state.proximity_graph[pair] <= GRAPH_WEIGHT_LEXICAL


# ── PR-Π2 — partial-survive fallback ──


def _journal_rows(journal_path: Path) -> list[dict]:
    import json

    if not journal_path.exists():
        return []
    return [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_partial_survive_floor_pinned() -> None:
    """K = 3 — Ranker needs ≥ C(3, 2) = 3 matches to be meaningful."""
    assert PARTIAL_SURVIVE_FLOOR == 3


def test_partial_survive_unit_returns_all_when_count_le_floor(tmp_path: Path) -> None:
    """``_partial_survive`` returns every candidate when the input batch is
    already at or below the floor — no point dropping below K."""
    cands = [_make_candidate(f"c{i}", tmp_path / f"c{i}.md", body="x") for i in range(3)]
    out = Proximity()._partial_survive(cands, graph={})
    assert len(out) == 3
    assert [c["id"] for c in out] == ["c0", "c1", "c2"]


def test_partial_survive_unit_picks_lowest_avg_proximity(tmp_path: Path) -> None:
    """Diversity score = mean of pair-wise proximities incident on a candidate;
    K lowest-avg candidates survive. c_far is orthogonal to the c0/c1/c2
    cluster so its avg is 0 → guaranteed survivor."""
    cands = [
        _make_candidate("c0", tmp_path / "c0.md", body="x"),
        _make_candidate("c1", tmp_path / "c1.md", body="x"),
        _make_candidate("c2", tmp_path / "c2.md", body="x"),
        _make_candidate("c_far", tmp_path / "c_far.md", body="x"),
    ]
    # c0/c1/c2 mutual high proximity; c_far never appears in the graph
    # (defaults to 0.0 avg via the counts-0 branch).
    graph = {
        ("c0", "c1"): 0.9,
        ("c0", "c2"): 0.9,
        ("c1", "c2"): 0.9,
    }
    out = Proximity()._partial_survive(cands, graph=graph)
    assert len(out) == PARTIAL_SURVIVE_FLOOR
    ids = {c["id"] for c in out}
    assert "c_far" in ids


def test_partial_survive_unit_tie_breaks_by_candidate_id(tmp_path: Path) -> None:
    """When proximities tie (e.g. empty graph), survivors are deterministic
    by lexicographic candidate id."""
    cands = [_make_candidate(f"c{i}", tmp_path / f"c{i}.md", body="x") for i in range(5)]
    out = Proximity()._partial_survive(cands, graph={})
    assert [c["id"] for c in out] == ["c0", "c1", "c2"]


def test_proximity_all_duplicates_falls_back_to_partial_survive(tmp_path: Path) -> None:
    """End-to-end — pool-vs-candidate dedup marks every candidate as a dup
    on 2 of 3 tracks, triggering partial-survive instead of the pre-Π2
    hard abort."""
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    pool_body = " ".join(["foo bar baz qux qaz wxy abc def"] * 5)
    (pool_dir / "pool_seed.md").write_text(pool_body, encoding="utf-8")

    state = _make_state(tmp_path)
    state.pool_path_in = pool_dir
    state.candidates = [
        _make_candidate(f"c{i}", tmp_path / f"c{i}.md", body=pool_body) for i in range(5)
    ]
    state.reflections = {}  # role track stays silent (only 2-track vote)
    # All candidates + 1 pool entry → embedding marks every candidate as
    # a pool-match; lexical track marks them via shingled overlap.
    fake_vectors = [[1.0, 0.0, 0.0, 0.0]] * 6  # 5 candidates + 1 pool
    with patch("core.tools.text_embed.embed_texts", return_value=fake_vectors):
        result = Proximity().execute(state)
    # Pre-Π2: would have been status="error" / error_category="all_duplicates".
    assert result.success
    assert len(state.candidates) == PARTIAL_SURVIVE_FLOOR


def test_proximity_emits_fallback_journal_event(tmp_path: Path) -> None:
    """The fallback path emits a ``proximity_all_duplicates_fallback`` warn
    event into the active SessionJournal."""
    from core.observability import SessionJournal, session_journal_scope

    journal_path = tmp_path / "journal.jsonl"
    journal = SessionJournal(
        session_id="t-prox", gen_tag="t", component="seed-generation", path=journal_path
    )

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    pool_body = " ".join(["foo bar baz qux qaz wxy abc def"] * 5)
    (pool_dir / "pool_seed.md").write_text(pool_body, encoding="utf-8")

    state = _make_state(tmp_path)
    state.pool_path_in = pool_dir
    state.candidates = [
        _make_candidate(f"c{i}", tmp_path / f"c{i}.md", body=pool_body) for i in range(5)
    ]
    state.reflections = {}
    fake_vectors = [[1.0, 0.0, 0.0]] * 6
    with (
        session_journal_scope(journal),
        patch("core.tools.text_embed.embed_texts", return_value=fake_vectors),
    ):
        result = Proximity().execute(state)
    assert result.success
    rows = _journal_rows(journal_path)
    fallback = [r for r in rows if r["event"] == "proximity_all_duplicates_fallback"]
    assert len(fallback) == 1
    payload = fallback[0]["payload"]
    assert payload["original_count"] == 5
    assert payload["survivor_count"] == PARTIAL_SURVIVE_FLOOR
    assert fallback[0]["level"] == "warn"


def test_proximity_partial_survive_silent_when_no_journal_scope(
    tmp_path: Path,
) -> None:
    """Fallback path must not raise when no SessionJournal scope is active."""
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    pool_body = " ".join(["foo bar baz qux qaz wxy abc def"] * 5)
    (pool_dir / "pool_seed.md").write_text(pool_body, encoding="utf-8")

    state = _make_state(tmp_path)
    state.pool_path_in = pool_dir
    state.candidates = [
        _make_candidate(f"c{i}", tmp_path / f"c{i}.md", body=pool_body) for i in range(5)
    ]
    state.reflections = {}
    fake_vectors = [[1.0, 0.0, 0.0]] * 6
    with patch("core.tools.text_embed.embed_texts", return_value=fake_vectors):
        result = Proximity().execute(state)
    assert result.success
    assert len(state.candidates) == PARTIAL_SURVIVE_FLOOR


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
        _make_candidate("c2", tmp_path / "c2.md", body="totally unrelated content here"),
    ]
    proximity = Proximity()
    candidate_texts = proximity._load_candidate_texts(state)
    pool_texts = proximity._load_pool_texts(state)
    lexical_dupes, _scores = proximity._lexical_track(candidate_texts, pool_texts)
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
        embed_dupes, _scores = proximity._embedding_track(candidate_texts, pool_texts)
    assert "c1" in embed_dupes
    assert "c2" not in embed_dupes


def test_proximity_pool_path_missing_dir_logged(tmp_path: Path) -> None:
    """Non-existent pool_path_in path returns empty list with WARNING."""
    state = _make_state(tmp_path)
    state.pool_path_in = tmp_path / "nonexistent_pool"
    proximity = Proximity()
    pool_texts = proximity._load_pool_texts(state)
    assert pool_texts == []
