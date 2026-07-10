"""Tests for the remaining bounded scheduler JSONL tail."""

from __future__ import annotations

from pathlib import Path

from core.observability.run_log import JobRunLog


def test_append_reads_newest_first(tmp_path: Path) -> None:
    log = JobRunLog(tmp_path)
    log.append("job:1", {"seq": 1})
    log.append("job:1", {"seq": 2})
    assert log.get_runs("job:1") == [{"seq": 2}, {"seq": 1}]


def test_append_auto_prunes_with_live_bounds(tmp_path: Path) -> None:
    log = JobRunLog(tmp_path)
    log.MAX_BYTES = 100
    log.MAX_LINES = 3
    for index in range(20):
        log.append("job-1", {"seq": index, "padding": "x" * 50})

    assert [row["seq"] for row in log.get_runs("job-1", limit=99)] == [19, 18, 17]
    assert log.prune("job-1") == 0


def test_malformed_rows_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "job-1.jsonl"
    path.write_text('{"seq":1}\nnot-json\n{"seq":2}\n', encoding="utf-8")
    assert JobRunLog(tmp_path).get_runs("job-1") == [{"seq": 2}, {"seq": 1}]
