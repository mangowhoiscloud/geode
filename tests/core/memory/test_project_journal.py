"""Tests for ProjectJournal — C2 layer append-only execution record."""

from __future__ import annotations

import json

from core.memory.project_journal import ProjectJournal, RunRecord
from core.time_format import format_age as _format_age


class TestRunRecord:
    def test_to_json_and_back(self):
        rec = RunRecord(
            ts=1710000000,
            session_id="s1",
            run_type="analysis",
            summary="Project Atlas S/81.3",
            cost_usd=0.15,
            duration_ms=12000,
            metadata={"tier": "S"},
        )
        line = rec.to_json()
        restored = RunRecord.from_json(line)
        assert restored.session_id == "s1"
        assert restored.summary == "Project Atlas S/81.3"
        assert restored.cost_usd == 0.15
        assert restored.metadata["tier"] == "S"

    def test_minimal_record(self):
        rec = RunRecord(ts=0, session_id="", run_type="chat", summary="hello")
        line = rec.to_json()
        d = json.loads(line)
        assert "cost" not in d  # zero cost omitted
        assert "dur_ms" not in d  # zero duration omitted


class TestProjectJournal:
    def test_record_and_get_runs(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        journal.record_run("s1", "analysis", "Project Atlas S/81.3", cost_usd=0.15)
        journal.record_run("s2", "research", "AI trends", cost_usd=0.08)

        runs = journal.get_recent_runs(5)
        assert len(runs) == 2
        assert runs[0].summary == "Project Atlas S/81.3"
        assert runs[1].summary == "AI trends"

    def test_reads_historical_learned_patterns_without_rewriting(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        learned_path = journal_dir / "learned.md"
        original = b"- [domain] historical pattern (2026-08-01)\n"
        learned_path.write_bytes(original)

        patterns = ProjectJournal(journal_dir).get_learned_patterns()

        assert patterns == ["- [domain] historical pattern (2026-08-01)"]
        assert learned_path.read_bytes() == original

    def test_get_context_summary(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        journal.record_run("s1", "analysis", "Project Atlas S/81.3")
        journal.record_run("s2", "research", "AI trends report")

        summary = journal.get_context_summary()
        assert "Project history:" in summary
        assert "Project Atlas" in summary
        assert "AI trends" in summary

    def test_get_context_summary_empty(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        assert journal.get_context_summary() == ""

    def test_ensure_structure(self, tmp_path):
        journal = ProjectJournal(tmp_path / "new_journal")
        assert not (tmp_path / "new_journal").exists()
        journal.ensure_structure()
        assert (tmp_path / "new_journal").exists()

    def test_get_recent_runs_limit(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        for i in range(10):
            journal.record_run(f"s{i}", "chat", f"chat {i}")

        runs = journal.get_recent_runs(3)
        assert len(runs) == 3
        # Should be most recent 3
        assert runs[-1].summary == "chat 9"


class TestJournalHooks:
    def test_handler_set_is_subagent_lifecycle_only(self, tmp_path):
        from core.memory.journal_hooks import make_journal_handlers

        journal = ProjectJournal(tmp_path / "journal")
        handlers = make_journal_handlers(journal)
        # PR-DEAD-PIPELINE — subagent lifecycle only (3 = subagent_completed
        # + subagent_started + subagent_failed).
        assert len(handlers) == 3

    def test_wrong_event_ignored(self, tmp_path):
        from core.hooks import HookEvent
        from core.memory.journal_hooks import make_journal_handlers

        journal = ProjectJournal(tmp_path / "journal")
        handlers = make_journal_handlers(journal)

        sub_handler = next(fn for name, fn in handlers if name == "journal_subagent")
        # Send wrong event type
        sub_handler(HookEvent.SESSION_STARTED, {"task_id": "demo-task"})
        assert journal.get_recent_runs(5) == []


class TestFormatAge:
    def test_now(self):
        assert _format_age(30) == "now"

    def test_minutes(self):
        assert _format_age(300) == "5m ago"

    def test_hours(self):
        assert _format_age(7200) == "2h ago"

    def test_days(self):
        assert _format_age(172800) == "2d ago"
