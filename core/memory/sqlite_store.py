"""Small shared SQLite context for short-lived mutable projections."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA_LOCK = threading.Lock()


@contextmanager
def short_sqlite_connection(
    db_path: Path,
    ensure_schema: Callable[[sqlite3.Connection], None],
    *,
    immediate: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Open one WAL connection and optionally wrap it in an immediate transaction."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        # SQLite serializes schema changes across processes; this small
        # in-process gate also prevents sibling first-access threads from
        # racing the journal-mode transition before that lock can settle.
        with _SCHEMA_LOCK:
            conn.execute("PRAGMA journal_mode=WAL")
            ensure_schema(conn)
            conn.commit()
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if immediate:
                conn.commit()
        except Exception:
            if immediate:
                conn.rollback()
            raise
    finally:
        conn.close()
