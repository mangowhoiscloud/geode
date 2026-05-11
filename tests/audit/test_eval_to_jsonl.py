"""Tests for ``core.audit.eval_to_jsonl`` — petri ``.eval`` → JSONL ledger.

The extractor is exercised against a fake ``EvalLog`` (built with simple
dataclasses) injected via ``monkeypatch`` on ``inspect_ai.log.read_eval_log``.
This avoids the cost + flake of building a real ``.eval`` ZIP just to
verify the bookkeeping path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai.log")

from core.audit.eval_to_jsonl import _parse_eval_ts, extract_to_usage_store
from core.llm.usage_store import UsageStore


@dataclass
class FakeModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    input_tokens_cache_write: int | None = None
    input_tokens_cache_read: int | None = None
    reasoning_tokens: int | None = None
    total_cost: float | None = None


@dataclass
class FakeModelCfg:
    model: str


@dataclass
class FakeEvalMeta:
    model_roles: dict[str, FakeModelCfg] = field(default_factory=dict)
    created: str = "2026-05-11T08:21:40+00:00"
    task: str = "inspect_petri/audit"


@dataclass
class FakeStats:
    model_usage: dict[str, FakeModelUsage] = field(default_factory=dict)


@dataclass
class FakeEvalLog:
    eval: FakeEvalMeta
    stats: FakeStats
    status: str = "success"


def _patch_read(monkeypatch: pytest.MonkeyPatch, fake_log: FakeEvalLog) -> None:
    """Replace ``inspect_ai.log.read_eval_log`` with a constant return."""

    def fake_read(*_args: Any, **_kwargs: Any) -> FakeEvalLog:
        return fake_log

    monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)


def _read_jsonl(tmp_path: Path) -> list[dict[str, Any]]:
    today = date.today()
    fpath = tmp_path / f"{today.year:04d}-{today.month:02d}.jsonl"
    if not fpath.exists():
        return []
    return [json.loads(line) for line in fpath.read_text(encoding="utf-8").splitlines() if line]


class TestParseEvalTs:
    def test_iso_with_offset(self):
        ts = _parse_eval_ts("2026-05-11T08:21:40+00:00")
        assert ts == pytest.approx(1778487700.0, abs=1.0)

    def test_iso_with_z(self):
        ts = _parse_eval_ts("2026-05-11T08:21:40Z")
        assert ts == pytest.approx(1778487700.0, abs=1.0)

    def test_missing_returns_none(self):
        assert _parse_eval_ts("") is None
        assert _parse_eval_ts(None) is None

    def test_garbage_returns_none(self):
        assert _parse_eval_ts("not-a-date") is None


class TestExtractToUsageStore:
    @pytest.fixture()
    def archive(self, tmp_path: Path) -> Path:
        """Create a placeholder file that passes ``is_file()``."""
        p = tmp_path / "2026-05-11T08-21-40-00-00_audit_X.eval"
        p.write_bytes(b"pretend this is a zip")
        return p

    @pytest.fixture()
    def store(self, tmp_path: Path) -> UsageStore:
        return UsageStore(usage_dir=tmp_path / "usage")

    def test_missing_file_is_silent_noop(self, store: UsageStore, tmp_path: Path):
        n = extract_to_usage_store(tmp_path / "nope.eval", store=store)
        assert n == 0
        assert _read_jsonl(tmp_path / "usage") == []

    def test_empty_model_usage_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, store: UsageStore
    ):
        _patch_read(
            monkeypatch,
            FakeEvalLog(eval=FakeEvalMeta(), stats=FakeStats(model_usage={})),
        )
        assert extract_to_usage_store(archive, store=store) == 0

    def test_appends_one_row_per_model_with_role_tag(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, store: UsageStore, tmp_path: Path
    ):
        # Mirror the actual 5/11 anthropic archive shape (judge + auditor)
        fake_log = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={
                    "auditor": FakeModelCfg(model="anthropic/claude-sonnet-4-6"),
                    "judge": FakeModelCfg(model="anthropic/claude-haiku-4-5-20251001"),
                },
                created="2026-05-11T08:21:40+00:00",
            ),
            stats=FakeStats(
                model_usage={
                    "anthropic/claude-sonnet-4-6": FakeModelUsage(
                        input_tokens=7,
                        output_tokens=1007,
                        input_tokens_cache_write=9169,
                        input_tokens_cache_read=34006,
                    ),
                    "anthropic/claude-haiku-4-5-20251001": FakeModelUsage(
                        input_tokens=21,
                        output_tokens=846,
                        input_tokens_cache_write=6740,
                    ),
                }
            ),
        )
        _patch_read(monkeypatch, fake_log)

        n = extract_to_usage_store(archive, store=store)
        assert n == 2

        rows = _read_jsonl(tmp_path / "usage")
        assert len(rows) == 2
        by_role = {r["role"]: r for r in rows}
        assert set(by_role) == {"auditor", "judge"}
        # Provider prefix stripped so MODEL_PRICING lookup hits
        assert by_role["auditor"]["model"] == "claude-sonnet-4-6"
        assert by_role["judge"]["model"] == "claude-haiku-4-5-20251001"
        # Cache fields preserved
        assert by_role["auditor"]["cache_w"] == 9169
        assert by_role["auditor"]["cache_r"] == 34006
        assert by_role["judge"]["cache_w"] == 6740
        # source / eval_id stamped
        for r in rows:
            assert r["source"] == "petri_eval"
            assert r["eval_id"] == archive.name
        # ts comes from eval.created, not now()
        assert by_role["auditor"]["ts"] == pytest.approx(1778487700.0, abs=1.0)

    def test_cost_filled_from_pricing_when_total_cost_missing(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, store: UsageStore, tmp_path: Path
    ):
        fake_log = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={"judge": FakeModelCfg(model="anthropic/claude-haiku-4-5-20251001")}
            ),
            stats=FakeStats(
                model_usage={
                    "anthropic/claude-haiku-4-5-20251001": FakeModelUsage(
                        input_tokens=1000,
                        output_tokens=200,
                    ),
                }
            ),
        )
        _patch_read(monkeypatch, fake_log)
        extract_to_usage_store(archive, store=store)

        rows = _read_jsonl(tmp_path / "usage")
        assert len(rows) == 1
        # haiku-4-5: $1/M in + $5/M out → 1000 * 1e-6 + 200 * 5e-6 = $0.002
        assert rows[0]["cost"] == pytest.approx(0.002, abs=1e-4)

    def test_idempotent_second_call_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, store: UsageStore, tmp_path: Path
    ):
        fake_log = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={"target": FakeModelCfg(model="anthropic/claude-opus-4-7")}
            ),
            stats=FakeStats(
                model_usage={
                    "anthropic/claude-opus-4-7": FakeModelUsage(input_tokens=100, output_tokens=50)
                }
            ),
        )
        _patch_read(monkeypatch, fake_log)
        assert extract_to_usage_store(archive, store=store) == 1
        assert extract_to_usage_store(archive, store=store) == 0
        # Still only one row
        assert len(_read_jsonl(tmp_path / "usage")) == 1

    def test_unknown_role_model_falls_through_with_empty_role(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, store: UsageStore, tmp_path: Path
    ):
        # Model in stats but no role mapping (e.g. an unconfigured sub-model)
        fake_log = FakeEvalLog(
            eval=FakeEvalMeta(model_roles={}),
            stats=FakeStats(
                model_usage={
                    "anthropic/claude-opus-4-7": FakeModelUsage(input_tokens=10, output_tokens=5)
                }
            ),
        )
        _patch_read(monkeypatch, fake_log)
        extract_to_usage_store(archive, store=store)
        rows = _read_jsonl(tmp_path / "usage")
        assert len(rows) == 1
        # role omitted (= "") when no model_roles match
        assert "role" not in rows[0]
