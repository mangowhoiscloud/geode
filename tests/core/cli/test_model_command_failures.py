"""Expected backend route failures remain command outcomes, never local fallback."""

from __future__ import annotations

import socket
import threading
import time
from io import StringIO
from unittest.mock import Mock

import pytest
from core.cli.commands import model as command
from core.cli.commands._state import ModelProfile
from core.cli.ipc_client import IPCClient
from core.config.session import SessionModelConfig
from core.ipc_protocol import IPC_FEATURES, decode_message, encode_message
from rich.console import Console


@pytest.fixture
def command_client(monkeypatch):
    from core.cli import commands

    client = IPCClient()
    client.features = IPC_FEATURES
    client.model_config = SessionModelConfig(
        model="gpt-6-sol", source="subscription", effort="high"
    ).model_dump()
    output = StringIO()
    monkeypatch.setattr(commands, "console", Console(file=output, color_system=None))
    monkeypatch.setattr(
        command,
        "get_model_profiles",
        lambda **kw: [ModelProfile("gpt-6.1-sol", "openai", "SOL", "subscription")],
    )
    monkeypatch.setattr(command, "model_unavailable_reason", lambda *a, **kw: None)
    monkeypatch.setattr(command, "model_available", lambda *a, **kw: pytest.fail("local fallback"))
    monkeypatch.setattr(
        command, "_ensure_profiles_hydrated", lambda: pytest.fail("local hydration")
    )
    persist = Mock()
    apply = Mock()
    picker = Mock()
    monkeypatch.setattr(command, "_apply_model", persist)
    monkeypatch.setattr(client, "apply_model_config", apply)
    monkeypatch.setattr("core.cli.effort_picker.pick_model_and_effort", picker)
    return client, output, persist, apply, picker


@pytest.mark.parametrize("entry", ["named", "picker", "role-picker", "list"])
@pytest.mark.parametrize("failure", ["old-feature", "disconnected", "malformed", "incomplete"])
def test_public_command_reports_route_failure_without_selection_or_persistence(
    monkeypatch, command_client, entry, failure
):
    client, output, persist, apply, picker = command_client
    original = dict(client.model_config)
    if failure == "old-feature":
        client.features = ("session_model_config",)
    elif failure != "disconnected":
        client._sock = Mock(gettimeout=Mock(return_value=None))
        monkeypatch.setattr(client, "_send", lambda payload: "query")
        rows = [{"model": "gpt-6.1-sol", "source": "subscription", "available": "yes"}]
        monkeypatch.setattr(
            client,
            "_recv_for",
            lambda request_id, **kwargs: {
                "status": "ok",
                "model_routes": rows if failure == "malformed" else [],
            },
        )
    monkeypatch.setattr("sys.stdin.isatty", lambda: entry in {"picker", "role-picker"})
    args = "gpt-6.1-sol" if entry == "named" else "reflection" if entry == "role-picker" else ""
    command.cmd_model(args, client=client)
    assert "Selection unchanged" in " ".join(output.getvalue().split())
    expected = {
        "old-feature": "Restart serve",
        "disconnected": "Not connected",
        "malformed": "Invalid backend",
        "incomplete": "Incomplete backend",
    }
    assert expected[failure] in output.getvalue()
    assert client.model_config == original
    persist.assert_not_called()
    apply.assert_not_called()
    picker.assert_not_called()


def test_public_command_redacts_and_escapes_inspection_failure(monkeypatch, command_client):
    client, output, persist, apply, _ = command_client
    secret = "sk-" + "x" * 48

    def failure(queries):
        raise ValueError(f"[bold]bad[/bold] Authorization: Bearer {secret}")

    monkeypatch.setattr(client, "inspect_model_routes", failure)
    command.cmd_model("gpt-6.1-sol", client=client)
    assert secret not in output.getvalue()
    assert "[bold]bad[/bold]" in output.getvalue()
    assert "Selection unchanged" in output.getvalue()
    persist.assert_not_called()
    apply.assert_not_called()


@pytest.mark.parametrize("failure", [KeyError("bug"), TypeError("bug")])
def test_public_command_does_not_swallow_programmer_errors(monkeypatch, command_client, failure):
    client, _, _, _, _ = command_client

    def broken(queries):
        raise failure

    monkeypatch.setattr(client, "inspect_model_routes", broken)
    with pytest.raises(type(failure), match="bug"):
        command.cmd_model("gpt-6.1-sol", client=client)


def test_public_command_does_not_swallow_unrelated_value_error(monkeypatch, command_client):
    client, _, _, _, _ = command_client

    def broken(**kwargs):
        raise ValueError("catalog bug")

    monkeypatch.setattr(command, "get_model_profiles", broken)
    with pytest.raises(ValueError, match="catalog bug"):
        command.cmd_model("gpt-6.1-sol", client=client)


def test_route_inspection_silent_peer_has_bounded_wait_and_invalidates_transport():
    local, peer = socket.socketpair()
    client = IPCClient()
    client._sock = local
    client.features = IPC_FEATURES
    assert local.gettimeout() is None
    started = time.monotonic()
    try:
        with pytest.raises(ValueError, match="reconnect"):
            client.inspect_model_routes([("gpt-6.1-sol", "subscription")], timeout_s=0.02)
        assert time.monotonic() - started < 1
        assert not client.connected
        assert client._sock is None and local.fileno() == -1
        assert "timed out" in client.last_error
    finally:
        local.close()
        peer.close()


@pytest.mark.parametrize("previous_timeout", [None, 2.0])
def test_successful_route_inspection_restores_socket_timeout(previous_timeout):
    local, peer = socket.socketpair()
    local.settimeout(previous_timeout)
    peer.settimeout(1)
    client = IPCClient()
    client._sock = local
    client.features = IPC_FEATURES

    def respond():
        request = decode_message(peer.recv(65536).strip())
        peer.sendall(
            encode_message(
                {
                    "type": "command_result",
                    "status": "ok",
                    "request_id": request["request_id"],
                    "model_routes": [
                        {**query, "available": True} for query in request["model_queries"]
                    ],
                }
            )
        )

    responder = threading.Thread(target=respond)
    responder.start()
    try:
        assert client.inspect_model_routes([("gpt-6.1-sol", "subscription")], timeout_s=1) == {
            ("gpt-6.1-sol", "subscription"): True
        }
        assert local.gettimeout() == previous_timeout
        assert client.connected and not client.last_error
    finally:
        responder.join(timeout=1)
        local.close()
        peer.close()
