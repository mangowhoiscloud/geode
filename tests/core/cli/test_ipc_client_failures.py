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
