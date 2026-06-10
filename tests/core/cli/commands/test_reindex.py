"""PR-Hermes-1d.2 — ``geode reindex`` CLI invariants.

Pins the command's surface: registered on the main Typer app, runs
end-to-end against a fixture projects root, handles the empty case
gracefully, exits non-zero only on SearchIndex error.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from core.cli import app
from typer.testing import CliRunner

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


def _seed_db(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_MESSAGES_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO messages (session_id, seq, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sess-1", 0, "user", content, 1.0),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def isolated_search_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "search" / "global.db"
    monkeypatch.setattr("core.paths.GLOBAL_SEARCH_DB", db)
    monkeypatch.setattr("core.memory.search_index.GLOBAL_SEARCH_DB", db)
    return db


def test_reindex_command_registered_on_app():
    """The command appears under the main Typer app."""
    registered = [c.name for c in app.registered_commands]
    assert "reindex" in registered


def test_reindex_empty_projects_root_exits_zero(
    tmp_path: Path,
    isolated_search_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """No project DBs anywhere → empty index, exit 0 with a message."""
    monkeypatch.setattr("core.paths.GLOBAL_PROJECTS_DIR", tmp_path / "empty")
    monkeypatch.setattr("core.memory.search_index.GLOBAL_PROJECTS_DIR", tmp_path / "empty")
    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--projects-root", str(tmp_path / "empty")])
    assert result.exit_code == 0
    assert "No projects found" in result.output


def test_reindex_rebuilds_against_fixture_projects(
    tmp_path: Path,
    isolated_search_db: Path,
):
    """Fixture projects root with messages → index populated, summary printed."""
    projects = tmp_path / "projects"
    _seed_db(projects / "alpha" / "sessions" / "sessions.db", "alpha content row")
    _seed_db(projects / "beta" / "sessions" / "sessions.db", "beta content row")

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--projects-root", str(projects)])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output
    assert "Indexed 2 messages across 2 projects" in result.output

    # Verify the index file actually carries the rows.
    conn = sqlite3.connect(isolated_search_db)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM indexed_messages").fetchone()[0]
        assert rows == 2
        project_ids = {
            r[0] for r in conn.execute("SELECT DISTINCT project_id FROM indexed_messages")
        }
        assert project_ids == {"alpha", "beta"}
    finally:
        conn.close()


def test_reindex_help_text_describes_purpose(monkeypatch: pytest.MonkeyPatch):
    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--help"])
    assert result.exit_code == 0
    assert "global.db" in result.output
    assert "sessions.db" in result.output
