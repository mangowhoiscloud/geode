"""Tests for core.cli.commands.lifecycle — stop, status, clean, uninstall."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.cli.commands.lifecycle import (
    _clean_stale_artifacts,
    _find_serve_pid,
    _format_size,
    _is_socket_orphan,
    _scan_directory,
    _scan_file,
    _start_serve_background,
    do_clean,
    do_uninstall,
    do_update,
    show_status,
    stop_serve,
)
from core.cli.update_provenance import UpdateKind, UpdateTarget

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
    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    def test_not_running(self, mock_running: MagicMock, mock_pid: MagicMock) -> None:
        """No error when serve is not running."""
        assert stop_serve(force=False, timeout=5)

    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=True)
    def test_active_socket_without_pid_is_not_stopped(
        self,
        mock_running: MagicMock,
        mock_pid: MagicMock,
    ) -> None:
        assert not stop_serve(force=True, timeout=5)

    @patch("core.cli.commands.lifecycle._clean_stale_artifacts")
    @patch("core.cli.commands.lifecycle._find_child_pids", return_value=[])
    @patch("os.kill")
    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=12345)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
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
        assert stop_serve(force=False, timeout=5)
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        mock_clean.assert_called_once()

    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=12345)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    def test_pid_already_gone(self, mock_running: MagicMock, mock_pid: MagicMock) -> None:
        """Handles process gone between find and kill."""
        with patch("os.kill", side_effect=ProcessLookupError):
            assert stop_serve(force=False, timeout=5)


class TestStartServe:
    def test_waits_for_socket_readiness(self, tmp_path: Path) -> None:
        executable = str(tmp_path / "bin" / "geode")
        with (
            patch("core.cli.commands.lifecycle.subprocess.Popen") as popen,
            patch(
                "core.cli.ipc_client.is_serve_running",
                side_effect=[False, True],
            ) as running,
            patch("core.cli.commands.lifecycle.time.sleep"),
        ):
            assert _start_serve_background(executable=executable)

        popen.assert_called_once()
        assert popen.call_args.args[0] == [executable, "serve"]
        assert running.call_count == 2


class TestCleanStaleArtifacts:
    def test_removes_orphan_socket(self, tmp_path: Path) -> None:
        sock = tmp_path / "cli.sock"
        sock.write_text("")
        with (
            patch("core.cli.commands.lifecycle.CLI_SOCKET_PATH", sock),
            patch("core.cli.commands.lifecycle.CLI_STARTUP_LOCK", tmp_path / "nolock"),
            patch("core.cli.commands.lifecycle._is_socket_orphan", return_value=True),
        ):
            _clean_stale_artifacts()
        assert not sock.exists()


# ---------------------------------------------------------------------------
# geode status
# ---------------------------------------------------------------------------


class TestStatus:
    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    def test_text_output(self, mock_running: MagicMock, mock_pid: MagicMock) -> None:
        """Runs without error in text mode."""
        show_status(json_output=False)

    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None)
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
        # v0.95.x — `PROJECT_EMBEDDING_CACHE` was removed (vestigial). Use
        # `PROJECT_TOOL_OFFLOAD` (still live) for the dry-run guard test.
        offload = tmp_path / "tool-offload"
        offload.mkdir()
        (offload / "result.json").write_text("payload")

        with patch("core.cli.commands.lifecycle.PROJECT_TOOL_OFFLOAD", offload):
            do_clean(scope="project", dry_run=True, force=True)

        assert offload.exists()
        assert (offload / "result.json").exists()

    def test_default_cleans_caches(self, tmp_path: Path) -> None:
        offload = tmp_path / "tool-offload"
        offload.mkdir()
        (offload / "result.json").write_text("{}")

        result_cache = tmp_path / "result_cache"
        result_cache.mkdir()
        (result_cache / "cached.json").write_text("{}")

        with (
            patch("core.cli.commands.lifecycle.PROJECT_TOOL_OFFLOAD", offload),
            patch("core.cli.commands.lifecycle.PROJECT_RESULT_CACHE_DIR", result_cache),
            patch("core.cli.commands.lifecycle.MCP_REGISTRY_CACHE", tmp_path / "no3"),
            patch("core.cli.commands.lifecycle.CLI_SOCKET_PATH", tmp_path / "no4"),
            patch("core.cli.commands.lifecycle.CLI_STARTUP_LOCK", tmp_path / "no5"),
        ):
            do_clean(scope="project", force=True)

        assert not offload.exists()
        assert not result_cache.exists()

    def test_nothing_to_clean(self, tmp_path: Path) -> None:
        """No error when nothing exists."""
        with (
            patch("core.cli.commands.lifecycle.PROJECT_TOOL_OFFLOAD", tmp_path / "no2"),
            patch("core.cli.commands.lifecycle.PROJECT_RESULT_CACHE_DIR", tmp_path / "no3"),
            patch("core.cli.commands.lifecycle.MCP_REGISTRY_CACHE", tmp_path / "no5"),
            patch("core.cli.commands.lifecycle.CLI_SOCKET_PATH", tmp_path / "no6"),
            patch("core.cli.commands.lifecycle.CLI_STARTUP_LOCK", tmp_path / "no7"),
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
# geode update
# ---------------------------------------------------------------------------


class TestUpdate:
    @patch("core.cli.commands.lifecycle._start_serve_background")
    @patch("core.cli.commands.lifecycle.stop_serve", return_value=True)
    @patch("core.cli.commands.lifecycle._run_update_step", return_value=True)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    @patch("core.cli.commands.lifecycle._has_dirty_worktree", return_value=False)
    @patch("core.cli.commands.lifecycle.detect_update_target")
    def test_runs_expected_steps(
        self,
        mock_target: MagicMock,
        mock_dirty: MagicMock,
        mock_running: MagicMock,
        mock_step: MagicMock,
        mock_stop: MagicMock,
        mock_start: MagicMock,
        tmp_path: Path,
    ) -> None:
        tool_dir = tmp_path / "custom-tools"
        bin_dir = tmp_path / "custom-bin"
        mock_target.return_value = UpdateTarget(
            UpdateKind.SOURCE,
            source_root=tmp_path,
            uv_tool_dir=tool_dir,
            uv_tool_bin_dir=bin_dir,
        )

        assert do_update(force=False, dry_run=False, restart=True)

        commands = [call.args[1] for call in mock_step.call_args_list]
        assert commands == [
            ["git", "pull", "--ff-only"],
            ["uv", "sync"],
            ["uv", "tool", "install", "-e", ".", "--force"],
            [str(bin_dir / "geode"), "version"],
        ]
        assert mock_step.call_args_list[2].kwargs["extra_env"] == {
            "UV_TOOL_DIR": str(tool_dir),
            "UV_TOOL_BIN_DIR": str(bin_dir),
        }
        mock_stop.assert_not_called()
        mock_start.assert_not_called()

    @patch("core.cli.commands.lifecycle._run_update_step")
    @patch("core.cli.commands.lifecycle._has_dirty_worktree", return_value=True)
    @patch("core.cli.commands.lifecycle.detect_update_target")
    def test_dirty_checkout_requires_force(
        self,
        mock_target: MagicMock,
        mock_dirty: MagicMock,
        mock_step: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_target.return_value = UpdateTarget(UpdateKind.SOURCE, source_root=tmp_path)

        assert not do_update(force=False)
        mock_step.assert_not_called()

    @patch("core.cli.commands.lifecycle._start_serve_background", return_value=True)
    @patch("core.cli.commands.lifecycle.stop_serve", return_value=True)
    @patch("core.cli.commands.lifecycle._run_update_step", return_value=True)
    @patch("core.cli.ipc_client.is_serve_running", return_value=True)
    @patch("core.cli.commands.lifecycle._has_dirty_worktree", return_value=False)
    @patch("core.cli.commands.lifecycle.detect_update_target")
    def test_restarts_serve_when_it_was_running(
        self,
        mock_target: MagicMock,
        mock_dirty: MagicMock,
        mock_running: MagicMock,
        mock_step: MagicMock,
        mock_stop: MagicMock,
        mock_start: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_target.return_value = UpdateTarget(UpdateKind.SOURCE, source_root=tmp_path)

        assert do_update(restart=True)

        mock_stop.assert_called_once_with(force=True, timeout=10)
        mock_start.assert_called_once_with(dry_run=False, executable="geode")

    def test_uv_tool_defaults_to_current_patch_series(self, tmp_path: Path) -> None:
        tool_dir = tmp_path / "custom-tools"
        bin_dir = tmp_path / "custom-bin"
        with (
            patch("core.__version__", "0.99.333"),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tool_dir,
                    uv_tool_bin_dir=bin_dir,
                ),
            ),
            patch("core.cli.ipc_client.is_serve_running", return_value=False),
            patch("core.cli.commands.lifecycle._run_update_step", return_value=True) as step,
        ):
            assert do_update()

        commands = [call.args[1] for call in step.call_args_list]
        assert commands == [
            [
                "uv",
                "tool",
                "install",
                "--upgrade",
                "--no-config",
                "--no-sources",
                "geode-agent~=0.99.333",
            ],
            [str(bin_dir / "geode"), "version"],
        ]
        working_dirs = {call.kwargs["cwd"] for call in step.call_args_list}
        assert len(working_dirs) == 1
        isolated_cwd = working_dirs.pop()
        assert isolated_cwd != Path.cwd()
        assert isolated_cwd.name.startswith("geode-update-")
        assert step.call_args_list[0].kwargs["extra_env"] == {
            "UV_TOOL_DIR": str(tool_dir),
            "UV_TOOL_BIN_DIR": str(bin_dir),
        }
        assert step.call_args_list[1].kwargs["extra_env"] is None

    def test_uv_tool_latest_is_explicit(self, tmp_path: Path) -> None:
        with (
            patch("core.__version__", "0.99.333"),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=tmp_path / "bin",
                ),
            ),
            patch("core.cli.ipc_client.is_serve_running", return_value=False),
            patch("core.cli.commands.lifecycle._run_update_step", return_value=True) as step,
        ):
            assert do_update(latest=True)

        assert step.call_args_list[0].args[1] == [
            "uv",
            "tool",
            "install",
            "--upgrade",
            "--no-config",
            "--no-sources",
            "geode-agent@latest",
        ]

    def test_uv_tool_leaves_existing_serve_running_when_update_fails(
        self,
        tmp_path: Path,
    ) -> None:
        with (
            patch("core.__version__", "0.99.333"),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=tmp_path / "bin",
                ),
            ),
            patch("core.cli.ipc_client.is_serve_running", return_value=True),
            patch("core.cli.commands.lifecycle.stop_serve") as stop,
            patch("core.cli.commands.lifecycle._run_update_step", return_value=False),
            patch(
                "core.cli.commands.lifecycle._start_serve_background",
                return_value=True,
            ) as start,
        ):
            assert not do_update()

        stop.assert_not_called()
        start.assert_not_called()

    def test_uv_tool_restarts_with_receipt_entrypoint(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "custom-bin"
        with (
            patch("core.__version__", "0.99.333"),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=bin_dir,
                ),
            ),
            patch("core.cli.ipc_client.is_serve_running", return_value=True),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
            patch("core.cli.commands.lifecycle._run_update_step", return_value=True),
            patch(
                "core.cli.commands.lifecycle._start_serve_background",
                return_value=True,
            ) as start,
        ):
            assert do_update()

        start.assert_called_once_with(
            dry_run=False,
            executable=str(bin_dir / "geode"),
        )
        stop.assert_called_once_with(force=True, timeout=10)

    def test_uv_tool_stops_only_after_install_and_verification(self, tmp_path: Path) -> None:
        events: list[str] = []

        def record_step(label: str, *_args: object, **_kwargs: object) -> bool:
            events.append(label)
            return True

        def record_stop(**_kwargs: object) -> bool:
            events.append("stop")
            return True

        def record_start(**_kwargs: object) -> bool:
            events.append("start")
            return True

        with (
            patch("core.__version__", "0.99.333"),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=tmp_path / "bin",
                ),
            ),
            patch("core.cli.ipc_client.is_serve_running", return_value=True),
            patch("core.cli.commands.lifecycle.stop_serve", side_effect=record_stop),
            patch("core.cli.commands.lifecycle._run_update_step", side_effect=record_step),
            patch(
                "core.cli.commands.lifecycle._start_serve_background",
                side_effect=record_start,
            ),
        ):
            assert do_update()

        assert events == [
            "Resolve and install GEODE update",
            "Verify CLI version",
            "stop",
            "start",
        ]

    def test_uv_tool_does_not_start_second_daemon_when_stop_fails(
        self,
        tmp_path: Path,
    ) -> None:
        with (
            patch("core.__version__", "0.99.333"),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=tmp_path / "bin",
                ),
            ),
            patch("core.cli.ipc_client.is_serve_running", return_value=True),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=False) as stop,
            patch("core.cli.commands.lifecycle._run_update_step", return_value=True),
            patch("core.cli.commands.lifecycle._start_serve_background") as start,
        ):
            assert not do_update()

        stop.assert_called_once_with(force=True, timeout=10)
        start.assert_not_called()

    def test_unsupported_install_does_not_run_commands(self) -> None:
        with (
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UNSUPPORTED,
                    reason="unsupported test install",
                ),
            ),
            patch("core.cli.commands.lifecycle._run_update_step") as step,
        ):
            assert not do_update()

        step.assert_not_called()


# ---------------------------------------------------------------------------
# geode uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text("[test]")

        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", geode_dir),
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "home_geode"),
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
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", geode_dir),
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "home_geode"),
            patch("core.cli.commands.lifecycle.stop_serve"),
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
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.commands.lifecycle.GEODE_HOME", home),
            patch("core.cli.commands.lifecycle.stop_serve"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(force=True, keep_config=True)

        assert (home / ".env").exists()
        assert (home / "config.toml").exists()
        assert not (home / "runs").exists()

    def test_nothing_to_uninstall(self, tmp_path: Path) -> None:
        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "nope2"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(force=True)

    def test_uninstalls_geode_agent_distribution(self, tmp_path: Path) -> None:
        geode_bin = tmp_path / "bin" / "geode"
        geode_bin.parent.mkdir()
        geode_bin.write_text("#!/bin/sh\n", encoding="utf-8")

        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "nope2"),
            patch("core.cli.commands.lifecycle.stop_serve"),
            patch("core.cli.commands.lifecycle.subprocess.run") as mock_run,
            patch("shutil.which", return_value=str(geode_bin)),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            do_uninstall(force=True)

        mock_run.assert_any_call(
            ["uv", "tool", "uninstall", "geode-agent"],
            capture_output=True,
            text=True,
            timeout=30,
        )


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
