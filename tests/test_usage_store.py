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


class TestUsageRecordExtensionFields:
    """Defect A F-A2 / 2026-05-11 — cache/think/role/source/eval_id extension."""

    def test_to_json_omits_falsy_extension_fields(self):
        rec = UsageRecord(
            ts=1710000000.0,
            model="claude-opus-4-6",
            input_tokens=1000,
            output_tokens=200,
            cost_usd=0.01,
        )
        data = json.loads(rec.to_json())
        # Pre-extension keys still present, extension keys omitted when 0/empty
        assert "cache_w" not in data
        assert "cache_r" not in data
        assert "think" not in data
        assert "role" not in data
        assert "source" not in data
        assert "eval_id" not in data

    def test_to_json_emits_extension_fields_when_set(self):
        rec = UsageRecord(
            ts=1710000000.0,
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            cache_creation_tokens=9169,
            cache_read_tokens=34006,
            thinking_tokens=12,
            role="auditor",
            source="petri_eval",
            eval_id="2026-05-11T08-21-40-00-00_audit_X.eval",
        )
        data = json.loads(rec.to_json())
        assert data["cache_w"] == 9169
        assert data["cache_r"] == 34006
        assert data["think"] == 12
        assert data["role"] == "auditor"
        assert data["source"] == "petri_eval"
        assert data["eval_id"] == "2026-05-11T08-21-40-00-00_audit_X.eval"

    def test_from_json_legacy_record_compat(self):
        # Pre-extension JSONL row — produced by code before 2026-05-11
        legacy = (
            '{"ts":1710000000,"model":"claude-opus-4-6","in":1200,'
            '"out":350,"cost":0.0148}'
        )
        rec = UsageRecord.from_json(legacy)
        # Pre-extension fields parse as before
        assert rec.input_tokens == 1200
        # Extension fields default to 0 / "" — no KeyError, no crash
        assert rec.cache_creation_tokens == 0
        assert rec.cache_read_tokens == 0
        assert rec.thinking_tokens == 0
        assert rec.role == ""
        assert rec.source == ""
        assert rec.eval_id == ""

    def test_from_json_extension_roundtrip(self):
        original = UsageRecord(
            ts=1778573700.0,
            model="claude-haiku-4-5-20251001",
            input_tokens=21,
            output_tokens=846,
            cost_usd=0.045,
            cache_creation_tokens=6740,
            cache_read_tokens=0,
            thinking_tokens=0,
            role="judge",
            source="petri_eval",
            eval_id="2026-05-11T08-21-40-00-00_audit_EfZ32YEeSNkzk5HittH65e.eval",
        )
        restored = UsageRecord.from_json(original.to_json())
        assert restored.cache_creation_tokens == 6740
        assert restored.role == "judge"
        assert restored.source == "petri_eval"
        assert restored.eval_id == original.eval_id


class TestUsageStoreCacheFields:
    """UsageStore.record forwards the new cache / think / role / source kwargs."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> UsageStore:
        return UsageStore(usage_dir=tmp_path)

    def test_record_persists_cache_fields(self, store: UsageStore, tmp_path: Path):
        store.record(
            "claude-opus-4-7",
            1000,
            200,
            0.01,
            cache_creation_tokens=500,
            cache_read_tokens=2000,
            thinking_tokens=50,
        )
        today = date.today()
        fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
        line = fpath.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["cache_w"] == 500
        assert data["cache_r"] == 2000
        assert data["think"] == 50

    def test_record_with_explicit_ts(self, store: UsageStore):
        # Eval extraction stamps rows with the eval's start time, not
        # the (later) extraction time.
        target_ts = 1778573700.0
        rec = store.record(
            "claude-sonnet-4-6",
            7,
            1007,
            0.05,
            cache_creation_tokens=9169,
            cache_read_tokens=34006,
            role="auditor",
            source="petri_eval",
            eval_id="some.eval",
            ts=target_ts,
        )
        assert rec.ts == target_ts

    def test_has_eval_id_skips_already_imported(self, store: UsageStore):
        eval_id = "2026-05-11T08-21-40-00-00_audit_X.eval"
        # Initially absent
        assert store.has_eval_id(eval_id) is False
        # After import
        store.record(
            "claude-haiku-4-5-20251001",
            21,
            846,
            0.045,
            cache_creation_tokens=6740,
            role="judge",
            source="petri_eval",
            eval_id=eval_id,
        )
        assert store.has_eval_id(eval_id) is True
        # Different source with same id does not register as imported —
        # ``source != 'petri_eval'`` is a per-call row, not an eval row.
        store.record("other-model", 1, 1, 0.0, eval_id=eval_id)
        assert store.has_eval_id(eval_id) is True  # the petri_eval row still counts


class TestTokenTrackerPersistsCacheFields:
    """TokenTracker.record → _persist_usage forwards cache/think to JSONL."""

    def test_record_propagates_cache_fields(self, tmp_path: Path):
        from core.llm import usage_store as us_mod
        from core.llm.token_tracker import TokenTracker

        # Redirect the singleton at the JSONL boundary so the tracker
        # writes into our tmp dir.
        custom = UsageStore(usage_dir=tmp_path)
        us_mod._store = custom
        try:
            tracker = TokenTracker()
            tracker.record(
                "claude-opus-4-7",
                1000,
                200,
                cache_creation_tokens=500,
                cache_read_tokens=2000,
                thinking_tokens=10,
            )
            today = date.today()
            fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
            data = json.loads(fpath.read_text(encoding="utf-8").strip())
            assert data["cache_w"] == 500
            assert data["cache_r"] == 2000
            assert data["think"] == 10
        finally:
            us_mod._store = None


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
