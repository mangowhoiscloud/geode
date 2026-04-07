"""Tests for centralized path validation — core.tools.sandbox."""

from __future__ import annotations

import os
from pathlib import Path

import core.paths as paths_mod
import pytest
from core.tools import sandbox


@pytest.fixture(autouse=True)
def _sandbox_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect sandbox root to tmp_path for all tests."""
    _root = lambda: tmp_path
    monkeypatch.setattr(paths_mod, "get_project_root", _root)
    monkeypatch.setattr("core.tools.sandbox.get_project_root", _root)
    sandbox._additional_dirs.clear()
    sandbox._resolve_symlink_cached.cache_clear()


# ---------------------------------------------------------------------------
# Shell expansion blocking (G4)
# ---------------------------------------------------------------------------


class TestShellExpansion:
    def test_blocks_dollar_var(self):
        err = sandbox.check_shell_expansion("$HOME/file.txt")
        assert err is not None
        assert err["error_type"] == "permission"

    def test_blocks_dollar_brace(self):
        err = sandbox.check_shell_expansion("${HOME}/file.txt")
        assert err is not None

    def test_blocks_dollar_paren(self):
        err = sandbox.check_shell_expansion("$(whoami)/file.txt")
        assert err is not None

    def test_blocks_percent(self):
        err = sandbox.check_shell_expansion("%TEMP%/file.txt")
        assert err is not None

    def test_blocks_zsh_equals(self):
        err = sandbox.check_shell_expansion("=rg")
        assert err is not None

    def test_blocks_tilde_user(self):
        err = sandbox.check_shell_expansion("~otheruser/file.txt")
        assert err is not None

    def test_blocks_tilde_plus(self):
        err = sandbox.check_shell_expansion("~+/file.txt")
        assert err is not None

    def test_blocks_tilde_minus(self):
        err = sandbox.check_shell_expansion("~-/file.txt")
        assert err is not None

    def test_allows_bare_tilde(self):
        assert sandbox.check_shell_expansion("~/file.txt") is None

    def test_allows_normal_path(self):
        assert sandbox.check_shell_expansion("core/tools/file.py") is None

    def test_allows_absolute_path(self):
        assert sandbox.check_shell_expansion("/tmp/file.txt") is None  # noqa: S108


# ---------------------------------------------------------------------------
# Dangerous file/directory blocking (G3)
# ---------------------------------------------------------------------------


class TestDangerousPath:
    def test_blocks_gitconfig_write(self, tmp_path: Path):
        path = tmp_path / ".gitconfig"
        err = sandbox.check_dangerous_path(path, write=True)
        assert err is not None
        assert "dangerous file" in err["error"].lower()

    def test_allows_gitconfig_read(self, tmp_path: Path):
        path = tmp_path / ".gitconfig"
        assert sandbox.check_dangerous_path(path, write=False) is None

    def test_blocks_bashrc_write(self, tmp_path: Path):
        path = tmp_path / ".bashrc"
        err = sandbox.check_dangerous_path(path, write=True)
        assert err is not None

    def test_blocks_git_dir_write(self, tmp_path: Path):
        path = tmp_path / ".git" / "config"
        err = sandbox.check_dangerous_path(path, write=True)
        assert err is not None
        assert "dangerous directory" in err["error"].lower()

    def test_allows_git_dir_read(self, tmp_path: Path):
        path = tmp_path / ".git" / "config"
        assert sandbox.check_dangerous_path(path, write=False) is None

    def test_blocks_claude_dir_write(self, tmp_path: Path):
        path = tmp_path / ".claude" / "settings.json"
        err = sandbox.check_dangerous_path(path, write=True)
        assert err is not None

    def test_allows_normal_file_write(self, tmp_path: Path):
        path = tmp_path / "core" / "tools" / "file.py"
        assert sandbox.check_dangerous_path(path, write=True) is None


# ---------------------------------------------------------------------------
# Glob-in-write blocking (G12)
# ---------------------------------------------------------------------------


class TestGlobInWrite:
    def test_blocks_asterisk(self):
        err = sandbox.check_glob_in_write("src/*.py")
        assert err is not None

    def test_blocks_question_mark(self):
        err = sandbox.check_glob_in_write("file?.txt")
        assert err is not None

    def test_blocks_brackets(self):
        err = sandbox.check_glob_in_write("file[0-9].txt")
        assert err is not None

    def test_blocks_braces(self):
        err = sandbox.check_glob_in_write("file{a,b}.txt")
        assert err is not None

    def test_allows_normal_write_path(self):
        assert sandbox.check_glob_in_write("src/main.py") is None


# ---------------------------------------------------------------------------
# macOS path normalization (G7)
# ---------------------------------------------------------------------------


class TestMacOSNormalization:
    def test_normalizes_private_var(self):
        assert sandbox.normalize_macos_path("/private/var/folders/x") == "/var/folders/x"

    def test_normalizes_private_tmp(self):
        assert sandbox.normalize_macos_path("/private/tmp/file.txt") == "/tmp/file.txt"  # noqa: S108

    def test_normalizes_private_tmp_bare(self):
        assert sandbox.normalize_macos_path("/private/tmp") == "/tmp"  # noqa: S108

    def test_preserves_normal_path(self):
        assert sandbox.normalize_macos_path("/Users/mango/file.txt") == "/Users/mango/file.txt"

    def test_preserves_var_without_private(self):
        assert sandbox.normalize_macos_path("/var/folders/x") == "/var/folders/x"


# ---------------------------------------------------------------------------
# Symlink chain resolution (G2, G11)
# ---------------------------------------------------------------------------


class TestSymlinkChain:
    def test_resolves_valid_symlink(self, tmp_path: Path):
        real = tmp_path / "real.txt"
        real.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        result = sandbox.resolve_symlink_chain(link, [tmp_path])
        assert isinstance(result, Path)
        assert result == real.resolve()

    def test_rejects_escaping_symlink(self, tmp_path: Path):
        external = tmp_path.parent / f"sandbox_test_{os.getpid()}.txt"
        external.write_text("external")
        try:
            link = tmp_path / "escape.txt"
            link.symlink_to(external)

            result = sandbox.resolve_symlink_chain(link, [tmp_path])
            assert isinstance(result, dict)
            assert "error" in result
        finally:
            external.unlink(missing_ok=True)

    def test_rejects_circular_symlink(self, tmp_path: Path):
        link_a = tmp_path / "a"
        link_b = tmp_path / "b"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)

        result = sandbox.resolve_symlink_chain(link_a, [tmp_path])
        assert isinstance(result, dict)
        assert "circular" in result["error"].lower() or "outside" in result["error"].lower()


# ---------------------------------------------------------------------------
# validate_path() orchestrator
# ---------------------------------------------------------------------------


class TestValidatePath:
    def test_allows_relative_path(self, tmp_path: Path):
        (tmp_path / "file.py").write_text("x")
        result = sandbox.validate_path("file.py", write=False)
        assert isinstance(result, Path)

    def test_allows_absolute_inside(self, tmp_path: Path):
        f = tmp_path / "file.py"
        f.write_text("x")
        result = sandbox.validate_path(str(f), write=False)
        assert isinstance(result, Path)

    def test_rejects_outside_path(self, tmp_path: Path):
        result = sandbox.validate_path("/etc/passwd", write=False)
        assert isinstance(result, dict)
        assert "error" in result

    def test_rejects_shell_expansion(self, tmp_path: Path):
        result = sandbox.validate_path("$HOME/file.txt", write=False)
        assert isinstance(result, dict)
        assert "shell expansion" in result["error"].lower()

    def test_rejects_dangerous_write(self, tmp_path: Path):
        (tmp_path / ".gitconfig").write_text("x")
        result = sandbox.validate_path(".gitconfig", write=True)
        assert isinstance(result, dict)
        assert "dangerous" in result["error"].lower()

    def test_allows_dangerous_read(self, tmp_path: Path):
        (tmp_path / ".gitconfig").write_text("x")
        result = sandbox.validate_path(".gitconfig", write=False)
        assert isinstance(result, Path)

    def test_rejects_glob_in_write(self, tmp_path: Path):
        result = sandbox.validate_path("src/*.py", write=True)
        assert isinstance(result, dict)
        assert "glob" in result["error"].lower()

    def test_allows_glob_in_read(self, tmp_path: Path):
        # Glob chars in read paths are allowed (Glob tool uses them)
        # validate_path won't error — the path just won't exist
        result = sandbox.validate_path("src/*.py", write=False)
        # Either Path (resolved) or error (outside sandbox) — both acceptable
        # The key: no glob-specific error
        if isinstance(result, dict):
            assert "glob" not in result.get("error", "").lower()

    def test_resolves_symlink_inside(self, tmp_path: Path):
        real = tmp_path / "real.txt"
        real.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        result = sandbox.validate_path(str(link), write=False)
        assert isinstance(result, Path)

    def test_additional_dir_expands_sandbox(self, tmp_path: Path):
        extra = tmp_path.parent / "extra_dir"
        extra.mkdir(exist_ok=True)
        target = extra / "file.txt"
        target.write_text("content")

        # Without additional dir — blocked
        result = sandbox.validate_path(str(target), write=False)
        assert isinstance(result, dict)

        # With additional dir — allowed
        sandbox.add_working_directory(extra)
        result = sandbox.validate_path(str(target), write=False)
        assert isinstance(result, Path)
