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


def _seed_db(
    path: Path,
    rows: list[tuple[str, int, str, str, float]],
    *,
    parents: dict[str, str] | None = None,
    unregistered: frozenset[str] = frozenset(),
) -> None:
    """Seed messages plus the ``sessions`` rows SessionManager always keeps.

    ``parents`` records worker parents; ``unregistered`` sessions get no
    ``sessions`` row (metadata never committed).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_MESSAGES_SCHEMA_SQL)
        conn.execute(
            "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, "
            "parent_session_id TEXT NOT NULL DEFAULT '')"
        )
        for session_id, seq, role, content, ts in rows:
            conn.execute(
                "INSERT INTO messages (session_id, seq, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, seq, role, content, ts),
            )
            if session_id not in unregistered:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions VALUES (?, ?)",
                    (session_id, (parents or {}).get(session_id, "")),
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


def test_scope_all_never_crosses_gateway_principals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every indexed row carries its owner: gateway threads and their workers
    (parent in ``sessions`` or ``collaboration_runs``) reach only that thread,
    and a session with no ownership record only itself."""
    from types import SimpleNamespace

    from core.memory.search_index import SearchIndex
    from core.tools.base import ToolContext

    alice, bob = "s-gw-aaaaaaaaaaaa", "s-gw-bbbbbbbbbbbb"
    source = tmp_path / "projects" / "alpha" / "sessions" / "sessions.db"
    _seed_db(
        source,
        [
            (alice, 0, "user", "quarterly alice payroll", 1.0),
            ("task-alice-1", 0, "user", "quarterly alice worker draft", 2.0),
            ("task-alice-2", 0, "user", "quarterly alice run-only worker", 3.0),
            ("s-orphan", 0, "user", "quarterly orphan transcript", 4.0),
            (bob, 0, "user", "quarterly bob own note", 5.0),
            ("sess-op", 0, "user", "quarterly operator analysis", 6.0),
        ],
        parents={"task-alice-1": alice},
        unregistered=frozenset({"task-alice-2", "s-orphan"}),
    )
    conn = sqlite3.connect(source)
    try:
        conn.execute(
            "CREATE TABLE collaboration_runs (task_id TEXT PRIMARY KEY, "
            "parent_session_id TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO collaboration_runs VALUES ('task-alice-2', ?)", (alice,))
        conn.commit()
    finally:
        conn.close()
    db_path = tmp_path / "search" / "global.db"
    monkeypatch.setattr("core.paths.GLOBAL_SEARCH_DB", db_path)
    monkeypatch.setattr("core.memory.search_index.GLOBAL_SEARCH_DB", db_path)
    with SearchIndex(db_path) as idx:
        assert idx.rebuild(projects_root=tmp_path / "projects") == {"alpha": 6}

    tool = SessionSearchTool()

    def sessions(context: object, **kwargs: object) -> set[str]:
        result = tool._execute_sync(
            query="quarterly", scope=SCOPE_ALL, _tool_context=context, **kwargs
        )
        return {h["session_id"] for h in result["hits"]}

    assert sessions(ToolContext(session_id=bob)) == {"sess-op", bob}
    assert sessions(ToolContext(session_id=bob), session_id="task-alice-1") == set()
    assert sessions(None) == {"sess-op"}
    assert sessions(ToolContext(session_id="s-orphan")) == {"sess-op", "s-orphan"}
    worker = ToolContext(
        session_id="task-alice-3",
        is_subagent=True,
        agent_loop=SimpleNamespace(_parent_session_id=alice),
    )
    assert sessions(worker) == {"sess-op", alice, "task-alice-1", "task-alice-2"}

    # A row whose owner was never recorded is not served even in a current index.
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            "INSERT INTO indexed_messages (project_id, project_slug, session_id, "
            "message_id, seq, role, content, timestamp) "
            "VALUES ('alpha', 'alpha', 'task-x', 99, 0, 'user', 'quarterly unowned', 9.0)"
        )
        raw.commit()
    finally:
        raw.close()
    assert "task-x" not in sessions(ToolContext(session_id=bob))


def test_scope_all_refuses_an_index_built_without_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index from an older ``geode reindex`` has worker rows of unknown
    ownership; it is not served until it is rebuilt."""
    from core.tools.base import ToolContext

    db_path = tmp_path / "search" / "global.db"
    db_path.parent.mkdir(parents=True)
    legacy = sqlite3.connect(db_path)
    try:
        legacy.executescript(
            """
            CREATE TABLE indexed_messages (
                rowid INTEGER PRIMARY KEY, project_id TEXT NOT NULL,
                project_slug TEXT NOT NULL, session_id TEXT NOT NULL,
                message_id INTEGER NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
                content TEXT, tool_name TEXT, tool_calls TEXT, timestamp REAL NOT NULL,
                UNIQUE(project_id, session_id, message_id));
            CREATE VIRTUAL TABLE indexed_messages_fts USING fts5(
                content, tool_name, tool_calls, content='indexed_messages',
                content_rowid='rowid', tokenize='unicode61');
            CREATE TRIGGER indexed_messages_after_insert AFTER INSERT ON indexed_messages
            BEGIN INSERT INTO indexed_messages_fts(rowid, content, tool_name, tool_calls)
            VALUES (new.rowid, new.content, new.tool_name, new.tool_calls); END;
            INSERT INTO indexed_messages (project_id, project_slug, session_id, message_id,
                seq, role, content, timestamp)
            VALUES ('alpha', 'alpha', 'task-alice-1', 1, 0, 'user',
                    'quarterly alice worker draft', 1.0);
            """
        )
        legacy.commit()
    finally:
        legacy.close()
    monkeypatch.setattr("core.paths.GLOBAL_SEARCH_DB", db_path)
    monkeypatch.setattr("core.memory.search_index.GLOBAL_SEARCH_DB", db_path)

    result = SessionSearchTool()._execute_sync(
        query="quarterly",
        scope=SCOPE_ALL,
        _tool_context=ToolContext(session_id="s-gw-bbbbbbbbbbbb"),
    )
    assert result["hits"] == [] and result["matched"] is False
    assert "geode reindex" in result["reason"]
    assert "alice" not in str(result)
