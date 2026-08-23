"""IPC Client — thin CLI client for connecting to geode serve.

When ``geode serve`` is running, the REPL can delegate agentic execution
to the server over a Unix domain socket, sharing MCP/skills/memory/hooks
instead of duplicating them.

Protocol: line-delimited JSON over Unix socket (matches CLIPoller server).
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any

from core.ipc_protocol import (
    IPC_CONTROL_TYPES,
    IPC_EVENT_TYPES,
    IPC_FEATURES,
    IPC_PROTOCOL_VERSION,
    MAX_IPC_MESSAGE_BYTES,
    decode_message,
    encode_message,
    negotiate_protocol,
    new_request_id,
)
from core.paths import CLI_SOCKET_PATH

log = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH: Path = CLI_SOCKET_PATH


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

        # Resolve serve working directory: the PROJECT root holding
        # ``.geode/config.toml``. Uses ``GEODE_PROJECT_DIR`` — NOT ``GEODE_HOME``,
        # which now means the user-global ``~/.geode`` tree (frontier
        # ``{APP}_HOME`` parity, core/paths.py). The two are different tiers;
        # the old ``GEODE_HOME`` name here was a misnomer (PR-PATH-MODERNIZE).
        _project_dir_env = os.environ.get("GEODE_PROJECT_DIR")
        serve_cwd = str(Path(_project_dir_env).expanduser()) if _project_dir_env else None
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


def query_serve_version(socket_path: Path | None = None, timeout_s: float = 2.0) -> str | None:
    """Read the running daemon's version from its IPC session greeting.

    Connects, reads the one-line ``{"type": "session", ...}`` greeting, and
    disconnects — no session exchange. Used by ``geode doctor`` to detect
    daemon/CLI install drift (a stale daemon serving old code after a rebuild).

    Returns the daemon's version string, ``""`` when the daemon greeted but
    its greeting has no ``version`` field (a build predating the version
    handshake — itself a drift signal), or ``None`` when the daemon is not
    reachable at all.
    """
    path = socket_path or DEFAULT_SOCKET_PATH
    if not path.exists():
        return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout_s)
        sock.connect(str(path))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                return None
            buf += chunk
            if b"\n" not in buf and len(buf) > MAX_IPC_MESSAGE_BYTES:
                return None
        line = buf.split(b"\n", 1)[0]
        greeting = decode_message(line)
        if not isinstance(greeting, dict) or greeting.get("type") != "session":
            return None
        return str(greeting.get("version", ""))
    except (OSError, ValueError):
        # ValueError covers malformed protocol data; OSError covers connect
        # refusal, socket timeout, and reset.
        return None
    finally:
        sock.close()


class IPCClient:
    """Thin client that relays prompts to geode serve via Unix socket.

    Usage::

        client = IPCClient()
        client.connect()
        result = client.send_prompt("summarize this repository")
        client.close()
    """

    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._sock: socket.socket | None = None
        self._buf = b""
        self.session_id: str = ""
        self.protocol_version: str = ""
        self.features: tuple[str, ...] = ()

    def connect(self) -> bool:
        """Connect to serve. Returns True on success.

        Right after the session greeting is received, sends a
        ``client_capability`` message describing the thin CLI's actual
        terminal state (TTY-ness, width). The daemon uses these values
        when constructing the per-thread Rich Console so that ANSI
        escape sequences and spinner frames are suppressed when the
        thin CLI's stdout is not a terminal (heredoc, pipe, CI).
        """
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(str(self._socket_path))
            # Read session greeting
            msg = self._recv()
            if not msg or msg.get("type") != "session":
                raise ValueError("Invalid IPC session greeting")
            self.session_id = msg.get("session_id", "")
            self.protocol_version, self.features = negotiate_protocol(
                msg.get("protocol_version"), msg.get("features")
            )
            log.info("Connected to serve (session=%s)", self.session_id)
            # Send terminal capability so the daemon knows whether to
            # emit ANSI / spinner output (v0.84.0). The daemon replies
            # with an ``ack`` which we drain here so subsequent
            # one-shot reads (``send_command`` / ``request_resume``)
            # see their actual response, not the stale ack.
            capability_request_id = self._send_client_capability()
            ack = self._recv_for(capability_request_id)
            if ack and ack.get("type") != "ack":
                log.debug("Unexpected response to client_capability: %s", ack)
                self.close()
                return False
            if ack and ack.get("protocol_version"):
                self.protocol_version, self.features = negotiate_protocol(
                    ack.get("protocol_version"), ack.get("features")
                )
            return True
        except (ConnectionRefusedError, OSError, ValueError) as exc:
            log.debug("IPC connect failed: %s", exc)
            if self._sock is not None:
                with contextlib.suppress(OSError):
                    self._sock.close()
            self._sock = None
            return False

    def _send_client_capability(self) -> str:
        """Send terminal capability to the daemon.

        Reports ``is_tty`` (both stdin and stdout are terminals) and
        ``width`` (terminal columns, falling back to 120). The daemon
        ignores unknown fields, so old daemons stay compatible.
        """
        import os
        import shutil
        import sys

        try:
            is_tty = bool(sys.stdin.isatty() and sys.stdout.isatty())
        except (ValueError, OSError):
            is_tty = False
        try:
            width = int(shutil.get_terminal_size().columns)
        except (ValueError, OSError):
            width = 120
        if width <= 0:
            width = 120
        # The thin CLI resolves the model at ITS cwd (the user's project). The
        # daemon otherwise resolves from its own launch cwd, so without this the
        # session's project model is ignored and the call diverges from the
        # banner. ``cwd`` is sent for diagnostics / future per-project routing.
        # Old daemons ignore unknown fields (back-compat).
        try:
            from core.config import settings as _settings

            model = _settings.model
        except Exception:
            model = ""
        # --dangerously-skip-permissions: advertise the bypass so a running
        # daemon adopts it for THIS connection (same handshake as model). The
        # thin CLI sets GEODE_DANGEROUSLY_SKIP_PERMISSIONS when the flag is
        # passed; sent explicitly (True/False) so a normal client resets it.
        skip_perms = os.getenv("GEODE_DANGEROUSLY_SKIP_PERMISSIONS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        return self._send(
            {
                "type": "client_capability",
                "protocol_version": IPC_PROTOCOL_VERSION,
                "features": list(IPC_FEATURES),
                "is_tty": is_tty,
                "width": width,
                "model": model,
                "cwd": os.getcwd(),
                "dangerously_skip_permissions": skip_perms,
            }
        )

    def close(self) -> None:
        """Disconnect from serve."""
        if self._sock:
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
        on_approval_request: Any = None,
    ) -> dict[str, Any]:
        """Send a prompt and wait for the streamed result."""
        return self._send_streaming_request(
            {"type": "prompt", "text": text},
            on_stream=on_stream,
            on_event=on_event,
            on_approval_start=on_approval_start,
            on_approval_end=on_approval_end,
            on_approval_request=on_approval_request,
        )

    def send_command_streaming(
        self,
        cmd: str,
        args: str = "",
        *,
        on_stream: Any = None,
        on_event: Any = None,
        on_approval_start: Any = None,
        on_approval_end: Any = None,
        on_approval_request: Any = None,
    ) -> dict[str, Any]:
        """Send a registered long-running slash command over the event channel."""
        return self._send_streaming_request(
            {"type": "command_stream", "cmd": cmd, "args": args},
            on_stream=on_stream,
            on_event=on_event,
            on_approval_start=on_approval_start,
            on_approval_end=on_approval_end,
            on_approval_request=on_approval_request,
        )

    def _send_streaming_request(
        self,
        payload: dict[str, Any],
        *,
        on_stream: Any = None,
        on_event: Any = None,
        on_approval_start: Any = None,
        on_approval_end: Any = None,
        on_approval_request: Any = None,
    ) -> dict[str, Any]:
        """Share prompt and streaming-command transport semantics."""
        if not self._sock:
            return {"type": "error", "message": "Not connected"}
        # Refresh width immediately before each run. The initial handshake
        # happens at connect-time, but users often resize the terminal between
        # runs; stale Rich widths make streamed panels/code blocks paint a
        # stair-step background at the old column count.
        self._send_client_capability()
        request_id = self._send(payload)

        while True:
            response = self._recv()
            if response is None:
                return {"type": "error", "message": "Connection lost"}
            rtype = response.get("type", "")
            response_request_id = response.get("request_id")
            if response_request_id and response_request_id != request_id:
                continue
            if rtype == "stream":
                if on_stream is not None:
                    on_stream(response.get("data", ""))
                continue
            # HITL approval relay — serve requests user confirmation
            if rtype == "approval_request":
                if on_approval_start is not None:
                    on_approval_start()
                try:
                    if on_approval_request is not None:
                        decision = str(on_approval_request(response))
                    else:
                        decision = self._handle_approval_request(response)
                finally:
                    if on_approval_end is not None:
                        on_approval_end()
                # Echo the approval_id so the serve side can match this reply
                # to the exact prompt it answers — a stale reply from a
                # previous (timed-out) prompt is discarded instead of
                # misrouted (PR-HITL-APPROVAL-FSM).
                self._send(
                    {
                        "type": "approval_response",
                        "decision": decision,
                        "approval_id": str(response.get("approval_id", "")),
                    }
                )
                continue
            if rtype in IPC_EVENT_TYPES or rtype in IPC_CONTROL_TYPES:
                if on_event is not None:
                    on_event(response)
                continue
            if rtype not in {
                "result",
                "error",
                "protocol_error",
                "resume_error",
                "command_result",
            }:
                log.debug("Ignoring unknown IPC event type %r", rtype)
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

    def _read_approval_line(self, prompt: str) -> str:
        """Read one HITL approval line from the real terminal.

        Rich ``console.input`` can inherit a raw prompt_toolkit terminal state,
        where Enter arrives as a literal carriage return instead of submitting
        the line. The thin client owns this prompt, so keep the read path
        deliberately simple: restore cooked mode, write a plain prompt, then
        read one line from stdin.
        """
        self._restore_terminal()
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line

    def _handle_approval_request(self, msg: dict[str, Any]) -> str:
        """Display approval prompt to user."""
        import time

        from core.ui import spinner_glyph
        from core.ui.console import console as c

        self._restore_terminal()

        tool = msg.get("tool_name", "?")
        detail = msg.get("detail", "")
        level = msg.get("safety_level", "write")

        # Same header shape as core/agent/approval.py::_approval_header (kept
        # inline — the thin client does not import the agent layer).
        _LEVEL_CATEGORIES = {
            "write": "write",
            "dangerous": "bash",
            "mcp": "mcp",
            "cost": "expensive",
        }
        category = _LEVEL_CATEGORIES.get(level, level)

        c.print()
        c.print(
            f"  [bold {spinner_glyph.ROSE_HEX}]{spinner_glyph.GLYPH}[/] Approval · "
            f"[bold]{tool}[/bold] [dim]({category})[/dim]"
        )
        if detail:
            # Single-line truncated detail
            short = detail.replace("\n", " ")[:80]
            c.print(f"  [muted]{short}[/muted]")
        c.print()

        t0 = time.monotonic()
        try:
            prompt = (
                "  y allow this request · n deny > "
                if level == "sensitive"
                else "  y allow · n deny · a always-allow > "
            )
            resp = self._read_approval_line(prompt)
        except (KeyboardInterrupt, EOFError):
            c.print()
            log.info(
                "HITL: approval interrupted tool=%s elapsed=%.1fs",
                tool,
                time.monotonic() - t0,
            )
            return "n"

        elapsed = time.monotonic() - t0
        resp = resp.replace("\r", "").strip().lower()
        if resp in ("a", "always") and level != "sensitive":
            decision = "a"
        elif resp in ("", "y", "yes"):
            decision = "y"
        else:
            decision = "n"
        log.info(
            "HITL: approval tool=%s input=%r decision=%s elapsed=%.1fs",
            tool,
            resp,
            decision,
            elapsed,
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
        request_id = self._send(payload)
        response = self._recv_for(request_id)
        if response is None:
            return {"type": "resume_error", "message": "Connection lost"}
        return response

    def send_command(self, cmd: str, args: str = "") -> dict[str, Any]:
        """Send a slash command to serve and wait for result.

        Returns {"type": "command_result", "cmd": ..., "status": "ok"/"error"}.
        """
        if not self._sock:
            return {"type": "error", "message": "Not connected"}
        request_id = self._send({"type": "command", "cmd": cmd, "args": args})
        response = self._recv_for(request_id)
        if response is None:
            return {"type": "error", "message": "Connection lost"}
        return response

    def _send(self, data: dict[str, Any]) -> str:
        """Send line-delimited JSON."""
        assert self._sock is not None
        request_id = str(data.setdefault("request_id", new_request_id()))
        self._sock.sendall(encode_message(data))
        return request_id

    def _recv(self) -> dict[str, Any] | None:
        """Receive one line-delimited JSON message."""
        assert self._sock is not None
        while b"\n" not in self._buf:
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    return None
                self._buf += chunk
                if b"\n" not in self._buf and len(self._buf) > MAX_IPC_MESSAGE_BYTES:
                    raise ValueError("IPC response exceeds the protocol size limit")
            except (ConnectionResetError, OSError):
                return None
        line, self._buf = self._buf.split(b"\n", 1)
        return decode_message(line)

    def _recv_for(self, request_id: str) -> dict[str, Any] | None:
        """Receive the matching response, accepting legacy uncorrelated peers."""
        while True:
            response = self._recv()
            if response is None:
                return None
            response_request_id = response.get("request_id")
            if not response_request_id or response_request_id == request_id:
                return response
