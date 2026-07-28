"""Tests for MCP adapter lifecycle (startup/shutdown hooks, orphan prevention).

Covers:
- MCPServerManager startup/shutdown lifecycle
- Signal handler registration/unregistration
- StdioMCPClient PID tracking and close timeout
- Health check with auto-restart
- HookEvent orphan pruning verification (MCP_SERVER_* removed in H6)
- Idempotent shutdown
- Atexit safety net registration
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from core.hooks import HookEvent
from core.mcp.manager import (
    ADAPTER_ONLY_MCP_SERVERS,
    MCPServerManager,
    _normalise_mcp_tool,
)
from core.mcp.stdio_client import _CLOSE_TIMEOUT_S, StdioMCPClient

# ---------------------------------------------------------------------------
# HookEvent tests
# ---------------------------------------------------------------------------


class TestMCPHookEvents:
    """Verify MCP lifecycle hook events exist."""

    def test_mcp_server_events_pruned(self) -> None:
        """MCP_SERVER_STARTED/STOPPED were orphan events — removed in H6."""
        assert not hasattr(HookEvent, "MCP_SERVER_STARTED")
        assert not hasattr(HookEvent, "MCP_SERVER_STOPPED")

    # Total HookEvent count assertion intentionally lives in
    # tests/core/hooks/test_hooks.py::TestHookEvent::test_all_events_exist —
    # PR-HOOKEVENT-RESERVE (2026-05-26) folded this site's duplicate.


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
        init_resp = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18"}}\n'
        tools_resp = b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
        mock_proc.stdout.readline.side_effect = [init_resp, tools_resp]

        with patch("subprocess.Popen", return_value=mock_proc):
            result = client.connect()

        assert result is True
        assert client.pid == 12345
        assert client.server_protocol_version == "2025-06-18"

    def test_negotiated_protocol_version_recorded(self) -> None:
        """A server negotiating a different revision still connects; the
        negotiated version is recorded for diagnostics (ADR-014)."""
        client = StdioMCPClient(command="echo", timeout_s=0.5)
        mock_proc = MagicMock()
        mock_proc.pid = 12346
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()

        init_resp = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25"}}\n'
        tools_resp = b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
        mock_proc.stdout.readline.side_effect = [init_resp, tools_resp]

        with patch("subprocess.Popen", return_value=mock_proc):
            assert client.connect() is True

        assert client.server_protocol_version == "2025-11-25"

        # The outbound initialize declared the pinned revision.
        import json

        first_write = mock_proc.stdin.write.call_args_list[0][0][0]
        assert json.loads(first_write)["params"]["protocolVersion"] == "2025-06-18"

    def test_unsupported_negotiated_version_disconnects(self) -> None:
        """Server answering with a revision outside the supported set is
        rejected (spec SHOULD: disconnect on unsupported negotiation)."""
        client = StdioMCPClient(command="echo", timeout_s=0.5)
        mock_proc = MagicMock()
        mock_proc.pid = 12347
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()

        init_resp = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2026-07-28"}}\n'
        mock_proc.stdout.readline.side_effect = [init_resp]

        with patch("subprocess.Popen", return_value=mock_proc):
            assert client.connect() is False

        assert client.server_protocol_version is None
        assert client.is_connected() is False

    def test_non_string_negotiated_version_disconnects(self) -> None:
        """A non-string protocolVersion (array/object) must not raise on the
        frozenset membership test — it is rejected and the child is closed."""
        client = StdioMCPClient(command="echo", timeout_s=0.5)
        mock_proc = MagicMock()
        mock_proc.pid = 12349
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()

        init_resp = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":["2025-06-18"]}}\n'
        mock_proc.stdout.readline.side_effect = [init_resp]

        with patch("subprocess.Popen", return_value=mock_proc):
            assert client.connect() is False

        assert client.server_protocol_version is None
        mock_proc.terminate.assert_called_once()

    def test_unsolicited_notification_frame_skipped(self) -> None:
        """A server-initiated notification interleaved before the response
        must not desynchronize the stream (JSON-RPC id matching, ADR-014 R1)."""
        client = StdioMCPClient(command="echo", timeout_s=2.0)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        client._process = mock_proc
        client._connected = True
        client._pid = 111

        notif = b'{"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info"}}\n'
        resp = b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}\n'
        mock_proc.stdout.readline.side_effect = [notif, resp]

        result = asyncio.run(client.acall_tool("some_tool", {}))
        assert result == {"content": []}

    def test_chatty_stderr_does_not_wedge_connect(self) -> None:
        """A child writing >64 KB to stderr before serving must not deadlock —
        the drain thread keeps the pipe moving (ADR-014 R2). Real subprocess."""
        import sys as _sys

        script = (
            "import sys\n"
            "sys.stderr.write('x'*262144)\n"
            "sys.stderr.flush()\n"
            "import json\n"
            "req=json.loads(sys.stdin.readline())\n"
            "sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':req['id'],"
            "'result':{'protocolVersion':'2025-06-18'}})+'\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
            "req=json.loads(sys.stdin.readline())\n"
            "sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':req['id'],"
            "'result':{'tools':[]}})+'\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
        )
        client = StdioMCPClient(command=_sys.executable, args=["-c", script], timeout_s=3.0)
        try:
            assert client.connect() is True
        finally:
            client.close()

    def test_missing_negotiated_version_disconnects(self) -> None:
        """An initialize result without protocolVersion is nonconforming —
        rejected instead of silently accepted."""
        client = StdioMCPClient(command="echo", timeout_s=0.5)
        mock_proc = MagicMock()
        mock_proc.pid = 12348
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()

        init_resp = b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
        mock_proc.stdout.readline.side_effect = [init_resp]

        with patch("subprocess.Popen", return_value=mock_proc):
            assert client.connect() is False

        assert client.server_protocol_version is None

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

    def test_calendar_adapter_servers_do_not_expose_raw_tools(self) -> None:
        manager = MCPServerManager()
        manager._servers = {
            "google-calendar": {},
            "caldav": {},
            "ordinary": {},
        }
        calendar_client = MagicMock()
        calendar_client.list_tools.return_value = [{"name": "list_events", "inputSchema": {}}]
        ordinary_client = MagicMock()
        ordinary_client.list_tools.return_value = [{"name": "other_tool", "inputSchema": {}}]
        manager._clients = {
            "google-calendar": calendar_client,
            "caldav": calendar_client,
            "ordinary": ordinary_client,
        }

        tools = manager.get_all_tools()

        assert {"google-calendar", "caldav"} == ADAPTER_ONLY_MCP_SERVERS
        assert [tool["name"] for tool in tools] == ["other_tool"]
        assert manager.find_server_for_tool("list_events") is None
        assert manager.find_server_for_tool("other_tool") == "ordinary"
        calendar_client.list_tools.assert_not_called()


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

    def test_failed_server_is_not_retried_until_cooldown(self) -> None:
        """Repeated tool-list builds must not spam MCP_SERVER_FAILED hooks."""
        mgr = MCPServerManager()
        mgr._servers = {"missing": {"command": "missing-mcp"}}

        mock_client = MagicMock()
        mock_client.connect.return_value = False

        with (
            patch("core.mcp.manager.StdioMCPClient", return_value=mock_client) as client_cls,
            patch("core.mcp.manager._fire_mcp_hook") as fire_hook,
        ):
            assert mgr._get_client("missing") is None
            assert mgr._get_client("missing") is None

        client_cls.assert_called_once()
        fire_hook.assert_called_once()

    def test_auto_restart_bypasses_failed_server_cooldown(self) -> None:
        mgr = MCPServerManager()
        mgr._servers = {"s1": {"command": "mock"}}
        mgr._failed_at["s1"] = 1.0

        with patch.object(mgr, "_get_client", return_value=None) as get_client:
            result = mgr.check_health(auto_restart=True)

        assert result == {"s1": False}
        assert "s1" not in mgr._failed_at
        get_client.assert_called_once_with("s1")


class TestMCPAsyncCalls:
    """Test async MCP dispatch wrappers."""

    def test_stdio_client_acall_tool_sends_request(self) -> None:
        client = StdioMCPClient(command="mock")
        client._connected = True
        client._process = MagicMock()
        client._process.poll.return_value = None
        with patch.object(client, "_send_request", return_value={"ok": True}) as mock_call:
            result = asyncio.run(client.acall_tool("navigate", {"url": "https://example.com"}))

        mock_call.assert_called_once_with(
            "tools/call",
            {"name": "navigate", "arguments": {"url": "https://example.com"}},
        )
        assert result == {"ok": True}

    def test_manager_acall_tool_uses_client_async_path(self) -> None:
        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.list_tools.return_value = [
            {
                "name": "navigate",
                "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}},
            }
        ]
        mock_client.acall_tool = AsyncMock(return_value={"result": "ok"})

        async def scenario() -> dict[str, Any]:
            with patch.object(mgr, "_get_client", return_value=mock_client):
                return await mgr.acall_tool("playwriter", "navigate", {"url": "x"})

        result = asyncio.run(scenario())

        mock_client.acall_tool.assert_awaited_once_with("navigate", {"url": "x"})
        assert result == {"result": "ok"}

    def test_manager_acall_tool_maps_file_path_alias_to_schema_path(self) -> None:
        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.list_tools.return_value = [
            {
                "name": "write_file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            }
        ]
        mock_client.acall_tool = AsyncMock(return_value={"result": "ok"})

        async def scenario() -> dict[str, Any]:
            with patch.object(mgr, "_get_client", return_value=mock_client):
                return await mgr.acall_tool(
                    "filesystem",
                    "write_file",
                    {"file_path": "/workspace/out.txt", "content": "hello"},
                )

        result = asyncio.run(scenario())

        mock_client.acall_tool.assert_awaited_once_with(
            "write_file",
            {"path": "/workspace/out.txt", "content": "hello"},
        )
        assert result == {"result": "ok"}

    def test_manager_acall_tool_preserves_file_path_when_schema_requires_it(self) -> None:
        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.list_tools.return_value = [
            {
                "name": "write_file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            }
        ]
        mock_client.acall_tool = AsyncMock(return_value={"result": "ok"})

        async def scenario() -> dict[str, Any]:
            with patch.object(mgr, "_get_client", return_value=mock_client):
                return await mgr.acall_tool(
                    "filesystem",
                    "write_file",
                    {"file_path": "/workspace/out.txt", "content": "hello"},
                )

        result = asyncio.run(scenario())

        mock_client.acall_tool.assert_awaited_once_with(
            "write_file",
            {"file_path": "/workspace/out.txt", "content": "hello"},
        )
        assert result == {"result": "ok"}

    def test_manager_acall_tool_drops_conflicting_read_text_window_args(self) -> None:
        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.list_tools.return_value = [
            {
                "name": "read_text_file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "head": {"type": "integer"},
                        "tail": {"type": "integer"},
                    },
                },
            }
        ]
        mock_client.acall_tool = AsyncMock(return_value={"result": "ok"})

        async def scenario() -> dict[str, Any]:
            with patch.object(mgr, "_get_client", return_value=mock_client):
                return await mgr.acall_tool(
                    "filesystem",
                    "read_text_file",
                    {"path": "/workspace/in.txt", "head": 2000, "tail": 2000},
                )

        result = asyncio.run(scenario())

        mock_client.acall_tool.assert_awaited_once_with(
            "read_text_file",
            {"path": "/workspace/in.txt"},
        )
        assert result == {"result": "ok"}

    def test_manager_acall_tool_offloads_eof_trim_from_cached_multi_read(self, tmp_path) -> None:
        source = tmp_path / "file_01.txt"
        target = tmp_path / "uppercase" / "file_01.txt"
        source.write_text("Hello world", encoding="utf-8")

        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.list_tools.return_value = [
            {
                "name": "read_multiple_files",
                "inputSchema": {
                    "type": "object",
                    "properties": {"paths": {"type": "array"}},
                },
            },
            {
                "name": "write_file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
        ]
        mock_client.acall_tool = AsyncMock(
            side_effect=[
                {"content": [{"type": "text", "text": f"{source}:\nHello world\n"}]},
                {"result": "ok"},
            ]
        )

        async def scenario() -> None:
            with patch.object(mgr, "_get_client", return_value=mock_client):
                await mgr.acall_tool(
                    "filesystem",
                    "read_multiple_files",
                    {"paths": [str(source)]},
                )
                await mgr.acall_tool(
                    "filesystem",
                    "write_file",
                    {"path": str(target), "content": "HELLO WORLD\n"},
                )

        asyncio.run(scenario())

        mock_client.acall_tool.assert_any_await(
            "write_file",
            {"path": str(target), "content": "HELLO WORLD"},
        )

    def test_manager_acall_tool_keeps_newline_when_cached_source_has_one(self, tmp_path) -> None:
        source = tmp_path / "file_01.txt"
        target = tmp_path / "uppercase" / "file_01.txt"
        source.write_text("Hello world\n", encoding="utf-8")

        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.list_tools.return_value = [
            {
                "name": "read_multiple_files",
                "inputSchema": {
                    "type": "object",
                    "properties": {"paths": {"type": "array"}},
                },
            },
            {
                "name": "write_file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
        ]
        mock_client.acall_tool = AsyncMock(
            side_effect=[
                {"content": [{"type": "text", "text": f"{source}:\nHello world\n"}]},
                {"result": "ok"},
            ]
        )

        async def scenario() -> None:
            with patch.object(mgr, "_get_client", return_value=mock_client):
                await mgr.acall_tool(
                    "filesystem",
                    "read_multiple_files",
                    {"paths": [str(source)]},
                )
                await mgr.acall_tool(
                    "filesystem",
                    "write_file",
                    {"path": str(target), "content": "HELLO WORLD\n"},
                )

        asyncio.run(scenario())

        mock_client.acall_tool.assert_any_await(
            "write_file",
            {"path": str(target), "content": "HELLO WORLD\n"},
        )

    def test_normalised_mcp_tool_adds_exact_read_warning(self) -> None:
        tool = _normalise_mcp_tool(
            {
                "name": "read_multiple_files",
                "description": "Read several files.",
                "inputSchema": {"type": "object", "properties": {}},
            }
        )

        assert "tracks local source EOF metadata" in tool["description"]
        assert "input_schema" in tool


class TestMCPFallbackHints:
    """Verify MCP fallback hints in error messages."""

    def test_unavailable_server_with_hint(self) -> None:
        """playwriter unavailable → error includes playwright fallback hint."""
        mgr = MCPServerManager()
        result = asyncio.run(
            mgr.acall_tool("playwriter", "navigate", {"url": "https://example.com"})
        )
        assert "error" in result
        # Hint is in dedicated field (LLM-friendly structured error)
        assert "playwright" in result.get("hint", "")

    def test_unavailable_server_without_hint(self) -> None:
        """Unknown server unavailable → no fallback hint."""
        mgr = MCPServerManager()
        result = asyncio.run(mgr.acall_tool("unknown_server", "some_tool", {}))
        assert "error" in result
        # No fallback server → hint should not mention fallback
        assert "instead" not in result.get("hint", "").lower() or "playwright" not in result.get(
            "hint", ""
        )

    def test_failed_call_with_hint(self) -> None:
        """playwriter call fails → error includes playwright fallback hint."""
        mgr = MCPServerManager()
        mock_client = MagicMock()
        mock_client.acall_tool = AsyncMock(side_effect=ConnectionError("extension not running"))

        with patch.object(mgr, "_get_client", return_value=mock_client):
            result = asyncio.run(
                mgr.acall_tool("playwriter", "navigate", {"url": "https://example.com"})
            )
        assert "error" in result
        # Hint is in dedicated field (LLM-friendly structured error)
        assert "playwright" in result.get("hint", "")


class TestServerRecycleResilience:
    """Stateless-era hardening (ADR-014 R3/R4/R5): server subprocesses may
    recycle mid-session; the manager retries, the executor stays honest, and
    the loop can detect the recycle via the connection epoch."""

    def test_acall_tool_retries_once_after_mid_call_death(self) -> None:
        mgr = MCPServerManager()
        mgr._servers["srv"] = {"command": "echo", "args": [], "env": {}}

        dead = MagicMock()
        dead.list_tools.return_value = [
            {"name": "t", "input_schema": {}, "annotations": {"idempotentHint": True}}
        ]
        dead.acall_tool = AsyncMock(return_value={"error": "MCP tool call failed: t"})
        dead.is_connected.return_value = False
        mgr._clients["srv"] = dead

        fresh = MagicMock()
        fresh.acall_tool = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

        with patch.object(mgr, "_get_client", side_effect=[dead, fresh]):
            result = asyncio.run(mgr.acall_tool("srv", "t", {}))

        assert result == {"content": [{"type": "text", "text": "ok"}]}
        dead.close.assert_called_once()

    def test_acall_tool_mid_call_death_without_respawn_is_connection_error(self) -> None:
        mgr = MCPServerManager()
        mgr._servers["srv"] = {"command": "echo", "args": [], "env": {}}

        dead = MagicMock()
        dead.list_tools.return_value = [
            {"name": "t", "input_schema": {}, "annotations": {"readOnlyHint": True}}
        ]
        dead.acall_tool = AsyncMock(return_value={"error": "MCP tool call failed: t"})
        dead.is_connected.return_value = False

        with patch.object(mgr, "_get_client", side_effect=[dead, None]):
            result = asyncio.run(mgr.acall_tool("srv", "t", {}))

        assert result.get("error_type") == "connection"
        assert "MCP tool call failed" in result.get("error", "")

    def test_connection_epoch_bumps_on_new_client(self) -> None:
        mgr = MCPServerManager()
        mgr._servers["srv"] = {"command": "echo", "args": [], "env": {}}
        assert mgr.connection_epoch == 0

        good = MagicMock()
        good.connect.return_value = True
        with patch("core.mcp.manager.StdioMCPClient", return_value=good):
            client = mgr._get_client("srv")

        assert client is good
        assert mgr.connection_epoch == 1

    def test_unavailable_mcp_tool_not_reported_as_unknown(self) -> None:
        from core.agent.tool_executor import ToolExecutor

        mgr = MCPServerManager()
        mgr._last_seen_tools["gone_tool"] = "srv"

        executor = ToolExecutor(action_handlers={}, mcp_manager=mgr, hitl_level=0)
        with patch.object(mgr, "find_server_for_tool", return_value=None):
            result = asyncio.run(executor._dispatch_async("gone_tool", {}))

        assert "currently unavailable" in result.get("error", "")
        assert "Unknown tool" not in result.get("error", "")

    def test_last_seen_tools_recorded_by_get_all_tools(self) -> None:
        mgr = MCPServerManager()
        mgr._servers["srv"] = {"command": "echo", "args": [], "env": {}}
        client = MagicMock()
        client.is_connected.return_value = True
        client.list_tools.return_value = [{"name": "t1", "inputSchema": {}}]
        mgr._clients["srv"] = client

        _tools = mgr.get_all_tools()
        assert mgr.last_known_server_for_tool("t1") == "srv"
        assert mgr.last_known_server_for_tool("nope") is None

    def test_acall_tool_no_retry_for_non_idempotent_tool(self) -> None:
        """Mid-call death of an unannotated tool must NOT auto-retry — the
        original call may have executed (at-least-once hazard)."""
        mgr = MCPServerManager()
        mgr._servers["srv"] = {"command": "echo", "args": [], "env": {}}
        dead = MagicMock()
        dead.list_tools.return_value = [{"name": "t", "input_schema": {}}]
        dead.acall_tool = AsyncMock(return_value={"error": "MCP tool call failed: t"})
        dead.is_connected.return_value = False

        with patch.object(mgr, "_get_client", side_effect=[dead]) as getc:
            result = asyncio.run(mgr.acall_tool("srv", "t", {}))

        assert result.get("error_type") == "connection"
        assert "outcome unknown" in result.get("error", "")
        assert getc.call_count == 1

    def test_find_server_for_tool_records_last_seen(self) -> None:
        mgr = MCPServerManager()
        mgr._servers["srv"] = {"command": "echo", "args": [], "env": {}}
        client = MagicMock()
        client.is_connected.return_value = True
        client.list_tools.return_value = [{"name": "t9"}]
        mgr._clients["srv"] = client

        assert mgr.find_server_for_tool("t9") == "srv"
        assert mgr.last_known_server_for_tool("t9") == "srv"

    def test_coalesced_notification_and_response_single_write(self) -> None:
        """Notification + response arriving in ONE stdout write must not
        starve the next select() — stdout is unbuffered (ADR-014 R1).
        Real subprocess."""
        import sys as _sys

        script = (
            "import sys,json\n"
            "def serve(result):\n"
            "    req=json.loads(sys.stdin.readline())\n"
            "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':req['id'],"
            "'result':result})+'\\n')\n"
            "    sys.stdout.flush()\n"
            "serve({'protocolVersion':'2025-06-18'})\n"
            "sys.stdin.readline()\n"
            "serve({'tools':[{'name':'t','inputSchema':{}}]})\n"
            "req=json.loads(sys.stdin.readline())\n"
            "notif=json.dumps({'jsonrpc':'2.0','method':'notifications/message','params':{}})\n"
            "resp=json.dumps({'jsonrpc':'2.0','id':req['id'],"
            "'result':{'content':[{'type':'text','text':'ok'}]}})\n"
            "sys.stdout.write(notif+'\\n'+resp+'\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stdin.readline()\n"
        )
        client = StdioMCPClient(command=_sys.executable, args=["-c", script], timeout_s=3.0)
        try:
            assert client.connect() is True
            result = asyncio.run(client.acall_tool("t", {}))
            assert result == {"content": [{"type": "text", "text": "ok"}]}
        finally:
            client.close()
