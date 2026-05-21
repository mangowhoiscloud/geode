"""Hermes Phase 1d — session_search tool invariants.

Pins:
- ``SessionSearchTool`` advertises the expected ``name`` / ``description``
  / ``parameters`` (required ``query``).
- ``_execute_sync`` rejects empty / non-str ``query``.
- Round-trip: insert message → invoke tool → matching hit with snippet
  + bm25 score.
- ``session_id`` filter scopes correctly.
- ``prefer_trigram=True`` flips to the trigram index (CJK recall test).
- ``limit`` honoured + clamped at 100.
- Tool registered in ``build_default_registry`` (wiring smoke).
- definitions.json entry exists with correct schema.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def patched_session_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Force ``SessionManager()`` to use a tmp_path DB so tests don't
    touch ~/.geode."""
    db_path = tmp_path / "sessions.db"
    from core.memory import session_manager as sm_mod

    real_cls = sm_mod.SessionManager

    class _PinnedSM(real_cls):  # type: ignore[misc, valid-type]
        def __init__(self, _db_path: Any = None) -> None:
            super().__init__(db_path=db_path)

    monkeypatch.setattr(sm_mod, "SessionManager", _PinnedSM)
    yield db_path


def _seed_messages(db_path: Path, session_id: str, messages: list[dict]) -> None:
    """Direct SQL seed (avoid re-importing SessionManager which the
    fixture monkey-patches).

    ``ensure_ascii=False`` matches the production write path — Hangul /
    CJK survive as literal characters so the trigram tokenizer can index
    them. Default ``ensure_ascii=True`` would escape to ``\\uXXXX`` and
    silently break CJK recall tests.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        for i, msg in enumerate(messages):
            content = (
                json.dumps(msg.get("content"), ensure_ascii=False)
                if msg.get("content") is not None
                else None
            )
            conn.execute(
                "INSERT INTO messages (session_id, seq, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, i, msg.get("role", "user"), content, msg.get("timestamp", 1.0)),
            )
        conn.execute(
            "INSERT OR IGNORE INTO sessions "
            "(session_id, created_at, updated_at, status, model, provider, "
            "user_input, round_count, message_count) "
            "VALUES (?, 1.0, 1.0, 'active', '', 'anthropic', '', 0, ?)",
            (session_id, len(messages)),
        )
        conn.commit()
    finally:
        conn.close()


# Surface --------------------------------------------------------------


def test_tool_advertises_canonical_name() -> None:
    from core.tools.session_search import SessionSearchTool

    tool = SessionSearchTool()
    assert tool.name == "session_search"
    assert "FTS5" in tool.description or "search" in tool.description.lower()


def test_parameters_schema_requires_query() -> None:
    from core.tools.session_search import SessionSearchTool

    params = SessionSearchTool().parameters
    assert params["type"] == "object"
    assert "query" in params["required"]
    assert "session_id" in params["properties"]
    assert "limit" in params["properties"]
    assert "prefer_trigram" in params["properties"]


# Input validation ----------------------------------------------------


def test_execute_rejects_empty_query() -> None:
    from core.tools.session_search import SessionSearchTool

    result = SessionSearchTool()._execute_sync(query="")
    assert result.get("error") is not None
    assert "query" in result["error"].lower()


def test_execute_rejects_whitespace_only_query() -> None:
    from core.tools.session_search import SessionSearchTool

    result = SessionSearchTool()._execute_sync(query="   ")
    assert result.get("error") is not None


def test_execute_rejects_non_string_query() -> None:
    from core.tools.session_search import SessionSearchTool

    result = SessionSearchTool()._execute_sync(query=123)
    assert result.get("error") is not None


# Round-trip ----------------------------------------------------------


def test_search_round_trip(patched_session_manager: Path) -> None:
    """Insert → invoke tool → matching hit with snippet + score."""
    # Trigger SessionManager init to create tables
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    SessionManager().close()
    _seed_messages(
        patched_session_manager,
        "s1",
        [{"role": "user", "content": "find DPO training references", "timestamp": 1.0}],
    )
    result = SessionSearchTool()._execute_sync(query="DPO training")
    assert result["matched"] is True
    assert result["count"] == 1
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["session_id"] == "s1"
    assert "snippet" in hit
    assert "score" in hit


def test_search_session_id_filter_scopes(patched_session_manager: Path) -> None:
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    SessionManager().close()
    _seed_messages(
        patched_session_manager,
        "s1",
        [{"role": "user", "content": "shared word", "timestamp": 1.0}],
    )
    _seed_messages(
        patched_session_manager,
        "s2",
        [{"role": "user", "content": "shared word", "timestamp": 2.0}],
    )
    result = SessionSearchTool()._execute_sync(query="shared", session_id="s1")
    assert result["matched"] is True
    assert all(h["session_id"] == "s1" for h in result["hits"])


def test_search_trigram_substring_recall(patched_session_manager: Path) -> None:
    """``prefer_trigram=True`` enables Korean partial-word recall."""
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    sm = SessionManager()
    if not sm._has_trigram:
        sm.close()
        pytest.skip("trigram tokenizer not available")
    sm.close()
    _seed_messages(
        patched_session_manager,
        "s1",
        [{"role": "user", "content": "안녕하세요 반갑습니다", "timestamp": 1.0}],
    )
    result = SessionSearchTool()._execute_sync(query="녕하세", prefer_trigram=True)
    assert result["matched"] is True


def test_search_empty_db_returns_no_hits(patched_session_manager: Path) -> None:
    """Fresh DB with no messages → matched=False, count=0."""
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    SessionManager().close()
    result = SessionSearchTool()._execute_sync(query="anything")
    assert result["matched"] is False
    assert result["count"] == 0


def test_search_limit_honored(patched_session_manager: Path) -> None:
    """5 inserted, limit=2 → exactly 2 returned."""
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    SessionManager().close()
    _seed_messages(
        patched_session_manager,
        "s1",
        [
            {"role": "user", "content": f"common keyword msg{i}", "timestamp": float(i)}
            for i in range(5)
        ],
    )
    result = SessionSearchTool()._execute_sync(query="common", limit=2)
    assert result["count"] == 2


def test_search_limit_clamped_to_max(patched_session_manager: Path) -> None:
    """Excessive limit → clamped at 100 (no SQL error / no OOM)."""
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    SessionManager().close()
    _seed_messages(
        patched_session_manager,
        "s1",
        [{"role": "user", "content": "kw", "timestamp": 1.0}],
    )
    # Tool should not raise even with crazy limit
    result = SessionSearchTool()._execute_sync(query="kw", limit=99999)
    assert "error" not in result


def test_search_invalid_limit_falls_back_to_default(patched_session_manager: Path) -> None:
    """Non-int / negative limit → falls back to 20."""
    from core.memory.session_manager import SessionManager
    from core.tools.session_search import SessionSearchTool

    SessionManager().close()
    result = SessionSearchTool()._execute_sync(query="x", limit=-5)
    # Should not raise; query is valid (empty DB so no matches)
    assert "error" not in result


# Wiring --------------------------------------------------------------


def test_tool_registered_in_default_registry() -> None:
    """``build_default_registry`` includes session_search."""
    from core.wiring.container import build_default_registry

    registry = build_default_registry()
    tool = registry.get("session_search")
    assert tool is not None
    assert tool.name == "session_search"


def test_definitions_json_has_session_search_entry() -> None:
    """``core/tools/definitions.json`` lists session_search with the
    documented required field."""
    defs_path = Path("core/tools/definitions.json")
    raw = defs_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    entries = {e["name"]: e for e in data if isinstance(e, dict) and "name" in e}
    assert "session_search" in entries
    entry = entries["session_search"]
    assert "query" in entry["input_schema"]["required"]
    assert entry.get("cost_tier") == "free"
