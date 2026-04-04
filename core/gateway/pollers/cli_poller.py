"""CLI Poller — Unix domain socket server for thin CLI client IPC.

Accepts multiple concurrent CLI client connections. Each connected client
gets an independent IPC session backed by serve's SharedServices (same MCP,
skills, hooks, memory as Slack/Discord pollers). SessionLane per-key
serialization ensures same-session ordering; different sessions run in parallel.

Protocol: line-delimited JSON over Unix domain socket.

Client → Server:
    {"type": "prompt", "text": "analyze Berserk", "session_id": "..."}
    {"type": "command", "cmd": "/model", "args": "sonnet"}
    {"type": "exit"}

Server → Client:
    {"type": "stream", "data": "▸ tool_call(...)\\n"}   (during prompt execution)
    {"type": "result", "text": "...", "rounds": 3, "tool_calls": [...]}
    {"type": "command_result", "cmd": "...", "output": "..."}
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


class _StreamingWriter:
    """File-like object that relays console writes to a client socket.

    Each ``write()`` call sends ``{"type": "stream", "data": "..."}`` over
    the socket, so the thin client can render agentic UI (tool calls,
    results, token usage) in real-time as the AgenticLoop executes.

    Inspired by:
    - Codex CLI item-based streaming (discrete events over API)
    - OpenClaw System Events Queue (event → client relay)
    - autoresearch P6 L1 capture (capture all stdout)
    """

    def __init__(self, client: socket.socket) -> None:
        self._client = client

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._send_json({"type": "stream", "data": text})
        return len(text)

    def send_event(self, event_type: str, **data: Any) -> None:
        """Send a structured event (tool_start, tool_end, etc.)."""
        self._send_json({"type": event_type, **data})

    def _send_json(self, obj: dict[str, Any]) -> None:
        try:
            payload = json.dumps(obj, ensure_ascii=False) + "\n"
            self._client.sendall(payload.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def request_approval(
        self,
        tool_name: str,
        detail: str,
        safety_level: str = "write",
    ) -> str:
        """Send approval request to thin CLI and wait for response.

        Returns 'y', 'n', or 'a' (always).
        """
        self._send_json(
            {
                "type": "approval_request",
                "tool_name": tool_name,
                "detail": detail,
                "safety_level": safety_level,
            }
        )
        log.debug("HITL: sent approval_request tool=%s level=%s", tool_name, safety_level)
        import time as _time

        _t0 = _time.monotonic()
        # Block until thin client sends approval_response
        try:
            self._client.settimeout(120.0)  # 2 min for user decision
            buf = b""
            while True:
                chunk = self._client.recv(4096)
                if not chunk:
                    log.warning(
                        "HITL: connection closed waiting for approval tool=%s elapsed=%.1fs",
                        tool_name,
                        _time.monotonic() - _t0,
                    )
                    return "n"
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = json.loads(line.decode("utf-8"))
                    if msg.get("type") == "approval_response":
                        decision = str(msg.get("decision", "n"))
                        log.info(
                            "HITL: approval_response tool=%s decision=%s elapsed=%.1fs",
                            tool_name,
                            decision,
                            _time.monotonic() - _t0,
                        )
                        return decision
                    else:
                        log.debug(
                            "HITL: ignoring non-approval msg type=%s while waiting",
                            msg.get("type"),
                        )
        except TimeoutError:
            log.warning(
                "HITL: approval TIMEOUT tool=%s elapsed=%.1fs (120s limit hit)",
                tool_name,
                _time.monotonic() - _t0,
            )
            return "n"
        except (OSError, json.JSONDecodeError) as exc:
            log.warning(
                "HITL: approval error tool=%s elapsed=%.1fs exc=%s",
                tool_name,
                _time.monotonic() - _t0,
                exc,
            )
            return "n"
        finally:
            self._client.settimeout(None)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True  # trick Rich into applying ANSI styles

    def fileno(self) -> int:
        return -1


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
        scheduler_service: Any = None,
    ) -> None:
        self._services = services
        self._socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._server: socket.socket | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()
        self._scheduler_service = scheduler_service

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
        self._server.listen(5)  # backlog for concurrent CLI connections
        self._server.settimeout(1.0)

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="geode-cli-poller",
            daemon=True,
        )
        self._thread.start()
        log.info("CLI channel listening on %s", self._socket_path)

    def stop_accepting(self) -> None:
        """Stop accepting new connections but let active handlers finish.

        Closes the server socket and sets the stop event so the accept loop
        exits. Active client handler threads continue running until their
        current request completes.
        """
        import contextlib

        self._stop_event.set()
        if self._server:
            with contextlib.suppress(OSError):
                self._server.close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("CLI channel stopped accepting new connections")

    def stop(self) -> None:
        """Stop the socket server and clean up all clients."""
        import contextlib

        self._stop_event.set()
        with self._clients_lock:
            for client in list(self._active_clients):
                with contextlib.suppress(OSError):
                    client.close()
            self._active_clients.clear()
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
        """Accept loop — spawns a handler thread per client."""
        while not self._stop_event.is_set():
            try:
                assert self._server is not None
                client, _ = self._server.accept()
                with self._clients_lock:
                    self._active_clients.add(client)
                log.info("CLI client connected (%d active)", len(self._active_clients))
                t = threading.Thread(
                    target=self._client_thread,
                    args=(client,),
                    name=f"geode-cli-{os.urandom(2).hex()}",
                    daemon=True,
                )
                t.start()
            except TimeoutError:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    log.warning("CLI accept error", exc_info=True)
                break

    def _client_thread(self, client: socket.socket) -> None:
        """Run _handle_client and clean up on exit."""
        try:
            self._handle_client(client)
        finally:
            with self._clients_lock:
                self._active_clients.discard(client)
            import contextlib

            with contextlib.suppress(OSError):
                client.close()
            log.info("CLI client session ended (%d active)", len(self._active_clients))

    def _handle_client(self, client: socket.socket) -> None:
        """Handle a connected CLI client session.

        Creates an IPC-mode session (DANGEROUS blocked, WRITE allowed)
        gated by SessionLane + Global Lane via acquire_all().
        """
        from core.agent.conversation import ConversationContext
        from core.gateway.shared_services import SessionMode

        # ContextVars do NOT propagate to threads — set them explicitly
        self._propagate_contextvars()

        # Thread-local session meter — each IPC session tracks its own
        # model, elapsed time, and token counts independently.
        from core.cli.ui.agentic_ui import init_session_meter

        init_session_meter()

        client.settimeout(None)  # blocking reads
        buf = b""
        conversation = ConversationContext()
        session_id = f"cli-{os.urandom(4).hex()}"

        # Build IPC approval relay: WRITE/DANGEROUS tools prompt thin CLI
        _writer = _StreamingWriter(client)

        def _ipc_approval(tool_name: str, detail: str, safety_level: str) -> str:
            return _writer.request_approval(tool_name, detail, safety_level)

        # Create an IPC session backed by serve's SharedServices
        _executor, loop = self._services.create_session(
            SessionMode.IPC,
            conversation=conversation,
            propagate_context=True,
            approval_callback=_ipc_approval,
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
                    msg["_client"] = client  # pass socket for streaming
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
                return self._run_prompt_streaming(
                    text,
                    loop,
                    session_id,
                    msg.get("_client"),
                )
            except Exception as exc:
                log.warning("CLI prompt execution error", exc_info=True)
                return {"type": "error", "message": str(exc)}

        if msg_type == "command":
            return self._handle_command_on_server(msg, loop)

        if msg_type == "resume":
            return self._handle_resume(msg, loop, conversation)

        # Stale approval_response from a timed-out request — silently drop
        if msg_type == "approval_response":
            log.debug("Dropping stale approval_response: %s", msg.get("decision"))
            return {"type": "ack"}

        return {"type": "error", "message": f"Unknown message type: {msg_type}"}

    def _run_prompt_streaming(
        self,
        text: str,
        loop: Any,
        session_id: str,
        client: socket.socket | None,
    ) -> dict[str, Any]:
        """Run a prompt with real-time console streaming to the client.

        Installs a **thread-local** Rich Console whose ``file`` is the
        client's ``_StreamingWriter``.  All ``console.print(...)`` calls
        within this thread are routed to the session's socket — never to
        the shared default Console — preventing cross-session output
        contamination when multiple thin-CLI clients connect concurrently.
        """
        from core.cli.ui.agentic_ui import _ipc_writer_local
        from core.cli.ui.console import (
            make_session_console,
            reset_thread_console,
            set_thread_console,
        )

        # Enable agentic UI for this run (same as old REPL)
        old_quiet = getattr(loop, "_quiet", True)
        old_op_quiet = getattr(loop, "_op_logger", None)
        loop._quiet = False
        if old_op_quiet is not None:
            loop._op_logger._quiet = False

        # Thread-local console: all console.print() in this thread → client socket
        writer = _StreamingWriter(client) if client else None
        if writer:
            set_thread_console(make_session_console(writer))
            _ipc_writer_local.writer = writer

        try:
            lane_queue = self._services.lane_queue
            if lane_queue is not None:
                with lane_queue.acquire_all(f"cli:{session_id}", ["session", "global"]):
                    result = loop.run(text)
            else:
                result = loop.run(text)
        finally:
            if writer:
                reset_thread_console()
                _ipc_writer_local.writer = None
            loop._quiet = old_quiet
            if old_op_quiet is not None:
                loop._op_logger._quiet = old_quiet

        # Build final result (tool_calls already rendered via streaming)
        tool_calls: list[dict[str, Any]] = []
        if result and result.tool_calls:
            for tc in result.tool_calls:
                if isinstance(tc, dict):
                    tool_calls.append(
                        {
                            "name": tc.get("name", "?"),
                            "args": tc.get("input", {}),
                        }
                    )
                elif hasattr(tc, "name"):
                    tool_calls.append(
                        {
                            "name": tc.name,
                            "args": getattr(tc, "arguments", {}),
                        }
                    )
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

    def _handle_command_on_server(self, msg: dict[str, Any], loop: Any) -> dict[str, Any]:
        """Execute a slash command on the server side.

        Captures all console output (with ANSI styling) so it can be
        relayed to the thin client for display.
        """
        cmd = msg.get("cmd", "")
        args = msg.get("args", "")
        try:
            from core.cli import _handle_command
            from core.cli.ui.console import capture_output

            with capture_output() as buf:
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
                "output": buf.getvalue(),
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

    def _handle_resume(
        self,
        msg: dict[str, Any],
        loop: Any,
        conversation: Any,
    ) -> dict[str, Any]:
        """Load a session checkpoint and restore conversation context."""
        try:
            from core.cli.session_checkpoint import SessionCheckpoint

            cp = SessionCheckpoint()

            state = None
            if msg.get("continue"):
                sessions = cp.list_resumable()
                if sessions:
                    state = sessions[0]
            else:
                sid = msg.get("session_id", "")
                if sid:
                    state = cp.load(sid)
            if state is None:
                return {"type": "resume_error", "message": "No resumable session found"}

            # Restore conversation messages
            conversation.messages.clear()
            conversation.messages.extend(state.messages)

            # Sync loop session_id for checkpoint continuity
            loop._session_id = state.session_id

            # Restore model if different
            if state.model and state.model != loop.model:
                loop.update_model(state.model)

            log.info(
                "Session resumed: %s (round=%d, messages=%d)",
                state.session_id,
                state.round_idx,
                len(state.messages),
            )
            return {
                "type": "resumed",
                "session_id": state.session_id,
                "round_idx": state.round_idx,
                "model": state.model,
                "user_input": state.user_input,
                "message_count": len(state.messages),
            }
        except Exception as exc:
            log.warning("Session resume failed", exc_info=True)
            return {"type": "resume_error", "message": str(exc)}

    def _propagate_contextvars(self) -> None:
        """Set ContextVars needed by slash command handlers in this thread.

        Python ContextVars do NOT inherit across threads. The CLI poller
        thread must explicitly set readiness, scheduler_service, domain,
        memory, and profile so that ``_handle_command()`` works correctly.
        """
        try:
            from core.cli import _set_readiness
            from core.cli.session_state import _scheduler_service_ctx
            from core.cli.startup import check_readiness

            _set_readiness(check_readiness())

            if self._scheduler_service is not None:
                _scheduler_service_ctx.set(self._scheduler_service)

            # Domain, memory, profile — delegated to SharedServices helper
            if hasattr(self._services, "_propagate_contextvars"):
                self._services._propagate_contextvars()
        except Exception:
            log.debug("ContextVar propagation skipped", exc_info=True)

    @staticmethod
    def _send(client: socket.socket, data: dict[str, Any]) -> None:
        """Send a JSON message to the client (line-delimited)."""
        try:
            payload = json.dumps(data, ensure_ascii=False) + "\n"
            client.sendall(payload.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            log.debug("CLI send failed — client disconnected")
