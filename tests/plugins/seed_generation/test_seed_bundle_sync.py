"""Tests for ``plugins.seed_generation.bundle_sync`` (CSP-14 seed publish).

Covers:
- Sync copies state.json + survivors.json + meta_review.json
- Selective candidate copy (survivors only, drafts skipped)
- Containment guard (resolved path under docs/petri-bundle/seeds/)
- Env knob ``GEODE_SEED_BUNDLE_SYNC_DISABLED`` short-circuit
- Idempotency (re-sync overwrites)
- Defensive read of malformed state.json
- iter_synced_runs aggregation helper
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from plugins.seed_generation.bundle_sync import iter_synced_runs, sync_run_to_bundle


def _make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a fake repo root with the bundle path skeleton + env override.

    The conftest's autouse fixture sets ``GEODE_SEED_BUNDLE_SYNC_DISABLED=1``
    to prevent unrelated tests from leaking into the real repo's
    docs/petri-bundle/seeds/. Bundle-sync's own tests need to actually
    exercise the sync, so we clear that knob here.
    """
    (tmp_path / "pyproject.toml").write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("GEODE_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("GEODE_SEED_BUNDLE_SYNC_DISABLED", raising=False)
    return tmp_path


def _make_run_dir(tmp_path: Path, run_id: str, *, state: dict[str, Any]) -> Path:
    """Build a fake state/seed-generation/<run_id>/ directory tree."""
    run_dir = tmp_path / "state" / "seed-generation" / run_id
    (run_dir / "candidates").mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir


def test_sync_copies_state_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """state.json is the minimum required file — sync copies it."""
    repo = _make_repo(tmp_path, monkeypatch)
    run = _make_run_dir(repo, "r-001", state={"run_id": "r-001"})
    dst = sync_run_to_bundle(run)
    assert dst is not None
    assert (repo / "docs/petri-bundle/seeds/r-001/state.json").is_file()


def test_sync_copies_optional_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """survivors.json + meta_review.json copied when present."""
    repo = _make_repo(tmp_path, monkeypatch)
    run = _make_run_dir(repo, "r-002", state={"run_id": "r-002", "survivors": []})
    (run / "survivors.json").write_text('{"survivors": []}', encoding="utf-8")
    (run / "meta_review.json").write_text('{"coverage": {}}', encoding="utf-8")
    sync_run_to_bundle(run)
    bundle = repo / "docs/petri-bundle/seeds/r-002"
    assert (bundle / "state.json").is_file()
    assert (bundle / "survivors.json").is_file()
    assert (bundle / "meta_review.json").is_file()


def test_sync_copies_only_survivor_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drafts that didn't survive are NOT copied to the publish bundle."""
    repo = _make_repo(tmp_path, monkeypatch)
    run = _make_run_dir(
        repo,
        "r-003",
        state={
            "run_id": "r-003",
            "candidates": [
                {"id": "c-1"},
                {"id": "c-2"},
                {"id": "c-3"},
            ],
            "survivors": ["c-1", "c-3"],  # c-2 dropped
        },
    )
    # Write 3 candidate bodies on disk.
    for cid in ("c-1", "c-2", "c-3"):
        (run / "candidates" / f"{cid}.md").write_text(f"# {cid}\n", encoding="utf-8")
    sync_run_to_bundle(run)
    bundle_cands = repo / "docs/petri-bundle/seeds/r-003/candidates"
    assert (bundle_cands / "c-1.md").is_file()
    assert not (bundle_cands / "c-2.md").exists(), "non-survivor draft leaked into publish bundle"
    assert (bundle_cands / "c-3.md").is_file()


def test_sync_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-sync overwrites in place; no error."""
    repo = _make_repo(tmp_path, monkeypatch)
    run = _make_run_dir(repo, "r-004", state={"run_id": "r-004"})
    sync_run_to_bundle(run)
    sync_run_to_bundle(run)
    # Single state.json — re-sync overwrote.
    assert (repo / "docs/petri-bundle/seeds/r-004/state.json").is_file()


def test_sync_env_knob_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``GEODE_SEED_BUNDLE_SYNC_DISABLED=1`` skips the sync."""
    repo = _make_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("GEODE_SEED_BUNDLE_SYNC_DISABLED", "1")
    run = _make_run_dir(repo, "r-005", state={"run_id": "r-005"})
    result = sync_run_to_bundle(run)
    assert result is None
    assert not (repo / "docs/petri-bundle/seeds/r-005").exists()


def test_sync_missing_state_json_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run dir without state.json → sync refuses (corrupt run signal)."""
    repo = _make_repo(tmp_path, monkeypatch)
    run = repo / "state/seed-generation/r-006"
    run.mkdir(parents=True)
    result = sync_run_to_bundle(run)
    assert result is None


def test_sync_missing_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-existent source dir → sync returns None gracefully."""
    repo = _make_repo(tmp_path, monkeypatch)
    result = sync_run_to_bundle(repo / "state/seed-generation/never-existed")
    assert result is None


def test_sync_malformed_state_json_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """state.json is unparseable → state.json still copied, survivor copy skipped."""
    repo = _make_repo(tmp_path, monkeypatch)
    run_dir = repo / "state/seed-generation/r-007"
    (run_dir / "candidates").mkdir(parents=True)
    (run_dir / "state.json").write_text("{not json", encoding="utf-8")
    (run_dir / "candidates" / "c-x.md").write_text("# c-x\n", encoding="utf-8")
    sync_run_to_bundle(run_dir)
    # state.json still copied (verbatim) — only survivor enumeration is best-effort.
    assert (repo / "docs/petri-bundle/seeds/r-007/state.json").is_file()
    # No survivor list → candidates dir is empty / absent.
    assert not (repo / "docs/petri-bundle/seeds/r-007/candidates").exists()


# ── iter_synced_runs ──────────────────────────────────────────────────────


def test_iter_synced_runs_empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_repo(tmp_path, monkeypatch)
    runs = iter_synced_runs()
    assert runs == []


def test_iter_synced_runs_enumerates_synced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path, monkeypatch)
    for run_id, gen_tag in (("r-001", "gen-1"), ("r-002", "gen-2"), ("r-003", "gen-3")):
        run = _make_run_dir(repo, run_id, state={"run_id": run_id, "gen_tag": gen_tag})
        sync_run_to_bundle(run)
    runs = iter_synced_runs()
    assert [r["run_id"] for r in runs] == ["r-001", "r-002", "r-003"]
    assert all(r["state"].get("gen_tag", "").startswith("gen-") for r in runs)


def test_iter_synced_runs_skips_unparseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path, monkeypatch)
    bundle = repo / "docs/petri-bundle/seeds/r-bad"
    bundle.mkdir(parents=True)
    (bundle / "state.json").write_text("not json", encoding="utf-8")
    bundle2 = repo / "docs/petri-bundle/seeds/r-good"
    bundle2.mkdir(parents=True)
    (bundle2 / "state.json").write_text(json.dumps({"run_id": "r-good"}), encoding="utf-8")
    runs = iter_synced_runs()
    assert [r["run_id"] for r in runs] == ["r-good"]
