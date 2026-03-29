"""CLI Poller — Unix domain socket server for thin CLI client IPC.

Accepts a single CLI client connection at a time. Each connected client
gets a REPL-mode session backed by serve's SharedServices (same MCP,
skills, hooks, memory as Slack/Discord pollers).

Protocol: line-delimited JSON over Unix domain socket.

Client → Server:
    {"type": "prompt", "text": "analyze Berserk", "session_id": "..."}
    {"type": "command", "cmd": "/model", "args": "sonnet"}
    {"type": "exit"}

Server → Client:
    {"type": "result", "text": "...", "rounds": 3, "tool_calls": [...]}
    {"type": "error", "message": "..."}
    {"type": "session", "session_id": "cli-abc123"}
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.gateway.shared_services import SharedServices

DEFAULT_SOCKET_PATH = Path.home() / ".geode" / "cli.sock"


class CLIPoller:
    """Unix domain socket server for CLI thin-client IPC.

    Unlike BasePoller subclasses (which poll external APIs), CLIPoller
    *listens* for a local CLI client connection. It does not inherit
    BasePoller because the lifecycle is fundamentally different:
    accept-loop vs poll-loop.
    """

    def __init__(
        self,
        services: SharedServices,
        *,
        socket_path: Path | None = None,
    ) -> None:
        self._services = services
        self._socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._server: socket.socket | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_client: socket.socket | None = None

    @property
    def channel_name(self) -> str:
        return "cli"

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        """Start listening on Unix domain socket."""
        if self._thread is not None and self._thread.is_alive():
            return

        # Clean up stale socket file
        if self._socket_path.exists():
            self._socket_path.unlink()

        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self._socket_path))
        os.chmod(str(self._socket_path), 0o600)  # User-only access
        self._server.listen(1)
        self._server.settimeout(1.0)

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="geode-cli-poller",
            daemon=True,
        )
        self._thread.start()
        log.info("CLI channel listening on %s", self._socket_path)

    def stop(self) -> None:
        """Stop the socket server and clean up."""
        import contextlib

        self._stop_event.set()
        if self._active_client:
            with contextlib.suppress(OSError):
                self._active_client.close()
        if self._server:
            with contextlib.suppress(OSError):
                self._server.close()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._socket_path.exists():
            with contextlib.suppress(OSError):
                self._socket_path.unlink()
        log.info("CLI channel stopped")

    def _accept_loop(self) -> None:
        """Accept loop — one client at a time."""
        while not self._stop_event.is_set():
            try:
                assert self._server is not None
                client, _ = self._server.accept()
                self._active_client = client
                log.info("CLI client connected")
                self._handle_client(client)
            except TimeoutError:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    log.warning("CLI accept error", exc_info=True)
                break
            finally:
                self._active_client = None

    def _handle_client(self, client: socket.socket) -> None:
        """Handle a connected CLI client session.

        Creates an IPC-mode session (DANGEROUS blocked, WRITE allowed)
        gated by SessionLane + Global Lane via acquire_all().
        """
        from core.agent.conversation import ConversationContext
        from core.gateway.shared_services import SessionMode

        client.settimeout(None)  # blocking reads
        buf = b""
        conversation = ConversationContext()
        session_id = f"cli-{os.urandom(4).hex()}"

        # Create an IPC session backed by serve's SharedServices
        _executor, loop = self._services.create_session(
            SessionMode.IPC,
            conversation=conversation,
            propagate_context=True,
        )

        # Send session ID to client
        self._send(client, {"type": "session", "session_id": session_id})

        while not self._stop_event.is_set():
            try:
                chunk = client.recv(65536)
                if not chunk:
                    log.info("CLI client disconnected")
                    break
                buf += chunk

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = json.loads(line.decode("utf-8"))
                    response = self._process_message(msg, loop, conversation, session_id)
                    if response is None:
                        # Exit signal
                        self._send(client, {"type": "exit_ack"})
                        return
                    self._send(client, response)
            except (ConnectionResetError, BrokenPipeError):
                log.info("CLI client connection lost")
                break
            except json.JSONDecodeError:
                self._send(client, {"type": "error", "message": "Invalid JSON"})
            except Exception:
                log.warning("CLI handler error", exc_info=True)
                self._send(
                    client,
                    {"type": "error", "message": "Internal error"},
                )

    def _process_message(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Process a single client message. Returns response dict or None for exit."""
        msg_type = msg.get("type", "")

        if msg_type == "exit":
            return None

        if msg_type == "prompt":
            text = msg.get("text", "").strip()
            if not text:
                return {"type": "error", "message": "Empty prompt"}

            try:
                # Gate through SessionLane + Global Lane
                lane_queue = self._services.lane_queue
                if lane_queue is not None:
                    with lane_queue.acquire_all(f"cli:{session_id}", ["session", "global"]):
                        result = loop.run(text)
                else:
                    result = loop.run(text)

                tool_calls = []
                if result and result.tool_calls:
                    for tc in result.tool_calls:
                        if isinstance(tc, dict):
                            tool_calls.append({"name": tc.get("name", "?"), "args": tc.get("input", {})})
                        elif hasattr(tc, "name"):
                            tool_calls.append({"name": tc.name, "args": getattr(tc, "arguments", {})})
                # Extract model/cost from last LLM call metadata if available
                model = getattr(loop, "model", "unknown")
                summary = getattr(result, "summary", "") if result else ""

                return {
                    "type": "result",
                    "text": result.text if result else "",
                    "rounds": result.rounds if result else 0,
                    "tool_calls": tool_calls,
                    "termination": (result.termination_reason if result else "unknown"),
                    "model": model,
                    "summary": summary,
                }
            except Exception as exc:
                log.warning("CLI prompt execution error", exc_info=True)
                return {"type": "error", "message": str(exc)}

        if msg_type == "command":
            return self._handle_command_on_server(msg, loop)

        return {"type": "error", "message": f"Unknown message type: {msg_type}"}

    def _handle_command_on_server(self, msg: dict[str, Any], loop: Any) -> dict[str, Any]:
        """Execute a slash command on the server side."""
        cmd = msg.get("cmd", "")
        args = msg.get("args", "")
        try:
            from core.cli import _handle_command

            should_break, _verbose, _resume = _handle_command(
                cmd,
                args,
                False,
                skill_registry=self._services.skill_registry,
                mcp_manager=self._services.mcp_manager,
            )
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "ok",
                "should_break": should_break,
            }
        except Exception as exc:
            log.warning("CLI command error: %s %s", cmd, exc, exc_info=True)
            return {
                "type": "command_result",
                "cmd": cmd,
                "status": "error",
                "message": str(exc),
            }

    @staticmethod
    def _send(client: socket.socket, data: dict[str, Any]) -> None:
        """Send a JSON message to the client (line-delimited)."""
        try:
            payload = json.dumps(data, ensure_ascii=False) + "\n"
            client.sendall(payload.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            log.debug("CLI send failed — client disconnected")
