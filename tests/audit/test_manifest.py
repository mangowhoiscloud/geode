"""Tests for ``core.audit.manifest`` — MANIFEST.jsonl append/read.

Same fake-EvalLog injection pattern as ``test_eval_to_jsonl.py`` —
``inspect_ai.log.read_eval_log`` is monkeypatched so we never need a
real ``.eval`` ZIP.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai.log")

from core.audit.manifest import (
    append_manifest,
    extract_manifest_entry,
    has_archive,
    parse_started_ts,
    read_manifest,
)


@dataclass
class FakeModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    input_tokens_cache_write: int | None = None
    input_tokens_cache_read: int | None = None


@dataclass
class FakeModelCfg:
    model: str


@dataclass
class FakeDataset:
    samples: int = 1
    sample_ids: list[str] = field(default_factory=list)


@dataclass
class FakeEvalMeta:
    model_roles: dict[str, FakeModelCfg] = field(default_factory=dict)
    dataset: FakeDataset = field(default_factory=FakeDataset)
    created: str = "2026-05-11T08:21:40+00:00"
    task: str = "inspect_petri/audit"


@dataclass
class FakeStats:
    role_usage: dict[str, FakeModelUsage] = field(default_factory=dict)
    completed_at: str = "2026-05-11T08:23:12+00:00"


@dataclass
class FakeEvalLog:
    eval: FakeEvalMeta
    stats: FakeStats
    status: str = "success"
    samples: list[Any] = field(default_factory=list)
    results: Any = None


def _patch_read(monkeypatch: pytest.MonkeyPatch, fake_log: FakeEvalLog) -> None:
    def fake_read(*_args: Any, **_kwargs: Any) -> FakeEvalLog:
        return fake_log

    monkeypatch.setattr("inspect_ai.log.read_eval_log", fake_read)


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    p = tmp_path / "2026-05-11T08-21-40-00-00_audit_X.eval"
    p.write_bytes(b"placeholder zip bytes")
    return p


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "MANIFEST.jsonl"


class TestExtractManifestEntry:
    def test_returns_core_fields(self, monkeypatch: pytest.MonkeyPatch, archive: Path):
        fake = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={
                    "auditor": FakeModelCfg(model="anthropic/claude-sonnet-4-6"),
                    "judge": FakeModelCfg(model="anthropic/claude-haiku-4-5-20251001"),
                    "target": FakeModelCfg(model="anthropic/claude-opus-4-7"),
                },
                dataset=FakeDataset(samples=1, sample_ids=["helpful_only_model_harmful_task"]),
            ),
            stats=FakeStats(
                role_usage={
                    "auditor": FakeModelUsage(input_tokens=7, output_tokens=1007),
                    "judge": FakeModelUsage(input_tokens=21, output_tokens=846),
                    "target": FakeModelUsage(input_tokens=100, output_tokens=50),
                },
            ),
        )
        _patch_read(monkeypatch, fake)
        entry = extract_manifest_entry(archive, summary_yaml="2026-05-11-abc.summary.yaml")

        assert entry["archive"] == archive.name
        assert len(entry["archive_sha"]) == 40  # sha1 hex
        assert entry["summary_yaml"] == "2026-05-11-abc.summary.yaml"
        assert entry["samples"] == 1
        assert entry["seed_ids"] == ["helpful_only_model_harmful_task"]
        assert entry["status"] == "success"
        assert entry["task"] == "inspect_petri/audit"
        assert entry["started_at"] == "2026-05-11T08:21:40+00:00"
        assert entry["completed_at"] == "2026-05-11T08:23:12+00:00"
        # Provider prefix stripped — cross-session search hits MODEL_PRICING
        assert entry["models"] == {
            "auditor": "claude-sonnet-4-6",
            "judge": "claude-haiku-4-5-20251001",
            "target": "claude-opus-4-7",
        }
        assert set(entry["role_usage_summary"].keys()) == {"auditor", "judge", "target"}
        assert entry["role_usage_summary"]["auditor"] == {
            "in": 7,
            "out": 1007,
            "cache_w": 0,
            "cache_r": 0,
        }

    def test_missing_role_usage_section_omitted(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path
    ):
        fake = FakeEvalLog(
            eval=FakeEvalMeta(dataset=FakeDataset(samples=0, sample_ids=[])),
            stats=FakeStats(role_usage={}),
        )
        _patch_read(monkeypatch, fake)
        entry = extract_manifest_entry(archive)
        assert "role_usage_summary" not in entry
        assert "seed_ids" not in entry
        assert entry["samples"] == 0

    def test_raises_on_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            extract_manifest_entry(tmp_path / "absent.eval")


class TestAppendManifest:
    def test_writes_jsonl_line(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, manifest_path: Path
    ):
        _patch_read(
            monkeypatch,
            FakeEvalLog(
                eval=FakeEvalMeta(
                    model_roles={"target": FakeModelCfg(model="anthropic/claude-opus-4-7")},
                    dataset=FakeDataset(samples=1, sample_ids=["x"]),
                ),
                stats=FakeStats(
                    role_usage={"target": FakeModelUsage(input_tokens=10, output_tokens=5)}
                ),
            ),
        )
        entry = append_manifest(archive, manifest_path=manifest_path)
        assert entry is not None
        assert manifest_path.is_file()
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["archive"] == archive.name

    def test_idempotent_via_archive_sha(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path, manifest_path: Path
    ):
        _patch_read(
            monkeypatch,
            FakeEvalLog(
                eval=FakeEvalMeta(dataset=FakeDataset(samples=0, sample_ids=[])),
                stats=FakeStats(),
            ),
        )
        first = append_manifest(archive, manifest_path=manifest_path)
        second = append_manifest(archive, manifest_path=manifest_path)
        assert first is not None
        assert second is None  # skipped — same archive_sha
        assert len(manifest_path.read_text(encoding="utf-8").splitlines()) == 1

    def test_missing_file_returns_none(self, tmp_path: Path, manifest_path: Path):
        out = append_manifest(tmp_path / "absent.eval", manifest_path=manifest_path)
        assert out is None
        assert not manifest_path.exists()


class TestHasArchive:
    def test_returns_false_when_manifest_missing(self, manifest_path: Path):
        assert has_archive("abc", manifest_path=manifest_path) is False

    def test_returns_false_for_empty_sha(self, manifest_path: Path):
        manifest_path.write_text('{"archive_sha":"abc"}\n', encoding="utf-8")
        assert has_archive("", manifest_path=manifest_path) is False

    def test_detects_existing_sha(self, manifest_path: Path):
        manifest_path.write_text(
            '{"archive_sha":"deadbeef","archive":"a.eval"}\n', encoding="utf-8"
        )
        assert has_archive("deadbeef", manifest_path=manifest_path) is True
        assert has_archive("absent", manifest_path=manifest_path) is False

    def test_skips_malformed_lines(self, manifest_path: Path):
        manifest_path.write_text(
            "not-json\n" + '{"archive_sha":"abc"}\n',
            encoding="utf-8",
        )
        assert has_archive("abc", manifest_path=manifest_path) is True


class TestReadManifest:
    def test_empty_when_missing(self, manifest_path: Path):
        assert read_manifest(manifest_path) == []

    def test_returns_all_entries(self, manifest_path: Path):
        manifest_path.write_text(
            '{"archive":"a.eval","archive_sha":"1"}\n{"archive":"b.eval","archive_sha":"2"}\n',
            encoding="utf-8",
        )
        out = read_manifest(manifest_path)
        assert [e["archive"] for e in out] == ["a.eval", "b.eval"]

    def test_skips_malformed(self, manifest_path: Path):
        manifest_path.write_text(
            'not-json\n{"archive":"a.eval","archive_sha":"1"}\n\n',
            encoding="utf-8",
        )
        out = read_manifest(manifest_path)
        assert len(out) == 1


class TestParseStartedTs:
    def test_parses_iso_offset(self):
        ts = parse_started_ts({"started_at": "2026-05-11T08:21:40+00:00"})
        assert ts == pytest.approx(1778487700.0, abs=1.0)

    def test_returns_none_when_missing(self):
        assert parse_started_ts({}) is None

    def test_returns_none_for_garbage(self):
        assert parse_started_ts({"started_at": "not-a-date"}) is None
