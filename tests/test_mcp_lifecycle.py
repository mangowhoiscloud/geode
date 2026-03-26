"""Tests for MCP adapter lifecycle (startup/shutdown hooks, orphan prevention).

Covers:
- MCPServerManager startup/shutdown lifecycle
- Signal handler registration/unregistration
- StdioMCPClient PID tracking and close timeout
- Health check with auto-restart
- HookEvent MCP_SERVER_STARTED / MCP_SERVER_STOPPED existence
- Idempotent shutdown
- Atexit safety net registration
"""

from __future__ import annotations

import signal
from typing import Any
from unittest.mock import MagicMock, patch

from core.hooks import HookEvent
from core.mcp.manager import MCPServerManager
from core.mcp.stdio_client import _CLOSE_TIMEOUT_S, StdioMCPClient

# ---------------------------------------------------------------------------
# HookEvent tests
# ---------------------------------------------------------------------------


class TestMCPHookEvents:
    """Verify MCP lifecycle hook events exist."""

    def test_mcp_server_started_event(self) -> None:
        assert hasattr(HookEvent, "MCP_SERVER_STARTED")
        assert HookEvent.MCP_SERVER_STARTED.value == "mcp_server_started"

    def test_mcp_server_stopped_event(self) -> None:
        assert hasattr(HookEvent, "MCP_SERVER_STOPPED")
        assert HookEvent.MCP_SERVER_STOPPED.value == "mcp_server_stopped"

    def test_hook_event_count_includes_mcp(self) -> None:
        """Total hook events should be 36 (includes 2 MCP_SERVER_* + 2 CONTEXT_* events)."""
        assert len(HookEvent) == 36


# ---------------------------------------------------------------------------
# StdioMCPClient tests
# ---------------------------------------------------------------------------


class TestStdioMCPClientLifecycle:
    """Test StdioMCPClient PID tracking and close behavior."""

    def test_pid_initially_none(self) -> None:
        client = StdioMCPClient(command="echo", args=["hello"])
        assert client.pid is None

    def test_pid_set_after_connect(self) -> None:
        """PID should be set after subprocess is spawned (mocked)."""
        client = StdioMCPClient(command="echo", args=["hello"])
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()

        # Mock the initialize response
        init_resp = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}\n'
        tools_resp = b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
        mock_proc.stdout.readline.side_effect = [init_resp, tools_resp]

        with patch("subprocess.Popen", return_value=mock_proc):
            result = client.connect()

        assert result is True
        assert client.pid == 12345

    def test_pid_cleared_after_close(self) -> None:
        """PID should be None after close."""
        client = StdioMCPClient(command="echo")
        client._process = MagicMock()
        client._process.pid = 99
        client._pid = 99
        client._connected = True

        client.close()

        assert client.pid is None
        assert client._process is None

    def test_close_graceful_then_kill(self) -> None:
        """Close should try terminate first, then kill on timeout."""
        import subprocess

        client = StdioMCPClient(command="echo")
        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_proc.stdin = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="echo", timeout=5)
        client._process = mock_proc
        client._pid = 42
        client._connected = True

        client.close()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert client._process is None
        assert client.pid is None

    def test_close_timeout_constant(self) -> None:
        """Verify the close timeout constant is 5 seconds."""
        assert _CLOSE_TIMEOUT_S == 5


# ---------------------------------------------------------------------------
# MCPServerManager lifecycle tests
# ---------------------------------------------------------------------------


class TestMCPManagerStartup:
    """Test MCPServerManager.startup() lifecycle."""

    def test_startup_calls_load_config_and_connect(self) -> None:
        mgr = MCPServerManager()

        with (
            patch.object(mgr, "load_config", return_value=2) as mock_load,
            patch.object(mgr, "_connect_all", return_value=2) as mock_connect,
            patch.object(mgr, "_install_signal_handlers") as mock_signals,
        ):
            result = mgr.startup()

        mock_load.assert_called_once()
        mock_connect.assert_called_once()
        mock_signals.assert_called_once()
        assert result == 2

    def test_startup_returns_connected_count(self) -> None:
        mgr = MCPServerManager()

        with (
            patch.object(mgr, "load_config", return_value=3),
            patch.object(mgr, "_connect_all", return_value=1),
            patch.object(mgr, "_install_signal_handlers"),
        ):
            result = mgr.startup()

        assert result == 1


class TestMCPManagerShutdown:
    """Test MCPServerManager.shutdown() lifecycle."""

    def test_shutdown_calls_close_all_and_uninstall(self) -> None:
        mgr = MCPServerManager()

        with (
            patch.object(mgr, "close_all") as mock_close,
            patch.object(mgr, "_uninstall_signal_handlers") as mock_unsig,
        ):
            mgr.shutdown()

        mock_close.assert_called_once()
        mock_unsig.assert_called_once()

    def test_shutdown_idempotent(self) -> None:
        """Calling shutdown() multiple times should only close once."""
        mgr = MCPServerManager()
        call_count = 0

        def counting_close() -> None:
            nonlocal call_count
            call_count += 1

        with (
            patch.object(mgr, "close_all", side_effect=counting_close),
            patch.object(mgr, "_uninstall_signal_handlers"),
        ):
            mgr.shutdown()
            mgr.shutdown()
            mgr.shutdown()

        assert call_count == 1

    def test_shutdown_sets_flag(self) -> None:
        mgr = MCPServerManager()
        assert mgr._shutdown_called is False

        with (
            patch.object(mgr, "close_all"),
            patch.object(mgr, "_uninstall_signal_handlers"),
        ):
            mgr.shutdown()

        assert mgr._shutdown_called is True


class TestMCPManagerSignalHandlers:
    """Test signal handler installation/uninstallation."""

    def test_signal_handler_installation(self) -> None:
        """Signal handler should be installed in main thread."""
        mgr = MCPServerManager()

        with (
            patch("core.mcp.manager._is_main_thread", return_value=True),
            patch("signal.getsignal", return_value=signal.SIG_DFL),
            patch("signal.signal") as mock_signal,
            patch("atexit.register") as mock_atexit,
        ):
            mgr._install_signal_handlers()

        assert mgr._signal_installed is True
        # SIGTERM handler should be installed
        mock_signal.assert_called()
        # atexit should be registered
        mock_atexit.assert_called_once()

    def test_signal_handler_not_installed_in_non_main_thread(self) -> None:
        mgr = MCPServerManager()

        with patch("core.mcp.manager._is_main_thread", return_value=False):
            mgr._install_signal_handlers()

        assert mgr._signal_installed is False

    def test_signal_handler_idempotent(self) -> None:
        """Installing twice should not double-register."""
        mgr = MCPServerManager()
        mgr._signal_installed = True

        with patch("signal.signal") as mock_signal:
            mgr._install_signal_handlers()

        mock_signal.assert_not_called()

    def test_uninstall_signal_handlers(self) -> None:
        mgr = MCPServerManager()
        mgr._signal_installed = True
        mgr._prev_sigterm = signal.SIG_DFL

        with (
            patch("core.mcp.manager._is_main_thread", return_value=True),
            patch("signal.signal") as mock_signal,
        ):
            mgr._uninstall_signal_handlers()

        assert mgr._signal_installed is False
        mock_signal.assert_called_once_with(signal.SIGTERM, signal.SIG_DFL)


class TestMCPManagerAtexitCleanup:
    """Test atexit safety net."""

    def test_atexit_cleanup_calls_close_all_if_not_shutdown(self) -> None:
        mgr = MCPServerManager()
        mgr._shutdown_called = False

        with patch.object(mgr, "close_all") as mock_close:
            mgr._atexit_cleanup()

        mock_close.assert_called_once()

    def test_atexit_cleanup_skips_if_already_shutdown(self) -> None:
        mgr = MCPServerManager()
        mgr._shutdown_called = True

        with patch.object(mgr, "close_all") as mock_close:
            mgr._atexit_cleanup()

        mock_close.assert_not_called()


class TestMCPManagerHealthCheck:
    """Test health_check with auto_restart."""

    def test_health_check_basic(self) -> None:
        mgr = MCPServerManager()
        mgr._servers = {"server-a": {"command": "echo"}, "server-b": {"command": "cat"}}

        client_a = MagicMock()
        client_a.is_connected.return_value = True
        client_b = MagicMock()
        client_b.is_connected.return_value = False

        mgr._clients = {"server-a": client_a, "server-b": client_b}

        result = mgr.check_health()
        assert result == {"server-a": True, "server-b": False}

    def test_health_check_auto_restart(self) -> None:
        mgr = MCPServerManager()
        mgr._servers = {"dead-server": {"command": "echo"}}

        dead_client = MagicMock()
        dead_client.is_connected.return_value = False
        mgr._clients = {"dead-server": dead_client}

        # Mock _get_client to simulate successful restart
        new_client = MagicMock()
        new_client.is_connected.return_value = True

        with patch.object(mgr, "_get_client", return_value=new_client):
            result = mgr.check_health(auto_restart=True)

        assert result == {"dead-server": True}

    def test_health_check_auto_restart_failure(self) -> None:
        mgr = MCPServerManager()
        mgr._servers = {"dead-server": {"command": "echo"}}

        dead_client = MagicMock()
        dead_client.is_connected.return_value = False
        mgr._clients = {"dead-server": dead_client}

        with patch.object(mgr, "_get_client", return_value=None):
            result = mgr.check_health(auto_restart=True)

        assert result == {"dead-server": False}

    def test_health_check_no_auto_restart_by_default(self) -> None:
        """Without auto_restart, dead servers stay dead."""
        mgr = MCPServerManager()
        mgr._servers = {"dead-server": {"command": "echo"}}

        dead_client = MagicMock()
        dead_client.is_connected.return_value = False
        mgr._clients = {"dead-server": dead_client}

        with patch.object(mgr, "_get_client") as mock_get:
            result = mgr.check_health()

        # _get_client should NOT be called when auto_restart is False
        mock_get.assert_not_called()
        assert result == {"dead-server": False}


class TestMCPManagerCloseAll:
    """Test close_all with PID logging."""

    def test_close_all_closes_every_client(self) -> None:
        mgr = MCPServerManager()
        client_a = MagicMock()
        client_a.pid = 100
        client_b = MagicMock()
        client_b.pid = 200

        mgr._clients = {"a": client_a, "b": client_b}

        mgr.close_all()

        client_a.close.assert_called_once()
        client_b.close.assert_called_once()
        assert len(mgr._clients) == 0

    def test_close_all_tolerates_exceptions(self) -> None:
        mgr = MCPServerManager()
        client = MagicMock()
        client.pid = 300
        client.close.side_effect = RuntimeError("boom")
        mgr._clients = {"failing": client}

        # Should not raise
        mgr.close_all()
        assert len(mgr._clients) == 0


class TestMCPManagerConnectAll:
    """Test _connect_all helper."""

    def test_connect_all_counts_successes(self) -> None:
        mgr = MCPServerManager()
        mgr._servers = {"s1": {}, "s2": {}, "s3": {}}

        call_count = 0

        def mock_get_client(name: str) -> Any:
            nonlocal call_count
            call_count += 1
            if name == "s2":
                return None  # failed to connect
            return MagicMock()

        with patch.object(mgr, "_get_client", side_effect=mock_get_client):
            result = mgr._connect_all()

        assert result == 2
        assert call_count == 3
