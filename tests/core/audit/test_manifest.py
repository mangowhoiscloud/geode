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


class TestB4Fallback:
    """Defect B-4 — when ``stats.role_usage`` misses a role declared in
    ``eval.model_roles``, ``extract_manifest_entry`` must re-aggregate
    from sample ``ModelEvent.output.usage`` so the manifest's
    ``role_usage_summary`` stays complete. 5/11 evidence: 8 archives,
    judge entry missing on 4 (43%) despite the ModelEvent existing in
    every sample.
    """

    def test_fallback_recovers_missing_judge_from_events(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path
    ):
        # Synthetic event types — duck-typed (type(e).__name__ ==
        # "ModelEvent" + .model + .output.usage). The fallback walks
        # them so we don't need real inspect_ai events.
        from dataclasses import dataclass as _dc

        @_dc
        class _Usage:
            input_tokens: int = 0
            output_tokens: int = 0
            input_tokens_cache_write: int = 0
            input_tokens_cache_read: int = 0
            reasoning_tokens: int = 0

        @_dc
        class _Output:
            usage: Any = None

        class ModelEvent:
            def __init__(self, model: str, usage: _Usage) -> None:
                self.model = model
                self.output = _Output(usage=usage)

        # Sample with judge ModelEvent but stats.role_usage 안 잡힘
        # (race) — auditor 만 stats.
        @_dc
        class _Sample:
            events: list[Any]

        judge_usage = _Usage(input_tokens=21, output_tokens=846, input_tokens_cache_write=6740)
        sample = _Sample(
            events=[
                ModelEvent("anthropic/claude-haiku-4-5-20251001", judge_usage),
            ]
        )

        # Header-only read sees auditor only; full read sees the judge
        # ModelEvent. ``_patch_read`` uses the same fake for both, so
        # we adjust ``samples`` so the fallback re-read finds events.
        fake_header = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={
                    "auditor": FakeModelCfg(model="anthropic/claude-sonnet-4-6"),
                    "judge": FakeModelCfg(model="anthropic/claude-haiku-4-5-20251001"),
                },
                dataset=FakeDataset(samples=1, sample_ids=["x"]),
            ),
            stats=FakeStats(
                role_usage={
                    "auditor": FakeModelUsage(input_tokens=7, output_tokens=1007),
                    # judge entry intentionally missing — reproduces B-4
                }
            ),
            samples=[sample],  # fallback re-read uses this
        )
        _patch_read(monkeypatch, fake_header)

        entry = extract_manifest_entry(archive)
        ru = entry["role_usage_summary"]
        # auditor stayed (from stats)
        assert ru["auditor"]["in"] == 7
        assert ru["auditor"]["out"] == 1007
        # judge recovered from events (the fix)
        assert ru["judge"]["in"] == 21
        assert ru["judge"]["out"] == 846
        assert ru["judge"]["cache_w"] == 6740

    def test_fallback_no_op_when_all_roles_present(
        self, monkeypatch: pytest.MonkeyPatch, archive: Path
    ):
        # All declared roles present in stats — fallback skipped.
        fake = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={
                    "auditor": FakeModelCfg(model="anthropic/claude-sonnet-4-6"),
                    "judge": FakeModelCfg(model="anthropic/claude-haiku-4-5-20251001"),
                },
                dataset=FakeDataset(samples=1, sample_ids=["x"]),
            ),
            stats=FakeStats(
                role_usage={
                    "auditor": FakeModelUsage(input_tokens=7, output_tokens=1007),
                    "judge": FakeModelUsage(input_tokens=21, output_tokens=846),
                }
            ),
        )
        _patch_read(monkeypatch, fake)
        entry = extract_manifest_entry(archive)
        assert set(entry["role_usage_summary"]) == {"auditor", "judge"}

    def test_fallback_logs_warning_when_no_events_match(
        self,
        monkeypatch: pytest.MonkeyPatch,
        archive: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        # Role declared but the sample carries no matching ModelEvent —
        # fallback logs WARNING but does not crash; role just absent.
        fake = FakeEvalLog(
            eval=FakeEvalMeta(
                model_roles={
                    "auditor": FakeModelCfg(model="anthropic/claude-sonnet-4-6"),
                    "judge": FakeModelCfg(model="anthropic/claude-haiku-4-5-20251001"),
                },
                dataset=FakeDataset(samples=1, sample_ids=["x"]),
            ),
            stats=FakeStats(
                role_usage={
                    "auditor": FakeModelUsage(input_tokens=7, output_tokens=1007),
                }
            ),
            samples=[],  # no events
        )
        _patch_read(monkeypatch, fake)
        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="core.audit.manifest"):
            entry = extract_manifest_entry(archive)
        assert "judge" not in entry.get("role_usage_summary", {})
        assert any("B-4 fallback" in r.message for r in caplog.records)
