"""Tests for SessionTranscript — Tier 1 JSONL event stream."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from core.cli.transcript import SessionTranscript, cleanup_old_transcripts


@pytest.fixture()
def tx(tmp_path: Path) -> SessionTranscript:
    return SessionTranscript("s-test", transcript_dir=tmp_path / "transcripts")


class TestSessionTranscriptWrite:
    """Event recording and file structure."""

    def test_session_lifecycle(self, tx: SessionTranscript) -> None:
        tx.record_session_start(model="claude-opus-4-6")
        tx.record_user_message("analyze Berserk")
        tx.record_tool_call("analyze_ip", {"ip_name": "Berserk"})
        tx.record_tool_result("analyze_ip", "ok", "S-tier 81.3")
        tx.record_assistant_message("Berserk is S-tier.")
        tx.record_cost("claude-opus-4-6", 1200, 350, 0.015)
        tx.record_session_end(duration_s=20, total_cost=0.015, rounds=3)

        assert tx.file_path.exists()
        events = tx.read_events()
        assert len(events) == 7
        assert events[0]["event"] == "session_start"
        assert events[1]["event"] == "user_message"
        assert events[2]["event"] == "tool_call"
        assert events[3]["event"] == "tool_result"
        assert events[4]["event"] == "assistant_message"
        assert events[5]["event"] == "cost"
        assert events[6]["event"] == "session_end"

    def test_text_truncation(self, tx: SessionTranscript) -> None:
        long_text = "x" * 1000
        tx.record_user_message(long_text)
        events = tx.read_events()
        assert len(events[0]["text"]) <= 503  # 500 + "..."

    def test_tool_input_truncation(self, tx: SessionTranscript) -> None:
        long_input = {"data": "y" * 500}
        tx.record_tool_call("big_tool", long_input)
        events = tx.read_events()
        assert len(events[0]["input"]) <= 303

    def test_error_event(self, tx: SessionTranscript) -> None:
        tx.record_error("api_error", "Rate limit exceeded")
        events = tx.read_events()
        assert events[0]["event"] == "error"
        assert events[0]["type"] == "api_error"

    def test_subagent_events(self, tx: SessionTranscript) -> None:
        tx.record_subagent_start("task-1", "analyze")
        tx.record_subagent_complete("task-1", "ok", "Berserk S-tier")
        events = tx.read_events()
        assert events[0]["event"] == "subagent_start"
        assert events[1]["event"] == "subagent_complete"

    def test_vault_save_event(self, tx: SessionTranscript) -> None:
        tx.record_vault_save("vault/reports/berserk.md", "report")
        events = tx.read_events()
        assert events[0]["event"] == "vault_save"
        assert events[0]["path"] == "vault/reports/berserk.md"


class TestSessionTranscriptRead:
    """Event reading."""

    def test_read_empty(self, tx: SessionTranscript) -> None:
        assert tx.read_events() == []

    def test_read_with_limit(self, tx: SessionTranscript) -> None:
        for i in range(20):
            tx.record_user_message(f"msg {i}")
        events = tx.read_events(limit=5)
        assert len(events) == 5
        assert events[0]["text"] == "msg 15"


class TestSessionTranscriptIndex:
    """Session index management."""

    def test_index_updated_on_session_end(self, tx: SessionTranscript) -> None:
        tx.record_session_start()
        tx.record_session_end(rounds=2)

        index_path = tx.file_path.parent / "index.json"
        assert index_path.exists()
        data = json.loads(index_path.read_text())
        assert "s-test" in data["sessions"]
        assert data["sessions"]["s-test"]["event_count"] == 2


class TestCleanup:
    """Old transcript cleanup."""

    def test_cleanup_removes_old(self, tmp_path: Path) -> None:
        tdir = tmp_path / "transcripts"
        tdir.mkdir()

        # Create an old file
        old = tdir / "s-old.jsonl"
        old.write_text('{"event":"test"}\n')
        old_time = time.time() - (40 * 86400)  # 40 days ago
        import os

        os.utime(old, (old_time, old_time))

        # Create a recent file
        new = tdir / "s-new.jsonl"
        new.write_text('{"event":"test"}\n')

        removed = cleanup_old_transcripts(tdir, max_age_days=30)
        assert removed == 1
        assert not old.exists()
        assert new.exists()

    def test_cleanup_no_dir(self, tmp_path: Path) -> None:
        removed = cleanup_old_transcripts(tmp_path / "nope")
        assert removed == 0
