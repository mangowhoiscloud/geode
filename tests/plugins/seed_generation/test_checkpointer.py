"""Unit tests for :mod:`plugins.seed_generation.checkpointer`.

PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — pin the atomic
write contract + the completed-phase ordering + the malformed-JSON
tolerance so a future refactor cannot silently drop them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plugins.seed_generation.checkpointer import (
    CHECKPOINT_SUBDIR,
    PhaseCheckpoint,
    list_completed_phases,
    load_checkpoint,
    write_checkpoint,
)


def _make_snapshot(phase: str) -> dict[str, object]:
    return {
        "run_id": "gen1-broken_tool_use",
        "target_dim": "broken_tool_use",
        "gen_tag": "gen1",
        "phase_marker": phase,
        "candidates": [{"id": f"c-{phase}"}],
    }


def test_write_checkpoint_creates_atomic_file(tmp_path: Path) -> None:
    target = write_checkpoint(
        tmp_path,
        phase="generator",
        state_snapshot=_make_snapshot("generator"),
        duration_ms=1234.5,
    )
    assert target == tmp_path / CHECKPOINT_SUBDIR / "generator.json"
    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["phase"] == "generator"
    assert payload["duration_ms"] == pytest.approx(1234.5)
    assert payload["state_snapshot"]["phase_marker"] == "generator"
    assert payload["error"] is None


def test_write_checkpoint_cleans_up_tmp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.replace failure removes the temp file (no stale ``.tmp`` accumulator)."""
    import os

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_checkpoint(
            tmp_path,
            phase="generator",
            state_snapshot=_make_snapshot("generator"),
            duration_ms=1.0,
        )
    leftovers = list((tmp_path / CHECKPOINT_SUBDIR).glob(".generator.*.tmp"))
    assert leftovers == []


def test_load_checkpoint_round_trip(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        phase="critic",
        state_snapshot=_make_snapshot("critic"),
        duration_ms=42.0,
    )
    ck = load_checkpoint(tmp_path, "critic")
    assert ck is not None
    assert isinstance(ck, PhaseCheckpoint)
    assert ck.phase == "critic"
    assert ck.duration_ms == pytest.approx(42.0)
    assert ck.state_snapshot["phase_marker"] == "critic"


def test_load_checkpoint_missing_returns_none(tmp_path: Path) -> None:
    assert load_checkpoint(tmp_path, "never_wrote") is None


def test_load_checkpoint_malformed_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / CHECKPOINT_SUBDIR / "evolver.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{this is not json", encoding="utf-8")
    assert load_checkpoint(tmp_path, "evolver") is None


def test_load_checkpoint_non_dict_payload_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / CHECKPOINT_SUBDIR / "evolver.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('["a", "b"]', encoding="utf-8")
    assert load_checkpoint(tmp_path, "evolver") is None


def test_list_completed_phases_ordered_by_completed_at(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        phase="pilot",
        state_snapshot=_make_snapshot("pilot"),
        duration_ms=1.0,
    )
    write_checkpoint(
        tmp_path,
        phase="generator",
        state_snapshot=_make_snapshot("generator"),
        duration_ms=1.0,
    )
    write_checkpoint(
        tmp_path,
        phase="critic",
        state_snapshot=_make_snapshot("critic"),
        duration_ms=1.0,
    )
    phases = list_completed_phases(tmp_path)
    assert phases == ["pilot", "generator", "critic"]


def test_list_completed_phases_skips_non_json_files(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        phase="generator",
        state_snapshot=_make_snapshot("generator"),
        duration_ms=1.0,
    )
    (tmp_path / CHECKPOINT_SUBDIR / "scratch.txt").write_text("ignore me")
    phases = list_completed_phases(tmp_path)
    assert phases == ["generator"]


def test_list_completed_phases_empty_dir(tmp_path: Path) -> None:
    assert list_completed_phases(tmp_path) == []
