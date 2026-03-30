"""IPC Client — thin CLI client for connecting to geode serve.

When ``geode serve`` is running, the REPL can delegate agentic execution
to the server over a Unix domain socket, sharing MCP/skills/memory/hooks
instead of duplicating them.

Protocol: line-delimited JSON over Unix socket (matches CLIPoller server).
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = Path.home() / ".geode" / "cli.sock"


def start_serve_if_needed(socket_path: Path | None = None, timeout_s: float = 10.0) -> bool:
    """Start serve in background if not running. Returns True when ready.

    Uses a pidfile lock to prevent TOCTOU race when multiple thin clients
    attempt to start serve simultaneously.
    """
    import fcntl
    import subprocess  # nosec B404 — used for controlled serve daemon spawn
    import sys
    import time

    if is_serve_running(socket_path):
        return True

    # Pidfile lock prevents duplicate serve spawn (TOCTOU fix)
    lock_path = (socket_path or DEFAULT_SOCKET_PATH).with_suffix(".startup.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = open(lock_path, "w")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Another client is already starting serve — just wait
        log.debug("Another client is starting serve, waiting...")
        for _ in range(int(timeout_s * 10)):
            if is_serve_running(socket_path):
                return True
            time.sleep(0.1)
        return False

    try:
        # Re-check after acquiring lock (serve may have started while waiting)
        if is_serve_running(socket_path):
            return True

        log.info("Starting geode serve in background...")
        import shutil

        geode_bin = shutil.which("geode")
        cmd = [geode_bin, "serve"] if geode_bin else [sys.executable, "-m", "geode.cli", "serve"]

        # Resolve serve working directory: needs .geode/config.toml
        serve_cwd = os.environ.get("GEODE_HOME")
        if not serve_cwd:
            # Find project root via this file's location (core/cli/ipc_client.py → ../../)
            pkg_dir = Path(__file__).resolve().parent.parent.parent
            if (pkg_dir / ".geode" / "config.toml").exists():
                serve_cwd = str(pkg_dir)

        subprocess.Popen(  # noqa: S603  # nosec B603 — fixed args, no untrusted input
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=serve_cwd,
        )

        for _ in range(int(timeout_s * 10)):
            if is_serve_running(socket_path):
                return True
            time.sleep(0.1)
        return False
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


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

    def send_prompt(
        self,
        text: str,
        *,
        on_stream: Any = None,
        on_event: Any = None,
    ) -> dict[str, Any]:
        """Send a prompt and wait for the result.

        Callbacks:
            on_stream(data: str): raw console output (ANSI-styled text)
            on_event(event: dict): structured events (tool_start, tool_end)

        Returns the final ``{"type": "result", ...}`` dict.
        """
        if not self._sock:
            return {"type": "error", "message": "Not connected"}
        self._send({"type": "prompt", "text": text})

        while True:
            response = self._recv()
            if response is None:
                return {"type": "error", "message": "Connection lost"}
            rtype = response.get("type", "")
            if rtype == "stream":
                if on_stream is not None:
                    on_stream(response.get("data", ""))
                continue
            # Structured events — all non-stream, non-terminal types
            if rtype in (
                "tool_start",
                "tool_end",
                "tokens",
                "round_start",
                "thinking_start",
                "thinking_end",
                "turn_end",
                "context_event",
                "subagent_dispatch",
                "subagent_progress",
                "subagent_complete",
                "session_cost",
            ):
                if on_event is not None:
                    on_event(response)
                continue
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
