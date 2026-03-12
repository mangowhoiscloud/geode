"""StdioMCPClient — subprocess-based MCP server communication via JSON-RPC.

Implements the MCP stdio transport:
  1. Spawn subprocess with command + args
  2. Send JSON-RPC messages on stdin
  3. Read JSON-RPC responses from stdout
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess  # nosec B404 — intentional: MCP server launch from trusted config
from typing import Any

log = logging.getLogger(__name__)


class StdioMCPClient:
    """MCP client using stdio transport (subprocess JSON-RPC)."""

    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._timeout_s = timeout_s
        self._process: subprocess.Popen[bytes] | None = None
        self._connected = False
        self._tools: list[dict[str, Any]] = []
        self._request_id = 0

    def is_connected(self) -> bool:
        return self._connected and self._process is not None and self._process.poll() is None

    def connect(self) -> bool:
        """Start the MCP server subprocess and initialize."""
        try:
            env = dict(os.environ)
            env.update(self._env)

            self._process = subprocess.Popen(  # noqa: S603  # nosec B603
                [self._command, *self._args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            # Send initialize request
            init_response = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "geode", "version": "0.9.0"},
                },
            )

            if init_response is None:
                self.close()
                return False

            # Send initialized notification
            self._send_notification("notifications/initialized", {})

            # List available tools
            tools_response = self._send_request("tools/list", {})
            if tools_response and "tools" in tools_response:
                self._tools = tools_response["tools"]

            self._connected = True
            log.info(
                "MCP connected: %s (%d tools)",
                self._command,
                len(self._tools),
            )
            return True

        except (OSError, FileNotFoundError) as exc:
            log.warning("Failed to start MCP server '%s': %s", self._command, exc)
            return False

    def list_tools(self) -> list[dict[str, Any]]:
        """Return cached tool definitions."""
        return list(self._tools)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        if not self.is_connected():
            raise ConnectionError(f"MCP server not connected: {self._command}")

        result = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )

        if result is None:
            return {"error": f"MCP tool call failed: {tool_name}"}

        return dict(result)

    def close(self) -> None:
        """Terminate the MCP server subprocess."""
        self._connected = False
        if self._process is not None:
            try:
                self._process.stdin.close()  # type: ignore[union-attr]
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                with contextlib.suppress(Exception):
                    self._process.kill()
            self._process = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for response."""
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            return None

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

        try:
            message = json.dumps(request) + "\n"
            self._process.stdin.write(message.encode("utf-8"))
            self._process.stdin.flush()

            # Read response line
            line = self._process.stdout.readline()
            if not line:
                return None

            response = json.loads(line.decode("utf-8"))
            if "error" in response:
                log.warning("MCP error: %s", response["error"])
                return None

            result: dict[str, Any] | None = response.get("result")
            return result
        except (json.JSONDecodeError, OSError, BrokenPipeError) as exc:
            log.warning("MCP communication error: %s", exc)
            return None

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._process is None or self._process.stdin is None:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            message = json.dumps(notification) + "\n"
            self._process.stdin.write(message.encode("utf-8"))
            self._process.stdin.flush()
        except (OSError, BrokenPipeError):
            pass
