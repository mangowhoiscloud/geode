"""Transport failures and cancellation remain visible to the thin client."""

from __future__ import annotations

import socket
import threading
import time

import pytest
from core.cli.fullscreen_app import FullscreenThinCli
from core.cli.ipc_client import IPCClient
from core.ipc_protocol import decode_message, encode_message


@pytest.mark.parametrize("wire", [b"", b"not-json\n", b"[]\n"])
def test_broken_wire_invalidates_connection_and_returns_error(wire):
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local
    if wire:
        peer.sendall(wire)
    peer.close()
    response = client._recv()
    assert response["type"] == "error"
    assert response["error_type"] in {"ConnectionError", "IPCProtocolError"}
    assert not client.connected
    assert client.last_error


def test_close_times_out_without_claiming_session_completion():
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local
    started = time.monotonic()
    try:
        assert client.close(timeout_s=0.02) is False
        assert time.monotonic() - started < 1
        assert not client.connected
        assert "timed out" in client.last_error
    finally:
        peer.close()


def test_close_requires_matching_exit_ack():
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local

    def serve():
        message = decode_message(peer.recv(65536).strip())
        peer.sendall(encode_message({"type": "exit_ack", "request_id": "stale"}))
        peer.sendall(
            encode_message(
                {
                    "type": "error",
                    "request_id": message["request_id"],
                    "message": "checkpoint failed",
                }
            )
        )

    worker = threading.Thread(target=serve)
    worker.start()
    try:
        assert client.close(timeout_s=1) is False
        assert client.last_error == "checkpoint failed"
    finally:
        worker.join(timeout=1)
        peer.close()


def test_greeting_wait_is_bounded(tmp_path):
    # AF_UNIX paths have a short OS limit, so use a socketpair via a socket factory.
    from unittest.mock import patch

    local, peer = socket.socketpair()

    class ConnectedSocket:
        def connect(self, _path):
            pass

        def __getattr__(self, name):
            return getattr(local, name)

    client = IPCClient(tmp_path / "not-used")
    try:
        with patch("core.cli.ipc_client.socket.socket", return_value=ConnectedSocket()):
            assert not client.connect(timeout_s=0.02)
        assert not client.connected
        assert "timed out" in client.last_error
    finally:
        peer.close()


def test_rejected_capability_refresh_does_not_send_prompt(monkeypatch):
    client = IPCClient()
    client._sock = object()
    sent = []
    monkeypatch.setattr(client, "_send", lambda payload: sent.append(payload) or "cap")
    monkeypatch.setattr(
        client,
        "_recv",
        lambda: {
            "type": "protocol_error",
            "request_id": "cap",
            "message": "bad settings",
        },
    )
    response = client.send_prompt("must not run")
    assert response["type"] == "protocol_error"
    assert [entry["type"] for entry in sent] == ["client_capability"]


def test_cancellation_writes_target_id_without_consuming_stream():
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local
    client.features = ("request_cancellation",)
    client._active_request_id = "running"
    try:
        assert client.cancel_current()
        message = decode_message(peer.recv(65536).strip())
        assert message["type"] == "cancel"
        assert message["target_request_id"] == "running"
        assert message["request_id"] != "running"
    finally:
        client._disconnect()
        peer.close()


def test_legacy_keyboard_interrupt_disconnects_active_request(monkeypatch):
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local
    monkeypatch.setattr(client, "_send_client_capability", lambda: "cap")
    monkeypatch.setattr(client, "_recv_for", lambda *_args: {"type": "ack", "status": "applied"})

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(client, "_read_streaming_result", interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            client.send_prompt("work")
        assert not client.connected
        assert client._active_request_id == ""
        assert decode_message(peer.recv(65536).strip())["type"] == "prompt"
        assert peer.recv(65536) == b""  # server's reader observes EOF and cancels
    finally:
        peer.close()


def test_exit_deadline_survives_nonmatching_responses():
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local

    def serve():
        peer.recv(65536)
        try:
            while True:
                peer.sendall(encode_message({"type": "ack", "request_id": "different"}))
                time.sleep(0.002)
        except OSError:
            pass

    worker = threading.Thread(target=serve)
    worker.start()
    started = time.monotonic()
    try:
        assert not client.close(timeout_s=0.03)
        assert time.monotonic() - started < 1
        assert "timed out" in client.last_error
    finally:
        worker.join(timeout=1)
        peer.close()


@pytest.mark.parametrize(
    "response",
    [
        {"type": "protocol_error", "message": "bad settings"},
        {"type": "resume_error", "message": "bad checkpoint"},
        {"type": "result", "status": "error", "error": "provider failed"},
    ],
)
def test_fullscreen_failure_never_prints_done(response):
    app = FullscreenThinCli(IPCClient())
    app._handle_prompt_response(response)
    transcript = "\n".join(app.state.transcript)
    assert "Error" in transcript
    assert "Worked for" not in transcript


def test_fullscreen_waits_for_cancel_terminal_outcome(monkeypatch):
    client = IPCClient()
    monkeypatch.setattr(client, "cancel_current", lambda: True)
    app = FullscreenThinCli(client)
    app.state.busy = True
    app._cancel_current_request()
    assert app.state.busy
    assert app.state.status == "Cancelling"
    assert "Cancelled" not in "\n".join(app.state.transcript)
    app._handle_prompt_response({"type": "result", "status": "cancelled"})
    transcript = "\n".join(app.state.transcript)
    assert "Cancelled" in transcript
    assert "Worked for" not in transcript


@pytest.mark.parametrize("acknowledged", [True, False])
def test_fullscreen_normal_return_closes_transport_and_reports_failure(monkeypatch, acknowledged):
    from unittest.mock import Mock

    from core.cli import _thin_interactive_loop
    from core.ui.console import capture_output

    client = Mock(session_id="cli-test", last_error="checkpoint failed")
    client.connect.return_value = True
    client.close.return_value = acknowledged
    screen = Mock()
    monkeypatch.setattr("core.cli.ipc_client.IPCClient", lambda: client)
    monkeypatch.setattr("core.cli._fullscreen_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "core.cli.fullscreen_app.FullscreenThinCli", lambda *_args, **_kwargs: screen
    )
    with capture_output() as output:
        _thin_interactive_loop()
    screen.run.assert_called_once()
    client.close.assert_called_once()
    assert ("Session exit was not acknowledged" in output.getvalue()) is not acknowledged
    if not acknowledged:
        assert "checkpoint failed" in output.getvalue()


def test_fullscreen_exit_releases_approval_waiter_and_denies_late_approval(monkeypatch):
    from unittest.mock import Mock

    app = FullscreenThinCli(IPCClient())
    ready = threading.Event()
    decision = []
    monkeypatch.setattr(app, "_set_status", lambda *_args: ready.set())
    screen = Mock()
    screen.run.side_effect = lambda: ready.wait(timeout=1)
    app._app = screen
    app.app = screen
    worker = threading.Thread(
        target=lambda: decision.append(app._on_approval_request({"tool_name": "write_file"}))
    )
    worker.start()
    app.run()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert decision == ["n"]
    assert app._on_approval_request({"tool_name": "late_write"}) == "n"


def test_failed_daemon_start_reaps_only_spawned_child(tmp_path, monkeypatch):
    from unittest.mock import Mock, patch

    from core.cli.ipc_client import start_serve_if_needed

    child = Mock()
    child.poll.return_value = None
    monkeypatch.setattr("core.cli.ipc_client.is_serve_running", lambda *_: False)
    monkeypatch.setattr("core.paths.resolve_cli_socket_path", lambda *_: tmp_path / "cli.sock")
    with patch("subprocess.Popen", return_value=child) as spawn:
        result = start_serve_if_needed(tmp_path / "cli.sock", timeout_s=0.01)
    assert not result.ready
    assert result.status == "timeout"
    assert result.exit_code is None  # termination is cleanup, not the startup failure
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=5)
    child.kill.assert_not_called()
    command = spawn.call_args.args[0]
    import sys

    assert command[0] == sys.executable
    assert spawn.call_args.kwargs["env"]["GEODE_GATEWAY_ENABLED"] == "false"
    assert spawn.call_args.kwargs["env"]["GEODE_CLI_SOCKET"] == str(tmp_path / "cli.sock")


def test_failed_initial_connection_exits_nonzero(monkeypatch):
    from unittest.mock import Mock

    import typer
    from core.cli import _thin_interactive_loop

    client = Mock(last_error="workspace mismatch")
    client.connect.return_value = False
    monkeypatch.setattr("core.cli.ipc_client.IPCClient", lambda: client)
    with pytest.raises(typer.Exit) as caught:
        _thin_interactive_loop()
    assert caught.value.exit_code == 1


@pytest.fixture
def startup_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr("core.cli.ipc_client.is_serve_running", lambda *_: False)
    monkeypatch.setattr("core.paths.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("core.paths.resolve_cli_socket_path", lambda *_: tmp_path / "cli.sock")
    return tmp_path


@pytest.mark.parametrize("log_change", ["append", "rotate", "truncate", "missing"])
def test_startup_exit_reports_only_fresh_redacted_log(startup_workspace, monkeypatch, log_change):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    log_path = startup_workspace / "serve.log"
    historical = "historical error must not be shown\n" * 30
    log_path.write_text(historical)
    child = Mock()
    child.poll.return_value = 17
    secret = "sk-ant-" + "x" * 40
    fresh = f"startup failed: api_key={secret}, refresh_token=private-refresh\n"

    def spawn(*_args, **_kwargs):
        if log_change == "append":
            with log_path.open("a") as stream:
                stream.write(fresh)
        elif log_change == "rotate":
            log_path.rename(log_path.with_suffix(".log.1"))
            log_path.write_text(fresh)
        elif log_change == "truncate":
            log_path.write_text(fresh)
        return child

    monkeypatch.setattr("subprocess.Popen", spawn)
    result = start_serve_if_needed(startup_workspace / "custom.sock")
    assert result.status == "exited"
    assert result.exit_code == 17
    assert result.log_path == log_path
    assert historical not in result.detail
    assert "historical error" not in result.detail
    assert secret not in result.detail
    assert "private-refresh" not in result.detail
    if log_change == "missing":
        assert result.detail == ""
    else:
        assert "startup failed" in result.detail
        assert "[REDACTED]" in result.detail
    child.terminate.assert_not_called()
    child.kill.assert_not_called()
    child.wait.assert_called_once_with(timeout=5)


def test_startup_pre_logging_exit_still_reports_status_and_log_path(startup_workspace, monkeypatch):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    child = Mock()
    child.poll.return_value = 2
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: child)
    result = start_serve_if_needed(startup_workspace / "cli.sock")
    assert result.status == "exited"
    assert result.exit_code == 2
    assert result.log_path == startup_workspace / "serve.log"
    assert result.detail == ""


def test_startup_spawn_error_is_redacted_and_excludes_old_log(startup_workspace, monkeypatch):
    from core.cli.ipc_client import start_serve_if_needed

    (startup_workspace / "serve.log").write_text("old error\n")

    def fail_spawn(*_args, **_kwargs):
        raise OSError("permission denied: access_token=private-access")

    monkeypatch.setattr("subprocess.Popen", fail_spawn)
    result = start_serve_if_needed(startup_workspace / "cli.sock")
    assert result.status == "spawn_error"
    assert "permission denied" in result.detail
    assert "[REDACTED]" in result.detail
    assert "private-access" not in result.detail
    assert "old error" not in result.detail


def test_startup_log_excerpt_is_bounded_without_partial_secret(startup_workspace, monkeypatch):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    child = Mock()
    child.poll.return_value = 1

    def spawn(*_args, **_kwargs):
        (startup_workspace / "serve.log").write_text(
            "token=" + "private" * 2000 + "\n" + "detail\n" * 400 + "startup failed\n"
        )
        return child

    monkeypatch.setattr("subprocess.Popen", spawn)
    result = start_serve_if_needed(startup_workspace / "cli.sock")
    assert "private" not in result.detail
    assert "startup failed" in result.detail
    assert len(result.detail) < 2100
    assert "truncated" in result.detail


def test_startup_log_drops_continuation_of_preexisting_line(startup_workspace, monkeypatch):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    log_path = startup_workspace / "serve.log"
    log_path.write_text("old failure: access_token=")
    child = Mock()
    child.poll.return_value = 1

    def spawn(*_args, **_kwargs):
        with log_path.open("a") as stream:
            stream.write("private-continuation\nnew failure\n")
        return child

    monkeypatch.setattr("subprocess.Popen", spawn)
    result = start_serve_if_needed(startup_workspace / "cli.sock")
    assert result.detail == "new failure"


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_startup_diagnostics_do_not_follow_nonregular_log(startup_workspace, monkeypatch, kind):
    import os
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    log_path = startup_workspace / "serve.log"
    if kind == "symlink":
        other = startup_workspace / "other.log"
        other.write_text("unrelated log\n")
        log_path.symlink_to(other)
    else:
        os.mkfifo(log_path)
    child = Mock()
    child.poll.return_value = 1
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: child)
    result = start_serve_if_needed(startup_workspace / "cli.sock")
    assert result.status == "exited"
    assert result.detail == ""


def test_startup_timeout_reaps_child_after_terminate_deadline(startup_workspace, monkeypatch):
    import subprocess
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [subprocess.TimeoutExpired("geode", 5), -9]
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: child)
    result = start_serve_if_needed(startup_workspace / "cli.sock", timeout_s=0)
    assert result.status == "timeout"
    assert result.exit_code is None
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert child.wait.call_count == 2


def test_startup_lock_timeout_does_not_spawn_or_read_old_log(startup_workspace, monkeypatch):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    (startup_workspace / "serve.log").write_text("old error\n")

    def busy_lock(*_args):
        raise BlockingIOError

    spawn = Mock()
    monkeypatch.setattr("fcntl.flock", busy_lock)
    monkeypatch.setattr("subprocess.Popen", spawn)
    result = start_serve_if_needed(startup_workspace / "cli.sock", timeout_s=0)
    assert result.status == "timeout"
    assert result.detail == ""
    spawn.assert_not_called()


@pytest.mark.parametrize("blocked_path", ["parent_file", "lock_directory"])
def test_startup_lock_path_error_is_reported_without_spawn(
    startup_workspace, monkeypatch, blocked_path
):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    (startup_workspace / "serve.log").write_text("historical error\n")
    socket_path = startup_workspace / "cli.sock"
    if blocked_path == "parent_file":
        parent = startup_workspace / "not-a-directory"
        parent.write_text("blocking file")
        socket_path = parent / "cli.sock"
    else:
        socket_path.with_suffix(".startup.lock").mkdir()
    spawn = Mock()
    read_log = Mock(side_effect=AssertionError("must not read a historical log"))
    monkeypatch.setattr("subprocess.Popen", spawn)
    monkeypatch.setattr("core.cli.ipc_client._snapshot_serve_log", read_log)
    result = start_serve_if_needed(socket_path)
    assert result.status == "spawn_error"
    assert result.exit_code is None
    assert result.detail
    assert "historical error" not in result.detail
    assert result.log_path == startup_workspace / "serve.log"
    spawn.assert_not_called()
    read_log.assert_not_called()


@pytest.mark.parametrize("programmer_error", [False, True])
def test_startup_lock_acquisition_reports_only_expected_errors(
    startup_workspace, monkeypatch, programmer_error
):
    from unittest.mock import Mock

    from core.cli.ipc_client import start_serve_if_needed

    lock_files = []

    def fail_lock(lock_fd, _flags):
        lock_files.append(lock_fd)
        if programmer_error:
            raise RuntimeError("invalid lock implementation")
        raise PermissionError("lock denied: access_token=private-access " + "x" * 3000)

    spawn = Mock()
    read_log = Mock(side_effect=AssertionError("must not read a historical log"))
    monkeypatch.setattr("fcntl.flock", fail_lock)
    monkeypatch.setattr("subprocess.Popen", spawn)
    monkeypatch.setattr("core.cli.ipc_client._snapshot_serve_log", read_log)
    if programmer_error:
        with pytest.raises(RuntimeError, match="invalid lock implementation"):
            start_serve_if_needed(startup_workspace / "cli.sock")
    else:
        result = start_serve_if_needed(startup_workspace / "cli.sock")
        assert result.status == "spawn_error"
        assert "lock denied" in result.detail
        assert "private-access" not in result.detail
        assert "[REDACTED]" in result.detail
        assert len(result.detail) < 2100
    assert len(lock_files) == 1
    assert lock_files[0].closed
    spawn.assert_not_called()
    read_log.assert_not_called()


@pytest.mark.parametrize("mode", ["exited", "timeout"])
def test_startup_failure_reaps_real_owned_process(startup_workspace, monkeypatch, mode):
    import subprocess
    import sys

    from core.cli.ipc_client import start_serve_if_needed

    real_spawn = subprocess.Popen
    children = []

    def spawn(*_args, **_kwargs):
        program = "raise SystemExit(19)" if mode == "exited" else "import time; time.sleep(30)"
        child = real_spawn(
            [sys.executable, "-S", "-c", program],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        children.append(child)
        if mode == "exited":
            # Establish an actual early exit without relying on host scheduling.
            child.wait(timeout=5)
        return child

    monkeypatch.setattr("subprocess.Popen", spawn)
    try:
        result = start_serve_if_needed(
            startup_workspace / "cli.sock", timeout_s=2 if mode == "exited" else 0.02
        )
        assert result.status == mode
        assert result.exit_code == (19 if mode == "exited" else None)
        assert len(children) == 1
        assert children[0].returncode is not None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("exited", "exit code 7"),
        ("timeout", "did not become ready within 30 seconds"),
        ("spawn_error", "Could not start geode serve"),
    ],
)
def test_startup_cli_renders_failure_and_foreground_recovery(
    tmp_path, monkeypatch, status, message
):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import typer
    from core.cli import _run_main
    from core.cli.ipc_client import ServeStartupResult
    from core.ui.console import capture_output
    from rich.text import Text

    result = ServeStartupResult(status, tmp_path / "serve.log", exit_code=7)
    spinner = Mock()
    interactive = Mock()
    monkeypatch.setattr("core.cli._welcome_screen", lambda: True)
    monkeypatch.setattr("core.cli.ipc_client.is_serve_running", lambda *_: False)
    monkeypatch.setattr("core.cli.ipc_client.start_serve_if_needed", lambda **_: result)
    monkeypatch.setattr("core.ui.status.TextSpinner", lambda *_: spinner)
    monkeypatch.setattr("core.cli._thin_interactive_loop", interactive)
    with capture_output() as output, pytest.raises(typer.Exit) as caught:
        _run_main(SimpleNamespace(invoked_subcommand=None), False, False, "", False)
    rendered = Text.from_ansi(output.getvalue()).plain
    assert caught.value.exit_code == 1
    assert message in rendered
    assert str(result.log_path) in rendered.replace("\n", "")
    assert "Run `geode serve` in this directory" in rendered
    assert "geode serve &" not in rendered
    spinner.stop.assert_called_once()
    interactive.assert_not_called()
