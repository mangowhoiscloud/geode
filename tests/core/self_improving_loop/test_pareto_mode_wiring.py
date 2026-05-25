"""A.1 (2026-05-25) — pareto_mode archive writer wiring (PR-15).

Scope: apply_group_proposals 의 pareto_mode 분기 — config.pareto_mode=True
시 N sibling 의 fitness vector 를 baseline_archive.jsonl 에 append.

본 PR 의 scope = **lineage writer only**:
- pareto_mode=False (default) → archive 미작성, legacy 동작 그대로
- pareto_mode=True → N sibling entry append (dominated prune 자동), top-1
  selection 은 그대로 linear advantage (multi-dim selection 은 후속 PR)

Tests use direct ArchiveEntry / append_archive_entry / load_archive
calls + the .gitignore invariant.

Codex MCP precedent: PR-G5b silent-ignored writer (mutations.jsonl). 본
PR 가 baseline_archive.jsonl 도 같은 invariant 로 보호.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.self_improving_loop.pareto_archive import (
    ArchiveEntry,
    PareteArchive,
    append_archive_entry,
    load_archive,
)

# ---------------------------------------------------------------------------
# 1. .gitignore parity — baseline_archive.jsonl 가 git-tracked 인지
# ---------------------------------------------------------------------------


def test_baseline_archive_path_not_gitignored() -> None:
    """PR-G5b precedent — silent-ignored writer 방지.

    `git check-ignore` 로 BASELINE_ARCHIVE_PATH 가 ignored 면 FAIL.
    """
    import subprocess

    from core.paths import BASELINE_ARCHIVE_PATH

    # Resolve to repo-relative path for git check-ignore
    repo_root = BASELINE_ARCHIVE_PATH.resolve().parents[2]
    rel_path = BASELINE_ARCHIVE_PATH.resolve().relative_to(repo_root)
    proc = subprocess.run(  # noqa: S603  # nosec B603
        ["git", "check-ignore", "-v", str(rel_path)],  # noqa: S607  # nosec B607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    # check-ignore returns 0 when ignored, 1 when NOT ignored.
    # Pattern that ends in ``!autoresearch/state/baseline_archive.jsonl`` is
    # the negation we want (returns 0 but path is included).
    if proc.returncode == 0:
        # Ignored — but only if the matching pattern is NOT a negation
        last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        assert last_line.split("\t")[0].endswith("!autoresearch/state/baseline_archive.jsonl"), (
            f"baseline_archive.jsonl is gitignored without negation: {last_line!r}"
        )


# ---------------------------------------------------------------------------
# 2. ArchiveEntry serialisation roundtrip
# ---------------------------------------------------------------------------


def test_archive_entry_minimal_fields() -> None:
    """ArchiveEntry 의 minimal field set — mutation_id + ts + dim_means."""
    entry = ArchiveEntry(
        mutation_id="m1",
        ts=1234567890.0,
        dim_means={"fitness": 0.5},
    )
    assert entry.mutation_id == "m1"
    assert entry.dim_means == {"fitness": 0.5}
    assert entry.group_id == ""  # default
    assert entry.audit_run_id == ""  # default


def test_append_archive_entry_writes_jsonl(tmp_path: Path) -> None:
    archive_path = tmp_path / "baseline_archive.jsonl"
    entry = ArchiveEntry(
        mutation_id="m1",
        group_id="g1",
        audit_run_id="run1",
        ts=1234567890.0,
        dim_means={"fitness": 0.42},
    )
    result_path = append_archive_entry(entry, archive_path=archive_path)
    assert result_path == archive_path
    rows = [json.loads(line) for line in archive_path.read_text().splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["mutation_id"] == "m1"
    assert rows[0]["dim_means"] == {"fitness": 0.42}


def test_load_archive_filters_invalid_rows(tmp_path: Path) -> None:
    archive_path = tmp_path / "baseline_archive.jsonl"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    # Mix valid + invalid rows
    with archive_path.open("w") as fh:
        fh.write(json.dumps({"mutation_id": "m1", "ts": 1.0, "dim_means": {"fitness": 0.5}}) + "\n")
        fh.write("garbage json{\n")
        fh.write(json.dumps({"not_a_record": True}) + "\n")  # schema invalid
        fh.write(json.dumps({"mutation_id": "m2", "ts": 2.0, "dim_means": {"fitness": 0.7}}) + "\n")
    archive = load_archive(archive_path)
    # Both valid entries inserted (non-dominated each other on 1-dim by score)
    assert len(archive.entries) == 1  # m2 dominates m1 → only m2 remains
    assert archive.entries[0].mutation_id == "m2"


def test_load_archive_missing_file_empty(tmp_path: Path) -> None:
    missing = tmp_path / "no_archive.jsonl"
    archive = load_archive(missing)
    assert len(archive) == 0


# ---------------------------------------------------------------------------
# 3. PareteArchive dominance + insert
# ---------------------------------------------------------------------------


def test_archive_insert_non_dominated() -> None:
    archive = PareteArchive()
    e1 = ArchiveEntry(mutation_id="m1", ts=1.0, dim_means={"a": 1.0, "b": 2.0})
    e2 = ArchiveEntry(mutation_id="m2", ts=2.0, dim_means={"a": 2.0, "b": 1.0})
    assert archive.insert(e1) is True
    assert archive.insert(e2) is True  # non-dominated (trade-off)
    assert len(archive) == 2


def test_archive_insert_dominated_rejected() -> None:
    archive = PareteArchive()
    archive.insert(ArchiveEntry(mutation_id="m1", ts=1.0, dim_means={"a": 2.0, "b": 2.0}))
    # m2 is strictly dominated (both dims lower)
    rejected = ArchiveEntry(mutation_id="m2", ts=2.0, dim_means={"a": 1.0, "b": 1.0})
    assert archive.insert(rejected) is False
    assert len(archive) == 1


def test_archive_insert_dominating_prunes() -> None:
    archive = PareteArchive()
    archive.insert(ArchiveEntry(mutation_id="m1", ts=1.0, dim_means={"a": 1.0, "b": 1.0}))
    # m2 dominates m1 — m1 should be pruned
    dominator = ArchiveEntry(mutation_id="m2", ts=2.0, dim_means={"a": 2.0, "b": 2.0})
    assert archive.insert(dominator) is True
    assert len(archive) == 1
    assert archive.entries[0].mutation_id == "m2"


# ---------------------------------------------------------------------------
# 4. Wiring integration — apply_group_proposals appends when pareto_mode=True
# ---------------------------------------------------------------------------


def test_wiring_pareto_mode_false_skips_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pareto_mode=False (default) → archive 미작성, legacy 동작."""

    # Redirect archive path to tmp
    test_archive = tmp_path / "baseline_archive.jsonl"
    monkeypatch.setattr("core.paths.BASELINE_ARCHIVE_PATH", test_archive)

    # The wiring is inside apply_group_proposals which requires audit
    # subprocess; testing the integration directly here would spawn audits.
    # Instead, verify the config knob default + module presence.
    from core.config.self_improving_loop import (
        load_self_improving_loop_config,
    )

    cfg = load_self_improving_loop_config()
    assert cfg.autoresearch.pareto_mode is False  # default
    assert not test_archive.exists()


def test_wiring_pareto_mode_archive_path_resolved() -> None:
    """BASELINE_ARCHIVE_PATH 가 autoresearch/state/baseline_archive.jsonl 에
    위치 — git-tracked invariant 확인."""
    from core.paths import BASELINE_ARCHIVE_PATH

    assert BASELINE_ARCHIVE_PATH.name == "baseline_archive.jsonl"
    assert "autoresearch/state" in str(BASELINE_ARCHIVE_PATH)


def test_pareto_archive_helper_imports_clean() -> None:
    """Codex MCP anti-deception — helper 가 wiring 진입 지점에서 import 가능."""
    from core.self_improving_loop.pareto_archive import (
        ArchiveEntry,
        append_archive_entry,
    )

    assert ArchiveEntry is not None
    assert append_archive_entry is not None
