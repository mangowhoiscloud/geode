"""Unit tests for scripts/check_repo_hygiene.py ratchet."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_repo_hygiene.py"


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


def test_release_venv_symlinks_ignored(tmp_path: Path) -> None:
    release_bin = tmp_path / ".release-venv" / "bin"
    release_bin.mkdir(parents=True)
    (release_bin / "python3.12").symlink_to("/usr/bin/python3")

    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr


def test_petri_bundle_absent_passes(tmp_path: Path) -> None:
    # No docs/self-improving/petri-bundle/ directory at all → ratchet must not trip.
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr


def test_petri_bundle_at_floor_passes(tmp_path: Path) -> None:
    from scripts.check_repo_hygiene import PETRI_EVAL_FLOOR

    logs = tmp_path / "docs" / "self-improving/petri-bundle" / "logs"
    logs.mkdir(parents=True)
    for i in range(PETRI_EVAL_FLOOR):
        (logs / f"archive-{i}.eval").write_bytes(b"placeholder")
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_petri_bundle_below_floor_fails(tmp_path: Path) -> None:
    from scripts.check_repo_hygiene import PETRI_EVAL_FLOOR

    logs = tmp_path / "docs" / "self-improving/petri-bundle" / "logs"
    logs.mkdir(parents=True)
    for i in range(PETRI_EVAL_FLOOR - 1):
        (logs / f"archive-{i}.eval").write_bytes(b"placeholder")
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "petri bundle deletion" in result.stderr
    assert f"floor is {PETRI_EVAL_FLOOR}" in result.stderr


def _init_git_repo(root: Path) -> None:
    """Minimal git repo so `git grep` (used by the home-path-leak check) works."""
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)  # noqa: S603


def test_real_username_home_path_fails(tmp_path: Path) -> None:
    """A tracked file embedding /Users/<real-username>/ is a PII leak → fail.

    The leak path is assembled at runtime (not a source literal) so this very
    test file does not itself trip the hygiene gate it exercises."""
    _init_git_repo(tmp_path)
    username = "operator9"  # not in _PLACEHOLDER_USERS
    leak = f"/Users/{username}/workspace/geode/state/x"
    (tmp_path / "run.json").write_text(f'{{"run_dir": "{leak}"}}\n')
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)  # noqa: S607
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "hardcoded home path" in result.stderr
    assert username in result.stderr


def test_bare_and_capitalized_home_path_fails(tmp_path: Path) -> None:
    """A bare ``/Users/<name>`` (no trailing component) and a capitalised
    username are both leaks (Codex review — the trailing-slash and lowercase
    gaps)."""
    _init_git_repo(tmp_path)
    bare = "/Users/" + "operator9"  # no trailing slash; split so the source has no literal
    cap = "/home/" + "Operator9"  # capitalised
    (tmp_path / "a.txt").write_text(f"see {bare}\n")
    (tmp_path / "b.txt").write_text(f"see {cap}\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)  # noqa: S607
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr.count("hardcoded home path") == 1
    assert "operator9" in result.stderr.lower()


def test_placeholder_home_path_passes(tmp_path: Path) -> None:
    """Generic placeholder usernames (user / dev / foo / <name> / Shared) are allowed."""
    _init_git_repo(tmp_path)
    (tmp_path / "doc.md").write_text(
        "Example: /home/user/workspace/geode and /Users/<name>/x and /Users/foo/y "
        "and /Users/Shared/data and /Users/dev\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)  # noqa: S607
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr
