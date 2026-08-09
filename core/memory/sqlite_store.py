"""Small shared SQLite context for short-lived mutable projections."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


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
