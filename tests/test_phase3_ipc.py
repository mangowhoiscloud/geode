"""Tests for Phase 3: CLIChannel IPC (H3 resolution).

Tests the Unix domain socket protocol between CLIPoller (server) and
IPCClient (client), including connection, prompt relay, and error handling.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
        from core.server.ipc_server.poller import CLIPoller

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
        from core.server.ipc_server.poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        poller = CLIPoller(mock_services, socket_path=sock_path)

        poller.start()
        assert sock_path.exists()
        poller.stop()
        assert not sock_path.exists()

    def test_cleans_stale_socket(self) -> None:
        from core.server.ipc_server.poller import CLIPoller

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

    def test_async_prompt_runner_uses_arun_and_async_lanes(self) -> None:
        """IPC daemon prompt execution should not use sync loop/lane boundaries."""
        from core.server.ipc_server.poller import CLIPoller

        mock_result = MagicMock()
        mock_result.text = "async ok"
        mock_result.rounds = 1
        mock_result.tool_calls = []
        mock_result.termination_reason = "natural"
        mock_result.summary = ""

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(return_value=mock_result)
        mock_loop.run = MagicMock(side_effect=AssertionError("sync loop.run path used"))
        mock_loop.model = "test-model"
        mock_loop._quiet = True
        mock_loop._op_logger = MagicMock(_quiet=True)

        entered: list[tuple[str, list[str]]] = []

        class AsyncLaneQueue:
            @asynccontextmanager
            async def acquire_all_async(self, key: str, lanes: list[str]) -> Any:
                entered.append((key, lanes))
                yield

        mock_services = MagicMock()
        mock_services.lane_queue = AsyncLaneQueue()
        poller = CLIPoller(mock_services, socket_path=_test_sock())

        result = asyncio.run(
            poller._run_prompt_streaming_async(
                "hello",
                mock_loop,
                "cli-test",
                None,
            )
        )

        assert result["type"] == "result"
        assert result["text"] == "async ok"
        mock_loop.arun.assert_awaited_once_with("hello")
        mock_loop.run.assert_not_called()
        assert entered == [("cli:cli-test", ["session", "global"])]

    def test_async_prompt_runner_isolates_ui_state_per_task(self) -> None:
        """Concurrent async IPC prompts should keep console and writer bindings isolated."""
        from core.server.ipc_server.poller import CLIPoller

        class FakeClient:
            def __init__(self, name: str) -> None:
                self.name = name
                self.messages: list[dict[str, Any]] = []

            def get_capability(self) -> tuple[bool, int]:
                return True, 80

            async def drain_pending_sends(self) -> None:
                return None

            def sendall(self, payload: bytes) -> None:
                for line in payload.decode("utf-8").splitlines():
                    self.messages.append(json.loads(line))

        def make_result(text: str) -> MagicMock:
            result = MagicMock()
            result.text = text
            result.rounds = 1
            result.tool_calls = []
            result.termination_reason = "natural"
            result.summary = ""
            return result

        console_bindings: list[tuple[str, str]] = []

        async def run_case(name: str, client: FakeClient) -> dict[str, Any]:
            from core.ui.agentic_ui import _ipc_writer_local
            from core.ui.console import _ConsoleProxy

            async def arun(prompt: str) -> MagicMock:
                writer = getattr(_ipc_writer_local, "writer", None)
                writer.send_event("probe", prompt=prompt, client=name)
                console_at_runtime = getattr(_ConsoleProxy._local, "console", None)
                console_bindings.append((name, console_at_runtime._file._client.name))
                await asyncio.sleep(0)
                writer_after = getattr(_ipc_writer_local, "writer", None)
                assert writer_after is writer
                console_after = getattr(_ConsoleProxy._local, "console", None)
                assert console_after is console_at_runtime
                return make_result(f"done:{name}:{prompt}")

            loop = MagicMock()
            loop.arun = AsyncMock(side_effect=arun)
            loop.run = MagicMock(side_effect=AssertionError("sync loop.run path used"))
            loop.model = f"model-{name}"
            loop._quiet = True
            loop._op_logger = MagicMock(_quiet=True)
            poller = CLIPoller(MagicMock(lane_queue=None), socket_path=_test_sock())
            return await poller._run_prompt_streaming_async(
                f"prompt-{name}",
                loop,
                f"session-{name}",
                client,  # type: ignore[arg-type]
            )

        client_a = FakeClient("a")
        client_b = FakeClient("b")

        async def run_both() -> tuple[dict[str, Any], dict[str, Any]]:
            return await asyncio.gather(
                run_case("a", client_a),
                run_case("b", client_b),
            )

        result_a, result_b = asyncio.run(run_both())

        assert result_a["text"] == "done:a:prompt-a"
        assert result_b["text"] == "done:b:prompt-b"
        assert any(m.get("type") == "probe" and m.get("client") == "a" for m in client_a.messages)
        assert not any(m.get("client") == "b" for m in client_a.messages)
        assert any(m.get("type") == "probe" and m.get("client") == "b" for m in client_b.messages)
        assert not any(m.get("client") == "a" for m in client_b.messages)
        assert sorted(console_bindings) == [("a", "a"), ("b", "b")]


# ---------------------------------------------------------------------------
# Integration: CLIPoller ↔ IPCClient
# ---------------------------------------------------------------------------


class TestCLIChannelIntegration:
    """End-to-end tests for CLIPoller ↔ IPCClient IPC."""

    def test_connect_and_receive_session(self) -> None:
        """Client should receive session ID on connect."""
        from core.cli.ipc_client import IPCClient
        from core.server.ipc_server.poller import CLIPoller

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
        from core.server.ipc_server.poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_result = MagicMock()
        mock_result.text = "Berserk scored S tier (81.2)"
        mock_result.rounds = 3
        mock_result.tool_calls = []
        mock_result.termination_reason = "natural"
        mock_result.summary = ""

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(return_value=mock_result)
        mock_loop.run = MagicMock(side_effect=AssertionError("sync loop.run path used"))
        mock_loop.model = "test-model"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)
        mock_services.lane_queue = None

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
            mock_loop.arun.assert_awaited_once_with("analyze Berserk")
            mock_loop.run.assert_not_called()

            client.close()
        finally:
            poller.stop()

    def test_send_prompt_error_handling(self) -> None:
        """Server should return error when loop.arun() raises."""
        from core.cli.ipc_client import IPCClient
        from core.server.ipc_server.poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(side_effect=RuntimeError("API key missing"))
        mock_loop.run = MagicMock(side_effect=AssertionError("sync loop.run path used"))
        mock_services.create_session.return_value = (MagicMock(), mock_loop)
        mock_services.lane_queue = None

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            result = client.send_prompt("do something")
            assert result["type"] == "error"
            assert "API key" in result["message"]
            mock_loop.run.assert_not_called()

            client.close()
        finally:
            poller.stop()

    def test_empty_prompt_rejected(self) -> None:
        """Empty prompt should return error without calling loop."""
        from core.cli.ipc_client import IPCClient
        from core.server.ipc_server.poller import CLIPoller

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
            mock_loop.arun.assert_not_called()
            mock_loop.run.assert_not_called()

            client.close()
        finally:
            poller.stop()

    def test_multiple_prompts_same_session(self) -> None:
        """Multiple prompts on same connection should use same session."""
        from core.cli.ipc_client import IPCClient
        from core.server.ipc_server.poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_result = MagicMock()
        mock_result.text = "response"
        mock_result.rounds = 1
        mock_result.tool_calls = []
        mock_result.termination_reason = "natural"

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(return_value=mock_result)
        mock_loop.run = MagicMock(side_effect=AssertionError("sync loop.run path used"))
        mock_services.create_session.return_value = (MagicMock(), mock_loop)
        mock_services.lane_queue = None

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            client.connect()

            client.send_prompt("first")
            client.send_prompt("second")
            client.send_prompt("third")

            assert mock_loop.arun.await_count == 3
            mock_loop.run.assert_not_called()
            # create_session called once (same session for all prompts)
            mock_services.create_session.assert_called_once()

            client.close()
        finally:
            poller.stop()

    def test_is_serve_running_with_real_server(self) -> None:
        """is_serve_running should detect a live CLIPoller."""
        from core.cli.ipc_client import is_serve_running
        from core.server.ipc_server.poller import CLIPoller

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
        from core.server.ipc_server.poller import CLIPoller

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
        from core.server.ipc_server.poller import CLIPoller

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
            from core.runtime_state.session_checkpoint import SessionCheckpoint, SessionState

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
        from core.server.ipc_server.poller import CLIPoller

        sock_path = _test_sock()
        mock_services = MagicMock()
        mock_loop = MagicMock()
        mock_loop.model = "claude-opus-4-6"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            from core.runtime_state.session_checkpoint import SessionCheckpoint, SessionState

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
        from core.server.ipc_server.poller import CLIPoller

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

    def test_client_capability_non_tty_disables_ansi(self) -> None:
        """v0.84.0 — non-TTY client capability propagates to daemon-side Console.

        When the thin CLI advertises ``is_tty=False`` at connect time,
        the daemon's per-thread Rich Console for that session must be
        constructed with ``force_terminal=False`` so spinners and ANSI
        cursor-control codes don't pollute the client's stdout.
        """
        from unittest.mock import patch

        from core.cli.ipc_client import IPCClient
        from core.server.ipc_server.poller import CLIPoller
        from core.ui.console import _ConsoleProxy

        sock_path = _test_sock()
        mock_services = MagicMock()

        mock_result = MagicMock()
        mock_result.text = "ok"
        mock_result.rounds = 1
        mock_result.tool_calls = []
        mock_result.termination_reason = "natural"
        mock_result.summary = ""

        captured: dict[str, Any] = {}

        async def capture_console(prompt: str) -> Any:
            console_at_runtime = getattr(_ConsoleProxy._local, "console", None)
            captured["is_terminal"] = console_at_runtime.is_terminal if console_at_runtime else None
            captured["width"] = console_at_runtime.width if console_at_runtime else None
            return mock_result

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(side_effect=capture_console)
        mock_loop.run = MagicMock(side_effect=AssertionError("sync loop.run path used"))
        mock_loop.model = "test-model"
        mock_services.create_session.return_value = (MagicMock(), mock_loop)
        mock_services.lane_queue = None  # bypass lane queue

        poller = CLIPoller(mock_services, socket_path=sock_path)
        poller.start()
        time.sleep(0.1)

        try:
            client = IPCClient(socket_path=sock_path)
            # Patch isatty/terminal-size so capability reports non-TTY
            with (
                patch("sys.stdin.isatty", return_value=False),
                patch("sys.stdout.isatty", return_value=False),
                patch("shutil.get_terminal_size") as size_mock,
            ):
                size_mock.return_value = type("S", (), {"columns": 80, "lines": 24})()
                assert client.connect()
            time.sleep(0.05)  # let daemon process client_capability

            client.send_prompt("hello")
            assert captured.get("is_terminal") is False
            assert captured.get("width") == 80
            client.close()
        finally:
            poller.stop()
