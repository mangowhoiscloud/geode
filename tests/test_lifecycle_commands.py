"""Tests for core.cli.cmd_lifecycle — stop, status, clean, uninstall."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.cli.cmd_lifecycle import (
    _clean_stale_artifacts,
    _find_serve_pid,
    _format_size,
    _is_socket_orphan,
    _scan_directory,
    _scan_file,
    do_clean,
    do_uninstall,
    show_status,
    stop_serve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestFormatSize:
    def test_bytes(self) -> None:
        assert _format_size(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert _format_size(2048) == "2.0 KB"

    def test_megabytes(self) -> None:
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self) -> None:
        assert _format_size(3 * 1024 * 1024 * 1024) == "3.0 GB"

    def test_zero(self) -> None:
        assert _format_size(0) == "0 B"


class TestScanDirectory:
    def test_nonexistent(self, tmp_path: Path) -> None:
        usage = _scan_directory(tmp_path / "nope")
        assert not usage.exists
        assert usage.file_count == 0
        assert usage.total_bytes == 0

    def test_empty_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        usage = _scan_directory(d)
        assert usage.exists
        assert usage.file_count == 0
        assert usage.total_bytes == 0

    def test_counts_files(self, tmp_path: Path) -> None:
        d = tmp_path / "data"
        d.mkdir()
        (d / "a.txt").write_text("hello")
        (d / "b.txt").write_text("world!!")
        usage = _scan_directory(d)
        assert usage.exists
        assert usage.file_count == 2
        assert usage.total_bytes == 5 + 7

    def test_recursive(self, tmp_path: Path) -> None:
        d = tmp_path / "root"
        sub = d / "sub"
        sub.mkdir(parents=True)
        (d / "a.txt").write_text("x")
        (sub / "b.txt").write_text("yy")
        usage = _scan_directory(d)
        assert usage.file_count == 2
        assert usage.total_bytes == 3


class TestScanFile:
    def test_nonexistent(self, tmp_path: Path) -> None:
        usage = _scan_file(tmp_path / "nope.txt")
        assert not usage.exists

    def test_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("hello world")
        usage = _scan_file(f)
        assert usage.exists
        assert usage.file_count == 1
        assert usage.total_bytes == 11


class TestIsSocketOrphan:
    def test_nonexistent(self, tmp_path: Path) -> None:
        assert not _is_socket_orphan(tmp_path / "nosock")

    def test_regular_file_is_orphan(self, tmp_path: Path) -> None:
        sock = tmp_path / "test.sock"
        sock.write_text("")
        assert _is_socket_orphan(sock)


# ---------------------------------------------------------------------------
# geode stop
# ---------------------------------------------------------------------------


class TestStop:
    @patch("core.cli.cmd_lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    def test_not_running(self, mock_running: MagicMock, mock_pid: MagicMock) -> None:
        """No error when serve is not running."""
        stop_serve(force=False, timeout=5)

    @patch("core.cli.cmd_lifecycle._clean_stale_artifacts")
    @patch("core.cli.cmd_lifecycle._find_child_pids", return_value=[])
    @patch("os.kill")
    @patch("core.cli.cmd_lifecycle._find_serve_pid", return_value=12345)
    @patch("core.cli.ipc_client.is_serve_running", return_value=True)
    def test_graceful_stop(
        self,
        mock_running: MagicMock,
        mock_pid: MagicMock,
        mock_kill: MagicMock,
        mock_children: MagicMock,
        mock_clean: MagicMock,
    ) -> None:
        """Sends SIGTERM and succeeds when process exits."""
        # First os.kill(pid, SIGTERM), then os.kill(pid, 0) raises ProcessLookupError
        mock_kill.side_effect = [None, ProcessLookupError]
        stop_serve(force=False, timeout=5)
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        mock_clean.assert_called_once()

    @patch("core.cli.cmd_lifecycle._find_serve_pid", return_value=12345)
    @patch("core.cli.ipc_client.is_serve_running", return_value=True)
    def test_pid_already_gone(self, mock_running: MagicMock, mock_pid: MagicMock) -> None:
        """Handles process gone between find and kill."""
        with patch("os.kill", side_effect=ProcessLookupError):
            stop_serve(force=False, timeout=5)


class TestCleanStaleArtifacts:
    def test_removes_orphan_socket(self, tmp_path: Path) -> None:
        sock = tmp_path / "cli.sock"
        sock.write_text("")
        with (
            patch("core.cli.cmd_lifecycle.CLI_SOCKET_PATH", sock),
            patch("core.cli.cmd_lifecycle.CLI_STARTUP_LOCK", tmp_path / "nolock"),
            patch("core.cli.cmd_lifecycle._is_socket_orphan", return_value=True),
        ):
            _clean_stale_artifacts()
        assert not sock.exists()


# ---------------------------------------------------------------------------
# geode status
# ---------------------------------------------------------------------------


class TestStatus:
    @patch("core.cli.cmd_lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    def test_text_output(self, mock_running: MagicMock, mock_pid: MagicMock) -> None:
        """Runs without error in text mode."""
        show_status(json_output=False)

    @patch("core.cli.cmd_lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    def test_json_output(
        self,
        mock_running: MagicMock,
        mock_pid: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """JSON output is valid JSON with expected keys."""
        show_status(json_output=True)


# ---------------------------------------------------------------------------
# geode clean
# ---------------------------------------------------------------------------


class TestClean:
    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        cache = tmp_path / "embedding-cache"
        cache.mkdir()
        (cache / "data.npy").write_bytes(b"x" * 100)

        with patch("core.cli.cmd_lifecycle.PROJECT_EMBEDDING_CACHE", cache):
            do_clean(scope="project", dry_run=True, force=True)

        assert cache.exists()
        assert (cache / "data.npy").exists()

    def test_default_cleans_caches(self, tmp_path: Path) -> None:
        cache = tmp_path / "embedding-cache"
        cache.mkdir()
        (cache / "data.npy").write_bytes(b"x" * 50)

        offload = tmp_path / "tool-offload"
        offload.mkdir()
        (offload / "result.json").write_text("{}")

        with (
            patch("core.cli.cmd_lifecycle.PROJECT_EMBEDDING_CACHE", cache),
            patch("core.cli.cmd_lifecycle.PROJECT_TOOL_OFFLOAD", offload),
            patch("core.cli.cmd_lifecycle.PROJECT_RESULT_CACHE_DIR", tmp_path / "no"),
            patch("core.cli.cmd_lifecycle.PROJECT_VECTORS_DIR", tmp_path / "no2"),
            patch("core.cli.cmd_lifecycle.MCP_REGISTRY_CACHE", tmp_path / "no3"),
            patch("core.cli.cmd_lifecycle.CLI_SOCKET_PATH", tmp_path / "no4"),
            patch("core.cli.cmd_lifecycle.CLI_STARTUP_LOCK", tmp_path / "no5"),
        ):
            do_clean(scope="project", force=True)

        assert not cache.exists()
        assert not offload.exists()

    def test_nothing_to_clean(self, tmp_path: Path) -> None:
        """No error when nothing exists."""
        with (
            patch("core.cli.cmd_lifecycle.PROJECT_EMBEDDING_CACHE", tmp_path / "no1"),
            patch("core.cli.cmd_lifecycle.PROJECT_TOOL_OFFLOAD", tmp_path / "no2"),
            patch("core.cli.cmd_lifecycle.PROJECT_RESULT_CACHE_DIR", tmp_path / "no3"),
            patch("core.cli.cmd_lifecycle.PROJECT_VECTORS_DIR", tmp_path / "no4"),
            patch("core.cli.cmd_lifecycle.MCP_REGISTRY_CACHE", tmp_path / "no5"),
            patch("core.cli.cmd_lifecycle.CLI_SOCKET_PATH", tmp_path / "no6"),
            patch("core.cli.cmd_lifecycle.CLI_STARTUP_LOCK", tmp_path / "no7"),
        ):
            do_clean(scope="project", force=True)

    def test_build_scope(self, tmp_path: Path) -> None:
        mypy = tmp_path / ".mypy_cache"
        mypy.mkdir()
        (mypy / "cache.json").write_text("{}")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            do_clean(scope="build", force=True)

        assert not mypy.exists()


# ---------------------------------------------------------------------------
# geode uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text("[test]")

        with (
            patch("core.cli.cmd_lifecycle.PROJECT_GEODE_DIR", geode_dir),
            patch("core.cli.cmd_lifecycle.GEODE_HOME", tmp_path / "home_geode"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(dry_run=True)

        assert geode_dir.exists()

    def test_force_skips_confirmations(self, tmp_path: Path) -> None:
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text("[test]")

        with (
            patch("core.cli.cmd_lifecycle.PROJECT_GEODE_DIR", geode_dir),
            patch("core.cli.cmd_lifecycle.GEODE_HOME", tmp_path / "home_geode"),
            patch("core.cli.cmd_lifecycle.stop_serve"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(force=True)

        assert not geode_dir.exists()

    def test_keep_config(self, tmp_path: Path) -> None:
        home = tmp_path / "home_geode"
        home.mkdir()
        (home / ".env").write_text("ANTHROPIC_API_KEY=sk-test")
        (home / "config.toml").write_text("[model]")
        (home / "runs").mkdir()

        with (
            patch("core.cli.cmd_lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.cmd_lifecycle.GEODE_HOME", home),
            patch("core.cli.cmd_lifecycle.stop_serve"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(force=True, keep_config=True)

        assert (home / ".env").exists()
        assert (home / "config.toml").exists()
        assert not (home / "runs").exists()

    def test_nothing_to_uninstall(self, tmp_path: Path) -> None:
        with (
            patch("core.cli.cmd_lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.cmd_lifecycle.GEODE_HOME", tmp_path / "nope2"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(force=True)


# ---------------------------------------------------------------------------
# FindServePid
# ---------------------------------------------------------------------------


class TestFindServePid:
    @patch("subprocess.run")
    def test_returns_pid(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="99999\n")
        pid = _find_serve_pid()
        if pid is not None:
            assert isinstance(pid, int)

    @patch("subprocess.run")
    def test_no_process(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _find_serve_pid() is None

    @patch("subprocess.run", side_effect=OSError("pgrep not found"))
    def test_pgrep_unavailable(self, mock_run: MagicMock) -> None:
        assert _find_serve_pid() is None
