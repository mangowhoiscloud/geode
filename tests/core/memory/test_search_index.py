"""PR-Hermes-1d.2 — ``core.memory.search_index`` invariants.

Pins the cross-project FTS5 index schema, the rebuild idempotency,
the search contract (project filter + bm25 ordering + snippet
shape), and the discovery walker's graceful no-op behaviour.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from core.memory.search_index import (
    SearchIndex,
    SearchIndexHit,
    iter_project_dbs,
)

_MESSAGES_SCHEMA_SQL = """
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT,
    tool_call_id  TEXT,
    tool_calls    TEXT,
    tool_name     TEXT,
    timestamp     REAL NOT NULL,
    token_count   INTEGER,
    finish_reason TEXT,
    reasoning     TEXT,
    metadata      TEXT,
    UNIQUE(session_id, seq)
)
"""


def _seed_project_db(db_path: Path, *rows: tuple[str, int, str, str, str | None, float]) -> None:
    """Populate a per-project sessions.db fixture with ``messages`` rows.

    Each row tuple is (session_id, seq, role, content, tool_name, timestamp).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_MESSAGES_SCHEMA_SQL)
        for session_id, seq, role, content, tool_name, timestamp in rows:
            conn.execute(
                "INSERT INTO messages "
                "(session_id, seq, role, content, tool_name, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, seq, role, content, tool_name, timestamp),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fixture_projects_root(tmp_path: Path) -> Path:
    """Build a 2-project, 3-session fixture under ``tmp_path/projects/``."""
    root = tmp_path / "projects"
    _seed_project_db(
        root / "geode-main" / "sessions" / "sessions.db",
        ("sess-a", 0, "user", "Hello world", None, 1.0),
        ("sess-a", 1, "assistant", "Hi, how can I help with the index?", None, 2.0),
        ("sess-b", 0, "user", "Lookup the search wiring", None, 3.0),
    )
    _seed_project_db(
        root / "geode-experimental" / "sessions" / "sessions.db",
        ("sess-c", 0, "user", "Look at the search index", None, 4.0),
    )
    return root


# ── iter_project_dbs ─────────────────────────────────────────────────


def test_iter_project_dbs_missing_root_returns_empty(tmp_path: Path):
    result = list(iter_project_dbs(tmp_path / "nonexistent"))
    assert result == []


def test_iter_project_dbs_skips_directories_without_sessions_db(tmp_path: Path):
    root = tmp_path / "projects"
    root.mkdir()
    (root / "no-sessions").mkdir()  # legitimate project dir, no DB yet
    (root / "fake-file.txt").write_text("not a dir", encoding="utf-8")
    assert list(iter_project_dbs(root)) == []


def test_iter_project_dbs_yields_alphabetical(fixture_projects_root: Path):
    pairs = list(iter_project_dbs(fixture_projects_root))
    assert [p[0] for p in pairs] == ["geode-experimental", "geode-main"]
    for _, db in pairs:
        assert db.is_file()
        assert db.name == "sessions.db"


# ── SearchIndex schema + rebuild ─────────────────────────────────────


def test_search_index_creates_schema_on_init(tmp_path: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        cur = idx._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' OR type='trigger'"
        )
        names = {r[0] for r in cur.fetchall()}
        assert "indexed_messages" in names
        assert "indexed_messages_after_insert" in names
        assert "indexed_messages_after_delete" in names
        assert "indexed_messages_after_update" in names
        cur = idx._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'indexed_messages_fts%'"
        )
        # FTS5 virtual table creates a set of shadow tables — main fts is enough.
        fts_names = {r[0] for r in cur.fetchall()}
        assert "indexed_messages_fts" in fts_names


def test_search_index_path_property(tmp_path: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        assert idx.path == db
        assert db.parent.is_dir()


def test_rebuild_empty_projects_root_returns_empty_stats(tmp_path: Path):
    empty_root = tmp_path / "projects"
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        stats = idx.rebuild(projects_root=empty_root)
        assert stats == {}


def test_rebuild_populates_stats(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        stats = idx.rebuild(projects_root=fixture_projects_root)
        assert stats == {"geode-main": 3, "geode-experimental": 1}


def test_rebuild_is_idempotent(tmp_path: Path, fixture_projects_root: Path):
    """Running rebuild twice on the same input → identical row counts."""
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        first = idx.rebuild(projects_root=fixture_projects_root)
        second = idx.rebuild(projects_root=fixture_projects_root)
        assert first == second
        rows = idx._conn.execute("SELECT COUNT(*) FROM indexed_messages").fetchone()[0]
        assert rows == 4


def test_rebuild_clears_stale_rows(tmp_path: Path, fixture_projects_root: Path):
    """A project removed from disk → its rows are gone after rebuild."""
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        rows_before = idx._conn.execute(
            "SELECT COUNT(*) FROM indexed_messages WHERE project_id = 'geode-experimental'"
        ).fetchone()[0]
        assert rows_before == 1

        # Simulate operator deleting the experimental project.
        import shutil

        shutil.rmtree(fixture_projects_root / "geode-experimental")

        idx.rebuild(projects_root=fixture_projects_root)
        rows_after = idx._conn.execute(
            "SELECT COUNT(*) FROM indexed_messages WHERE project_id = 'geode-experimental'"
        ).fetchone()[0]
        assert rows_after == 0


# ── search() ─────────────────────────────────────────────────────────


def test_search_empty_query_returns_empty(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        assert idx.search("") == []
        assert idx.search("   ") == []


def test_search_cross_project_match(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        hits = idx.search("search")
        assert len(hits) >= 2
        project_ids = {h.project_id for h in hits}
        assert project_ids == {"geode-main", "geode-experimental"}


def test_search_hit_shape(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        hits = idx.search("search")
        h = hits[0]
        assert isinstance(h, SearchIndexHit)
        assert h.project_id
        assert h.project_slug == h.project_id  # Phase-1d.2 stub equality
        assert h.session_id
        assert isinstance(h.message_id, int)
        assert isinstance(h.seq, int)
        assert h.role in {"user", "assistant"}
        assert isinstance(h.timestamp, float)
        assert "[" in h.snippet and "]" in h.snippet
        # bm25 returns negative scores by convention (lower = more relevant).
        assert isinstance(h.score, float)


def test_search_project_filter(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        hits = idx.search("search", project_id="geode-experimental")
        assert all(h.project_id == "geode-experimental" for h in hits)
        assert len(hits) == 1


def test_search_limit_respected(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        hits = idx.search("search", limit=1)
        assert len(hits) == 1


def test_search_no_match_returns_empty(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        assert idx.search("xyzqqq_nomatch_xyz") == []


def test_search_results_ordered_by_timestamp_desc(tmp_path: Path, fixture_projects_root: Path):
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        hits = idx.search("search")
        timestamps = [h.timestamp for h in hits]
        assert timestamps == sorted(timestamps, reverse=True)


def test_search_returns_empty_on_malformed_fts_grammar(tmp_path: Path, fixture_projects_root: Path):
    """FTS5 grammar errors should be trapped — the sanitiser cleans most,
    but raw quotes can still get through. Verify the trap path."""
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        # Empty after sanitisation
        assert idx.search("....") == []


def test_search_session_id_push_down_into_sql(tmp_path: Path, fixture_projects_root: Path):
    """``session_id`` filter is applied INSIDE the SQL query so
    ``limit`` semantics are correct (Codex MCP catch — pre-fix the
    tool post-filtered after limit, hiding hits in non-matching
    sessions past row N)."""
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        idx.rebuild(projects_root=fixture_projects_root)
        hits = idx.search("search", session_id="sess-b", limit=10)
        assert all(h.session_id == "sess-b" for h in hits)
        assert len(hits) == 1


def test_busy_timeout_pragma_applied(tmp_path: Path):
    """busy_timeout=5000 — concurrent readers must not race-fail the
    rebuild's BEGIN IMMEDIATE."""
    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        result = idx._conn.execute("PRAGMA busy_timeout").fetchone()
        assert result[0] == 5000


def test_rebuild_savepoint_isolates_corrupt_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A ``sqlite3.Error`` during one project's indexing rolls back
    JUST that project's partial rows; siblings remain fully indexed
    (Codex MCP catch — docstring claimed per-project savepoints but
    pre-fix the outer catch leaked half-inserted state)."""
    projects = tmp_path / "projects"
    _seed_project_db(
        projects / "good" / "sessions" / "sessions.db",
        ("sess-g", 0, "user", "good content one", None, 1.0),
        ("sess-g", 1, "user", "good content two", None, 2.0),
    )
    _seed_project_db(
        projects / "bad" / "sessions" / "sessions.db",
        ("sess-b", 0, "user", "bad content one", None, 3.0),
    )

    db = tmp_path / "search" / "global.db"
    with SearchIndex(db) as idx:
        original_index = idx._index_project

        def _flaky_index(cur, project_id: str, db_path: Path) -> int:
            if project_id == "bad":
                cur.execute(
                    "INSERT OR REPLACE INTO indexed_messages "
                    "(project_id, project_slug, session_id, message_id, "
                    "seq, role, content, tool_name, tool_calls, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "bad",
                        "bad",
                        "sess-b",
                        1,
                        0,
                        "user",
                        "partial insert",
                        None,
                        None,
                        3.0,
                    ),
                )
                raise sqlite3.Error("simulated source DB corruption")
            return original_index(cur, project_id, db_path)

        monkeypatch.setattr(idx, "_index_project", _flaky_index)
        stats = idx.rebuild(projects_root=projects)

        assert stats == {"good": 2}
        good_rows = idx._conn.execute(
            "SELECT COUNT(*) FROM indexed_messages WHERE project_id = 'good'"
        ).fetchone()[0]
        bad_rows = idx._conn.execute(
            "SELECT COUNT(*) FROM indexed_messages WHERE project_id = 'bad'"
        ).fetchone()[0]
        assert good_rows == 2
        assert bad_rows == 0, "savepoint rollback must wipe the partial insert from the bad project"
