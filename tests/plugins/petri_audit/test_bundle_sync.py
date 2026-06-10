"""Tests for plugins.petri_audit.bundle_sync."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from plugins.petri_audit import bundle_sync
from plugins.petri_audit.bundle_sync import (
    _extract_listing_entry,
    _merge_listing,
    sync_eval_to_bundle,
)


def _make_eval(path: Path, header: dict[str, Any]) -> Path:
    """Build a minimal .eval zip carrying a header.json the sync can parse.

    Uses ZIP_STORED (no compression) — bundle_sync's zipfile-zstd patch only
    matters for reading zstd entries, plain-stored entries always work.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("header.json", json.dumps(header))
    return path


def _sample_header() -> dict[str, Any]:
    """Header.json shape that matches inspect-ai's actual output."""
    return {
        "version": 2,
        "status": "success",
        "invalidated": False,
        "eval": {
            "eval_id": "EVAL_ABC",
            "run_id": "RUN_XYZ",
            "task": "inspect_petri/audit",
            "task_id": "TASK_001",
            "task_version": 0,
            "model": "none/none",
            "model_roles": {
                "auditor": {"model": "claude-cli/claude-sonnet-4-6", "config": {}, "args": {}},
                "target": {"model": "geode/gpt-5.5", "config": {}, "args": {}},
                "judge": {"model": "claude-cli/claude-opus-4-7", "config": {}, "args": {}},
            },
        },
        "stats": {
            "started_at": "2026-05-22T05:56:42+00:00",
            "completed_at": "2026-05-22T06:06:45+00:00",
        },
        "results": {
            "scores": [
                {
                    "name": "mean_score",
                    "metrics": {
                        "mean": {"name": "mean", "value": 0.877, "params": {}},
                        "stderr": {"name": "stderr", "value": 0.0, "params": {}},
                    },
                }
            ]
        },
    }


def test_extract_listing_entry_flattens_model_roles(tmp_path: Path) -> None:
    eval_path = _make_eval(tmp_path / "sample.eval", _sample_header())
    entry = _extract_listing_entry(eval_path)

    assert entry["model_roles"] == {
        "auditor": "claude-cli/claude-sonnet-4-6",
        "target": "geode/gpt-5.5",
        "judge": "claude-cli/claude-opus-4-7",
    }, "nested {role: {model, ...}} must flatten to {role: model_id}"


def test_extract_listing_entry_picks_first_metric_as_primary(tmp_path: Path) -> None:
    eval_path = _make_eval(tmp_path / "sample.eval", _sample_header())
    entry = _extract_listing_entry(eval_path)

    assert entry["primary_metric"] == {"name": "mean", "value": 0.877, "params": {}}, (
        "primary_metric should be the first scorer's first metric (viewer heuristic)"
    )


def test_extract_listing_entry_preserves_core_fields(tmp_path: Path) -> None:
    eval_path = _make_eval(tmp_path / "sample.eval", _sample_header())
    entry = _extract_listing_entry(eval_path)

    assert entry["eval_id"] == "EVAL_ABC"
    assert entry["run_id"] == "RUN_XYZ"
    assert entry["task"] == "inspect_petri/audit"
    assert entry["task_id"] == "TASK_001"
    assert entry["status"] == "success"
    assert entry["invalidated"] is False
    assert entry["started_at"] == "2026-05-22T05:56:42+00:00"
    assert entry["completed_at"] == "2026-05-22T06:06:45+00:00"


def test_merge_listing_preserves_existing_entries(tmp_path: Path) -> None:
    listing = tmp_path / "listing.json"
    listing.write_text(
        json.dumps({"old.eval": {"eval_id": "OLD", "status": "success"}}), encoding="utf-8"
    )

    _merge_listing(listing, "new.eval", {"eval_id": "NEW", "status": "success"})

    data = json.loads(listing.read_text(encoding="utf-8"))
    assert "old.eval" in data, "existing entries must survive a merge"
    assert "new.eval" in data
    assert data["new.eval"]["eval_id"] == "NEW"


def test_merge_listing_bootstraps_missing_file(tmp_path: Path) -> None:
    listing = tmp_path / "fresh-listing.json"
    assert not listing.exists()

    _merge_listing(listing, "first.eval", {"eval_id": "FIRST"})

    data = json.loads(listing.read_text(encoding="utf-8"))
    assert data == {"first.eval": {"eval_id": "FIRST"}}


def test_merge_listing_overwrites_same_key(tmp_path: Path) -> None:
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps({"x.eval": {"value": 1}}), encoding="utf-8")

    _merge_listing(listing, "x.eval", {"value": 2})

    data = json.loads(listing.read_text(encoding="utf-8"))
    assert data["x.eval"] == {"value": 2}, "re-syncing same eval must overwrite, not duplicate"


def test_sync_eval_to_bundle_copies_and_updates_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_dir = tmp_path / "bundle" / "logs"
    monkeypatch.setattr(bundle_sync, "BUNDLE_LOGS_DIR", bundle_dir)
    src = _make_eval(tmp_path / "src" / "audit-1.eval", _sample_header())

    dst = sync_eval_to_bundle(src)

    assert dst == bundle_dir / "audit-1.eval"
    assert dst is not None
    assert dst.is_file(), "source .eval must be copied to bundle dir"
    listing = json.loads((bundle_dir / "listing.json").read_text(encoding="utf-8"))
    assert "audit-1.eval" in listing
    assert listing["audit-1.eval"]["eval_id"] == "EVAL_ABC"


def test_sync_eval_to_bundle_env_knob_disables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_dir = tmp_path / "bundle" / "logs"
    monkeypatch.setattr(bundle_sync, "BUNDLE_LOGS_DIR", bundle_dir)
    monkeypatch.setenv("GEODE_PETRI_BUNDLE_SYNC_DISABLED", "1")
    src = _make_eval(tmp_path / "src" / "audit-1.eval", _sample_header())

    assert sync_eval_to_bundle(src) is None, "env knob must short-circuit before copy"
    assert not bundle_dir.exists(), "bundle dir must not be created when sync is disabled"


def test_sync_eval_to_bundle_missing_source_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_dir = tmp_path / "bundle" / "logs"
    monkeypatch.setattr(bundle_sync, "BUNDLE_LOGS_DIR", bundle_dir)

    assert sync_eval_to_bundle(tmp_path / "does-not-exist.eval") is None


def test_sync_eval_to_bundle_idempotent_resync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_dir = tmp_path / "bundle" / "logs"
    monkeypatch.setattr(bundle_sync, "BUNDLE_LOGS_DIR", bundle_dir)
    src = _make_eval(tmp_path / "src" / "audit-1.eval", _sample_header())

    sync_eval_to_bundle(src)
    sync_eval_to_bundle(src)  # second run must overwrite, not crash

    listing = json.loads((bundle_dir / "listing.json").read_text(encoding="utf-8"))
    assert list(listing.keys()) == ["audit-1.eval"], "re-sync must not duplicate the entry"
