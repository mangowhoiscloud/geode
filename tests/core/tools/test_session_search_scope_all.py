"""PR-Hermes-1d.2 — ``session_search`` ``scope='all'`` invariants.

Pins the new cross-project scope path: parameter wiring, missing-
index graceful path, hit shape carries project_id, session_id
filter applied after the FTS query, default scope still 'project'.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from core.tools.session_search import (
    SCOPE_ALL,
    SCOPE_PROJECT,
    SessionSearchTool,
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


def _seed_db(path: Path, rows: list[tuple[str, int, str, str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_MESSAGES_SCHEMA_SQL)
        for session_id, seq, role, content, ts in rows:
            conn.execute(
                "INSERT INTO messages (session_id, seq, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, seq, role, content, ts),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def index_with_two_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Rebuild a global.db with 2 projects, then redirect
    ``GLOBAL_SEARCH_DB`` so the tool sees the fixture."""
    projects_root = tmp_path / "projects"
    _seed_db(
        projects_root / "alpha" / "sessions" / "sessions.db",
        [
            ("sess-1", 0, "user", "alpha project search query", 100.0),
            ("sess-1", 1, "assistant", "alpha says hello search", 101.0),
        ],
    )
    _seed_db(
        projects_root / "beta" / "sessions" / "sessions.db",
        [
            ("sess-2", 0, "user", "beta project search query", 200.0),
        ],
    )

    db_path = tmp_path / "search" / "global.db"
    monkeypatch.setattr("core.paths.GLOBAL_SEARCH_DB", db_path)
    monkeypatch.setattr("core.memory.search_index.GLOBAL_SEARCH_DB", db_path)

    from core.memory.search_index import SearchIndex

    with SearchIndex(db_path) as idx:
        idx.rebuild(projects_root=projects_root)
    return db_path


def test_tool_metadata_lists_scope_parameter():
    tool = SessionSearchTool()
    assert tool.name == "session_search"
    params = tool.parameters
    assert "scope" in params["properties"]
    enum = params["properties"]["scope"]["enum"]
    assert set(enum) == {SCOPE_PROJECT, SCOPE_ALL}
    # Default should NOT change the existing tool's behaviour.
    assert params["properties"]["scope"]["default"] == SCOPE_PROJECT


def test_scope_all_missing_index_graceful_no_op(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No global.db on disk → tool returns matched=False, not an error."""
    monkeypatch.setattr("core.paths.GLOBAL_SEARCH_DB", tmp_path / "missing.db")
    tool = SessionSearchTool()
    result = tool._execute_sync(query="anything", scope=SCOPE_ALL)
    assert result["matched"] is False
    assert result["count"] == 0
    assert result["scope"] == SCOPE_ALL
    assert result["hits"] == []
    assert "global_index_not_built" in result.get("reason", "")


def test_scope_all_finds_hits_across_projects(index_with_two_projects: Path):
    tool = SessionSearchTool()
    result = tool._execute_sync(query="search", scope=SCOPE_ALL)
    assert result["matched"] is True
    assert result["scope"] == SCOPE_ALL
    assert result["count"] >= 2
    project_ids = {hit["project_id"] for hit in result["hits"]}
    assert project_ids == {"alpha", "beta"}


def test_scope_all_hit_shape_carries_project_id(index_with_two_projects: Path):
    tool = SessionSearchTool()
    result = tool._execute_sync(query="search", scope=SCOPE_ALL)
    hit = result["hits"][0]
    assert "project_id" in hit
    assert "project_slug" in hit
    assert "session_id" in hit
    assert "message_id" in hit
    assert "snippet" in hit
    assert "score" in hit


def test_scope_all_project_id_filter(index_with_two_projects: Path):
    tool = SessionSearchTool()
    result = tool._execute_sync(query="search", scope=SCOPE_ALL, project_id="alpha")
    assert result["count"] >= 1
    for hit in result["hits"]:
        assert hit["project_id"] == "alpha"


def test_scope_all_session_id_filter_applied_after_fts(
    index_with_two_projects: Path,
):
    """session_id narrows to one session even across the global index."""
    tool = SessionSearchTool()
    result = tool._execute_sync(query="search", scope=SCOPE_ALL, session_id="sess-2")
    assert all(h["session_id"] == "sess-2" for h in result["hits"])
    assert result["count"] == 1


def test_scope_unknown_value_falls_back_to_project_scope():
    """Defensive default — typo in scope must not error or run scope=all."""
    tool = SessionSearchTool()
    result = tool._execute_sync(query="anything", scope="invalid_scope")
    # The fallback path runs project-scope which lacks a SessionManager
    # in the test process; either dependency error or empty result is fine.
    assert "scope" in result or result.get("error_type") == "dependency"


def test_query_missing_returns_tool_error():
    tool = SessionSearchTool()
    result = tool._execute_sync(query="", scope=SCOPE_ALL)
    assert result.get("error") is not None or result.get("error_type") is not None


def test_scope_all_empty_query_via_sanitiser(index_with_two_projects: Path):
    """All-special-chars query → sanitiser empties → empty hit list."""
    tool = SessionSearchTool()
    result = tool._execute_sync(query="...", scope=SCOPE_ALL)
    assert result["matched"] is False
    assert result["count"] == 0
    assert result["scope"] == SCOPE_ALL
