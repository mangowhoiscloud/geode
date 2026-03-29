"""IPC Client — thin CLI client for connecting to geode serve.

When ``geode serve`` is running, the REPL can delegate agentic execution
to the server over a Unix domain socket, sharing MCP/skills/memory/hooks
instead of duplicating them.

Protocol: line-delimited JSON over Unix socket (matches CLIPoller server).
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = Path.home() / ".geode" / "cli.sock"


def start_serve_if_needed(socket_path: Path | None = None, timeout_s: float = 10.0) -> bool:
    """Start serve in background if not running. Returns True when ready."""
    import subprocess  # nosec B404 — used for controlled serve daemon spawn
    import sys

    if is_serve_running(socket_path):
        return True

    log.info("Starting geode serve in background...")
    subprocess.Popen(  # noqa: S603  # nosec B603 — fixed args, no untrusted input
        [sys.executable, "-m", "geode.cli", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for socket to appear
    import time

    for _ in range(int(timeout_s * 10)):
        if is_serve_running(socket_path):
            return True
        time.sleep(0.1)
    return False


def is_serve_running(socket_path: Path | None = None) -> bool:
    """Check if geode serve is running by probing the socket."""
    path = socket_path or DEFAULT_SOCKET_PATH
    if not path.exists():
        return False
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(str(path))
        sock.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


class IPCClient:
    """Thin client that relays prompts to geode serve via Unix socket.

    Usage::

        client = IPCClient()
        client.connect()
        result = client.send_prompt("analyze Berserk")
        client.close()
    """

    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._sock: socket.socket | None = None
        self._buf = b""
        self.session_id: str = ""

    def connect(self) -> bool:
        """Connect to serve. Returns True on success."""
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(str(self._socket_path))
            # Read session greeting
            msg = self._recv()
            if msg and msg.get("type") == "session":
                self.session_id = msg.get("session_id", "")
                log.info("Connected to serve (session=%s)", self.session_id)
            return True
        except (ConnectionRefusedError, OSError) as exc:
            log.debug("IPC connect failed: %s", exc)
            self._sock = None
            return False

    def close(self) -> None:
        """Disconnect from serve."""
        if self._sock:
            import contextlib

            with contextlib.suppress(OSError):
                self._send({"type": "exit"})
                self._recv()
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def send_prompt(self, text: str) -> dict[str, Any]:
        """Send a prompt and wait for the result.

        Returns a dict with keys: type, text, rounds, tool_calls, termination.
        On error, returns {"type": "error", "message": "..."}.
        """
        if not self._sock:
            return {"type": "error", "message": "Not connected"}
        self._send({"type": "prompt", "text": text})
        response = self._recv()
        if response is None:
            return {"type": "error", "message": "Connection lost"}
        return response

    def send_command(self, cmd: str, args: str = "") -> dict[str, Any]:
        """Send a slash command to serve and wait for result.

        Returns {"type": "command_result", "cmd": ..., "status": "ok"/"error"}.
        """
        if not self._sock:
            return {"type": "error", "message": "Not connected"}
        self._send({"type": "command", "cmd": cmd, "args": args})
        response = self._recv()
        if response is None:
            return {"type": "error", "message": "Connection lost"}
        return response

    def _send(self, data: dict[str, Any]) -> None:
        """Send line-delimited JSON."""
        assert self._sock is not None
        payload = json.dumps(data, ensure_ascii=False) + "\n"
        self._sock.sendall(payload.encode("utf-8"))

    def _recv(self) -> dict[str, Any] | None:
        """Receive one line-delimited JSON message."""
        assert self._sock is not None
        while b"\n" not in self._buf:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    return None
                self._buf += chunk
            except (ConnectionResetError, OSError):
                return None
        line, self._buf = self._buf.split(b"\n", 1)
        result: dict[str, Any] = json.loads(line.decode("utf-8"))
        return result
