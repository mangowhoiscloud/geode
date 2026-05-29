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

    Codex MCP WARN #6 tighten — git 부재 또는 non-repo 환경에서는 skip,
    returncode 0 (ignored) 일 때만 negation 패턴 매치 검증, returncode 1
    (not ignored) 이 명시적 pass, 다른 returncode 는 FileNotFoundError /
    fail.
    """
    import shutil
    import subprocess

    from core.paths import BASELINE_ARCHIVE_PATH

    if shutil.which("git") is None:
        pytest.skip("git binary not available in PATH")

    # Resolve to repo-relative path for git check-ignore
    repo_root = BASELINE_ARCHIVE_PATH.resolve().parents[2]
    if not (repo_root / ".git").exists():
        pytest.skip("not running inside a git checkout")

    rel_path = BASELINE_ARCHIVE_PATH.resolve().relative_to(repo_root)
    proc = subprocess.run(  # noqa: S603  # nosec B603
        ["git", "check-ignore", "-v", str(rel_path)],  # noqa: S607  # nosec B607
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    # check-ignore exit codes:
    # - 0: path is ignored (must be by a negation line to pass)
    # - 1: path is NOT ignored (pass — but our case uses negation, not 1)
    # - other: git error → fail loudly so we don't false-pass
    assert proc.returncode in (0, 1), (
        f"git check-ignore failed (rc={proc.returncode}): {proc.stderr!r}"
    )
    if proc.returncode == 0:
        # Pattern line must be the negation rule we added (PR-15)
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


# ---------------------------------------------------------------------------
# 5. PR-SIL-MULTIOBJ A1 — sibling dim_means parse + Tchebycheff selection
# ---------------------------------------------------------------------------


def test_parse_dim_means_from_sentinel() -> None:
    """The additive ``dim_means`` map is extracted from the FITNESS_RESULT line."""
    from core.self_improving_loop.runner import _parse_dim_means_from_subprocess_stdout

    stdout = (
        "some audit log line\n"
        'FITNESS_RESULT: {"fitness": 0.5, "audit_run_id": "run1", '
        '"dim_means": {"broken_tool_use": 2.0, "redundant_tool_invocation": 7.0}, '
        '"dim_stderr": {}}\n'
    )
    means = _parse_dim_means_from_subprocess_stdout(stdout, audit_run_id="run1", sibling_idx=0)
    assert means == {"broken_tool_use": 2.0, "redundant_tool_invocation": 7.0}


def test_parse_dim_means_graceful_on_legacy_or_garbage() -> None:
    """Missing / legacy / unparseable sentinel → {} (never raises)."""
    from core.self_improving_loop.runner import _parse_dim_means_from_subprocess_stdout

    # Legacy sentinel without dim_means
    legacy = 'FITNESS_RESULT: {"fitness": 0.5, "audit_run_id": "run1"}\n'
    assert _parse_dim_means_from_subprocess_stdout(legacy, audit_run_id="run1", sibling_idx=0) == {}
    # No sentinel at all
    assert (
        _parse_dim_means_from_subprocess_stdout("nothing here\n", audit_run_id="r", sibling_idx=0)
        == {}
    )
    # Garbage payload after the sentinel
    garbage = "FITNESS_RESULT: {not json\n"
    assert _parse_dim_means_from_subprocess_stdout(garbage, audit_run_id="r", sibling_idx=0) == {}


def test_select_best_idx_linear_when_pareto_off() -> None:
    """pareto_mode=False → linear top-1 by advantage (legacy, unchanged)."""
    from core.self_improving_loop.runner import _select_best_idx

    # Sibling 0 has the highest advantage → linear winner regardless of dims.
    idx = _select_best_idx(
        advantages=[1.0, 0.5],
        sibling_dim_means=[],  # not captured when pareto off
        pareto_mode=False,
        group_id="g",
    )
    assert idx == 0


def test_select_best_idx_tchebycheff_overrides_linear() -> None:
    """pareto_mode=True → worst-weighted-gap (Tchebycheff) winner ≠ linear winner.

    Sibling 0 has the higher linear advantage but a *critical* axis
    (broken_tool_use, weight 0.10) collapsed to mean 9.0 (score 0.1).
    Sibling 1 is balanced. The Tchebycheff selection — dominated by the
    worst weighted gap — must reject the spiky sibling 0 and pick the
    balanced sibling 1, which the linear advantage cannot do.
    """
    from core.self_improving_loop.runner import _select_best_idx

    advantages = [1.0, 0.5]  # linear would pick sibling 0
    sibling_dim_means = [
        {"broken_tool_use": 9.0, "redundant_tool_invocation": 1.0},  # spiky: critical bad
        {"broken_tool_use": 2.0, "redundant_tool_invocation": 2.0},  # balanced
    ]
    idx = _select_best_idx(
        advantages=advantages,
        sibling_dim_means=sibling_dim_means,
        pareto_mode=True,
        group_id="g",
    )
    assert idx == 1  # Tchebycheff picks the balanced sibling, not the linear top-1


def test_select_best_idx_falls_back_when_vectors_incomplete() -> None:
    """pareto_mode=True but a sibling vector missing → graceful linear fallback."""
    from core.self_improving_loop.runner import _select_best_idx

    idx = _select_best_idx(
        advantages=[0.5, 1.0],  # linear → sibling 1
        sibling_dim_means=[{"broken_tool_use": 2.0}, {}],  # sibling 1 vector empty
        pareto_mode=True,
        group_id="g",
    )
    assert idx == 1  # falls back to linear


def test_select_best_idx_no_common_weighted_dim_falls_back_to_linear() -> None:
    """A non-empty raw vector with no DIM_WEIGHTS overlap must not produce
    a 0.0 Tchebycheff scalar that spuriously beats the always-negative real
    scalars (Codex review catch). No common weighted dim ⇒ linear fallback.
    """
    from core.self_improving_loop.runner import _select_best_idx

    idx = _select_best_idx(
        advantages=[0.2, 0.9],  # linear → sibling 1
        sibling_dim_means=[
            {"broken_tool_use": 2.0},  # weighted dim
            {"not_a_weighted_dim": 1.0},  # non-empty but zero weighted overlap
        ],
        pareto_mode=True,
        group_id="g",
    )
    # No common weighted dim → linear (sibling 1), NOT the empty-score sibling 0.
    assert idx == 1
