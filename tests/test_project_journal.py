"""Tests for ProjectJournal — C2 layer append-only execution record."""

from __future__ import annotations

import json

from core.memory.project_journal import ProjectJournal, RunRecord, _format_age


class TestRunRecord:
    def test_to_json_and_back(self):
        rec = RunRecord(
            ts=1710000000,
            session_id="s1",
            run_type="analysis",
            summary="Berserk S/81.3",
            cost_usd=0.15,
            duration_ms=12000,
            metadata={"tier": "S"},
        )
        line = rec.to_json()
        restored = RunRecord.from_json(line)
        assert restored.session_id == "s1"
        assert restored.summary == "Berserk S/81.3"
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
        journal.record_run("s1", "analysis", "Berserk S/81.3", cost_usd=0.15)
        journal.record_run("s2", "research", "AI trends", cost_usd=0.08)

        runs = journal.get_recent_runs(5)
        assert len(runs) == 2
        assert runs[0].summary == "Berserk S/81.3"
        assert runs[1].summary == "AI trends"

    def test_record_cost(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        journal.record_cost("claude-opus-4-6", 1200, 350, 0.015)
        journal.record_cost("gpt-5.4", 800, 200, 0.005)

        summary = journal.get_project_cost_summary()
        assert summary["total_calls"] == 2
        assert summary["total_cost"] > 0
        assert "claude-opus-4-6" in summary["by_model"]

    def test_add_learned_dedup(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        journal.add_learned("pattern A", "domain")
        journal.add_learned("pattern A", "domain")  # duplicate

        patterns = journal.get_learned_patterns()
        # Should have only 1 (dedup)
        matching = [p for p in patterns if "pattern A" in p]
        assert len(matching) == 1

    def test_add_learned_rotation(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        for i in range(120):
            journal.add_learned(f"pattern {i}", "test")

        patterns = journal.get_learned_patterns()
        assert len(patterns) <= 100
        # Most recent should be preserved
        assert any("pattern 119" in p for p in patterns)

    def test_record_error(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        journal.record_error("s1", "timeout", "API call timed out")

        errors_file = tmp_path / "journal" / "errors.jsonl"
        assert errors_file.exists()
        line = errors_file.read_text().strip()
        d = json.loads(line)
        assert d["type"] == "timeout"
        assert "timed out" in d["msg"]

    def test_get_context_summary(self, tmp_path):
        journal = ProjectJournal(tmp_path / "journal")
        journal.record_run("s1", "analysis", "Berserk S/81.3")
        journal.record_run("s2", "research", "AI trends report")

        summary = journal.get_context_summary()
        assert "Project history:" in summary
        assert "Berserk" in summary
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
    def test_pipeline_end_records_run(self, tmp_path):
        from core.memory.journal_hooks import make_journal_handlers
        from core.orchestration.hooks import HookEvent

        journal = ProjectJournal(tmp_path / "journal")
        handlers = make_journal_handlers(journal)
        assert len(handlers) == 3

        # Simulate PIPELINE_END
        end_handler = next(fn for name, fn in handlers if name == "journal_pipeline_end")
        end_handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
                "session_id": "test-s1",
            },
        )

        runs = journal.get_recent_runs(5)
        assert len(runs) == 1
        assert "Berserk" in runs[0].summary
        assert "S/81.3" in runs[0].summary

        # Should also add learned pattern
        patterns = journal.get_learned_patterns()
        assert any("Berserk" in p for p in patterns)

    def test_pipeline_error_records(self, tmp_path):
        from core.memory.journal_hooks import make_journal_handlers
        from core.orchestration.hooks import HookEvent

        journal = ProjectJournal(tmp_path / "journal")
        handlers = make_journal_handlers(journal)

        error_handler = next(fn for name, fn in handlers if name == "journal_pipeline_error")
        error_handler(
            HookEvent.PIPELINE_ERROR,
            {
                "ip_name": "Test",
                "error": "API timeout",
                "session_id": "test-s2",
            },
        )

        runs = journal.get_recent_runs(5)
        assert len(runs) == 1
        assert runs[0].status == "error"

    def test_wrong_event_ignored(self, tmp_path):
        from core.memory.journal_hooks import make_journal_handlers
        from core.orchestration.hooks import HookEvent

        journal = ProjectJournal(tmp_path / "journal")
        handlers = make_journal_handlers(journal)

        end_handler = next(fn for name, fn in handlers if name == "journal_pipeline_end")
        # Send wrong event type
        end_handler(HookEvent.NODE_ENTER, {"ip_name": "X"})
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
