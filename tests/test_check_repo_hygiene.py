"""Unit tests for scripts/check_repo_hygiene.py ratchet."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_repo_hygiene.py"


def run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the ratchet script with the given working directory."""
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_repo_passes(tmp_path: Path) -> None:
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr


def test_dangling_symlink_fails(tmp_path: Path) -> None:
    # Relative-path symlink to a nonexistent target → dangling only, not absolute
    (tmp_path / "broken").symlink_to("nonexistent-target")
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "dangling symlink" in result.stderr
    assert "broken" in result.stderr


def test_absolute_symlink_fails(tmp_path: Path) -> None:
    # Symlink to an existing absolute path → absolute only, not dangling
    real = tmp_path / "real_file"
    real.write_text("ok")
    (tmp_path / "abslink").symlink_to(str(real))  # str of absolute path
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "absolute symlink" in result.stderr
    assert "abslink" in result.stderr
    assert "ln -sr" in result.stderr


def test_orphan_worktree_fails(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "worktrees" / "abandoned").mkdir(parents=True)
    # no .owner file
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "orphan worktree" in result.stderr
    assert "abandoned" in result.stderr
    assert "missing .owner" in result.stderr


def test_valid_worktree_passes(tmp_path: Path) -> None:
    worktree = tmp_path / ".claude" / "worktrees" / "valid"
    worktree.mkdir(parents=True)
    (worktree / ".owner").write_text("session=x task_id=y\n")
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr


def test_excluded_paths_ignored(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    # A dangling symlink inside .git/ must be ignored
    (git_dir / "broken").symlink_to("nonexistent")
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr
