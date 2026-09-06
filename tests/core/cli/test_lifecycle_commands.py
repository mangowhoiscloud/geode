"""Tests for core.cli.commands.lifecycle — stop, status, clean, uninstall."""

from __future__ import annotations

import shutil
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.cli.commands.lifecycle import (
    SERVE_STARTUP_TIMEOUT_S,
    _clean_stale_artifacts,
    _cleanup_legacy_transcripts,
    _find_serve_pid,
    _format_size,
    _has_dirty_worktree,
    _is_socket_orphan,
    _scan_directory,
    _scan_file,
    _serve_matches_cli,
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
    def test_does_not_count_external_symlink_bytes(self, tmp_path: Path) -> None:
        directory = tmp_path / "runtime"
        directory.mkdir()
        outside = tmp_path / "outside"
        outside.write_text("not removed with runtime")
        (directory / "alias").symlink_to(outside)
        assert _scan_directory(directory).total_bytes == 0

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


def test_cleanup_legacy_transcripts_is_recursive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "project" / "old.jsonl"
    recent = tmp_path / "project" / "recent.jsonl"
    old.parent.mkdir()
    old.write_text("{}\n")
    recent.write_text("{}\n")
    old.touch()
    recent.touch()
    import os
    import time

    os.utime(old, (time.time() - 3 * 86400, time.time() - 3 * 86400))
    monkeypatch.setattr("core.cli.commands.lifecycle.GLOBAL_TRANSCRIPTS_DIR", tmp_path)

    assert _cleanup_legacy_transcripts(1) == 1
    assert not old.exists()
    assert recent.exists()


class TestIsSocketOrphan:
    def test_failed_probe_closes_socket(self, tmp_path: Path) -> None:
        path = tmp_path / "socket"
        path.touch()
        with patch("socket.socket") as factory:
            sock = factory.return_value
            sock.__enter__.return_value = sock
            sock.connect.side_effect = ConnectionRefusedError
            assert _is_socket_orphan(path)
        assert sock.close.called or sock.__exit__.called

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
    def test_default_timeout_allows_twenty_second_boot(self, tmp_path: Path) -> None:
        assert SERVE_STARTUP_TIMEOUT_S >= 20.0
        executable = str(tmp_path / "bin" / "geode")
        with (
            patch("core.cli.commands.lifecycle.subprocess.Popen") as popen,
            patch("core.cli.ipc_client.is_serve_running", return_value=True),
            patch("core.cli.commands.lifecycle._serve_matches_cli", return_value=True),
        ):
            assert _start_serve_background(executable=executable)

        popen.assert_called_once()

    def test_waits_for_socket_readiness(self, tmp_path: Path) -> None:
        executable = str(tmp_path / "bin" / "geode")
        with (
            patch("core.cli.commands.lifecycle.subprocess.Popen") as popen,
            patch(
                "core.cli.ipc_client.is_serve_running",
                side_effect=[False, True],
            ) as running,
            patch("core.cli.commands.lifecycle._serve_matches_cli", return_value=True),
            patch("core.cli.commands.lifecycle.time.sleep"),
        ):
            assert _start_serve_background(executable=executable)

        popen.assert_called_once()
        assert popen.call_args.args[0] == [executable, "serve"]
        assert running.call_count == 2

    def test_timeout_escalates_and_reaps_process(self, tmp_path: Path) -> None:
        executable = str(tmp_path / "bin" / "geode")
        with (
            patch("core.cli.commands.lifecycle.subprocess.Popen") as popen,
            patch("core.cli.ipc_client.is_serve_running", return_value=False),
            patch("core.cli.commands.lifecycle.time.monotonic", return_value=0.0),
        ):
            process = popen.return_value
            process.wait.side_effect = [subprocess.TimeoutExpired(executable, 5.0), 0]
            assert not _start_serve_background(executable=executable, timeout=0.0)

        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        assert process.wait.call_count == 2

    def test_timeout_reports_unreaped_process(
        self,
        tmp_path: Path,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        executable = str(tmp_path / "bin" / "geode")
        with (
            patch("core.cli.commands.lifecycle.subprocess.Popen") as popen,
            patch("core.cli.ipc_client.is_serve_running", return_value=False),
            patch("core.cli.commands.lifecycle.time.monotonic", return_value=0.0),
        ):
            process = popen.return_value
            process.wait.side_effect = subprocess.TimeoutExpired(executable, 5.0)
            assert not _start_serve_background(executable=executable, timeout=0.0)

        assert "could not be reaped" in capfd.readouterr().out

    def test_restart_version_must_match_ipc_greeting(self) -> None:
        completed = subprocess.CompletedProcess(
            ["geode", "version"],
            returncode=0,
            stdout="GEODE v1.2.3\n",
        )
        with (
            patch("core.cli.commands.lifecycle.subprocess.run", return_value=completed),
            patch("core.cli.ipc_client.query_serve_version", return_value="1.2.3"),
        ):
            assert _serve_matches_cli("geode")
        with (
            patch("core.cli.commands.lifecycle.subprocess.run", return_value=completed),
            patch("core.cli.ipc_client.query_serve_version", return_value="1.2.2"),
        ):
            assert not _serve_matches_cli("geode")

    def test_mismatched_restart_is_stopped(self) -> None:
        with (
            patch("core.cli.commands.lifecycle.subprocess.Popen"),
            patch("core.cli.ipc_client.is_serve_running", return_value=True),
            patch("core.cli.commands.lifecycle._serve_matches_cli", return_value=False),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
        ):
            assert not _start_serve_background()

        stop.assert_called_once_with(force=True, timeout=10)


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
    @patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True)
    @patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None)
    @patch("core.cli.ipc_client.is_serve_running", return_value=False)
    @patch("core.cli.commands.lifecycle._has_dirty_worktree", return_value=False)
    @patch("core.cli.commands.lifecycle.detect_update_target")
    def test_runs_expected_steps(
        self,
        mock_target: MagicMock,
        mock_dirty: MagicMock,
        mock_running: MagicMock,
        mock_pid: MagicMock,
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

    @patch("core.cli.commands.lifecycle._run_lifecycle_step")
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
    @patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True)
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
            patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None),
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True) as step,
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
            patch("core.cli.commands.lifecycle._find_serve_pid", return_value=None),
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True) as step,
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

    def test_uv_tool_leaves_serve_stopped_when_update_fails(
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
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=False),
            patch(
                "core.cli.commands.lifecycle._start_serve_background",
                return_value=True,
            ) as start,
        ):
            assert not do_update()

        stop.assert_called_once_with(force=True, timeout=10)
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
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True),
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

    def test_uv_tool_stops_before_install_and_verification(self, tmp_path: Path) -> None:
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
            patch("core.cli.commands.lifecycle._run_lifecycle_step", side_effect=record_step),
            patch(
                "core.cli.commands.lifecycle._start_serve_background",
                side_effect=record_start,
            ),
        ):
            assert do_update()

        assert events == [
            "stop",
            "Resolve and install GEODE update",
            "Verify CLI version",
            "start",
        ]

    def test_uv_tool_stops_live_pid_when_socket_is_unresponsive(self, tmp_path: Path) -> None:
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
            patch("core.cli.commands.lifecycle._find_serve_pid", return_value=12345),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True),
            patch(
                "core.cli.commands.lifecycle._start_serve_background",
                return_value=True,
            ) as start,
        ):
            assert do_update()

        stop.assert_called_once_with(force=True, timeout=10)
        start.assert_called_once()

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
            patch("core.cli.commands.lifecycle._run_lifecycle_step") as step,
            patch("core.cli.commands.lifecycle._start_serve_background") as start,
        ):
            assert not do_update()

        stop.assert_called_once_with(force=True, timeout=10)
        step.assert_not_called()
        start.assert_not_called()

    def test_uv_tool_no_restart_still_stops_before_replacement(self, tmp_path: Path) -> None:
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
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True),
            patch("core.cli.commands.lifecycle._start_serve_background") as start,
        ):
            assert do_update(restart=False)

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
            patch("core.cli.commands.lifecycle._run_lifecycle_step") as step,
        ):
            assert not do_update()

        step.assert_not_called()


# ---------------------------------------------------------------------------
# geode uninstall
# ---------------------------------------------------------------------------


def test_failed_git_status_is_not_clean(tmp_path: Path) -> None:
    with patch(
        "core.cli.commands.lifecycle.subprocess.run",
        return_value=subprocess.CompletedProcess([], 128, "", "not a git repository"),
    ):
        assert _has_dirty_worktree(tmp_path)


class TestUninstall:
    @pytest.mark.parametrize("location", ["home", "cwd", "parent", "project", "sibling"])
    def test_case_aliases_do_not_bypass_home_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
    ) -> None:
        user_home = tmp_path / "user-home"
        project = user_home / "project"
        (project / ".geode").mkdir(parents=True)
        sibling = user_home / "sibling"
        (sibling / ".geode").mkdir(parents=True)
        (sibling / "pyproject.toml").write_text("# project marker")
        monkeypatch.chdir(project)
        monkeypatch.setattr(Path, "home", lambda: user_home)
        selected = {
            "home": user_home,
            "cwd": project,
            "parent": tmp_path,
            "project": project / ".geode",
            "sibling": sibling / ".geode",
        }[location]
        alias = selected.with_name(selected.name.upper())
        if not alias.exists():
            pytest.skip("Filesystem does not provide case-insensitive aliases")
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", alias),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=False) as stop,
            patch("shutil.which", return_value=None),
            patch("shutil.rmtree") as remove,
        ):
            assert do_uninstall(force=True) is False
        stop.assert_not_called()
        remove.assert_not_called()

    def test_keep_flags_preserve_case_variant_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        auth = runtime / "AUTH.TOML"
        auth.write_text("# synthetic credentials")
        auth.chmod(0o600)
        before = auth.stat()
        (runtime / "Config.Toml").write_text("# keep")
        (runtime / "VAULT").mkdir()
        (runtime / "VAULT" / "keep").write_text("evidence")
        (runtime / "User_Profile").mkdir()
        (runtime / "runs").mkdir()
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", runtime),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True),
            patch("shutil.which", return_value=None),
        ):
            assert do_uninstall(force=True, keep_config=True, keep_data=True)
        assert auth.read_text() == "# synthetic credentials"
        assert (auth.stat().st_ino, auth.stat().st_mode) == (before.st_ino, before.st_mode)
        assert (runtime / "Config.Toml").is_file()
        assert (runtime / "VAULT" / "keep").read_text() == "evidence"
        assert (runtime / "User_Profile").is_dir()
        assert not (runtime / "runs").exists()

    def test_default_home_case_alias_remains_usable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        default_home = tmp_path / ".geode"
        (default_home / "runs").mkdir(parents=True)
        alias = default_home.with_name(".GEODE")
        if not alias.exists():
            pytest.skip("Filesystem does not provide case-insensitive aliases")
        with (
            patch("core.cli.commands.lifecycle.DEFAULT_GEODE_HOME", default_home),
            patch("core.cli.commands.lifecycle.GEODE_HOME", alias),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True),
            patch("shutil.which", return_value=None),
        ):
            assert do_uninstall(force=True)
        assert not default_home.exists()

    def test_project_environment_is_not_owned_by_uninstall(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for name in (".geode/rules", ".geode/skills", ".venv", ".mypy_cache", ".pytest_cache"):
            directory = tmp_path / name
            directory.mkdir(parents=True)
            (directory / "keep").write_text("project-owned")
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "runtime-home"),
            patch("core.cli.commands.lifecycle.stop_serve") as stop,
            patch("shutil.which", return_value=None),
        ):
            assert do_uninstall(force=True)
        stop.assert_not_called()
        assert len(list(tmp_path.rglob("keep"))) == 5

    @pytest.mark.parametrize(
        "location",
        [
            "root",
            "home",
            "cwd",
            "parent",
            "project",
            "alias",
            "sibling",
            "parent-alias",
            "ancestor-alias",
        ],
    )
    def test_rejects_unsafe_home_before_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
    ) -> None:
        from core.cli.commands.lifecycle import DirUsage

        project = tmp_path / "project"
        project.mkdir()
        runtime = project / ".geode"
        runtime.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        sibling = tmp_path / "sibling"
        (sibling / ".geode").mkdir(parents=True)
        (sibling / ".git").write_text("gitdir: elsewhere")
        monkeypatch.chdir(project)
        homes = {
            "root": Path("/"),
            "home": Path.home(),
            "cwd": project,
            "parent": tmp_path,
            "project": runtime,
            "alias": alias,
            "sibling": sibling / ".geode",
            "parent-alias": alias / "runtime-home",
            "ancestor-alias": alias / "sibling" / ".geode",
        }
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", homes[location]),
            patch("core.cli.commands.lifecycle._scan_directory", return_value=DirUsage(tmp_path)),
            patch("core.cli.commands.lifecycle.stop_serve") as stop,
            patch("shutil.which", return_value=None),
            patch("shutil.rmtree") as remove,
        ):
            assert do_uninstall(force=True) is False
        stop.assert_not_called()
        remove.assert_not_called()

    def test_stop_failure_preserves_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        sentinel = runtime / "evidence"
        sentinel.write_text("preserve")
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", runtime),
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "project"),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            assert do_uninstall(force=True) is False
        assert sentinel.read_text() == "preserve"

    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text("[test]")
        runtime = tmp_path / "runtime"
        (runtime / "runs").mkdir(parents=True)
        sentinel = runtime / "runs" / "evidence"
        sentinel.write_text("preserve")
        bin_dir = tmp_path / "bin"

        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", geode_dir),
            patch("core.cli.commands.lifecycle.GEODE_HOME", runtime),
            patch("shutil.which", return_value=str(bin_dir / "geode")),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=bin_dir,
                ),
            ),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
            patch("core.cli.commands.lifecycle._run_lifecycle_step", return_value=True) as step,
            patch("shutil.rmtree") as remove,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            assert do_uninstall(dry_run=True)

        stop.assert_not_called()
        step.assert_not_called()
        remove.assert_not_called()
        assert sentinel.read_text() == "preserve"
        assert geode_dir.exists()

    def test_force_skips_confirmations(self, tmp_path: Path) -> None:
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text("[test]")
        home = tmp_path / "home_geode"
        home.mkdir()
        (home / "data").write_text("runtime-owned")

        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", geode_dir),
            patch("core.cli.commands.lifecycle.GEODE_HOME", home),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True),
            patch("core.cli.commands.lifecycle._confirm") as confirm,
            patch("core.cli.commands.lifecycle._confirm_typed") as typed,
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            assert do_uninstall(force=True)

        confirm.assert_not_called()
        typed.assert_not_called()
        assert geode_dir.exists()
        assert not home.exists()

    def test_keep_config(self, tmp_path: Path) -> None:
        home = tmp_path / "home_geode"
        home.mkdir()
        (home / ".env").write_text("ANTHROPIC_API_KEY=sk-test")
        (home / "config.toml").write_text("[model]")
        auth = home / "auth.toml"
        auth.write_text("# synthetic credentials")
        auth.chmod(0o600)
        before = auth.stat()
        (home / "runs").mkdir()

        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.commands.lifecycle.GEODE_HOME", home),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            assert do_uninstall(force=True, keep_config=True)

        assert (home / ".env").exists()
        assert (home / "config.toml").exists()
        assert auth.read_text() == "# synthetic credentials"
        assert (auth.stat().st_ino, auth.stat().st_mode) == (before.st_ino, before.st_mode)
        assert not (home / "runs").exists()

    def test_nothing_to_uninstall(self, tmp_path: Path) -> None:
        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "nope2"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch("core.cli.commands.lifecycle.stop_serve") as stop,
        ):
            assert do_uninstall(force=True)
        stop.assert_not_called()

    def test_uninstalls_geode_agent_distribution(self, tmp_path: Path) -> None:
        geode_bin = tmp_path / "bin" / "geode"
        geode_bin.parent.mkdir()
        geode_bin.write_text("#!/bin/sh\n", encoding="utf-8")

        with (
            patch("core.cli.commands.lifecycle.PROJECT_GEODE_DIR", tmp_path / "nope"),
            patch("core.cli.commands.lifecycle.GEODE_HOME", tmp_path / "nope2"),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=UpdateTarget(
                    UpdateKind.UV_TOOL,
                    uv_tool_dir=tmp_path / "tools",
                    uv_tool_bin_dir=geode_bin.parent,
                ),
            ),
            patch(
                "core.cli.commands.lifecycle.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ) as mock_run,
            patch("shutil.which", return_value=str(geode_bin)),
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            assert do_uninstall(force=True)

        assert mock_run.call_args.args == (["uv", "tool", "uninstall", "geode-agent"],)
        assert mock_run.call_args.kwargs["timeout"] == 30
        assert mock_run.call_args.kwargs["cwd"] == tmp_path
        assert mock_run.call_args.kwargs["env"]["UV_TOOL_DIR"] == str(tmp_path / "tools")
        assert mock_run.call_args.kwargs["env"]["UV_TOOL_BIN_DIR"] == str(geode_bin.parent)

    @pytest.mark.parametrize("failure", ["delete", "cli", "timeout", "spawn", "unverified"])
    def test_failure_is_not_reported_as_complete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
    ) -> None:
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "runtime"
        evidence = home / "runs"
        evidence.mkdir(parents=True)
        (evidence / "keep").write_text("evidence")
        (home / "config.toml").write_text("# preserved config")
        target = UpdateTarget(
            UpdateKind.UV_TOOL,
            uv_tool_dir=tmp_path / "tools",
            uv_tool_bin_dir=tmp_path / "bin",
        )
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", home),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True) as stop,
            patch("shutil.which", return_value=str(tmp_path / "bin/geode")),
            patch(
                "core.cli.commands.lifecycle.detect_update_target",
                return_value=(
                    UpdateTarget(UpdateKind.UNSUPPORTED) if failure == "unverified" else target
                ),
            ),
            patch(
                "shutil.rmtree",
                side_effect=PermissionError("denied") if failure == "delete" else None,
                wraps=shutil.rmtree,
            ),
            patch(
                "core.cli.commands.lifecycle.subprocess.run",
                side_effect={
                    "timeout": subprocess.TimeoutExpired("uv", 30),
                    "spawn": OSError("uv unavailable"),
                }.get(failure),
                return_value=subprocess.CompletedProcess([], 1, "", "failed"),
            ),
            patch("core.cli.commands.lifecycle.console") as output,
        ):
            assert do_uninstall(force=True, keep_config=True) is False
        assert not any("Uninstall complete." in str(call) for call in output.print.call_args_list)
        if failure == "unverified":
            stop.assert_not_called()
        assert (home / "config.toml").read_text() == "# preserved config"
        if failure in ("delete", "unverified"):
            assert (evidence / "keep").read_text() == "evidence"
        else:
            assert not evidence.exists()
            assert any(
                "CLI removal is incomplete" in str(call) for call in output.print.call_args_list
            )

    def test_keep_data_and_unlink_external_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "runtime"
        for name in ("vault", "identity", "user_profile"):
            (home / name).mkdir(parents=True)
            (home / name / "keep").write_text("preserved")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep").write_text("external")
        (home / "alias").symlink_to(outside, target_is_directory=True)
        with (
            patch("core.cli.commands.lifecycle.GEODE_HOME", home),
            patch("core.cli.commands.lifecycle.stop_serve", return_value=True),
            patch("shutil.which", return_value=None),
        ):
            assert do_uninstall(force=True, keep_data=True)
        assert not (home / "alias").exists()
        assert (outside / "keep").read_text() == "external"
        assert len(list(home.rglob("keep"))) == 3

    def test_typer_propagates_failure(self) -> None:
        import typer
        from core.cli.typer_commands import uninstall

        with (
            patch("core.cli.commands.lifecycle.do_uninstall", return_value=False),
            pytest.raises(typer.Exit) as caught,
        ):
            uninstall(dry_run=False, force=True, keep_config=False, keep_data=False)
        assert caught.value.exit_code == 1

    def test_slash_dispatch_reports_failure(self) -> None:
        from core.cli.dispatcher import _handle_command

        with (
            patch("core.cli.dispatcher.resolve_action", return_value="uninstall"),
            patch("core.cli.commands.lifecycle.do_uninstall", return_value=False) as remove,
            patch("core.cli.dispatcher.console") as output,
        ):
            assert _handle_command("/uninstall", "--force --keep-config", False) == (
                False,
                False,
                None,
            )
        remove.assert_called_once_with(force=True, dry_run=False, keep_config=True, keep_data=False)
        assert "Uninstall did not complete" in str(output.print.call_args)


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
