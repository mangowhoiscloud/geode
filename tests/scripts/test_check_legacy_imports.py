"""Legacy import checks must distinguish empty diffs from failed Git queries."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_legacy_imports as checker
from scripts.git_command import run_git


def _git(root: Path, *args: str) -> str:
    result = run_git(args, cwd=root)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "GEODE CI")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    (tmp_path / "module.py").write_text("from core import config\n", encoding="utf-8")
    _git(tmp_path, "add", "module.py")
    tree = _git(tmp_path, "write-tree")
    base = _git(tmp_path, "commit-tree", tree, "-m", "base")
    legacy_module = "core.nodes"
    (tmp_path / "module.py").write_text(f"from {legacy_module} import legacy\n", encoding="utf-8")
    _git(tmp_path, "add", "module.py")
    tree = _git(tmp_path, "write-tree")
    head = _git(tmp_path, "commit-tree", tree, "-p", base, "-m", "legacy import")
    _git(tmp_path, "update-ref", "HEAD", head)
    _git(tmp_path, "update-ref", "refs/remotes/origin/develop", head)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("base", "status", "output"),
    [
        ("HEAD", 0, "No legacy imports in 0 changed files."),
        ("HEAD^", 1, "module.py:1: use external package nodes"),
        ("missing-ref", 1, "cannot compare"),
        ("module.py", 1, "cannot compare"),
    ],
)
def test_real_git_diff_requires_a_resolvable_base(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    base: str,
    status: int,
    output: str,
) -> None:
    monkeypatch.setattr("sys.argv", ["check_legacy_imports.py", "--base-ref", base])
    assert checker.main() == status
    captured = capsys.readouterr()
    assert output in captured.out + captured.err
    if base == "HEAD^":
        # On develop pushes this remote ref already points to the new HEAD.
        assert _git(repository, "diff", "--name-only", "origin/develop", "HEAD") == ""


@pytest.mark.parametrize("args", [["--base-ref"], ["--base-ref", ""], ["--base-ref=--stat"]])
def test_invalid_base_arguments_fail_before_git(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["check_legacy_imports.py", *args])
    with pytest.raises(SystemExit) as raised:
        checker.main()
    assert raised.value.code == 2
