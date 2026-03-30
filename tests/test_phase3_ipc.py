"""Tests for Phase 3: CLIChannel IPC (H3 resolution).

Tests the Unix domain socket protocol between CLIPoller (server) and
IPCClient (client), including connection, prompt relay, and error handling.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Unix domain socket paths must be < 104 chars on macOS.
# pytest tmp_path is too long, so we use /tmp/ directly.
_SOCK_PREFIX = Path("/tmp/geode-test-ipc")  # noqa: S108


@pytest.fixture(autouse=True)
def _clean_test_sockets() -> None:
    """Clean up test sockets before and after each test."""
    import glob

    for f in glob.glob(str(_SOCK_PREFIX) + "*"):
        Path(f).unlink(missing_ok=True)
    yield  # type: ignore[misc]
    for f in glob.glob(str(_SOCK_PREFIX) + "*"):
        Path(f).unlink(missing_ok=True)


def _test_sock() -> Path:
    return _SOCK_PREFIX.with_suffix(f".{time.monotonic_ns()}.sock")


# ---------------------------------------------------------------------------
# IPC Client unit tests
# ---------------------------------------------------------------------------


class TestIPCClient:
    """Test the thin CLI IPC client."""

    def test_request_resume_not_connected(self) -> None:
        from core.cli.ipc_client import IPCClient

        client = IPCClient()
        result = client.request_resume(continue_latest=True)
        assert result["type"] == "resume_error"

    def test_is_serve_running_no_socket(self, tmp_path: Path) -> None:
        from core.cli.ipc_client import is_serve_running

        assert not is_serve_running(tmp_path / "nonexistent.sock")

    def test_is_serve_running_stale_socket(self, tmp_path: Path) -> None:
        from core.cli.ipc_client import is_serve_running

        sock_path = tmp_path / "stale.sock"
        sock_path.touch()  # file exists but no server
        assert not is_serve_running(sock_path)

    def test_client_connect_no_server(self, tmp_path: Path) -> None:
        from core.cli.ipc_client import IPCClient

        client = IPCClient(socket_path=tmp_path / "noserver.sock")
        assert not client.connect()
        assert not client.connected

    def test_client_send_prompt_not_connected(self) -> None:
        from core.cli.ipc_client import IPCClient

        client = IPCClient()
        result = client.send_prompt("test")
        assert result["type"] == "error"
        assert "Not connected" in result["message"]


# ---------------------------------------------------------------------------
# CLIPoller unit tests
# ---------------------------------------------------------------------------


class TestCLIPoller:
    """Test the Unix socket server for CLI IPC."""

    def test_start_creates_socket(self) -> None:
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        poller = CLIPoller(mock_services, socket_path=sock_path)

        poller.start()
        try:
            assert sock_path.exists()
            assert poller.channel_name == "cli"
        finally:
            poller.stop()

    def test_stop_removes_socket(self) -> None:
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        poller = CLIPoller(mock_services, socket_path=sock_path)

        poller.start()
        assert sock_path.exists()
        poller.stop()
        assert not sock_path.exists()

    def test_cleans_stale_socket(self) -> None:
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        sock_path.touch()  # stale file from previous run
        mock_services = MagicMock()
        poller = CLIPoller(mock_services, socket_path=sock_path)

        poller.start()
        try:
            # Should have cleaned up stale and created new
            assert sock_path.exists()
        finally:
            poller.stop()


# ---------------------------------------------------------------------------
# Integration: CLIPoller ↔ IPCClient
# ---------------------------------------------------------------------------


class TestCLIChannelIntegration:
    """End-to-end tests for CLIPoller ↔ IPCClient IPC."""

    def test_connect_and_receive_session(self) -> None:
        """Client should receive session ID on connect."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        # Mock create_session to return a mock loop
        mock_loop = MagicMock()
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)  # wait for accept loop

        try:
            client = IPCClient(socket_path=sock_path)
            assert client.connect()
            assert client.session_id.startswith("cli-")
            client.close()
        finally:
            poller.stop()

    def test_send_prompt_and_receive_result(self) -> None:
        """Client sends prompt, server runs loop, client gets result."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_result = MagicMock()
        mock_result.text = "Berserk scored S tier (81.2)"
        mock_result.rounds = 3
        mock_result.tool_calls = []
        mock_result.termination_reason = "natural"
        mock_result.summary = ""

        mock_loop = MagicMock()
        mock_loop.run.return_value = mock_result
        mock_loop.model = "test-model"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.send_prompt("analyze Berserk")
            assert result["type"] == "result"
            assert "Berserk" in result["text"]
            assert result["rounds"] == 3
            assert result["tool_calls"] == []

            client.close()
        finally:
            poller.stop()

    def test_send_prompt_error_handling(self) -> None:
        """Server should return error when loop.run() raises."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_loop = MagicMock()
        mock_loop.run.side_effect = RuntimeError("API key missing")
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.send_prompt("do something")
            assert result["type"] == "error"
            assert "API key" in result["message"]

            client.close()
        finally:
            poller.stop()

    def test_empty_prompt_rejected(self) -> None:
        """Empty prompt should return error without calling loop."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_loop = MagicMock()
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.send_prompt("")
            assert result["type"] == "error"
            assert "Empty" in result["message"]
            mock_loop.run.assert_not_called()

            client.close()
        finally:
            poller.stop()

    def test_multiple_prompts_same_session(self) -> None:
        """Multiple prompts on same connection should use same session."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_result = MagicMock()
        mock_result.text = "response"
        mock_result.rounds = 1
        mock_result.tool_calls = []
        mock_result.termination_reason = "natural"

        mock_loop = MagicMock()
        mock_loop.run.return_value = mock_result
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            client.send_prompt("first")
            client.send_prompt("second")
            client.send_prompt("third")

            assert mock_loop.run.call_count == 3
            # create_session called once (same session for all prompts)
            mock_services.create_session.assert_called_once()

            client.close()
        finally:
            poller.stop()

    def test_is_serve_running_with_real_server(self) -> None:
        """is_serve_running should detect a live CLIPoller."""
        from core.cli.ipc_client import is_serve_running
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_services.create_session.return_value = (MagicMock(), MagicMock())

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            assert is_serve_running(sock_path)
        finally:
            poller.stop()

        assert not is_serve_running(sock_path)

    def test_quit_relayed_returns_should_break(self) -> None:
        """P1 fix: /quit should relay to serve and return should_break=True."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_loop = MagicMock()
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.send_command("/quit", "")
            assert result["type"] == "command_result"
            assert result.get("should_break") is True
            # Output should contain "Goodbye" from _handle_command
            assert "Goodbye" in result.get("output", "")

            client.close()
        finally:
            poller.stop()

    def test_resume_with_checkpoint(self) -> None:
        """P2 fix: resume message should load checkpoint into conversation."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_loop = MagicMock()
        mock_loop.model = "claude-opus-4-6"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            # Save a checkpoint first
            from core.cli.session_checkpoint import SessionCheckpoint, SessionState

            cp = SessionCheckpoint()
            state = SessionState(
                session_id="s-test123",
                round_idx=3,
                model="claude-opus-4-6",
                status="active",
                messages=[
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi there"},
                ],
                user_input="hello",
            )
            cp.save(state)

            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.request_resume(session_id="s-test123")
            assert result["type"] == "resumed"
            assert result["session_id"] == "s-test123"
            assert result["round_idx"] == 3
            assert result["message_count"] == 2

            client.close()
        finally:
            poller.stop()

    def test_resume_continue_latest(self) -> None:
        """P2 fix: --continue should resume the most recent session."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_loop = MagicMock()
        mock_loop.model = "claude-opus-4-6"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            from core.cli.session_checkpoint import SessionCheckpoint, SessionState

            cp = SessionCheckpoint()
            cp.save(
                SessionState(
                    session_id="s-old",
                    round_idx=1,
                    model="claude-opus-4-6",
                    status="active",
                    messages=[{"role": "user", "content": "old"}],
                    user_input="old",
                )
            )
            time.sleep(0.01)  # ensure different updated_at
            cp.save(
                SessionState(
                    session_id="s-latest",
                    round_idx=5,
                    model="claude-opus-4-6",
                    status="active",
                    messages=[{"role": "user", "content": "latest"}],
                    user_input="latest",
                )
            )

            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.request_resume(continue_latest=True)
            assert result["type"] == "resumed"
            assert result["session_id"] == "s-latest"
            assert result["round_idx"] == 5

            client.close()
        finally:
            poller.stop()

    def test_resume_no_sessions(self) -> None:
        """Resume should return error when no sessions exist."""
        from core.cli.ipc_client import IPCClient
        from core.gateway.pollers.cli_poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_loop = MagicMock()
        mock_loop.model = "claude-opus-4-6"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.request_resume(session_id="s-nonexistent")
            assert result["type"] == "resume_error"

            client.close()
        finally:
            poller.stop()
