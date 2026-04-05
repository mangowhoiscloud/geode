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
        on_approval_start: Any = None,
        on_approval_end: Any = None,
    ) -> dict[str, Any]:
        """Send a prompt and wait for the result.

        Callbacks:
            on_stream(data: str): raw console output (ANSI-styled text)
            on_event(event: dict): structured events (tool_start, tool_end)
            on_approval_start(): called before HITL approval prompt (suspend spinners)
            on_approval_end(): called after HITL approval prompt (resume spinners)

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
            # HITL approval relay — serve requests user confirmation
            if rtype == "approval_request":
                if on_approval_start is not None:
                    on_approval_start()
                decision = self._handle_approval_request(response)
                if on_approval_end is not None:
                    on_approval_end()
                self._send({"type": "approval_response", "decision": decision})
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
                # AgenticLoop state events
                "model_escalation",
                "cost_budget_exceeded",
                "time_budget_expired",
                "convergence_detected",
                "goal_decomposition",
                "tool_backpressure",
                "tool_diversity_forced",
                "model_switched",
                "checkpoint_saved",
                # Pipeline milestone events
                "pipeline_header",
                "pipeline_gather",
                "pipeline_analysis",
                "pipeline_evaluation",
                "pipeline_score",
                "pipeline_verification",
                "pipeline_result",
                "feedback_loop",
                "node_skipped",
                # Internal protocol acks — silently drop
                "ack",
                "exit_ack",
            ):
                if on_event is not None:
                    on_event(response)
                continue
            return response

    @staticmethod
    def _restore_terminal() -> None:
        """Restore terminal to cooked mode before console.input().

        prompt_toolkit may leave the terminal in raw mode (no ICANON)
        after session.prompt() returns. Without ICANON, input() cannot
        receive line-buffered Enter keystrokes, causing it to block
        indefinitely and trigger the 120s server-side timeout.
        """
        import sys
        import termios

        try:
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            had_icanon = bool(attrs[3] & termios.ICANON)
            attrs[3] |= termios.ECHO | termios.ICANON
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            if not had_icanon:
                log.info("HITL: terminal restored (ICANON was missing)")
        except (ValueError, OSError, termios.error) as exc:
            log.warning("HITL: _restore_terminal failed: %s", exc)

    def _handle_approval_request(self, msg: dict[str, Any]) -> str:
        """Display approval prompt to user with animated spinner."""
        import sys
        import threading
        import time
        import unicodedata

        from core.cli.ui.console import console as c

        self._restore_terminal()

        tool = msg.get("tool_name", "?")
        detail = msg.get("detail", "")
        level = msg.get("safety_level", "write")

        _LEVEL_LABELS = {
            "write": "Write",
            "dangerous": "Dangerous",
            "mcp": "MCP",
            "cost": "Cost",
        }
        label = _LEVEL_LABELS.get(level, level.title())
        _LEVEL_COLORS = {
            "write": "33",  # yellow
            "dangerous": "31",  # red
            "mcp": "36",  # cyan
            "cost": "33",  # yellow
        }
        color = _LEVEL_COLORS.get(level, "33")

        # Truncate detail for display (CJK-aware)
        def _trunc(text: str, width: int = 50) -> str:
            w = 0
            for i, ch in enumerate(text):
                w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
                if w > width - 3:
                    return text[:i] + "..."
            return text

        detail_short = _trunc(detail.replace("\n", " ")) if detail else ""
        args_display = f"({detail_short})" if detail_short else ""

        # Animated spinner while waiting for input
        _FRAMES = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
        out = sys.stdout
        spinning = True

        def _spin() -> None:
            while spinning:
                frame = _FRAMES[int(time.monotonic() * 12) % len(_FRAMES)]
                out.write(
                    f"\r\033[2K  {frame} \033[{color}m{tool}\033[0m"
                    f"{args_display}"
                    f" \033[2m\u2014 {label} approval\033[0m"
                )
                out.flush()
                time.sleep(0.08)

        spinner_thread = threading.Thread(target=_spin, daemon=True)
        spinner_thread.start()

        # Brief pause so spinner is visible before prompt replaces it
        time.sleep(0.3)
        spinning = False
        spinner_thread.join(timeout=0.3)

        # Replace spinner line with static prompt
        out.write("\r\033[2K")
        out.flush()
        c.print(f"  \033[{color}m\u25b8 {tool}\033[0m{args_display}")
        c.print(f"    \033[2m{label} tool requires approval\033[0m")
        c.print()

        t0 = time.monotonic()
        try:
            resp = c.input("  [header]Allow? [Y/n/A][/header] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            c.print()
            log.info(
                "HITL: approval interrupted tool=%s elapsed=%.1fs",
                tool, time.monotonic() - t0,
            )
            return "n"

        elapsed = time.monotonic() - t0
        if resp in ("a", "always"):
            decision = "a"
        elif resp in ("", "y", "yes"):
            decision = "y"
        else:
            decision = "n"
        log.info(
            "HITL: approval tool=%s input=%r decision=%s elapsed=%.1fs",
            tool, resp, decision, elapsed,
        )
        return decision

    def request_resume(
        self,
        session_id: str = "",
        *,
        continue_latest: bool = False,
    ) -> dict[str, Any]:
        """Request session resume from serve.

        Args:
            session_id: Specific session ID to resume (--resume <id>).
            continue_latest: Resume the most recent session (--continue).

        Returns {"type": "resumed", ...} or {"type": "resume_error", ...}.
        """
        if not self._sock:
            return {"type": "resume_error", "message": "Not connected"}
        payload: dict[str, Any] = {"type": "resume"}
        if continue_latest:
            payload["continue"] = True
        elif session_id:
            payload["session_id"] = session_id
        self._send(payload)
        response = self._recv()
        if response is None:
            return {"type": "resume_error", "message": "Connection lost"}
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
