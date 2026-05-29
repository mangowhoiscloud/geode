"""Tests for SessionTranscript — Tier 1 JSONL event stream."""

from __future__ import annotations

import json
import time

from core.observability.transcript import (
    MAX_BODY_CHARS,
    MAX_INPUT_CHARS,
    MAX_PREVIEW_CHARS,
    SessionTranscript,
    _truncate,
    cleanup_old_transcripts,
)


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        result = _truncate("a" * 600, 500)
        assert len(result) == 500
        assert result.endswith("...")

    def test_exact_limit(self):
        assert _truncate("a" * 500, 500) == "a" * 500


class TestSessionTranscript:
    def test_record_session_lifecycle(self, tmp_path):
        tx = SessionTranscript("s-test1", tmp_path / "transcripts")
        tx.record_session_start(model="claude-opus-4-6")
        tx.record_user_message("hello world")
        tx.record_assistant_message("hi there")
        tx.record_session_end(duration_s=5.0, total_cost=0.01, rounds=1)

        events = tx.read_events()
        assert len(events) == 4
        assert events[0]["event"] == "session_start"
        assert events[1]["event"] == "user_message"
        assert events[1]["text"] == "hello world"
        assert events[2]["event"] == "assistant_message"
        assert events[3]["event"] == "session_end"
        assert events[3]["rounds"] == 1

    def test_record_tool_call_and_result(self, tmp_path):
        tx = SessionTranscript("s-test2", tmp_path / "transcripts")
        tx.record_tool_call("web_fetch", {"url": "https://example.com"})
        tx.record_tool_result("web_fetch", "ok", "page content here")

        events = tx.read_events()
        assert len(events) == 2
        assert events[0]["event"] == "tool_call"
        assert events[0]["tool"] == "web_fetch"
        assert events[1]["event"] == "tool_result"
        assert events[1]["status"] == "ok"

    def test_record_vault_save(self, tmp_path):
        tx = SessionTranscript("s-test3", tmp_path / "transcripts")
        tx.record_vault_save("vault/profile/report.md", "profile")

        events = tx.read_events()
        assert len(events) == 1
        assert events[0]["event"] == "vault_save"
        assert events[0]["category"] == "profile"

    def test_record_cost(self, tmp_path):
        tx = SessionTranscript("s-test4", tmp_path / "transcripts")
        tx.record_cost("claude-opus-4-6", 1200, 350, 0.015)

        events = tx.read_events()
        assert len(events) == 1
        assert events[0]["event"] == "cost"
        assert events[0]["model"] == "claude-opus-4-6"
        assert events[0]["cost"] == 0.015

    def test_record_error(self, tmp_path):
        tx = SessionTranscript("s-test5", tmp_path / "transcripts")
        tx.record_error("timeout", "API call timed out after 30s")

        events = tx.read_events()
        assert len(events) == 1
        assert events[0]["event"] == "error"
        assert events[0]["type"] == "timeout"

    def test_record_subagent(self, tmp_path):
        tx = SessionTranscript("s-test6", tmp_path / "transcripts")
        tx.record_subagent_start("task-1", "research")
        tx.record_subagent_complete("task-1", "ok", "found 3 results")

        events = tx.read_events()
        assert len(events) == 2
        assert events[0]["event"] == "subagent_start"
        assert events[1]["event"] == "subagent_complete"

    def test_body_captured_in_full(self, tmp_path):
        # PR-TRANSCRIPT-FULL-BODY — the dialogue.jsonl turn body is NO LONGER
        # capped at the old 500 preview limit; a real-size turn is kept whole.
        tx = SessionTranscript("s-trunc", tmp_path / "transcripts")
        long_text = "x" * 1000
        tx.record_user_message(long_text)

        events = tx.read_events()
        assert events[0]["text"] == long_text  # full body, not a 500-char fragment

    def test_body_capped_at_ceiling(self, tmp_path):
        # The only bound on a single turn is the MAX_BODY_CHARS sanity ceiling
        # (so one pathological turn cannot dwarf the 5MB file guard).
        tx = SessionTranscript("s-trunc-ceiling", tmp_path / "transcripts")
        tx.record_assistant_message("y" * (MAX_BODY_CHARS + 5000))

        events = tx.read_events()
        assert len(events[0]["text"]) == MAX_BODY_CHARS
        assert events[0]["text"].endswith("...")

    def test_pipeline_preview_stays_short(self, tmp_path):
        # The split the mirror always documented: the FULL body lands in
        # dialogue.jsonl, only a short PREVIEW is lifted into the pipeline
        # timeline (RunTranscript). Pinned so a future edit can't re-truncate
        # the body or let the preview balloon.
        import json

        from core.observability.run_dir import run_dir_scope
        from core.self_improving_loop.run_transcript import (
            RunTranscript,
            run_transcript_scope,
        )

        long_text = "z" * 4000
        run_path = tmp_path / "transcript.jsonl"
        with run_dir_scope(str(tmp_path)):
            journal = RunTranscript(
                session_id="s-mirror",
                gen_tag="gen1",
                component="seed-generation",
                path=run_path,
            )
            with run_transcript_scope(journal):
                tx = SessionTranscript("s-mirror", tmp_path / "transcripts")
                tx.record_assistant_message(long_text)

        # dialogue.jsonl body is full…
        assert tx.read_events()[0]["text"] == long_text
        # …but the mirrored pipeline-timeline row is a short preview.
        rows = [json.loads(ln) for ln in run_path.read_text().splitlines() if ln.strip()]
        mirror = next(r for r in rows if r.get("action") == "agent.assistant_message")
        assert len(mirror["payload"]["text"]) <= MAX_PREVIEW_CHARS

    def test_input_truncation(self, tmp_path):
        tx = SessionTranscript("s-trunc2", tmp_path / "transcripts")
        long_input = {"data": "y" * 1000}
        tx.record_tool_call("test_tool", long_input)

        events = tx.read_events()
        assert len(events[0]["input"]) <= MAX_INPUT_CHARS

    def test_event_count(self, tmp_path):
        tx = SessionTranscript("s-count", tmp_path / "transcripts")
        assert tx.event_count == 0
        tx.record_user_message("a")
        tx.record_user_message("b")
        assert tx.event_count == 2

    def test_read_events_limit(self, tmp_path):
        tx = SessionTranscript("s-limit", tmp_path / "transcripts")
        for i in range(20):
            tx.record_user_message(f"msg {i}")

        events = tx.read_events(limit=5)
        assert len(events) == 5
        # Should be most recent 5
        assert events[-1]["text"] == "msg 19"

    def test_read_empty_transcript(self, tmp_path):
        tx = SessionTranscript("s-empty", tmp_path / "transcripts")
        assert tx.read_events() == []

    def test_timestamps_present(self, tmp_path):
        tx = SessionTranscript("s-ts", tmp_path / "transcripts")
        tx.record_user_message("test")

        events = tx.read_events()
        assert "ts" in events[0]
        assert isinstance(events[0]["ts"], float)

    def test_session_index_updated(self, tmp_path):
        tx = SessionTranscript("s-idx", tmp_path / "transcripts")
        tx.record_session_start()
        tx.record_user_message("test")
        tx.record_session_end()

        index_path = tmp_path / "transcripts" / "index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert "s-idx" in index["sessions"]
        assert index["sessions"]["s-idx"]["event_count"] == 3

    def test_file_path(self, tmp_path):
        tx = SessionTranscript("s-path", tmp_path / "transcripts")
        assert tx.file_path == tmp_path / "transcripts" / "s-path.jsonl"


class TestCleanupOldTranscripts:
    def test_removes_old_files(self, tmp_path):
        tdir = tmp_path / "transcripts"
        tdir.mkdir()
        # Create old file
        old_file = tdir / "old-session.jsonl"
        old_file.write_text('{"event":"test"}\n')
        # Backdate modification time
        import os

        old_time = time.time() - 40 * 86400  # 40 days ago
        os.utime(old_file, (old_time, old_time))

        # Create recent file
        recent_file = tdir / "recent-session.jsonl"
        recent_file.write_text('{"event":"test"}\n')

        removed = cleanup_old_transcripts(tdir, max_age_days=30)
        assert removed == 1
        assert not old_file.exists()
        assert recent_file.exists()

    def test_no_op_on_empty_dir(self, tmp_path):
        assert cleanup_old_transcripts(tmp_path / "nonexistent") == 0
