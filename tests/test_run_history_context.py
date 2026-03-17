"""Tests for Run History Context Injection (Karpathy P6)."""

import time

from core.memory.context import ContextAssembler, _format_age
from core.orchestration.run_log import RunLog, RunLogEntry


class TestFormatAge:
    def test_now(self):
        assert _format_age(0) == "now"

    def test_negative(self):
        assert _format_age(-10) == "now"

    def test_seconds(self):
        assert _format_age(30) == "now"

    def test_minutes(self):
        assert _format_age(300) == "5m ago"

    def test_hours(self):
        assert _format_age(7200) == "2h ago"

    def test_days(self):
        assert _format_age(172800) == "2d ago"

    def test_one_minute(self):
        assert _format_age(60) == "1m ago"

    def test_one_hour(self):
        assert _format_age(3600) == "1h ago"

    def test_one_day(self):
        assert _format_age(86400) == "1d ago"


class TestRunHistoryInjection:
    def test_no_run_log_dir(self):
        """Without run_log_dir, no _run_history is injected."""
        assembler = ContextAssembler()
        ctx = assembler.assemble("sess-1", "Berserk")
        assert "_run_history" not in ctx

    def test_empty_run_log_dir(self, tmp_path):
        """Empty run_log_dir produces no _run_history."""
        log_dir = tmp_path / "runs"
        log_dir.mkdir()
        assembler = ContextAssembler(run_log_dir=log_dir)
        ctx = assembler.assemble("sess-1", "Berserk")
        assert "_run_history" not in ctx

    def test_nonexistent_run_log_dir(self, tmp_path):
        """Non-existent run_log_dir is handled gracefully."""
        assembler = ContextAssembler(run_log_dir=tmp_path / "no_such_dir")
        ctx = assembler.assemble("sess-1", "Berserk")
        assert "_run_history" not in ctx

    def test_injects_pipeline_end_entries(self, tmp_path):
        """Pipeline end entries are injected as 1-line summary."""
        log_dir = tmp_path / "runs"
        log_dir.mkdir()

        run_log = RunLog("ip_berserk_analysis", log_dir=log_dir)
        now = time.time()
        run_log.append(
            RunLogEntry(
                session_key="ip_berserk_analysis",
                event="pipeline_end",
                status="ok",
                timestamp=now - 3600,  # 1h ago
                metadata={"ip_name": "Berserk", "tier": "S", "score": 81.3},
            )
        )

        assembler = ContextAssembler(run_log_dir=log_dir)
        ctx = assembler.assemble("sess-1", "Berserk")

        assert "_run_history" in ctx
        assert "Berserk" in ctx["_run_history"]
        assert "S/81.3" in ctx["_run_history"]

    def test_max_entries_limit(self, tmp_path):
        """Only up to max_entries are injected."""
        log_dir = tmp_path / "runs"
        log_dir.mkdir()

        run_log = RunLog("ip_all_analysis", log_dir=log_dir)
        now = time.time()
        for i in range(5):
            run_log.append(
                RunLogEntry(
                    session_key="ip_all_analysis",
                    event="pipeline_end",
                    status="ok",
                    timestamp=now - (i * 3600),
                    metadata={"ip_name": f"IP_{i}", "tier": "A", "score": 60 + i},
                )
            )

        assembler = ContextAssembler(run_log_dir=log_dir)
        ctx = assembler.assemble("sess-1", "Test")
        history = ctx.get("_run_history", "")
        # Default max is 3, so we should see at most 3 entries
        assert history.count("|") <= 2  # 3 entries separated by 2 pipes

    def test_non_pipeline_end_events_excluded(self, tmp_path):
        """Only pipeline_end events are injected, not start or node events."""
        log_dir = tmp_path / "runs"
        log_dir.mkdir()

        run_log = RunLog("ip_test_analysis", log_dir=log_dir)
        now = time.time()
        run_log.append(
            RunLogEntry(
                session_key="ip_test_analysis",
                event="pipeline_start",
                status="ok",
                timestamp=now - 1800,
                metadata={"ip_name": "Test"},
            )
        )
        run_log.append(
            RunLogEntry(
                session_key="ip_test_analysis",
                event="node_exit",
                node="router",
                status="ok",
                timestamp=now - 1700,
                metadata={"ip_name": "Test"},
            )
        )

        assembler = ContextAssembler(run_log_dir=log_dir)
        ctx = assembler.assemble("sess-1", "Test")
        assert "_run_history" not in ctx

    def test_multiple_log_files(self, tmp_path):
        """Entries from multiple JSONL files are merged."""
        log_dir = tmp_path / "runs"
        log_dir.mkdir()

        now = time.time()
        log1 = RunLog("ip_berserk_analysis", log_dir=log_dir)
        log1.append(
            RunLogEntry(
                session_key="ip_berserk_analysis",
                event="pipeline_end",
                timestamp=now - 3600,
                metadata={"ip_name": "Berserk", "tier": "S", "score": 81.3},
            )
        )
        log2 = RunLog("ip_cowboy_bebop_analysis", log_dir=log_dir)
        log2.append(
            RunLogEntry(
                session_key="ip_cowboy_bebop_analysis",
                event="pipeline_end",
                timestamp=now - 7200,
                metadata={"ip_name": "Cowboy Bebop", "tier": "A", "score": 68.4},
            )
        )

        assembler = ContextAssembler(run_log_dir=log_dir)
        ctx = assembler.assemble("sess-1", "Test")
        history = ctx["_run_history"]
        assert "Berserk" in history
        assert "Cowboy Bebop" in history

    def test_sorted_by_most_recent(self, tmp_path):
        """Entries are sorted newest first."""
        log_dir = tmp_path / "runs"
        log_dir.mkdir()

        now = time.time()
        run_log = RunLog("ip_mixed_analysis", log_dir=log_dir)
        run_log.append(
            RunLogEntry(
                session_key="ip_mixed_analysis",
                event="pipeline_end",
                timestamp=now - 86400,  # 1d ago
                metadata={"ip_name": "Old", "tier": "C", "score": 30.0},
            )
        )
        run_log.append(
            RunLogEntry(
                session_key="ip_mixed_analysis",
                event="pipeline_end",
                timestamp=now - 60,  # 1m ago
                metadata={"ip_name": "Recent", "tier": "S", "score": 90.0},
            )
        )

        assembler = ContextAssembler(run_log_dir=log_dir)
        ctx = assembler.assemble("sess-1", "Test")
        history = ctx["_run_history"]
        # Recent should appear before Old
        assert history.index("Recent") < history.index("Old")
