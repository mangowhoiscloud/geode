"""StdioMCPClient — subprocess-based MCP server communication via JSON-RPC.

Implements the MCP stdio transport:
  1. Spawn subprocess with command + args
  2. Send JSON-RPC messages on stdin
  3. Read JSON-RPC responses from stdout
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess  # nosec B404 — intentional: MCP server launch from trusted config
import threading
import time
from typing import Any

log = logging.getLogger(__name__)


def _geode_version() -> str:
    """Real package version for the MCP handshake clientInfo.

    PR-V1-PRE-CLEANUP (2026-06-13): was a hardcoded "0.9.0" — the same
    handshake-misreport class geode-mcp fixed in v0.99.169, on the
    client side this time.
    """
    from core import __version__

    return __version__


# Graceful shutdown timeout before force kill (seconds)
_CLOSE_TIMEOUT_S = 5

# MCP protocol revision declared in `initialize`. This client only uses the
# base operations (initialize / tools/list / tools/call) shared by every
# published pre-2026 revision; the server answers with the revision it will
# actually speak, captured in ``server_protocol_version``.
# ref: mcp/shared/version.py SUPPORTED_PROTOCOL_VERSIONS (python-sdk v1 line).
# The 2026-07-28 stateless revision removes `initialize` entirely, but SDK-v2
# servers detect the protocol era from this opening request and keep serving
# classic clients — see docs/adr/ADR-014-mcp-2026-07-28-stateless-spec.md.
_PROTOCOL_VERSION = "2025-06-18"

# Revisions whose wire shape this client can speak (base operations:
# initialize / tools/list / tools/call are identical across these). Per the
# spec's version negotiation, the client SHOULD disconnect when the server
# answers with a revision outside this set.
_SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})


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
        self._pid: int | None = None
        self._request_lock = threading.Lock()
        # Revision the server negotiated in the `initialize` response;
        # None until connected (or if the server omitted it).
        self.server_protocol_version: str | None = None

    @property
    def pid(self) -> int | None:
        """Return the PID of the subprocess, or None if not running."""
        return self._pid

    def is_connected(self) -> bool:
        return self._connected and self._process is not None and self._process.poll() is None

    def connect(self) -> bool:
        """Start the MCP server subprocess and initialize."""
        try:
            self.server_protocol_version = None  # reset on (re)connect
            env = dict(os.environ)
            env.update(self._env)

            # bufsize=0: stdout stays UNBUFFERED so readline() never pulls a
            # second frame into a Python-side buffer select() cannot see —
            # with default buffering, a notification+response arriving
            # together left the response invisible to the next select() and
            # the call timed out despite the data being buffered.
            self._process = subprocess.Popen(  # noqa: S603  # nosec B603
                [self._command, *self._args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=0,
            )
            self._pid = self._process.pid
            log.debug(
                "MCP subprocess spawned: %s (PID %d)",
                self._command,
                self._pid,
            )

            # Drain stderr in a daemon thread — an undrained PIPE wedges the
            # child at the 64 KB buffer while is_connected() keeps reporting
            # healthy (every call then times out). Skipped for mocked pipes.
            stderr_pipe = self._process.stderr
            if stderr_pipe is not None:
                try:
                    real_fd = isinstance(stderr_pipe.fileno(), int)
                except Exception:
                    real_fd = False
                if real_fd:
                    threading.Thread(
                        target=self._drain_stderr,
                        args=(stderr_pipe,),
                        daemon=True,
                        name=f"mcp-stderr-{self._pid}",
                    ).start()

            # Wait for server to be ready (npx may download packages first)
            import time

            wait_deadline = time.time() + min(self._timeout_s, 10.0)
            while time.time() < wait_deadline:
                if self._process.poll() is not None:
                    log.debug(
                        "MCP server exited prematurely (PID %d, code=%s)",
                        self._pid,
                        self._process.returncode,
                    )
                    self._process = None
                    self._pid = None
                    return False
                time.sleep(0.5)

            # Send initialize request
            init_response = self._send_request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "geode", "version": _geode_version()},
                },
            )

            if init_response is None:
                self.close()
                return False

            # Version negotiation: the server answers with the revision it
            # will speak. Outside our supported set → disconnect (spec SHOULD).
            negotiated = init_response.get("protocolVersion")
            # isinstance first: a non-string (array/object) value would raise
            # TypeError on the frozenset membership test and leak the child.
            if not isinstance(negotiated, str) or negotiated not in _SUPPORTED_PROTOCOL_VERSIONS:
                log.warning(
                    "MCP server %s negotiated unsupported protocol %r "
                    "(client supports %s) — disconnecting",
                    self._command,
                    negotiated,
                    sorted(_SUPPORTED_PROTOCOL_VERSIONS),
                )
                self.close()
                return False
            self.server_protocol_version = negotiated
            if negotiated != _PROTOCOL_VERSION:
                log.info(
                    "MCP server %s negotiated protocol %s (client requested %s)",
                    self._command,
                    negotiated,
                    _PROTOCOL_VERSION,
                )

            # Send initialized notification
            self._send_notification("notifications/initialized", {})

            # List available tools
            tools_response = self._send_request("tools/list", {})
            if tools_response and "tools" in tools_response:
                self._tools = tools_response["tools"]

            self._connected = True
            log.info(
                "MCP connected: %s (PID %d, %d tools)",
                self._command,
                self._pid,
                len(self._tools),
            )
            return True

        except (OSError, FileNotFoundError) as exc:
            log.debug("Failed to start MCP server '%s': %s", self._command, exc)
            self._pid = None
            return False

    def list_tools(self) -> list[dict[str, Any]]:
        """Return cached tool definitions."""
        return list(self._tools)

    async def acall_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        if not self.is_connected():
            raise ConnectionError(f"MCP server not connected: {self._command}")

        result = await asyncio.to_thread(
            self._send_request,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

        if result is None:
            return {"error": f"MCP tool call failed: {tool_name}"}

        return dict(result)

    def close(self) -> None:
        """Terminate the MCP server subprocess.

        Two-phase shutdown: graceful SIGTERM with timeout, then SIGKILL
        if the process does not exit within ``_CLOSE_TIMEOUT_S`` seconds.
        """
        self._connected = False
        if self._process is not None:
            pid = self._pid
            try:
                # subprocess.Popen.stdin is Optional[IO[bytes]] (None when
                # ``stdin`` was not piped); only close if we actually own a
                # writable handle.
                if self._process.stdin is not None:
                    self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=_CLOSE_TIMEOUT_S)
                log.debug("MCP subprocess terminated gracefully (PID %s)", pid)
            except subprocess.TimeoutExpired:
                log.warning(
                    "MCP subprocess did not exit within %ds, sending SIGKILL (PID %s)",
                    _CLOSE_TIMEOUT_S,
                    pid,
                )
                with contextlib.suppress(Exception):
                    self._process.kill()
                    self._process.wait(timeout=2)
            except Exception:
                with contextlib.suppress(Exception):
                    self._process.kill()
            self._process = None
            self._pid = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for response with timeout."""
        with self._request_lock:
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

                # Read frames until the response matching OUR request id.
                # Servers may interleave unsolicited traffic (notifications/
                # message, progress, tools/list_changed); before id matching a
                # single such frame permanently desynchronized the stream while
                # is_connected() kept reporting healthy.
                deadline = time.monotonic() + self._timeout_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        log.warning("MCP timeout waiting for %s response", method)
                        return None

                    try:
                        import select

                        ready, _, _ = select.select(
                            [self._process.stdout],
                            [],
                            [],
                            remaining,
                        )
                        if not ready:
                            log.warning("MCP timeout waiting for %s response", method)
                            return None
                    except (TypeError, ValueError):
                        # Mock/non-real fd (tests) — fall through to a blocking
                        # read. Real pipes always take the select() path above,
                        # so the timeout contract holds outside of mocks.
                        pass

                    line = self._process.stdout.readline()
                    if not line:
                        return None

                    try:
                        response = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        log.debug("MCP: skipping non-JSON frame on stdout")
                        continue

                    if response.get("id") != request["id"]:
                        log.debug(
                            "MCP: skipping unsolicited frame (method=%s, id=%s)",
                            response.get("method"),
                            response.get("id"),
                        )
                        continue

                    if "error" in response:
                        log.warning("MCP error: %s", response["error"])
                        return None

                    result: dict[str, Any] | None = response.get("result")
                    return result
            except (OSError, BrokenPipeError) as exc:
                log.warning("MCP communication error: %s", exc)
                return None

    def _drain_stderr(self, pipe: Any) -> None:
        """Consume the child's stderr so it can never block on a full pipe."""
        with contextlib.suppress(Exception):  # drain thread must never propagate
            for raw in iter(pipe.readline, b""):
                log.debug(
                    "MCP stderr[%s]: %s",
                    self._command,
                    raw.decode("utf-8", "replace").rstrip(),
                )
        with contextlib.suppress(Exception):
            pipe.close()

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
