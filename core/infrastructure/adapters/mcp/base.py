"""MCP Client Base — abstract client for MCP server communication."""

from __future__ import annotations

import logging
import signal
from typing import Any

log = logging.getLogger(__name__)


class MCPTimeoutError(TimeoutError):
    """Raised when an MCP tool call exceeds the configured timeout."""


class MCPClientBase:
    """Base MCP client with connection management and tool calling.

    The timeout_s parameter enforces a maximum duration for tool calls
    to prevent pipeline hangs from unresponsive MCP servers.
    """

    def __init__(self, server_url: str, *, timeout_s: float = 30.0) -> None:
        self._server_url = server_url
        self._timeout_s = timeout_s
        self._connected = False

    @property
    def server_url(self) -> str:
        return self._server_url

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Attempt to connect to MCP server. Returns True if successful."""
        # Stub: actual MCP connection via stdio/SSE will be added when servers are available
        log.info("MCP connect attempt: %s (stub)", self._server_url)
        return False

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server with timeout enforcement.

        Raises:
            ConnectionError: If not connected.
            MCPTimeoutError: If call exceeds timeout_s.
            NotImplementedError: Stub — MCP SDK not yet wired.
        """
        if not self._connected:
            raise ConnectionError(f"MCP server not connected: {self._server_url}")

        def _timeout_handler(signum: int, frame: Any) -> None:
            raise MCPTimeoutError(
                f"MCP tool call '{tool_name}' timed out after {self._timeout_s}s "
                f"(server: {self._server_url})"
            )

        # Set alarm for timeout (Unix only; on Windows, skip timeout enforcement)
        old_handler = None
        if hasattr(signal, "SIGALRM"):
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(int(self._timeout_s))

        try:
            # Stub: will use mcp SDK when available
            raise NotImplementedError("MCP tool calling not yet implemented")
        finally:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)  # Cancel alarm
                if old_handler is not None:
                    signal.signal(signal.SIGALRM, old_handler)

    def list_tools(self) -> list[dict[str, Any]]:
        """List available tools on the MCP server."""
        if not self._connected:
            return []
        return []

    def close(self) -> None:
        """Close the MCP connection."""
        self._connected = False
