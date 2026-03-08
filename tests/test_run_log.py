"""Tests for JSONL Run Log with auto-pruning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geode.orchestration.run_log import RunLog, RunLogEntry


@pytest.fixture
def tmp_log_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs"


class TestRunLogEntry:
    def test_to_json(self):
        entry = RunLogEntry(
            session_key="ip:berserk:router",
            event="pipeline_start",
            node="router",
        )
        raw = entry.to_json()
        data = json.loads(raw)
        assert data["session_key"] == "ip:berserk:router"
        assert data["event"] == "pipeline_start"
        assert data["status"] == "ok"

    def test_from_json_roundtrip(self):
        original = RunLogEntry(
            session_key="ip:test:analysis",
            event="node_exit",
            node="router",
            duration_ms=123.4,
            metadata={"ip_name": "test"},
        )
        raw = original.to_json()
        restored = RunLogEntry.from_json(raw)
        assert restored.session_key == original.session_key
        assert restored.event == original.event
        assert restored.duration_ms == original.duration_ms

    def test_default_status_ok(self):
        entry = RunLogEntry(session_key="x", event="y")
        assert entry.status == "ok"

    def test_timestamp_auto_set(self):
        entry = RunLogEntry(session_key="x", event="y")
        assert entry.timestamp > 0


class TestRunLog:
    def test_append_and_read(self, tmp_log_dir: Path):
        log = RunLog("ip:berserk:full", log_dir=tmp_log_dir)
        log.append(RunLogEntry(session_key="ip:berserk:full", event="start"))
        log.append(RunLogEntry(session_key="ip:berserk:full", event="end"))

        entries = log.read(limit=10)
        assert len(entries) == 2
        # Newest first
        assert entries[0].event == "end"
        assert entries[1].event == "start"

    def test_read_empty_log(self, tmp_log_dir: Path):
        log = RunLog("nonexistent", log_dir=tmp_log_dir)
        assert log.read() == []

    def test_read_with_limit(self, tmp_log_dir: Path):
        log = RunLog("ip:test:full", log_dir=tmp_log_dir)
        for i in range(10):
            log.append(RunLogEntry(session_key="ip:test:full", event=f"event_{i}"))

        entries = log.read(limit=3)
        assert len(entries) == 3
        assert entries[0].event == "event_9"

    def test_read_with_offset(self, tmp_log_dir: Path):
        log = RunLog("ip:test:full", log_dir=tmp_log_dir)
        for i in range(5):
            log.append(RunLogEntry(session_key="ip:test:full", event=f"event_{i}"))

        entries = log.read(limit=2, offset=2)
        assert len(entries) == 2
        assert entries[0].event == "event_2"

    def test_count(self, tmp_log_dir: Path):
        log = RunLog("ip:test:count", log_dir=tmp_log_dir)
        assert log.count() == 0

        log.append(RunLogEntry(session_key="x", event="a"))
        log.append(RunLogEntry(session_key="x", event="b"))
        assert log.count() == 2

    def test_clear(self, tmp_log_dir: Path):
        log = RunLog("ip:test:clear", log_dir=tmp_log_dir)
        log.append(RunLogEntry(session_key="x", event="a"))
        assert log.count() == 1

        log.clear()
        assert log.count() == 0
        assert not log.file_path.exists()

    def test_prune_under_limit_noop(self, tmp_log_dir: Path):
        log = RunLog("ip:test:prune", log_dir=tmp_log_dir, max_bytes=1024 * 1024)
        log.append(RunLogEntry(session_key="x", event="a"))
        removed = log.prune()
        assert removed == 0

    def test_prune_over_limit(self, tmp_log_dir: Path):
        # Very small max_bytes to trigger pruning
        log = RunLog("ip:test:prune2", log_dir=tmp_log_dir, max_bytes=100, keep_lines=3)
        for i in range(20):
            log.append(
                RunLogEntry(
                    session_key="ip:test:prune2",
                    event=f"event_{i}",
                    metadata={"padding": "x" * 50},
                )
            )

        removed = log.prune()
        assert removed > 0
        assert log.count() == 3

    def test_prune_uses_atomic_write(self, tmp_log_dir: Path):
        log = RunLog("ip:test:atomic", log_dir=tmp_log_dir, max_bytes=100, keep_lines=2)
        for i in range(10):
            log.append(
                RunLogEntry(
                    session_key="ip:test:atomic",
                    event=f"event_{i}",
                    metadata={"padding": "x" * 50},
                )
            )

        # Tmp file should not exist after prune
        tmp_file = log.file_path.with_suffix(".jsonl.tmp")
        log.prune()
        assert not tmp_file.exists()
        assert log.file_path.exists()

    def test_file_path_sanitized(self, tmp_log_dir: Path):
        log = RunLog("ip:berserk:full_pipeline", log_dir=tmp_log_dir)
        assert log.file_path.name == "ip_berserk_full_pipeline.jsonl"

    def test_creates_directory(self, tmp_log_dir: Path):
        nested = tmp_log_dir / "deep" / "nested"
        log = RunLog("ip:test:dir", log_dir=nested)
        log.append(RunLogEntry(session_key="x", event="y"))
        assert nested.exists()
