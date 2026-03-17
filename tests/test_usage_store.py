"""Tests for UsageStore -- persistent LLM cost tracking."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest
from core.llm.usage_store import UsageRecord, UsageStore, get_usage_store, reset_usage_store


class TestUsageRecord:
    """Tests for UsageRecord data class."""

    def test_to_json_basic(self):
        rec = UsageRecord(
            ts=1710000000.0,
            model="claude-opus-4-6",
            input_tokens=1200,
            output_tokens=350,
            cost_usd=0.0148,
        )
        j = rec.to_json()
        data = json.loads(j)
        assert data["ts"] == 1710000000.0
        assert data["model"] == "claude-opus-4-6"
        assert data["in"] == 1200
        assert data["out"] == 350
        assert data["cost"] == 0.0148
        # No session or ip when empty
        assert "session" not in data
        assert "ip" not in data

    def test_to_json_with_context(self):
        rec = UsageRecord(
            ts=1710000000.0,
            model="gpt-5.4",
            input_tokens=500,
            output_tokens=100,
            cost_usd=0.005,
            session="abc123",
            ip_name="Berserk",
        )
        j = rec.to_json()
        data = json.loads(j)
        assert data["session"] == "abc123"
        assert data["ip"] == "Berserk"

    def test_from_json_roundtrip(self):
        original = UsageRecord(
            ts=1710000000.0,
            model="claude-opus-4-6",
            input_tokens=1200,
            output_tokens=350,
            cost_usd=0.0148,
            session="test",
            ip_name="Berserk",
        )
        j = original.to_json()
        restored = UsageRecord.from_json(j)
        assert restored.ts == original.ts
        assert restored.model == original.model
        assert restored.input_tokens == original.input_tokens
        assert restored.output_tokens == original.output_tokens
        assert restored.cost_usd == original.cost_usd
        assert restored.session == original.session
        assert restored.ip_name == original.ip_name

    def test_from_json_missing_optional_fields(self):
        data = '{"ts":1710000000,"model":"test","in":100,"out":50,"cost":0.01}'
        rec = UsageRecord.from_json(data)
        assert rec.session == ""
        assert rec.ip_name == ""


class TestUsageStore:
    """Tests for UsageStore JSONL persistence."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> UsageStore:
        return UsageStore(usage_dir=tmp_path)

    def test_record_creates_file(self, store: UsageStore, tmp_path: Path):
        store.record("claude-opus-4-6", 1000, 200, 0.01)
        today = date.today()
        fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
        assert fpath.exists()
        content = fpath.read_text(encoding="utf-8").strip()
        data = json.loads(content)
        assert data["model"] == "claude-opus-4-6"
        assert data["in"] == 1000
        assert data["out"] == 200

    def test_record_appends(self, store: UsageStore, tmp_path: Path):
        store.record("model-a", 100, 50, 0.01)
        store.record("model-b", 200, 100, 0.02)
        today = date.today()
        fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
        lines = fpath.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_record_with_context(self, store: UsageStore):
        rec = store.record(
            "claude-opus-4-6",
            500,
            100,
            0.005,
            session="sess1",
            ip_name="Berserk",
        )
        assert rec.session == "sess1"
        assert rec.ip_name == "Berserk"

    def test_get_monthly_summary_empty(self, store: UsageStore):
        summary = store.get_monthly_summary()
        assert summary["total_calls"] == 0
        assert summary["total_cost"] == 0.0

    def test_get_monthly_summary(self, store: UsageStore):
        store.record("claude-opus-4-6", 1000, 200, 0.0100)
        store.record("claude-opus-4-6", 500, 100, 0.0050)
        store.record("gpt-5.4", 300, 80, 0.0020)

        summary = store.get_monthly_summary()
        assert summary["total_calls"] == 3
        assert summary["total_cost"] == pytest.approx(0.017, abs=0.001)
        assert "claude-opus-4-6" in summary["by_model"]
        assert "gpt-5.4" in summary["by_model"]
        claude = summary["by_model"]["claude-opus-4-6"]
        assert claude["calls"] == 2
        assert claude["in"] == 1500
        assert claude["out"] == 300

    def test_get_daily_summary(self, store: UsageStore):
        store.record("claude-opus-4-6", 1000, 200, 0.01)
        summary = store.get_daily_summary()
        today = date.today()
        assert summary["date"] == today.isoformat()
        assert summary["total_calls"] == 1
        assert summary["total_cost"] == pytest.approx(0.01, abs=0.001)

    def test_get_daily_summary_filters_other_days(self, store: UsageStore, tmp_path: Path):
        # Write a record with yesterday's timestamp directly
        today = date.today()
        fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        yesterday_ts = time.time() - 86400 * 2  # 2 days ago
        record = UsageRecord(
            ts=yesterday_ts,
            model="old-model",
            input_tokens=999,
            output_tokens=999,
            cost_usd=9.99,
        )
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")
        # Add today's record
        store.record("new-model", 100, 50, 0.01)

        summary = store.get_daily_summary()
        assert summary["total_calls"] == 1
        assert summary["total_cost"] == pytest.approx(0.01, abs=0.001)

    def test_get_recent_records(self, store: UsageStore):
        for i in range(5):
            store.record(f"model-{i}", 100 * i, 50 * i, 0.01 * i)
        recent = store.get_recent_records(limit=3)
        assert len(recent) == 3
        # Newest first
        assert recent[0].model == "model-4"
        assert recent[2].model == "model-2"

    def test_get_recent_records_fewer_than_limit(self, store: UsageStore):
        store.record("model-a", 100, 50, 0.01)
        recent = store.get_recent_records(limit=10)
        assert len(recent) == 1

    def test_malformed_line_skipped(self, store: UsageStore, tmp_path: Path):
        today = date.today()
        fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("not-json\n")
            f.write('{"ts":1710000000,"model":"valid","in":100,"out":50,"cost":0.01}\n')
        summary = store.get_monthly_summary()
        assert summary["total_calls"] == 1

    def test_missing_month_file(self, store: UsageStore):
        summary = store.get_monthly_summary(2020, 1)
        assert summary["total_calls"] == 0


class TestUsageStoreSingleton:
    """Tests for module-level singleton."""

    def test_get_returns_same_instance(self):
        reset_usage_store(None)
        a = get_usage_store()
        b = get_usage_store()
        assert a is b
        reset_usage_store(None)  # cleanup

    def test_reset_clears_singleton(self):
        reset_usage_store(None)
        a = get_usage_store()
        custom = UsageStore()
        reset_usage_store(custom)
        b = get_usage_store()
        assert b is custom
        assert b is not a
        reset_usage_store(None)  # cleanup
