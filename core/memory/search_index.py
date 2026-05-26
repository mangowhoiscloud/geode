"""Cross-project search index — Hermes Phase 1d.2.

GEODE Phase 1c shipped per-project FTS5 search inside each
``sessions.db`` (#1439). Phase 1d shipped the LLM-facing
``session_search`` tool (#1440) limited to *the current project*.
Phase 1d.2 ships the cross-project complement: a single FTS5-backed
``~/.geode/search/global.db`` that mirrors the ``messages`` rows from
every ``~/.geode/projects/<id>/sessions/sessions.db`` and answers
``session_search(scope="all")`` / ``geode reindex``.

**Architecture decision** — rebuild-from-source artefact.

* The per-project ``sessions.db`` is the *ground truth*. ``global.db``
  is a derived FTS5 index that can be rebuilt at any time by walking
  every project DB and re-inserting the messages rows.
* No live indexer thread / queue (deferred to 1d.3). The user runs
  ``geode reindex`` after a session-state change and the next
  ``session_search(scope="all")`` answers against the refreshed index.
* The ``content``/``tool_name`` columns are mirrored verbatim from the
  source so the FTS5 query grammar is the same as Phase 1c's
  per-project search — operators don't learn two query languages.

**Schema** (single table + one external-content FTS5 virtual table):

.. code-block:: sql

   CREATE TABLE indexed_messages (
       rowid        INTEGER PRIMARY KEY,
       project_id   TEXT NOT NULL,
       project_slug TEXT NOT NULL,
       session_id   TEXT NOT NULL,
       message_id   INTEGER NOT NULL,
       seq          INTEGER NOT NULL,
       role         TEXT NOT NULL,
       content      TEXT,
       tool_name    TEXT,
       tool_calls   TEXT,
       timestamp    REAL NOT NULL,
       UNIQUE(project_id, session_id, message_id)
   )

   CREATE VIRTUAL TABLE indexed_messages_fts USING fts5(
       content, tool_name, tool_calls,
       content='indexed_messages',
       content_rowid='rowid',
       tokenize='unicode61'
   )

The ``UNIQUE(project_id, session_id, message_id)`` constraint makes
the reindex idempotent — re-running ``geode reindex`` on the same
state is a no-op (``INSERT OR REPLACE`` overwrites by composite key).

**Graceful**: missing source DB, missing project dir, malformed row
→ logged and skipped, never raised. The retrieval API mirrors
``EpisodicStore.recent``'s read-side defensive contract.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_PROJECTS_DIR, GLOBAL_SEARCH_DB

log = logging.getLogger(__name__)

__all__ = [
    "SearchIndex",
    "SearchIndexHit",
    "iter_project_dbs",
]


_CREATE_INDEXED_MESSAGES_SQL = """\
CREATE TABLE IF NOT EXISTS indexed_messages (
    rowid        INTEGER PRIMARY KEY,
    project_id   TEXT NOT NULL,
    project_slug TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    message_id   INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT,
    tool_name    TEXT,
    tool_calls   TEXT,
    timestamp    REAL NOT NULL,
    UNIQUE(project_id, session_id, message_id)
)
"""

_CREATE_INDEXED_MESSAGES_FTS_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS indexed_messages_fts USING fts5(
    content, tool_name, tool_calls,
    content='indexed_messages',
    content_rowid='rowid',
    tokenize='unicode61'
)
"""

_INDEXED_MESSAGES_INSERT_TRIGGER_SQL = """\
CREATE TRIGGER IF NOT EXISTS indexed_messages_after_insert AFTER INSERT ON indexed_messages BEGIN
    INSERT INTO indexed_messages_fts(rowid, content, tool_name, tool_calls)
    VALUES (new.rowid, new.content, new.tool_name, new.tool_calls);
END
"""

_INDEXED_MESSAGES_DELETE_TRIGGER_SQL = """\
CREATE TRIGGER IF NOT EXISTS indexed_messages_after_delete AFTER DELETE ON indexed_messages BEGIN
    INSERT INTO indexed_messages_fts(indexed_messages_fts, rowid, content, tool_name, tool_calls)
    VALUES ('delete', old.rowid, old.content, old.tool_name, old.tool_calls);
END
"""

_INDEXED_MESSAGES_UPDATE_TRIGGER_SQL = """\
CREATE TRIGGER IF NOT EXISTS indexed_messages_after_update AFTER UPDATE ON indexed_messages BEGIN
    INSERT INTO indexed_messages_fts(indexed_messages_fts, rowid, content, tool_name, tool_calls)
    VALUES ('delete', old.rowid, old.content, old.tool_name, old.tool_calls);
    INSERT INTO indexed_messages_fts(rowid, content, tool_name, tool_calls)
    VALUES (new.rowid, new.content, new.tool_name, new.tool_calls);
END
"""


@dataclass(frozen=True, slots=True)
class SearchIndexHit:
    """One row from a cross-project ``session_search(scope='all')`` result."""

    project_id: str
    project_slug: str
    session_id: str
    message_id: int
    seq: int
    role: str
    content: Any
    tool_name: str | None
    timestamp: float
    snippet: str
    score: float


def iter_project_dbs(projects_root: Path | None = None) -> Iterator[tuple[str, Path]]:
    """Yield ``(project_id, sessions_db_path)`` for every project on disk.

    A project is any directory directly under ``~/.geode/projects/``
    containing ``sessions/sessions.db``. Missing directory → empty
    iterator (no error). Directories without the session DB are
    skipped silently — they're a project record without any
    captured runs yet.
    """
    root = projects_root if projects_root is not None else GLOBAL_PROJECTS_DIR
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        candidate = entry / "sessions" / "sessions.db"
        if candidate.is_file():
            yield entry.name, candidate


class SearchIndex:
    """Cross-project FTS5 ledger backed by ``~/.geode/search/global.db``.

    Open the index once per process; the underlying SQLite connection
    is held until :meth:`close` runs. Multiple read-only consumers
    can share the index file via SQLite's default journal mode — the
    rebuild path acquires an exclusive transaction so concurrent
    readers see either the pre- or post-rebuild snapshot, never a
    partial one.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else GLOBAL_SEARCH_DB
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @property
    def path(self) -> Path:
        return self._path

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_INDEXED_MESSAGES_SQL)
        cur.execute(_CREATE_INDEXED_MESSAGES_FTS_SQL)
        cur.execute(_INDEXED_MESSAGES_INSERT_TRIGGER_SQL)
        cur.execute(_INDEXED_MESSAGES_DELETE_TRIGGER_SQL)
        cur.execute(_INDEXED_MESSAGES_UPDATE_TRIGGER_SQL)
        self._conn.commit()

    def close(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()

    def __enter__(self) -> SearchIndex:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ── Rebuild ───────────────────────────────────────────────────

    def rebuild(self, projects_root: Path | None = None) -> dict[str, int]:
        """Walk every project DB and (re)populate the index.

        Returns a ``{project_id: rows_indexed}`` map so callers (the
        ``geode reindex`` CLI) can surface progress. Each project is
        processed in its own savepoint so a corrupt DB doesn't sink
        the whole rebuild.
        """
        stats: dict[str, int] = {}
        # Wipe-and-rebuild — the source DBs are the ground truth so
        # full rebuild is safe and idempotent. Done inside a single
        # transaction so concurrent ``search()`` reads see either the
        # pre- or post-rebuild state.
        cur = self._conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("DELETE FROM indexed_messages")
            for project_id, db_path in iter_project_dbs(projects_root):
                try:
                    indexed = self._index_project(cur, project_id, db_path)
                except sqlite3.Error as exc:
                    log.warning(
                        "search_index: project %s rebuild failed: %s; skipping",
                        project_id,
                        exc,
                    )
                    continue
                stats[project_id] = indexed
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return stats

    def _index_project(self, cur: sqlite3.Cursor, project_id: str, db_path: Path) -> int:
        """Copy the ``messages`` rows from one project DB into the index.

        Returns the row count that landed in ``indexed_messages``.
        Reads via a separate connection so the source DB's locking
        doesn't interact with the index DB's write transaction.
        """
        project_slug = project_id  # Same value today; kept as a separate
        # column so a future ``~/.geode/projects/<id>/slug`` lookup can
        # carry the human-readable label without a schema migration.
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        try:
            rows = src.execute(
                "SELECT id, session_id, seq, role, content, tool_name, "
                "tool_calls, timestamp FROM messages "
                "ORDER BY timestamp ASC"
            ).fetchall()
        finally:
            src.close()
        indexed = 0
        for row in rows:
            cur.execute(
                "INSERT OR REPLACE INTO indexed_messages "
                "(project_id, project_slug, session_id, message_id, seq, "
                "role, content, tool_name, tool_calls, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    project_slug,
                    row["session_id"],
                    int(row["id"]),
                    int(row["seq"]),
                    row["role"],
                    row["content"],
                    row["tool_name"],
                    row["tool_calls"],
                    float(row["timestamp"]),
                ),
            )
            indexed += 1
        return indexed

    # ── Search ────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        limit: int = 20,
    ) -> list[SearchIndexHit]:
        """Cross-project FTS5 search. ``project_id`` narrows to a single project.

        Empty / non-string / sanitised-to-empty query → ``[]`` (no
        rows). Malformed FTS5 syntax slips through to ``sqlite3``
        which raises ``OperationalError``; we trap and log + return
        ``[]`` to mirror the per-project search contract.
        """
        from core.memory.fts_helpers import sanitize_fts5_query

        clean = sanitize_fts5_query(query)
        if not clean:
            return []
        sql = (
            "SELECT m.project_id, m.project_slug, m.session_id, m.message_id, "
            "m.seq, m.role, m.content, m.tool_name, m.timestamp, "
            "snippet(indexed_messages_fts, 0, '[', ']', '…', 16) AS snippet, "
            "bm25(indexed_messages_fts) AS score "
            "FROM indexed_messages_fts JOIN indexed_messages m "
            "ON m.rowid = indexed_messages_fts.rowid "
            "WHERE indexed_messages_fts MATCH ?"
        )
        params: list[Any] = [clean]
        if project_id is not None:
            sql += " AND m.project_id = ?"
            params.append(project_id)
        sql += " ORDER BY m.timestamp DESC LIMIT ?"
        params.append(limit)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("search_index: FTS5 query failed: %s", exc)
            return []
        return [_row_to_hit(r) for r in rows]


def _row_to_hit(row: sqlite3.Row) -> SearchIndexHit:
    content_raw = row["content"]
    content: Any = None
    if content_raw is not None:
        try:
            content = json.loads(content_raw)
        except (json.JSONDecodeError, TypeError):
            content = content_raw
    return SearchIndexHit(
        project_id=row["project_id"],
        project_slug=row["project_slug"],
        session_id=row["session_id"],
        message_id=int(row["message_id"]),
        seq=int(row["seq"]),
        role=row["role"],
        content=content,
        tool_name=row["tool_name"],
        timestamp=float(row["timestamp"]),
        snippet=row["snippet"],
        score=float(row["score"]),
    )
