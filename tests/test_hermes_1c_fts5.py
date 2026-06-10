"""Hermes Phase 1c — FTS5 + trigram index invariants.

Pins:
- ``sanitize_fts5_query`` wraps non-alnum tokens in escaped double quotes
  and strips pure-metachar tokens; empty input → ``""``.
- ``has_trigram_support`` returns ``True`` on the test runner's SQLite
  build (modern CI ships 3.34+).
- ``SessionManager`` creates ``messages_fts`` + 3 triggers (insert /
  delete / update). On trigram-capable builds it also creates
  ``messages_fts_trigram`` + its 3 triggers.
- Triggers keep FTS in sync — inserting a message indexes it; deleting
  removes the index row; updating reindexes.
- ``search_messages`` returns hits via FTS5 ``MATCH`` with snippet +
  bm25 score; ``session_id`` filter scopes correctly; ``prefer_trigram``
  flips to the trigram index when available.
- Korean partial-word recall via the trigram index.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

# fts_query ---------------------------------------------------------------


def test_sanitize_empty_returns_empty() -> None:
    from core.memory.fts_query import sanitize_fts5_query

    assert sanitize_fts5_query("") == ""


def test_sanitize_passes_bare_alnum_tokens() -> None:
    from core.memory.fts_query import sanitize_fts5_query

    assert sanitize_fts5_query("hello world") == "hello world"


def test_sanitize_wraps_hyphenated_token() -> None:
    """``file-not-found`` would be parsed as ``file NOT not NOT found`` —
    must be wrapped."""
    from core.memory.fts_query import sanitize_fts5_query

    out = sanitize_fts5_query("file-not-found")
    assert out == '"file-not-found"'


def test_sanitize_wraps_dotted_token() -> None:
    """Version strings like ``v3.34`` get token-split otherwise."""
    from core.memory.fts_query import sanitize_fts5_query

    out = sanitize_fts5_query("v3.34")
    assert out == '"v3.34"'


def test_sanitize_escapes_internal_double_quote() -> None:
    from core.memory.fts_query import sanitize_fts5_query

    out = sanitize_fts5_query('she said "hi"')
    assert '""hi""' in out


def test_sanitize_drops_pure_meta_token() -> None:
    """Bare ``-`` after splitting must NOT survive (would mean NOT)."""
    from core.memory.fts_query import sanitize_fts5_query

    assert sanitize_fts5_query("foo - bar") == "foo bar"


def test_sanitize_keeps_unicode_letters_bare() -> None:
    """Non-ASCII letters / digits should NOT trigger quote-wrapping —
    that would defeat the unicode61 tokenizer."""
    from core.memory.fts_query import sanitize_fts5_query

    out = sanitize_fts5_query("안녕하세요 セッション")
    assert out == "안녕하세요 セッション"


# Capability probe ----------------------------------------------------------


def test_has_trigram_support_on_modern_sqlite() -> None:
    """SQLite 3.34+ ships trigram; the test runner is modern enough."""
    from core.memory.fts_query import has_trigram_support

    conn = sqlite3.connect(":memory:")
    try:
        assert has_trigram_support(conn) is True
    finally:
        conn.close()


def test_has_trigram_support_graceful_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If ``execute`` raises, the probe returns False — caller still works."""
    from core.memory.fts_query import has_trigram_support

    class _BadConn:
        def execute(self, *_a: object, **_kw: object) -> None:
            raise sqlite3.OperationalError("trigram not supported")

    assert has_trigram_support(_BadConn()) is False  # type: ignore[arg-type]


# SessionManager FTS wiring -------------------------------------------------


@pytest.fixture
def sm(tmp_path: Path) -> Iterator:
    """Fresh SessionManager with a temp DB."""
    from core.memory.session_manager import SessionManager

    mgr = SessionManager(db_path=tmp_path / "sessions.db")
    try:
        yield mgr
    finally:
        mgr.close()


def _seed_session_with_messages(sm: object, session_id: str, messages: list[dict]) -> None:
    """Helper: create a session row + insert messages via the mirror API."""
    from core.memory.session_manager import SessionMeta

    sm.upsert(  # type: ignore[attr-defined]
        SessionMeta(
            session_id=session_id,
            created_at=1.0,
            updated_at=1.0,
            status="active",
            model="",
            provider="anthropic",
            user_input="",
            round_count=0,
            message_count=len(messages),
        )
    )
    sm.upsert_messages(session_id, messages)  # type: ignore[attr-defined]


def test_fts_tables_created(sm: object) -> None:
    """Both unicode + trigram FTS tables exist after __init__."""
    rows = sm._conn.execute(  # type: ignore[attr-defined]
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('messages_fts', 'messages_fts_trigram')"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "messages_fts" in names
    # trigram may or may not exist depending on SQLite build
    if sm._has_trigram:  # type: ignore[attr-defined]
        assert "messages_fts_trigram" in names


def test_fts_triggers_created(sm: object) -> None:
    """3 triggers per FTS table (insert + delete + update)."""
    rows = sm._conn.execute(  # type: ignore[attr-defined]
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'messages_fts%'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "messages_fts_after_insert" in names
    assert "messages_fts_after_delete" in names
    assert "messages_fts_after_update" in names


def test_insert_indexes_message(sm: object) -> None:
    """Inserting via ``upsert_messages`` populates the FTS table."""
    _seed_session_with_messages(
        sm,
        "s1",
        [{"role": "user", "content": "find DPO training references", "timestamp": 1.0}],
    )
    count = sm._conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]  # type: ignore[attr-defined]
    assert count == 1


def test_search_finds_inserted_message(sm: object) -> None:
    """Round-trip: insert → search → match."""
    _seed_session_with_messages(
        sm,
        "s1",
        [{"role": "user", "content": "find DPO training references", "timestamp": 1.0}],
    )
    hits = sm.search_messages("DPO training")  # type: ignore[attr-defined]
    assert len(hits) == 1
    assert hits[0]["session_id"] == "s1"
    assert "snippet" in hits[0]
    assert "DPO" in hits[0]["snippet"] or "training" in hits[0]["snippet"]


def test_search_session_id_filter_scopes(sm: object) -> None:
    """``session_id=`` restricts to that session only."""
    _seed_session_with_messages(
        sm, "s1", [{"role": "user", "content": "shared word", "timestamp": 1.0}]
    )
    _seed_session_with_messages(
        sm, "s2", [{"role": "user", "content": "shared word", "timestamp": 2.0}]
    )
    s1_hits = sm.search_messages("shared", session_id="s1")  # type: ignore[attr-defined]
    assert len(s1_hits) == 1
    assert s1_hits[0]["session_id"] == "s1"


def test_search_empty_query_returns_empty(sm: object) -> None:
    """Empty / pure-meta query → empty list, no SQL error."""
    assert sm.search_messages("") == []  # type: ignore[attr-defined]
    assert sm.search_messages("---") == []  # type: ignore[attr-defined]


def test_search_hyphenated_query_via_sanitizer(sm: object) -> None:
    """``file-not-found`` query works thanks to the sanitiser."""
    _seed_session_with_messages(
        sm,
        "s1",
        [{"role": "user", "content": "got file-not-found error", "timestamp": 1.0}],
    )
    hits = sm.search_messages("file-not-found")  # type: ignore[attr-defined]
    assert len(hits) == 1


def test_search_trigram_substring_recall(sm: object) -> None:
    """Trigram index recalls partial words (Korean / fragments)."""
    if not sm._has_trigram:  # type: ignore[attr-defined]
        pytest.skip("trigram tokenizer not available on this SQLite build")
    _seed_session_with_messages(
        sm,
        "s1",
        [{"role": "user", "content": "안녕하세요 반갑습니다", "timestamp": 1.0}],
    )
    hits = sm.search_messages("녕하세", prefer_trigram=True)  # type: ignore[attr-defined]
    assert len(hits) >= 1


def test_delete_message_removes_from_index(sm: object) -> None:
    """``delete_messages`` cascades through the FTS delete trigger."""
    _seed_session_with_messages(
        sm, "s1", [{"role": "user", "content": "ephemeral note", "timestamp": 1.0}]
    )
    assert sm._conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 1  # type: ignore[attr-defined]
    sm.delete_messages("s1")  # type: ignore[attr-defined]
    assert sm._conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 0  # type: ignore[attr-defined]
